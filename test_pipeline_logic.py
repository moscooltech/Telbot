"""
Unit checks for the pure-Python logic of the new pipeline components.
Run: python3 verify_logic.py
No network or ffmpeg required. Safe to delete afterwards.
"""
import json
import os
import sys

os.environ.setdefault("TELEGRAM_TOKEN", "123:test")

PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"  PASS {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


print("== 1. config sanity ==")
import config
check("groq model is gpt-oss (llama removed from free tier)", "gpt-oss" in config.GROQ_MODEL, config.GROQ_MODEL)
check("gemini model is 2.5 (1.5 shut down)", "2.5" in config.GEMINI_MODEL, config.GEMINI_MODEL)
check("BYTEZ models split (no overwrite bug)", config.BYTEZ_LLM_MODEL != config.BYTEZ_IMAGE_MODEL)
check("tts voice default", "Andrew" in config.TTS_VOICE, config.TTS_VOICE)
check("subtitle chunk size sane", 1 <= config.SUBTITLE_WORDS_PER_CHUNK <= 5)
check("series cap is 50", config.SERIES_MAX_PROMPTS == 50, config.SERIES_MAX_PROMPTS)
check("series completion message exact",
      config.SERIES_COMPLETE_MESSAGE ==
      "\u2705 Series complete! All prompts have been used. Use /series create <title> to start a new series.",
      config.SERIES_COMPLETE_MESSAGE)

print("== 2. llm_service provider chain ==")
import services.llm_service as _llm_mod
from services.llm_service import LLMService
llm = LLMService()
nu = len(config.UNOROUTER_MODELS)   # uno is expanded to one virtual provider per model
check("uno entries + 4 base providers", len(llm.providers) == nu + 4, str(len(llm.providers)))
check("uno first in chain", llm.providers[0]["name"].startswith("UnoRouter"), llm.providers[0]["name"])
check("uno models in configured order",
      [p["model"] for p in llm.providers[:nu]] == config.UNOROUTER_MODELS)
check("uno hits api.unorouter.com v1",
      all("api.unorouter.com/v1" in p["url"] for p in llm.providers[:nu]))
check("uno json_mode on", all(p["json_mode"] for p in llm.providers[:nu]))
check("groq after uno block",
      llm.providers[nu]["name"] == "Groq" and llm.providers[nu]["model"] == config.GROQ_MODEL)
check("gemini after groq", llm.providers[nu + 1]["name"] == "Gemini")
check("bytez uses TEXT model (not SDXL)", llm.providers[nu + 3]["model"] == config.BYTEZ_LLM_MODEL)
check("json_mode flagged for groq+gemini",
      llm.providers[nu]["json_mode"] and llm.providers[nu + 1]["json_mode"])

# Key gating: with a fake UnoRouter key its entries become the first ACTIVE
# providers; without it the chain falls through to the keyed providers after.
_saved_uno_key = _llm_mod.UNOROUTER_API_KEY
try:
    _llm_mod.UNOROUTER_API_KEY = "fake-key-123"
    llm2 = _llm_mod.LLMService()
    active = [p for p in llm2.providers if p["key"]]
    names = [p["name"] for p in active]
    check("fake key -> uno entries active first",
          len(active) >= nu and names[0].startswith("UnoRouter") and active[0]["key"] == "fake-key-123",
          str(names[:3]))
    if "Groq" in names:
        check("groq behind active uno", names.index("Groq") >= nu, str(names))
    else:
        check("active chain is uno-only when no other keys", len(active) == nu, str(names))
finally:
    _llm_mod.UNOROUTER_API_KEY = _saved_uno_key

print("== 3. scene_generator logic ==")
from services.scene_generator import detect_scene_count, clean_narration, extract_json
check("detect '10 scenes'", detect_scene_count("make a story with 10 scenes") == (9, 11))
check("detect 'short'", detect_scene_count("a quick story about cats") == (2, 4))
check("detect none", detect_scene_count("a story about cats") is None)
check("clean_narration joins spaced letters", clean_narration("e a c h word") == "each word", clean_narration("e a c h word"))
check("clean_narration keeps two-letter words", "us in" in clean_narration("us in the city"))
check("extract_json plain", extract_json('{"a": 1}') == {"a": 1})
check("extract_json fenced", extract_json('```json\n{"a": 1}\n```') == {"a": 1})
check("extract_json with prose", extract_json('Here you go:\n{"a": 1}\nDone.') == {"a": 1})

