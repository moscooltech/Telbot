"""
Unit checks for the pure-Python logic of the new pipeline components.
Run: python3 verify_logic.py
No network or ffmpeg required. Safe to delete afterwards.
"""
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

print("== 2. llm_service provider chain ==")
from services.llm_service import LLMService
llm = LLMService()
check("4 providers configured", len(llm.providers) == 4)
check("groq uses new model", llm.providers[0]["model"] == config.GROQ_MODEL)
check("bytez uses TEXT model (not SDXL)", llm.providers[3]["model"] == config.BYTEZ_LLM_MODEL)
check("json_mode flagged for groq+gemini", llm.providers[0]["json_mode"] and llm.providers[1]["json_mode"])

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

print("")
print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("Failed checks:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL CHECKS PASSED")
