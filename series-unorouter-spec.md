# Spec: Content Series / Queue System + UnoRouter LLM Provider

**Source:** `ne instruction.txt` (task brief) + 6 rounds of clarifying interview (2026-10-05)
**Status:** Spec only — no code changes made yet.
**Repo:** Telbot — Python Telegram bot that turns a text prompt into a 9:16 viral video using free-tier LLMs + image providers (script spine, karaoke subtitles, Cloudflare/Pollinations/etc. fallbacks), tuned for Render free tier (512 MB RAM, `MAX_CONCURRENT_JOBS = 1`, ephemeral disk).

---

## 0. Interview Decisions (authoritative)

| # | Topic | Decision |
|---|-------|----------|
| 1 | Job-slot conflict | **Wait for idle slot.** Scheduled run starts only when no job is running; starts right after the current job finishes. Queue order preserved. |
| 2 | Failed automated run | **Keep + retry next slot.** Failed prompt stays first in queue; retried at next scheduled slot; owner gets a failure notification. No drop counter. |
| 3 | Persistence | **Local only (`series/active.json`), accept loss on Render redeploy.** No remote sync in scope. |
| 4 | Access control | No in-app gate. Owner already restricts the bot to themselves via BotFather privacy/user settings. Code stays permission-agnostic. |
| 5 | First-run timing | Interactive: after `/series schedule` is set, the bot **asks via inline buttons** whether to generate the next prompt now or wait N hours (the previously persisted `next_run` approach is noted; the button-ask is what ships). `next_run` is persisted in the JSON and recalculated on each scheduler tick (this part of the user's answer is adopted regardless). |
| 6 | `/series run` command | **Yes — added** on top of the 8 spec subcommands (9 total). Generates the next pending prompt immediately, skipping approval buttons. |
| 7 | Empty-queue behavior | **Keep schedule armed.** Completion message sent; `schedule.enabled` stays `true`. Adding prompts later auto-resumes the schedule. |
| 8 | Multi-prompt add | **Both, auto-detect:** single line = one prompt; multi-line text = split per line (one prompt per line). |
| 9 | Schedule type | **Interval + optional time-of-day anchor.** `/series schedule <hours>`; `/series schedule <hours> at HH:MM` anchors to wall-clock time in the series timezone. |
| 10 | Pause/resume | If scheduled time passed while paused, the next run **fires immediately** on the first scheduler tick after `/series resume`. |
| 11 | `/series clear` | **Confirm via inline ✅ button** showing title + prompt count before deleting. |
| 12 | UnoRouter chain position | **UnoRouter first** (UnoRouter → Groq → Gemini → Pollinations → Bytez). Rationale: strongest free models primary; protects Groq's 1,000 req/day quota from series automation; fallback chain guards outages. |
| 13 | UnoRouter default model | **Multi-model list** tried in order via `UNOROUTER_MODELS` (first that responds wins). |
| 14 | Brief expansion | **Batch + title context:** one LLM call expands `<brief>` into N prompts, conditioned on the series title so every generated video carries the series theme in its script spine. |
| 15 | Run notifications | **Full progress + prefix:** scheduled runs post the same Step 1/5…5/5 progress edits as manual runs, prefixed `🎬 Series run k/n:` (k = prompt position, n = pending count at start). |
| 16 | Timezone | **Default `SERIES_TIMEZONE=Africa/Lagos`** (config.py + .env.example), used for anchor scheduling and `next_run` display. |
| 17 | Destination chat | **`owner_chat_id` set at `/series create`** (stored in `active.json`); all series videos + notifications go there. |
| 18 | Queue cap | **Hard cap 50 pending prompts.** `/series add` / `/series generate` reject beyond 50 with a clear message. |
| 19 | Missed scheduled slot | **Catch up + notify:** if `next_run` passed while the bot was down, the scheduler fires the run on its first tick after startup and first sends "⏰ Scheduled run was missed (bot was down) — generating now." |
| 20 | Prompt format field | **Per-prompt:** each prompt entry stores its own `format` (default `narration`); `--format narration|description` flag accepted on `/series add` and `/series generate`, applying to prompts created by that command. |
| 21 | `list` vs `status` | `/series list` = full queue (every pending prompt: ID + first ~80 chars); `/series status` = compact summary (enabled/paused, count, next_run in local time, interval, last result). |
| 22 | Tests | **Extend `test_pipeline_logic.py`** with a `series_manager` section (offline, mocked file I/O + LLM); keep single CI entry point. |

---

## 1. Feature A — Content Series / Queue System (main feature)

### 1.1 Hard constraints (from the instruction)

- **Only one active series at a time.**
- State lives in a **single JSON file: `series/active.json`** (add `series/` to `.gitignore`; add a `series/active.json.example` for reference).
- On **successful** video generation, **delete the used prompt** from the file so the next becomes first in line.
- When the last prompt is used and the queue becomes empty, send the owner exactly:

  > ✅ Series complete! All prompts have been used. Use /series create <title> to start a new series.

- **`/gen` and `/generate` must keep working exactly as today** (script preview + ✅ Proceed / 🔄 Regenerate buttons). The series system is **purely additive** — no changes to the single-video pipeline behavior.
- Reuse existing patterns: `TelegramAPI` for background-thread messaging, temp-dir cleanup, logging style, config-from-`config.py`, no new heavy dependencies.

### 1.2 New module: `services/series_manager.py`

Pure-logic class + file I/O, no Telegram imports (keeps it unit-testable):

```
SeriesManager
  load() -> dict | None          # read series/active.json, validate schema, repair tolerantly
  save(data)                     # atomic write (tmp file + os.replace) to survive crashes mid-write
  create(title, owner_chat_id)   # build fresh series dict (replaces only after caller confirms)
  add_prompt(text, fmt="narration")   # enforce 50-prompt cap
  list_prompts() -> list
  pop_next() -> dict | None      # remove + return first pending prompt (caller saves on success)
  set_schedule(enabled=None, interval_hours=None, anchor=None)  # anchor = "HH:MM" | None
  advance_next_run(from_ts=None) # next_run = max(now, last_run) + interval, honoring anchor
  pause() / resume()             # resume recomputes next_run if overdue (fires immediately)
  mark_run_started() / mark_run_failed(reason)
  is_due(now_ts) -> tuple[bool, str]   # (due?, reason: ok|paused|empty|not-due|busy)
  summary() -> str               # /series status text
  queue_text() -> str            # /series list text
```

**All mutations go through SeriesManager; handlers never hand-edit the JSON.**

### 1.3 Data model (`series/active.json`)

```json
{
  "series_id": "s_1728140400_ab12",
  "title": "Electricity Bill Hacks",
  "owner_chat_id": 123456789,
  "created_at": "2026-10-05T09:00:00+01:00",
  "schedule": {
    "enabled": true,
    "interval_hours": 24,
    "next_run": "2026-10-06T09:00:00+01:00",
    "anchor": "09:00",
    "timezone": "Africa/Lagos",
    "last_run": "2026-10-05T09:00:03+01:00",
    "last_result": "success"
  },
  "prompts": [
    {
      "id": "p001",
      "prompt": "Why your fridge adds ₦5,000 to your bill",
      "format": "narration",
      "status": "pending",
      "created_at": "2026-10-05T09:00:00+01:00"
    }
  ]
}
```

Notes:
- `status` is always `"pending"` in this scope (no partial/paused prompt states; failed runs just retry).
- `prompts[0]` is next in line; deletion-on-success keeps this invariant.
- Timestamps stored ISO-8601 with tz offset.

### 1.4 New commands (single `/series` dispatcher handler)

| Command | Behavior |
|---------|----------|
| `/series create <title>` | If an active series exists → inline ⚠️ confirm button before replacing. Creates empty series, sets `owner_chat_id` to issuing chat, schedule disabled by default. Replies with next-step help. |
| `/series add <prompt text>` | Auto-detect multi-line: split on newlines, one prompt per line (trimmed, empty lines skipped). Each prompt gets `id p###`, `format` from optional `--format narration\|description` flag (default `narration`), `status: pending`. Enforces 50-prompt cap per command and total. |
| `/series generate <N> <brief>` | Validate N (1–20) and remaining capacity. One **batch LLM call** (via `LLMService`, JSON mode) conditioned on **series title + brief** returns N ready prompts. Show the generated prompts as a numbered preview with an ✅ Add all / ❌ Discard inline choice, then append with per-prompt ids/`format`. Optional `--format` flag applies to all N. |
| `/series list` | Full queue: header (title, count), then every pending prompt as `p001 · narration · first ~80 chars…`. Notes cap usage (e.g. `12/50`). |
| `/series schedule <hours>` | Set `interval_hours` (allowed: 1–168, integers). `anchor` = None → next_run = now + interval. Then **ask via inline buttons**: "▶️ Generate next prompt now" / "⏰ Wait for first slot" (decision #5). |
| `/series schedule <hours> at HH:MM` | Anchor mode: runs every `<hours>` at wall-clock `HH:MM` in `SERIES_TIMEZONE`. Same button ask. |
| `/series pause` | `schedule.enabled = false`; replies with current next_run noted ("will fire immediately on resume if overdue"). |
| `/series resume` | `schedule.enabled = true`; if `next_run` already passed → leave overdue so the scheduler fires on next tick (decision #10); else keep. |
| `/series clear` | Inline ✅ confirm button showing `"<title>" (N prompts)` before wiping `active.json`. |
| `/series status` | Compact summary: enabled/paused, prompt count, interval, anchor, `next_run` rendered in `SERIES_TIMEZONE` local time (e.g. "next run: Oct 6, 09:00 (in 12h 3m)"), last result, last failure reason if any. |
| `/series run` | *(added in interview)* Generate the **next pending prompt immediately** via the automated path (no approval buttons). Refuses politely if a job is running, series is empty, or no series exists. Also advances `next_run`. |

Also: extend `/start` help text with a short series section.

Handler placement: `CommandHandler("series", series_command)` in both `main.py` and `app.py`; subcommand routing inside `bot/handlers.py::series_command`. A `SeriesCallbackHandler` pattern (or `sc_`-prefixed callback data routed through the existing `handle_callback`) covers confirm/discard buttons: `sc_confirm_create`, `sc_confirm_clear`, `sc_add_generated`, `sc_discard_generated`, `sc_run_now`, `sc_wait_slot`.

### 1.5 Scheduler

**Where:** `services/series_scheduler.py`, started as an `asyncio.create_task` in both `app.py::on_startup` (webhook) and `main.py` (polling), after the keep-alive pinger. Also runs under local dev.

**Loop (every ~120 s — "every few minutes"):**

1. `load()` the series file (tolerant of corruption → log warning, skip tick).
2. If no series, or schedule disabled, or queue empty, or not due → sleep, continue.
3. **Busy check (decision #1):** a module-level `_job_running` flag (set by the generation thread in `run_generation_sync`, cleared in its `finally`) or equivalent. If busy → leave `next_run` untouched; this tick just skips; run fires right after the slot frees.
4. **Missed-slot catch-up (decision #19):** if `now > next_run + grace (120 s)`, send `"⏰ Scheduled run was missed (bot was down) — generating now."` before generating. Catch-up happens only once per overdue `next_run` (mark it consumed).
5. Spawn the generation in a **background thread** (same `threading.Thread` pattern as `handle_callback` → `run_generation_sync`), passing the popped prompt + `owner_chat_id` + a `series_run` context object.
6. Sleep.

**Automated generation path (shares pipeline, skips approval):**

- Reuse `SceneGenerator.generate_all(prompt)` directly → **no preview, no Proceed/Regenerate buttons** (per instruction).
- Then call the existing `run_generation_sync(chat_id, scenes, narrations, metadata, job_id, video_format)` — extended with an optional `series_ctx=None` parameter rather than forked:
  - `series_ctx` = `{"k": <position>, "n": <pending_count>, "prompt_id": "p###", "title": <series title>}`
  - All progress messages prefixed `🎬 Series run k/n: …` (decision #15).
  - **On success (video uploaded):** `series_manager.pop_next()` has already removed the prompt *before* generation starts; if generation succeeds nothing more needed; if it **fails**, the prompt is **re-inserted at position 0** (decision #2: keep + retry next slot) and the owner gets the standard failure message plus "🔁 Will retry at next scheduled slot."
  - **On success also:** `advance_next_run()`, `schedule.last_result = "success"`, `save()`.
  - **Queue-emptied check:** after removing the prompt, if `len(prompts) == 0` → send the exact completion message from §1.1 to `owner_chat_id`. Schedule stays armed (decision #7).
  - Failure → `schedule.last_result = "failed: <reason[:100]>"`, owner notified, prompt re-inserted, `next_run` advanced (retry at next slot).

**Concurrency guard:** simple module-level boolean/lock around the slot check + claim (single-process bot on one Render instance; file lock not needed given `MAX_CONCURRENT_JOBS=1`).

**Render keep-alive compatibility:** scheduler is just another asyncio task in the same event loop as the pinger; it adds no new process/thread churn beyond per-run generation threads. Scheduler tick work is trivial (one file read).

### 1.6 Config additions (`config.py`)

```python
# Series / queue system
SERIES_DIR = os.getenv("SERIES_DIR", "series")
SERIES_FILE = os.getenv("SERIES_FILE", os.path.join(SERIES_DIR, "active.json"))
SERIES_MAX_PROMPTS = int(os.getenv("SERIES_MAX_PROMPTS", "50"))
SERIES_SCHEDULER_TICK_SECONDS = int(os.getenv("SERIES_SCHEDULER_TICK_SECONDS", "120"))
SERIES_TIMEZONE = os.getenv("SERIES_TIMEZONE", "Africa/Lagos")   # decision #16
SERIES_MAX_PROMPTS_PER_GENERATE = 20   # /series generate upper bound
```

`.env.example` gets the same keys with comments (timezone + cap documented).

### 1.7 Tests (extend `test_pipeline_logic.py`)

New section using `tempfile` to point `SERIES_FILE` at a temp path (and restoring after):

- create → add → pop order is FIFO; pop removes the prompt.
- 50-cap enforced (add rejects #51).
- Multi-line add splits correctly; `--format description` recorded per prompt.
- `advance_next_run` math: interval mode and anchor mode (e.g. `24h at 09:00` Africa/Lagos) — anchor math via a small injected tz helper (see 1.8).
- `is_due` returns correct reasons: paused / empty / not-due / due.
- Pause-then-overdue-resume → `is_due` fires immediately.
- Atomic save: no `.tmp` leftovers after save; corrupted JSON → `load()` returns None without raising.
- Completion message trigger condition (`prompts` empty after pop).

CI: no workflow change needed (decision #22 — same file, same command).

### 1.8 Timezone handling

No new dependency if possible: implement a minimal fixed-offset helper for the default `Africa/Lagos` (UTC+1, no DST) and fall back to UTC for unknown tz strings; **if** `zoneinfo` (Python 3.9+ stdlib) works on the Render image, prefer `zoneinfo.ZoneInfo(SERIES_TIMEZONE)` with a try/except to the fixed-offset fallback. (3.12 is the CI/runtime Python, so `zoneinfo` should be available; tzdata may need to be present — verify in Docker; if not, add `tzdata` to `requirements.txt`, it's tiny and pure-Python.)

---

## 2. Feature B — UnoRouter LLM provider

### 2.1 Research summary (verified 2026-10-05)

- **Endpoint:** OpenAI-compatible chat completions at `https://api.unorouter.com/v1` (i.e. POST `/v1/chat/completions`), Bearer-token auth.
- **Auth:** `UNOROUTER_API_KEY` (free account, no credit card).
- **Free models:** model IDs ending in `:free`. Current catalog (models.dev) free entries include: `gpt-5.4:free`, `gpt-5.5:free`, `deepseek-v4-flash:free`, `deepseek-v4-pro:free`, `glm-5.2:free`, `qwen3.5-397b-a17b:free`, `gemma-4-31b-it:free`, `glm-4.5-flash:free`, `minimax-m2.7:free`, `nemotron-3-ultra-550b-a55b:free`, `step-3.7-flash:free`.
- ⚠️ `gpt-oss-120b:free` (named in the original instruction) is **not** in the current catalog — hence the multi-model list decision (#13) instead of a single hardcoded `gpt-oss-120b:free`.
- **JSON/structured output:** several free models advertise structured-output support (e.g. `gpt-5.4:free`, `deepseek-v4-*:free`, `glm-5.2:free`, `qwen3.5:free`); others don't. The existing chain already guards this: `json_mode` providers get `response_format={"type":"json_object"}` and every caller has brace-slicing `extract_json()` fallback — so per-model `json_mode` flags are a best-effort optimization, not a correctness requirement.

### 2.2 Integration (`services/llm_service.py`)

- Import `UNOROUTER_API_KEY` + model list from `config.py`.
- **Chain order (decision #12):** `UnoRouter → Groq → Gemini → Pollinations → Bytez`.
- Provider entry:

```python
{
    "name": "UnoRouter",
    "url": "https://api.unorouter.com/v1/chat/completions",
    "key": UNOROUTER_API_KEY,
    "model": UNOROUTER_MODELS[0],      # first of the list
    "json_mode": True,                 # best-effort; brace-slicing fallback covers non-supporters
}
```

- **Multi-model behavior:** when `UNOROUTER_MODELS` has >1 entry, the UnoRouter step is *expanded* into one virtual provider entry per model (each `{"name": "UnoRouter (gpt-5.4:free)", ...}`); the loop's normal try/except falls through to the next model, then to Groq etc. This reuses the existing fallback loop with zero new machinery.
- One failing model must not poison the others; a 404 on a retired free model just logs a warning and moves on — same as today's provider failures.

### 2.3 Config additions (`config.py` + `.env.example`)

```python
# UnoRouter — OpenAI-compatible gateway (https://unorouter.com), free ":free" models.
# Free-tier catalog shifts over time -> UNOROUTER_MODELS is a comma-separated list
# tried in order; first that responds wins. Update if a model retires.
UNOROUTER_API_KEY = os.getenv("UNOROUTER_API_KEY", "")
UNOROUTER_MODELS = [
    m.strip() for m in os.getenv(
        "UNOROUTER_MODELS",
        "gpt-5.4:free,gpt-5.5:free,deepseek-v4-flash:free"
    ).split(",") if m.strip()
]
```

`.env.example` gains `UNOROUTER_API_KEY=your_unorouter_api_key_here` + `UNOROUTER_MODELS=...` with a short setup comment (create free account at unorouter.com → copy key).

### 2.4 Docs (`README.md`)

- Phase-1 key table: new `UNOROUTER_API_KEY` row (recommended, "free GPT/DeepSeek-class models; set as primary").
- New "Content Series" section: what it is, all 9 subcommands with examples, schedule + anchor examples, notification/catch-up behavior, Render-ephemeral-disk caveat (series file is lost on redeploy), 50-prompt cap.
- Pipeline description note: LLM chain order is now UnoRouter first.
- Technical notes: scheduler tick + MAX_CONCURRENT_JOBS interaction.

### 2.5 Tests

- Extend `test_pipeline_logic.py` LLM-chain section: with `UNOROUTER_API_KEY` unset → chain starts with Groq; with a fake key set in env → `llm.providers[0]["name"].startswith("UnoRouter")` and model == first of `UNOROUTER_MODELS`; multi-model expansion produces N UnoRouter entries in listed order followed by the 4 existing providers; `json_mode` flag True.
- No live-network test in CI (matches existing practice; `test_llm_fallbacks.py` remains the manual live harness and automatically covers UnoRouter because it iterates `llm.providers`).

---

## 3. Files touched (planned)

| File | Change |
|------|--------|
| `services/series_manager.py` | **NEW** — series state + logic (spec §1.2) |
| `services/series_scheduler.py` | **NEW** — asyncio background loop (spec §1.5) |
| `bot/handlers.py` | `series_command` dispatcher + series callbacks + `run_generation_sync(..., series_ctx=None)` extension + `_job_running` flag + `/start` help text |
| `services/llm_service.py` | UnoRouter provider entries + multi-model expansion (spec §2.2) |
| `config.py` | `SERIES_*` + `UNOROUTER_*` settings |
| `.env.example` | matching env keys + comments |
| `main.py` | register `/series` handler + start scheduler (polling mode) |
| `app.py` | register `/series` handler + start scheduler (webhook mode) |
| `test_pipeline_logic.py` | series_manager section + LLM-chain updates (spec §1.7, §2.5) |
| `README.md` | series feature + UnoRouter docs (spec §2.4) |
| `.gitignore` | add `series/` |
| `series/active.json.example` | **NEW** — schema reference |
| `requirements.txt` | possibly add `tzdata` (only if `zoneinfo` lacks tz db in Docker — verify first) |

**Untouched by design:** `services/scene_generator.py`, `image_generator.py`, `audio_processor.py`, `video_processor.py`, `utils/telegram_api.py`, existing `/gen` `/generate` `/status` `/testimage` behavior.

---

## 4. Implementation order (from the instruction)

1. **Series system first:** `series_manager.py` (+ tests) → handlers/commands → scheduler → wire into `app.py`/`main.py`.
2. **UnoRouter second:** config → `llm_service.py` chain → tests.
3. Docs last (README, .env.example), then full CI run.

## 5. Acceptance criteria

- [ ] `/gen` / `/generate` behavior byte-identical to today (preview + buttons).
- [ ] Single active series enforced; `series/active.json` is the only state store; atomic writes.
- [ ] Successful run removes its prompt; empty queue → exact completion message; schedule stays armed.
- [ ] All 9 `/series` subcommands work as specced (incl. `/series run`), with button confirms for create-replace and clear, and the "run now vs wait" ask after scheduling.
- [ ] Scheduler: 120 s tick, waits for idle job slot, catch-up + notify after downtime, advances `next_run`, respects interval/anchor + Africa/Lagos default, per-prompt format honored.
- [ ] Failed automated run keeps prompt at queue head and notifies; success deletes.
- [ ] UnoRouter first in chain, multi-model list with graceful per-model fallback, no regression to Groq/Gemini/Pollinations/Bytez.
- [ ] `python test_pipeline_logic.py` passes with the new sections; `python -m compileall` clean; CI green without live API calls.
- [ ] README + .env.example document both features.