print("== 3.5 image prompt quality ==")
from services.image_generator import ImageGenerator
from services.scene_generator import SceneGenerator

ig = ImageGenerator("verify_prompt_job", style_bible="a red fox, watercolor style, soft light")
check("commas kept in prompt", ig._clean_prompt("a fox, running, forest") == "a fox, running, forest",
      ig._clean_prompt("a fox, running, forest"))
check("quotes stripped", '"' not in ig._clean_prompt('a "fox" \' runs\''))
check("newlines collapsed", "\n" not in ig._clean_prompt("a fox\nruns"))
check("word cap enforced", len(ig._clean_prompt(" ".join(["word"] * 100)).split()) <= config.IMAGE_PROMPT_MAX_WORDS)
check("prompt cap raised to 60", config.IMAGE_PROMPT_MAX_WORDS >= 60, config.IMAGE_PROMPT_MAX_WORDS)

built = ig._build_prompt("a fox, running, forest")
check("style bible fused into prompt", "watercolor style" in built, built)
check("quality suffix present", built.endswith("high quality, detailed, professional, 4k"), built)

check("prompt polish enabled", config.ENABLE_PROMPT_POLISH)
check("pollinations enhance off", not config.POLLINATIONS_ENHANCE)

# Polish pass: good LLM output replaces descriptions, garbage falls back gracefully
class FakeLLMGood:
    def generate_text(self, *a, **k):
        return ('{"prompts": ["a red fox, leaping over rocks, misty pine forest, wide shot, '
                'soft morning light, watercolor style", "bad words"]}')

class FakeLLMBad:
    def generate_text(self, *a, **k):
        return "not json at all"

sg = SceneGenerator.__new__(SceneGenerator)
raw_scenes = [{"description": "desc one"}, {"description": "desc two"}]

sg.llm = FakeLLMGood()
polished = sg._polish_visuals({"motive": "m", "style_bible": "x"}, raw_scenes)
check("polish returns same scene count", isinstance(polished, list) and len(polished) == 2, str(polished))
check("polished prompt keeps style identity", "watercolor" not in polished[0] or "red fox" in polished[0])

sg.llm = FakeLLMBad()
try:
    sg._polish_visuals({"motive": "m", "style_bible": "x"}, raw_scenes)
    check("polish raises on garbage LLM output", False)
except Exception:
    check("polish raises on garbage LLM output", True)  # generate_all catches this and falls back

print("== 4. video_processor ASS karaoke ==")
from services.video_processor import VideoProcessor
vp = VideoProcessor("verify_job")
check("font resolution (dejavu or default)", vp.fontfile is None or os.path.exists(vp.fontfile), vp.fontfile)
check("ass time format", VideoProcessor._ass_time(65.5) == "0:01:05.50", VideoProcessor._ass_time(65.5))
check("ass time clamps negatives", VideoProcessor._ass_time(-3) == "0:00:00.00")
check("ass escapes braces", VideoProcessor._ass_escape("{hi}") == "(hi)")

words = ["Hello", "amazing", "world", "today"]
times = [(0.0, 0.5), (0.5, 1.2), (1.2, 1.9), (1.9, 2.6)]
chunks = vp._build_chunks(words, times, chunk_size=2)
check("chunking produces 2 chunks", len(chunks) == 2, str(len(chunks)))
check("chunk 1 covers words 1-2", [w for w, _, _ in chunks[0]["words"]] == ["Hello", "amazing"])
check("chunk 2 covers words 3-4", [w for w, _, _ in chunks[1]["words"]] == ["world", "today"])
check("chunk end does not overlap next", chunks[0]["end"] <= chunks[1]["start"] + 1e-9,
      f"{chunks[0]['end']} vs {chunks[1]['start']}")

kt = vp._karaoke_tag(chunks[0])
check("karaoke tags present", "\\k" in kt, kt)
check("karaoke highlight order", kt.index("Hello") < kt.index("amazing"), kt)

