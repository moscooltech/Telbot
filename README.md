# 🤖 AI Viral Video Generator Bot (100% Free)

A fully automated Telegram bot that transforms a text prompt into a viral-ready TikTok/Reels video: coherent AI images, natural narration with **frame-accurate karaoke subtitles**, and a viral caption — all on free tiers, tuned for Render's free 512MB container.

---

## ✨ How It Works (Pipeline)

1. **Script (2-pass, aligned)** — the LLM first writes a *story spine* (motive, style bible, beats, hook, CTA), then writes every scene **from that spine** so scenes never drift off-topic. A cheap reviewer pass scores each scene 1–10 against the motive and auto-rewrites weak ones.
2. **Approval** — you get a script preview with ✅ Proceed / 🔄 Regenerate buttons.
3. **Images** — priority fallback chain: **Cloudflare Workers AI first when credentials are set** (`CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN`, free): FLUX.2 klein 4B (photorealistic, best prompt adherence) → SDXL → keyed Pollinations (real Flux; needs `POLLINATIONS_API_KEY`) → Gemini Nano Banana (paid only — zero free-tier image quota) → keyless Pollinations (always works, but weak cartoonish "sana" model — last-resort safety net) → Bytez. Photorealism is enforced with a negative prompt (no cartoon/anime/illustration) and a photo-style suffix by default — overridable per image with an inline **`/mode`** directive ([Image Styles](#-image-styles-inline-mode-directives)). Coherence comes from the **style bible + one seed per job**, while every scene is prompted as **its own moment** (different place, action and camera shot — see [Scene variety](#-scene-variety)), so the video is not one frame re-rendered.
4. **Voice** — edge-tts (`en-US-AndrewMultilingualNeural` by default, configurable via `TTS_VOICE`/`TTS_RATE`), with loudness normalization (-14 LUFS) and gTTS fallback. **Real word-level timings** are captured from the TTS engine.
5. **Video** — per-scene clips with **TikTok-style karaoke subtitles**: words appear in 2–3 word chunks and the current word highlights **in perfect sync with the voice** (timings come from the TTS engine itself, not estimates). Bold font, safe-zone positioning, static-subtitle fallback if libass ever fails.
6. **Assembly** — stream-copy concat (≈0 RAM) + audio mux, uploaded to Telegram with caption + hashtags.

## 🚀 Setup Guide

### Phase 1: API Keys (Free)

| Key | Where | Required |
|---|---|---|
| `TELEGRAM_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` | ✅ |
| `UNOROUTER_API_KEY` | [unorouter.com](https://unorouter.com/) — **primary LLM**: OpenAI-compatible gateway with free GPT/DeepSeek/GLM models (free account, no credit card). Tried first so series automation doesn't burn Groq's 1k/day quota. Optional `UNOROUTER_MODELS` overrides the free-model list (tried in order). | recommended |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com/) (free tier: gpt-oss-120b) | recommended |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com/) (free tier: gemini-2.5-flash) | recommended |
| `POLLINATIONS_API_KEY` | [pollinations.ai](https://pollinations.ai/) — **recommended for images**: the key unlocks real Flux on gen.pollinations.ai, tried first. Without a key, the bot still works via the keyless legacy endpoint (weaker cartoonish "sana" model) | recommended |
| `BYTEZ_API_KEY` | [bytez.com](https://bytez.com/) — optional last-resort image fallback (SDXL) and LLM fallback | optional |
| `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` | [Cloudflare](https://dash.cloudflare.com/) Workers AI (SDXL): dash.cloudflare.com → Workers AI → **"Use REST API"** → "Create a Workers AI token" (skips the confusing policy screen); Account ID is in the Workers & Pages dashboard right sidebar | optional |

At least one LLM key is required. When `UNOROUTER_API_KEY` is set it is tried first, then Groq → Gemini → Pollinations → Bytez, each with automatic fallback.

### Phase 2: Deploy on Render (Free Tier)

1. Push this repo to GitHub.
2. Render → **New +** → **Web Service** → connect the repo.
3. **Runtime: Docker** (installs ffmpeg + fonts automatically), Instance Type: **Free**.
4. Add the environment variables from `.env.example` (at minimum `TELEGRAM_TOKEN` + one LLM key). Set `WEBHOOK_URL` to your service URL (e.g. `https://my-bot.onrender.com`).
5. Deploy. The bot registers its own webhook on startup and self-pings to avoid sleeping.

Local development alternative: `python main.py` (polling mode — no webhook needed).

### Phase 3: Use It

```
/start
/gen A story about a lost astronaut on a neon planet
/gen 10 scenes explaining how black holes work --format narration
```

- `--format narration` → voiceover + subtitles (default)
- `--format description` → on-screen scene descriptions, no voiceover

Wait 2–4 minutes on the free tier. You get a 9:16 MP4 with burned-in karaoke subtitles plus a ready-to-paste caption and hashtags.

### Phase 4: More Commands

```
/status     — show the image provider fallback order + last job's winner
/testimage  — generate ONE image with a provider you pick from buttons,
              then send it back so you can judge quality before a full video
```

`/testimage` is the fastest way to compare providers (e.g. Cloudflare FLUX.2 klein vs. the keyless fallback) without spending a whole video generation on it. Add a style to preview it: `/testimage /diagram`.

## 🎨 Image Styles (inline `/mode` directives)

Every image renders as a **photorealistic photo by default**. Some topics need the opposite — an illustration, a design/spec sheet, an exploded (item-decomposition) view, a technical schematic or a typographic poster — so a prompt may start with **one** directive and that image is rendered that way instead:

| Directive | Renders |
|---|---|
| `/illustration` | drawn / editorial art |
| `/design` (alias `/spec`) | design or specification sheet, labelled callouts |
| `/decompose` (alias `/exploded`) | exploded view / item decomposition |
| `/diagram` (alias `/schematic`) | technical schematic, labelled parts |
| `/poster` | graphic poster with typography |
| `/photo` | the default photorealistic look (forces a photo back) |

**Whole video** — put the directive first in the prompt:

```
/gen /decompose how a diesel engine works
/series add /illustration the water cycle explained for kids
```

**One image** — the script LLM may also attach a directive to a single scene when it judges a photo would be wrong (a mechanism diagram, an exploded view, a spec sheet…). It is told to use them **sparingly** and never more than one per prompt. An inline directive in a scene **overrides** the job-wide one, so `/gen /illustration …` plus one `/diagram` scene gives you exactly one diagram. Set `ENABLE_LLM_IMAGE_MODES=false` to stop the LLM choosing modes yourself and only honour the directives you type.

What a mode actually swaps, for the images it applies to:

| | photo (default) | non-photo modes |
|---|---|---|
| style suffix | `IMAGE_STYLE_SUFFIX` (photorealistic, DSLR…) | the mode's own style words |
| negative prompt | `IMAGE_NEGATIVE_PROMPT` (bans cartoon/anime/illustration/**text**) | `IMAGE_NEGATIVE_CORE` + mode bans — **text/labels allowed**, drawings allowed |
| klein reference image | only if `ENABLE_IMAGE_ANCHOR=true` (keeps the same character) | no (a photo reference would fight a schematic) |

The directive is stripped before anything reaches an image provider, so providers never see a slash command. Modes are data: `IMAGE_MODES` in `config.py`.

## 🎞️ Scene Variety

Coherence and variety are two different things, and getting the balance wrong is what turns a video into **one image edited over and over**. Two rules keep them apart:

- **Each scene is its own moment.** The script LLM must move the story forward and change the **place, action and camera shot** between scenes, and the prompt-polish pass must vary the shot list (wide establishing → medium → close-up) instead of re-describing the previous frame. The style bible pins the *look* (art style, palette, lighting, lens) — never the location or the framing.
- **The klein reference image is OFF by default.** `ENABLE_IMAGE_ANCHOR=false` (default) sends no reference image, so every scene is generated from its own prompt. Set `ENABLE_IMAGE_ANCHOR=true` only for a character-driven video where one person must look identical in every scene — on a 4-step distilled model like FLUX.2 klein a reference image outranks the text prompt, which is exactly what makes later scenes come back as near-copies of scene 1.

Scene ↔ image ↔ narration pairing is **index-stable**: a scene is only kept if both its image and its narration rendered. A failed image (or a failed TTS line) drops that whole scene — image, clip, narration audio, subtitles — instead of shifting every later scene onto the previous scene's image and the next scene's duration/subtitle timings. The prompt-polish pass also sees each scene's narration, so the image presents what that scene actually says.

## 📺 Content Series (Queue + Auto-Schedule)

Queue up a batch of prompts once, then let the bot generate them one at a time on a recurring schedule — hands-off content. State lives in `series/active.json` (one active series at a time).

**Typical flow**

```
/series create Mind-bending physics
/series add Why time slows near a black hole
/series add The double-slit experiment as a security camera
/series schedule 24 at 09:00        → one video/day at 9am (Africa/Lagos)
```

After `/series schedule`, the bot asks whether to **generate the next prompt now** or **wait for the first slot**. Progress messages are prefixed `🎬 Series run k/n:`.

**Subcommands**

| Command | What it does |
|---|---|
| `/series` or `/series help` | Show this help. |
| `/series create <title>` | Start a series (asks before replacing an existing one). Sets the owner chat for notifications. |
| `/series add <text>` | Add prompt(s). Paste multi-line text → **one prompt per line** (blank lines skipped). Optional `--format narration\|description`. |
| `/series generate <N> <brief>` | AI expands a brief into N distinct prompts, previews them, and queues them all on confirm. |
| `/series list` | Show every queued prompt. |
| `/series schedule <hours> [at HH:MM]` | Auto-generate every N hours, optionally anchored to a wall-clock time in `SERIES_TIMEZONE`. |
| `/series pause` / `/series resume` | Suspend/resume the schedule (an overdue run fires immediately on resume). |
| `/series run` | Generate the next queued prompt immediately. |
| `/series status` | Compact summary: state, pending count, next run, last result. |
| `/series clear` | Delete the series (asks for confirmation). |

**How runs behave**

- One video at a time — a due run waits for the idle job slot (queue order preserved).
- A **failed** run keeps its prompt at the head of the queue and retries at the next scheduled slot.
- When the last prompt is used, the bot sends: `✅ Series complete! All prompts have been used. Use /series create <title> to start a new series.` The schedule stays armed for the new series.
- If the bot was down past a scheduled slot, it notifies you and generates on the next tick.
- Queue is capped at `SERIES_MAX_PROMPTS` (default 50).

> ⚠️ **Ephemeral disk on Render free tier:** `series/active.json` is wiped on every redeploy/restart. Re-add your prompts (or seed from `series/active.json.example`) after a deploy. Timezone defaults to `Africa/Lagos` (`SERIES_TIMEZONE`).

## 🛠️ Technical Notes

- **JSON mode** is enabled on UnoRouter/Groq/Gemini for reliable script output, with brace-slicing extraction as backup.
- **Fonts**: the Docker image ships DejaVu fonts; libass resolves the bold face automatically. Drop a `.ttf` in `assets/fonts/` to override.
- **RAM safety**: 720×1280 renders, 1 concurrent job, stream-copy assembly, per-clip 90–120s timeouts.
- **Tuning**: `SUBTITLE_WORDS_PER_CHUNK` (2), `SUBTITLE_FONT_SIZE` (54), `SUBTITLE_MARGIN_V` (210), `TTS_RATE` (+5%) — see `.env.example`.
- **Optional offline TTS**: set `ENABLE_PIPER=true` + `PIPER_VOICE_PATH` to add a Piper fallback between edge-tts and gTTS.
- Background music: drop `.mp3` files in `assets/music/` (mixed at 30% volume).
- **Content series**: state + scheduler in `services/series_manager.py` / `series_scheduler.py`; the run loop reuses the same `SceneGenerator` + `run_generation_sync` pipeline as `/gen`.
- **Image styles**: one source of truth — `IMAGE_MODES` / `IMAGE_MODE_ALIASES` in `config.py` (style suffix, negative prompt and klein-anchor flag per mode); `parse_image_mode()` in `services/image_generator.py` resolves a mode per scene (`ImageGenerator._resolve_mode`), and `services/scene_generator.py` tells the script LLM it may emit a directive.
- **Scene variety**: `ENABLE_IMAGE_ANCHOR` (default `false`) decides whether the job's first image is reused as a klein reference; `services/scene_generator.py` requires a distinct moment/place/shot per scene. `bot/handlers.py::_picked_pairs` / `_drop_unvoiced_scenes` keep scene ↔ image ↔ narration index-aligned when a scene is skipped.

## ⚠️ Free Tier Notes

- Render free instances sleep after 15 min idle; the bot self-pings every 14 min, but a cold start needs a moment.
- One video is generated at a time globally to stay within the 512MB limit.
- Groq free tier: 30 req/min, 1,000 req/day (gpt-oss-120b replaced Llama 3.3 on 2026-08-16). `UNOROUTER_API_KEY`, when set, is tried first so scheduled series runs don't consume that quota.

## 📜 License

Open source. Tweak the prompts in `services/scene_generator.py` to change the video style.