ass_path = vp.generate_ass("Hello amazing world today", words, times, 2.6, 0)
check("ass file written", ass_path and os.path.exists(ass_path))
content = open(ass_path, encoding="utf-8").read()
check("ass header has PlayRes", f"PlayResX: {config.IMAGE_WIDTH}" in content)
check("ass style has karaoke colors", config and "SecondaryColour" in content)
check("ass margin respects safe zone", f",{config.SUBTITLE_MARGIN_V},1" in content)

# estimated timing path (no TTS data)
est = vp._estimate_word_timing(words, 4.0)
check("estimate covers 4 words", len(est) == 4)
check("estimate monotonic", all(est[i][1] <= est[i + 1][0] + 1e-9 for i in range(3)))

print("== 5. audio_processor timing conversion ==")
from services.audio_processor import AudioProcessor
ap = AudioProcessor("verify_job")
import asyncio
import unittest.mock as mock

# Direct call against the real method with a stubbed communicate
class FakeCommunicate:
    def __init__(self, *a, **k):
        pass
    async def stream(self):
        yield {"type": "audio", "data": b"ID3fake"}
        yield {"type": "WordBoundary", "offset": 10_000_000, "duration": 3_000_000, "text": "hello"}
        yield {"type": "WordBoundary", "offset": 4_500_000, "duration": 2_500_000, "text": "world"}

async def run_capture():
    tmp = os.path.join(ap.audio_dir, "cap.mp3")
    return await ap._generate_edge_tts("hello world test", tmp)

with mock.patch("services.audio_processor.edge_tts.Communicate", FakeCommunicate):
    words_out = asyncio.run(run_capture())
check("two word boundaries captured", len(words_out) == 2, str(words_out))
check("tick->sec conversion", abs(words_out[0]["start"] - 1.0) < 0.01 and abs(words_out[0]["end"] - 1.3) < 0.01, str(words_out[0]))
check("second word timing", abs(words_out[1]["start"] - 0.45) < 0.01 or abs(words_out[1]["start"] - 4.5) < 0.01, str(words_out[1]))

print("== 6. caption length enforcement ==")
from services.scene_generator import SceneGenerator

spine = {
    "motive": "Show how deep-sea creatures survive crushing pressure",
    "style_bible": "cinematic underwater photography",
    "hook": "Three kilometers down, the pressure would crush a car in seconds.",
    "cta": "Follow for more ocean mysteries.",
}

# Empty LLM caption -> hook + cta + motive must clear the 200-char minimum
grown = SceneGenerator._build_long_caption("", spine, "deep sea creatures")
check("empty caption grows past minimum", len(grown) >= config.MIN_CAPTION_CHARS,
      f"len={len(grown)}")
check("grown caption includes hook", "crush a car" in grown, grown[:80])
check("grown caption includes cta", "Follow for more" in grown, grown[-80:])

# Short placeholder caption -> padded, original text kept
padded = SceneGenerator._build_long_caption("So cool!", spine, "deep sea creatures")
check("short caption padded", len(padded) >= config.MIN_CAPTION_CHARS, f"len={len(padded)}")
check("original text preserved", padded.startswith("So cool!"), padded[:20])

# Already-long caption -> returned untouched
long_caption = ("This video dives into the abyssal zone where sunlight never reaches, "
                "revealing bioluminescent hunters and creatures that look alien to us. "
                "Scientists keep finding new species here every single year, which makes "
                "you wonder what else is hiding in the dark. Watch until the end!")
check("long caption untouched", len(long_caption) >= config.MIN_CAPTION_CHARS)
check("long caption unchanged", SceneGenerator._build_long_caption(long_caption, spine, "x") == long_caption)

# Weak spine (empty fields) + empty caption -> boilerplate filler saves it
weak = SceneGenerator._build_long_caption("", {"motive": "", "hook": "", "cta": ""}, "the topic")
check("weak spine still reaches minimum", len(weak) >= config.MIN_CAPTION_CHARS,
      f"len={len(weak)}")

# Duplicates never appended
no_dup = SceneGenerator._build_long_caption(spine["hook"], spine, "deep sea creatures")
check("no duplicate hook", no_dup.count(spine["hook"]) == 1, no_dup[:120])

print("== 7. series_manager state machine ==")
import shutil
import tempfile
from datetime import datetime, timedelta
from services.series_manager import (
    SeriesManager, _tz, _anchor_seconds_past_midnight, _next_anchor_time,
    REASON_OK, REASON_NOT_DUE, REASON_PAUSED, REASON_EMPTY, REASON_NO_SERIES,
)

_tmpdir = tempfile.mkdtemp(prefix="series_test_")
sfile = os.path.join(_tmpdir, "active.json")
mgr = SeriesManager(file_path=sfile)
try:
    # create / load roundtrip
    data = mgr.create("Test Series", 42)
    check("create writes file", os.path.exists(sfile))
    check("create has empty queue", data["prompts"] == [])
    check("create schedule disabled", data["schedule"]["enabled"] is False)
    check("create owner chat id stored", data["owner_chat_id"] == 42)
    check("load roundtrip", mgr.load() == data)
    check("no tmp leftovers after save",
          not [f for f in os.listdir(_tmpdir) if f.endswith(".tmp")], str(os.listdir(_tmpdir)))

    # corrupt / invalid files degrade to None
    badfile = os.path.join(_tmpdir, "bad.json")
    with open(badfile, "w") as f:
        f.write("{not json")
    check("corrupt json -> None", SeriesManager(file_path=badfile).load() is None)
    check("missing file -> None",
          SeriesManager(file_path=os.path.join(_tmpdir, "nope.json")).load() is None)
    with open(badfile, "w") as f:
        json.dump({"title": "x", "prompts": [{"bad": 1}], "schedule": {}}, f)
    check("structurally invalid -> None", SeriesManager(file_path=badfile).load() is None)

    # add / pop FIFO + ids resequenced
    mgr.add_prompt(data, "first prompt")
    ok, reason = mgr.add_prompt(data, "second prompt", fmt="description")
    check("add_prompt ok", ok and reason == "ok")
    check("per-prompt format stored", data["prompts"][1]["format"] == "description")
    ok, reason = mgr.add_prompt(data, "third prompt", fmt="bogus")
    check("invalid format coerced to narration", data["prompts"][2]["format"] == "narration")
    popped = mgr.pop_next(data)
    check("pop is FIFO", popped["prompt"] == "first prompt", str(popped))
    check("resequence after pop", data["prompts"][0]["id"] == "p001")
    check("empty queue pop -> None", mgr.pop_next({"prompts": []}) is None)

    # failed run: reinsert at head keeps retry-first ordering
    mgr.reinsert_front(data, popped)
    check("reinsert at head", data["prompts"][0]["prompt"] == "first prompt")
    check("reinsert resets status pending", data["prompts"][0]["status"] == "pending")
    check("reinsert resequences", data["prompts"][0]["id"] == "p001")

    # 50-prompt hard cap
    cap = mgr.create("Cap", 1)
    for i in range(config.SERIES_MAX_PROMPTS):
        mgr.add_prompt(cap, "p%d" % i)
    ok, reason = mgr.add_prompt(cap, "one too many")
    check("cap enforced at 50", not ok and reason == "cap", str((ok, reason)))
    check("cap count exact", len(cap["prompts"]) == config.SERIES_MAX_PROMPTS)

    # run_position labels (uses runs_completed)
    pos = mgr.create("Pos", 1)
    for i in range(3):
        mgr.add_prompt(pos, "q%d" % i)
    mgr.pop_next(pos)
    check("run_position first of 3", mgr.run_position(pos) == (1, 3), str(mgr.run_position(pos)))
    mgr.mark_run_succeeded(pos)
    mgr.pop_next(pos)
    check("run_position second of 3", mgr.run_position(pos) == (2, 3), str(mgr.run_position(pos)))
    mgr.mark_run_failed(pos, "boom")
    check("failed retry keeps k label", mgr.run_position(pos) == (2, 3), str(mgr.run_position(pos)))
    check("failed reason stored", pos["schedule"]["last_failure"] == "boom")

    # schedule: enable + next_run + is_due reasons
    check("no series -> not due", mgr.is_due(None) == (False, REASON_NO_SERIES))
    due, reason = mgr.is_due(pos)
    check("disabled schedule -> paused", (due, reason) == (False, REASON_PAUSED), str((due, reason)))
    mgr.set_schedule(pos, interval_hours=24, enabled=True)
    check("set_schedule enables", pos["schedule"]["enabled"] is True)
    check("set_schedule sets next_run", bool(pos["schedule"]["next_run"]))
    due, reason = mgr.is_due(pos)
    check("future next_run -> not due", (due, reason) == (False, REASON_NOT_DUE), str((due, reason)))
    pos["schedule"]["next_run"] = (datetime.now(_tz()) - timedelta(minutes=5)).isoformat()
    due, reason = mgr.is_due(pos)
    check("overdue -> due", (due, reason) == (True, REASON_OK), str((due, reason)))

    # enabled + never scheduled fires immediately
    unsched = mgr.create("Unsched", 1)
    mgr.add_prompt(unsched, "x")
    unsched["schedule"]["enabled"] = True
    check("enabled+unscheduled fires", mgr.is_due(unsched) == (True, REASON_OK))

    # empty queue blocks firing even when overdue
    emptyq = mgr.create("EmptyQ", 1)
    mgr.set_schedule(emptyq, interval_hours=1, enabled=True)
    emptyq["schedule"]["next_run"] = (datetime.now(_tz()) - timedelta(minutes=5)).isoformat()
    check("empty queue -> not due", mgr.is_due(emptyq) == (False, REASON_EMPTY), str(mgr.is_due(emptyq)))

    # pause / resume: overdue next_run survives and fires immediately
    pos["schedule"]["enabled"] = False
    check("pause blocks overdue", mgr.is_due(pos) == (False, REASON_PAUSED))
    mgr.resume(pos)
    check("resume keeps overdue -> fires", mgr.is_due(pos) == (True, REASON_OK))

    # missed-slot detection + consume-once
    pos["schedule"]["next_run"] = (datetime.now(_tz()) - timedelta(hours=3)).isoformat()
    check("missed slot detected", mgr.is_missed_slot(pos, grace_seconds=120))
    mgr.clear_missed_slot(pos)
    check("clear_missed_slot stops repeat", not mgr.is_missed_slot(pos, grace_seconds=120))

    # anchor math
    check("anchor seconds", _anchor_seconds_past_midnight("09:30") == 9 * 3600 + 30 * 60)
    check("anchor bad -> None", _anchor_seconds_past_midnight("99:99") is None)
    tz = _tz()
    nxt = _next_anchor_time(datetime(2026, 10, 9, 10, 0, tzinfo=tz), 24, "09:00")
    check("anchor passed today -> tomorrow", (nxt.day, nxt.hour, nxt.minute) == (10, 9, 0), str(nxt))
    nxt = _next_anchor_time(datetime(2026, 10, 9, 8, 0, tzinfo=tz), 24, "09:00")
    check("anchor later today stays today", (nxt.day, nxt.hour) == (9, 9), str(nxt))
    nxt = _next_anchor_time(datetime(2026, 10, 9, 10, 0, tzinfo=tz), 48, "09:00")
    check("anchor honors 48h interval", (nxt.day, nxt.hour) == (11, 9), str(nxt))
    anch = mgr.create("Anchor", 1)
    mgr.add_prompt(anch, "x")
    mgr.set_schedule(anch, interval_hours=24, anchor="09:00", enabled=True)
    from services.series_manager import _parse_iso
    adt = _parse_iso(anch["schedule"]["next_run"])
    check("anchored next_run lands at 09:00 local",
          adt.astimezone(tz).strftime("%H:%M") == "09:00", str(adt))
    badanch = mgr.set_schedule(anch, anchor="99:99")
    check("invalid anchor cleared", badanch["anchor"] is None)

    # interval advance lands ~interval from now
    adv = mgr.create("Adv", 1)
    mgr.set_schedule(adv, interval_hours=6)
    dt6 = _parse_iso(adv["schedule"]["next_run"])
    delta_h = (dt6 - datetime.now(tz)).total_seconds() / 3600
    check("6h interval advance", 5.8 < delta_h < 6.1, str(delta_h))

    # completion condition: queue empty after final pop
    fin = mgr.create("Fin", 1)
    mgr.add_prompt(fin, "last one")
    mgr.mark_run_started(fin)
    last = mgr.pop_next(fin)
    mgr.mark_run_succeeded(fin)
    check("complete when queue empty after pop", len(mgr.pending_prompts(fin)) == 0)
    check("runs_completed incremented", fin["schedule"]["runs_completed"] == 1)
    check("last_result success", fin["schedule"]["last_result"] == "success")

    # display text smoke
    check("queue_text lists prompts", "p001" in mgr.queue_text(cap))
    check("summary_text has title", "Cap" in mgr.summary_text(cap))
finally:
    shutil.rmtree(_tmpdir, ignore_errors=True)

print("== 8. /series arg parsing ==")
# Importing bot.handlers pulls telegram + edge-tts; slow but CI installs requirements.
from bot.handlers import _parse_series_args, _series_add_payload
sub, rest, fmt = _parse_series_args(["add", "hello", "world"])
check("parse: sub + rest", sub == "add" and rest == ["hello", "world"])
sub, rest, fmt = _parse_series_args(["add", "--format", "description", "x"])
check("parse: --format stripped", fmt == "description" and rest == ["x"], str((rest, fmt)))
payload, fmt = _series_add_payload("/series add line one\nline two")
check("add payload keeps newlines", payload == "line one\nline two", repr(payload))
check("add payload default fmt", fmt == "narration")
payload, fmt = _series_add_payload("/series add --format description a\nb")
check("add payload strips leading --format", payload == "a\nb" and fmt == "description", repr((payload, fmt)))
payload, fmt = _series_add_payload("/series add single line --format narration")
check("add payload strips trailing --format", payload == "single line" and fmt == "narration", repr((payload, fmt)))
payload, fmt = _series_add_payload("/series add")
check("add payload bare command empty", payload == "")
payload, fmt = _series_add_payload("/series add p1\n\np2\np3")
check("add payload skips blank lines downstream", [l for l in payload.split("\n") if l.strip()] == ["p1", "p2", "p3"], repr(payload))

print("== 9. /gen inline /mode wiring ==")
import asyncio
from unittest import mock as _mock
from config import TEMP_DIR
import bot.handlers as _handlers
from services.image_generator import parse_image_mode

check("parse: topic unchanged without a directive",
      parse_image_mode("how a diesel engine works") == (None, "how a diesel engine works"))
check("parse: /decompose split off",
      parse_image_mode("/decompose how a diesel engine works")
      == ("decompose", "how a diesel engine works"))


class _FakeMessage:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)


class _FakeUpdate:
    def __init__(self):
        self.message = _FakeMessage()
        self.effective_chat = type("Chat", (), {"id": 4242})()
        self.effective_user = type("User", (), {"id": 7})()


class _FakeContext:
    def __init__(self, args):
        self.args = args


_seen = {}


class _FakeSceneGenerator:
    def generate_all(self, prompt):
        _seen["topic"] = prompt
        return (["scene one"], ["narr one"],
                {"style_bible": "s", "caption": "c", "hashtags": "#x"})


def _newest_job_file():
    os.makedirs(TEMP_DIR, exist_ok=True)
    files = [os.path.join(TEMP_DIR, f) for f in os.listdir(TEMP_DIR)
             if f.startswith("job_7_") and f.endswith(".json")]
    return max(files, key=os.path.getmtime) if files else None


_update = _FakeUpdate()
with _mock.patch.object(_handlers, "SceneGenerator", lambda: _FakeSceneGenerator()):
    asyncio.run(_handlers.generate(_update, _FakeContext(
        ["/decompose", "how", "a", "diesel", "engine", "works"])))

check("/gen hands the LLM the directive-free topic",
      _seen.get("topic") == "how a diesel engine works", str(_seen))
_job_file = _newest_job_file()
check("/gen writes the job file", _job_file is not None, str(_job_file))
if _job_file:
    with open(_job_file, "r") as _fh:
        _job = json.load(_fh)
    check("/gen stores image_mode for the proceed callback",
          _job.get("image_mode") == "decompose", str(_job.get("image_mode")))
    os.remove(_job_file)

# A bare directive with no topic after it is rejected, not silently generated.
_update_bare = _FakeUpdate()
with _mock.patch.object(_handlers, "SceneGenerator", lambda: _FakeSceneGenerator()):
    asyncio.run(_handlers.generate(_update_bare, _FakeContext(["/diagram"])))
check("/gen rejects a bare directive",
      any("style directive" in t for t in _update_bare.message.texts),
      str(_update_bare.message.texts))

print("== 10. scene / image / narration pairing stays index-aligned ==")
from bot.handlers import _picked_pairs, _drop_unvoiced_scenes, _drop_silent_scenes

_scenes = ["s0", "s1", "s2", "s3"]
_narrs = ["n0", "n1", "n2", "n3"]

# The regression: image 1 failed, so image 2's path must NOT slide onto scene 1.
_paths, _sc, _na = _picked_pairs(_scenes, _narrs, [(0, "img0"), (2, "img2"), (3, "img3")])
check("failed image does not shift the pairing",
      (_paths, _sc, _na) == (["img0", "img2", "img3"], ["s0", "s2", "s3"], ["n0", "n2", "n3"]),
      str((_paths, _sc, _na)))
check("pairing lists are the same length",
      len(_paths) == len(_sc) == len(_na) == 3, str((len(_paths), len(_sc), len(_na))))

# Order of `generated` is what the clip order follows - it must survive as-is.
_paths2, _sc2, _na2 = _picked_pairs(["a", "b"], ["na", "nb"], [(1, "b_img"), (0, "a_img")])
check("pairs follow generation order",
      (_paths2, _sc2, _na2) == (["b_img", "a_img"], ["b", "a"], ["nb", "na"]),
      str((_paths2, _sc2, _na2)))

# Defensive: a short narration/scene list must not raise or mispair.
_paths3, _sc3, _na3 = _picked_pairs(["only"], [], [(0, "p")])
check("missing narration becomes an empty slot",
      (_paths3, _sc3, _na3) == (["p"], ["only"], [""]), str((_paths3, _sc3, _na3)))
_paths4, _sc4, _na4 = _picked_pairs([], [], [(3, "p")])
check("out-of-range index yields empty text, keeps the image",
      (_paths4, _sc4, _na4) == (["p"], [""], [""]), str((_paths4, _sc4, _na4)))

# Unvoiced scenes are dropped as PAIRS (before any image is rendered).
_sc, _na = _drop_unvoiced_scenes(["s0", "s1", "s2"], ["n0", "", "n2"])
check("empty narration drops its scene too", (_sc, _na) == (["s0", "s2"], ["n0", "n2"]),
      str((_sc, _na)))
_sc, _na = _drop_unvoiced_scenes(["s0", "s1", "s2"], ["n0", "n1"])
check("narration shorter than scenes drops the extras", (_sc, _na) == (["s0", "s1"], ["n0", "n1"]),
      str((_sc, _na)))
_sc, _na = _drop_unvoiced_scenes(["s0", "s1"], ["n0", "n1"])
check("all-voiced input is untouched", (_sc, _na) == (["s0", "s1"], ["n0", "n1"]), str((_sc, _na)))
_sc, _na = _drop_unvoiced_scenes(["s0", "s1"], ["", "  "])
check("all-unvoiced input yields empty lists", (_sc, _na) == ([], []), str((_sc, _na)))

# A scene whose TTS failed is dropped with its image, so every later clip keeps
# its own duration/subtitle timings instead of borrowing the next scene's.
_imgs, _narrs, _audio = _drop_silent_scenes(
    ["i0", "i1", "i2"], ["n0", "n1", "n2"],
    [("/a0", 5.0, "t0"), (None, 0, None), ("/a2", 7.0, "t2")],
)
check("failed narration drops its scene, image and clip text together",
      (_imgs, _narrs, [a[0] for a in _audio]) == (["i0", "i2"], ["n0", "n2"], ["/a0", "/a2"]),
      str((_imgs, _narrs, _audio)))
check("surviving scenes keep their own durations/timings",
      [_audio[0][1], _audio[1][1]] == [5.0, 7.0] and _audio[1][2] == "t2", str(_audio))
_imgs, _narrs, _audio = _drop_silent_scenes(["i0", "i1"], ["n0", "n1"],
                                            [("/a0", 1.0, None), ("/a1", 2.0, None)])
check("all-voiced scenes are untouched",
      (_imgs, _narrs, len(_audio)) == (["i0", "i1"], ["n0", "n1"], 2), str((_imgs, _narrs)))
_imgs, _narrs, _audio = _drop_silent_scenes(["i0"], ["n0"], [(None, 0, None)])
check("all-silent scenes are dropped", (_imgs, _narrs, _audio) == ([], [], []), str((_imgs, _narrs, _audio)))

print("")
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("Failed checks:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL CHECKS PASSED")
