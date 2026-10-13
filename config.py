import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# LLM Provider API Keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
BYTEZ_API_KEY = os.getenv("BYTEZ_API_KEY", "")

# UnoRouter - OpenAI-compatible gateway (https://unorouter.com), free ":free" models.
# When set, UnoRouter is the FIRST provider in the LLM fallback chain (strongest free
# models primary; protects Groq's 1,000 req/day quota from series automation).
UNOROUTER_API_KEY = os.getenv("UNOROUTER_API_KEY", "")
# Free-tier catalog shifts over time -> UNOROUTER_MODELS is a comma-separated list
# tried in order (first that responds wins). Update here if a free model retires.
UNOROUTER_MODELS = [
    m.strip() for m in os.getenv(
        "UNOROUTER_MODELS",
        "gpt-5.4:free,gpt-5.5:free,deepseek-v4-flash:free"
    ).split(",") if m.strip()
]

# Gemini image generation (Nano Banana) - NOTE: image models have ZERO free-tier
# API quota (text works free, images do not). Only useful with a paid key.
# Keep it in the chain behind Cloudflare; it is skipped automatically on 429s.
GEMINI_IMAGE_MODELS = os.getenv(
    "GEMINI_IMAGE_MODELS", "gemini-3.1-flash-image,gemini-2.5-flash-image"
).split(",")
GEMINI_IMAGE_ASPECT = os.getenv("GEMINI_IMAGE_ASPECT", "9:16")

# Cloudflare Workers AI - real SDXL on a generous free tier:
# 10,000 Neurons/day free, ~30 Neurons per 576x1024 image => ~300 photorealistic images/day.
# Optional: with POLLINATIONS_API_KEY set, keyed Pollinations Flux is tried first.
# Setup (both values come from a FREE Cloudflare account):
#   Account ID: dash.cloudflare.com -> Workers & Pages -> right sidebar "Account ID"
#   API Token:  dash.cloudflare.com -> Workers AI -> "Use REST API" ->
#               "Create a Workers AI token" (easiest; skips the policy-selection screen)
#               or dash.cloudflare.com/profile/api-tokens -> Create custom token ->
#               single permission: Account > Workers AI > Edit
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
# FLUX.2 klein models (4B distilled, fixed 4-step, multipart form input, JSON out
# with base64 image). Better photorealism + prompt adherence than SDXL; both are
# free-tier. Configurable via env (comma-separated). SDXL stays the JSON fallback.
CLOUDFLARE_KLEIN_MODELS = [
    m.strip() for m in os.getenv(
        "CLOUDFLARE_KLEIN_MODELS",
        "@cf/black-forest-labs/flux-2-klein-4b"
    ).split(",") if m.strip()
]
CLOUDFLARE_IMAGE_MODEL = os.getenv(
    "CLOUDFLARE_IMAGE_MODEL", "@cf/stabilityai/stable-diffusion-xl-base-1.0"
)
# Photorealism controls. Negative prompt steers ALL providers away from the
# plastic/cartoon AI look. (Cloudflare FLUX.2 klein has no native negative-prompt
# field; for it this is sent as a best-effort hint — set IMAGE_NEGATIVE_PROMPT=""
# if the API ever rejects unknown multipart fields.)
IMAGE_NEGATIVE_PROMPT = os.getenv(
    "IMAGE_NEGATIVE_PROMPT",
    "low quality, blurry, deformed, extra fingers, watermark, text, logo, "
    "oversaturated, cartoon, anime, 3d render, cgi, illustration, painting, "
    "drawing, plastic skin, waxy skin, smooth airbrushed skin, doll, toy",
)
# Photo-style suffix appended to every image prompt (bends generic models toward
# real-looking photos instead of the default cartoon/illustration drift).
IMAGE_STYLE_SUFFIX = os.getenv(
    "IMAGE_STYLE_SUFFIX",
    "photorealistic, candid documentary photograph, natural skin texture, "
    "realistic lighting, shot on dslr, 35mm, shallow depth of field",
)

# ---------------------------------------------------------------------------
# Image style modes - inline "/mode" directives
# ---------------------------------------------------------------------------
# The default pipeline forces photorealism: IMAGE_STYLE_SUFFIX pushes models
# toward photos and IMAGE_NEGATIVE_PROMPT actively bans "illustration",
# "drawing" and "text". Some videos legitimately need the opposite - an
# illustration, a design/specification sheet, an exploded (item decomposition)
# view, a technical schematic or a typographic poster - and the photo-forcing
# config above made those images impossible.
#
# Any image prompt may therefore START with an inline directive - "/illustration
# ...", "/design ...", "/decompose ...", "/diagram ...", "/poster ...", or
# "/photo" to force the default back - and the renderer swaps that image's
# style suffix and negative prompt for the mode's own. The directive itself is
# never sent to the image model.
#
# Two sources, and an inline directive always wins over the job default:
#   * the user, on /gen or /series add -> job-wide default for that video
#   * the script LLM, inside one scene description -> that single image only
#     (tools/services/scene_generator.py tells it to pick the best mode per
#      scene when - and only when - a realistic photo would be wrong)
#
# ENABLE_LLM_IMAGE_MODES=false stops the LLM from choosing modes itself;
# user-typed directives keep working either way.

# Shared quality floor, safe for EVERY mode: unlike IMAGE_NEGATIVE_PROMPT it
# bans neither text/labels nor drawings, because design sheets, exploded views,
# schematics and posters legitimately contain both.
IMAGE_NEGATIVE_CORE = (
    "low quality, blurry, deformed, watermark, oversaturated, jpeg artifacts"
)

# mode -> {"style": positive-prompt suffix, "negative": provider negative prompt,
#          "anchor": use the job's first image as the klein multi-reference input}
IMAGE_MODES = {
    # Default mode == exactly the pre-mode behavior (photo suffix + photo negatives).
    "photo": {
        "style": IMAGE_STYLE_SUFFIX,
        "negative": IMAGE_NEGATIVE_PROMPT,
        "anchor": True,      # keeps the main character/look consistent across scenes
    },
    "illustration": {
        "style": (
            "digital illustration, clean confident line art, flat vibrant color "
            "palette, editorial illustration style, hand-drawn texture"
        ),
        "negative": (
            IMAGE_NEGATIVE_CORE + ", photograph, photorealistic, photo, 3d render, cgi"
        ),
        "anchor": True,      # same character, drawn
    },
    "design": {
        "style": (
            "clean design specification sheet, structured technical layout, "
            "labelled callouts and annotations, alignment grid, neutral background, "
            "professional spec-sheet presentation"
        ),
        "negative": (
            IMAGE_NEGATIVE_CORE + ", photograph, photorealistic, clutter, mess, "
            "unreadable text, gibberish text"
        ),
        "anchor": False,     # a character reference would fight the layout
    },
    "decompose": {
        "style": (
            "exploded view technical illustration, components separated in space "
            "along alignment axes, labelled parts, clean neutral background, "
            "precise line work"
        ),
        "negative": (
            IMAGE_NEGATIVE_CORE + ", photograph, photorealistic, fully assembled, "
            "cluttered background"
        ),
        "anchor": False,
    },
    "diagram": {
        "style": (
            "technical schematic diagram, precise clean line work, labelled "
            "components and flow arrows, blueprint aesthetic, neutral background"
        ),
        "negative": (
            IMAGE_NEGATIVE_CORE + ", photograph, photorealistic, 3d render, "
            "heavy shading, photographic depth of field"
        ),
        "anchor": False,
    },
    "poster": {
        "style": (
            "bold graphic poster design, strong typographic hierarchy, high "
            "contrast composition, print-ready layout, limited color palette"
        ),
        "negative": (
            IMAGE_NEGATIVE_CORE + ", photograph, photorealistic, low resolution, "
            "muddy colors"
        ),
        "anchor": False,
    },
}

IMAGE_MODE_DEFAULT = "photo"

# Accepted spellings -> canonical mode key. Keeps the directive forgiving while
# never guessing: an unknown "/word" is left in the prompt untouched.
IMAGE_MODE_ALIASES = {
    "photo": "photo", "photograph": "photo", "photorealistic": "photo",
    "illustration": "illustration", "illustrate": "illustration",
    "art": "illustration", "artwork": "illustration",
    "design": "design", "spec": "design", "specsheet": "design",
    "decompose": "decompose", "decomposition": "decompose",
    "exploded": "decompose", "explode": "decompose",
    "diagram": "diagram", "schematic": "diagram", "blueprint": "diagram",
    "poster": "poster",
}

# Let the script LLM choose a non-photo mode when a scene needs one.
ENABLE_LLM_IMAGE_MODES = os.getenv("ENABLE_LLM_IMAGE_MODES", "true").lower() == "true"

# Default Models (verified September 2026)
# NOTE: Llama 3.3 70B left Groq's free tier on 2026-08-16 -> gpt-oss-120b is the free replacement.
GROQ_MODEL = "openai/gpt-oss-120b"
# NOTE: gemini-1.5-flash is shut down -> 2.5 Flash is the current free-tier model.
GEMINI_MODEL = "gemini-2.5-flash"
POLLINATIONS_MODEL = "openai"
# Bytez serves text and image models under different names. The image model is
# reserved (images are generated via Pollinations); the LLM fallback uses the text model.
BYTEZ_LLM_MODEL = "google/gemma-2-9b-it"
BYTEZ_IMAGE_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"

# Directories
TEMP_DIR = "temp"
ASSETS_DIR = "assets"
MUSIC_DIR = "assets/music"
FONTS_DIR = "assets/fonts"

# Image Generation - OPTIMIZED FOR 512MB RAM
# Provider order (services/image_generator.py::_provider_chain):
#   1. cloudflare FLUX.2 klein 4B then SDXL (needs CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN; confirmed working)
#   2. pollinations-gen  "flux" then "z-image-turbo"  (keyed photorealistic Flux backup; needs POLLINATIONS_API_KEY)
#   3. gemini Nano Banana (zero free-tier image quota; usually 429s)
#   4. pollinations-legacy  keyless, always works, but serves the weak cartoonish "sana" model
#   5. bytez SDXL        (needs BYTEZ_API_KEY)
# gen.pollinations.ai requires an API key; the legacy image.pollinations.ai/prompt
# endpoint is free & keyless (verified 2026-09-26).
IMAGE_WIDTH = 720      # Reduced from 1080 (saves 33% memory)
IMAGE_HEIGHT = 1280    # Reduced from 1920 (saves 33% memory)
IMAGE_LEGACY_MODEL = "flux"           # model hint on the keyless legacy endpoint
IMAGE_TIMEOUT = 120                   # legacy endpoint can queue for ~45s per image
IMAGE_MIN_BYTES = 3000                # smaller payloads are error pages, not photos
CONSISTENT_SEED = True                # one base seed per job -> coherent look across scenes
IMAGE_PROMPT_MAX_WORDS = 60           # commas structure image prompts; 20 words loses style details

# Prompt engineering pass: rewrite scene descriptions into structured image prompts
ENABLE_PROMPT_POLISH = True

# Inject IMAGE_STYLE_SUFFIX into every prompt sent to image providers
ENABLE_STYLE_SUFFIX = os.getenv("ENABLE_STYLE_SUFFIX", "true").lower() == "true"

# Pollinations server-side prompt rewriting (rewrites curated prompts -> usually off)
POLLINATIONS_ENHANCE = False

# Video Settings - AGENTIC PLANNING
MIN_SCENES = 8                      # Minimum scenes for 40s+
MAX_SCENES = 20                     # Maximum scenes for RAM safety
VIDEO_DURATION_PER_SCENE = 6        # Targeted seconds per scene
ASPECT_RATIO = "9:16"               # TikTok format

# Scenes must still be worth rendering even if a few images failed; below this ratio
# the job aborts with a clear message instead of shipping a mostly-broken video.
IMAGE_MIN_SUCCESS_RATIO = 0.5

# Scene alignment (story spine + relevance self-check)
ENABLE_RELEVANCE_CHECK = True
RELEVANCE_MIN_SCORE = 7             # scenes scoring below this get one rewrite against the motive
MAX_SCENE_REWRITES = 4              # cap rewrites per video to bound latency

# Social caption: Telegram/TikTok posts under ~200 chars look like placeholders.
# The LLM is instructed to write longer captions; anything shorter is padded from
# the story spine (hook + CTA + motive) and, if still short, the topic sentence.
MIN_CAPTION_CHARS = int(os.getenv("MIN_CAPTION_CHARS", "200"))

# FFmpeg Optimization for Free Tier
FFMPEG_PRESET = "veryfast"          # 40% faster encoding
FFMPEG_CRF = 22                     # Quality (0-51, 22 is good)
FFMPEG_THREADS = 2                  # Limit CPU threads

# Audio Settings
AUDIO_BITRATE = "64k"               # Low bitrate for TTS
AUDIO_SAMPLE_RATE = 22050           # Sufficient for TTS
SKIP_BACKGROUND_MUSIC = True        # Disable background music
ENABLE_LOUDNORM = True              # Normalize loudness across scenes (-14 LUFS streaming standard)

# TTS
TTS_VOICE = os.getenv("TTS_VOICE", "en-US-AndrewMultilingualNeural")
TTS_RATE = os.getenv("TTS_RATE", "+5%")
TTS_VOLUME = os.getenv("TTS_VOLUME", "+0%")
# Optional offline fallback (requires: pip install piper-tts + a .onnx voice file)
ENABLE_PIPER = os.getenv("ENABLE_PIPER", "false").lower() == "true"
PIPER_VOICE_PATH = os.getenv("PIPER_VOICE_PATH", "")

# Subtitles (ASS/libass karaoke rendering)
SUBTITLE_WORDS_PER_CHUNK = int(os.getenv("SUBTITLE_WORDS_PER_CHUNK", "2"))
SUBTITLE_FONT_SIZE = int(os.getenv("SUBTITLE_FONT_SIZE", "54"))
SUBTITLE_FONT_NAME = os.getenv("SUBTITLE_FONT_NAME", "DejaVu Sans")
SUBTITLE_MARGIN_V = int(os.getenv("SUBTITLE_MARGIN_V", "210"))   # bottom safe zone (~16% of 1280)
SUBTITLE_MARGIN_LR = int(os.getenv("SUBTITLE_MARGIN_LR", "60"))

# Memory Management
MAX_MEMORY_MB = 380                 # Safety threshold
CLEANUP_INTERVAL = 5                # Clean every N scenes
ENABLE_MEMORY_MONITORING = True

# Queue settings
MAX_CONCURRENT_JOBS = 1             # ONE JOB AT A TIME
JOB_TIMEOUT_SECONDS = 600           # 10 minutes max

# Content Series / Queue System (services/series_manager.py + services/series_scheduler.py)
# State lives in ONE local JSON file. NOTE: Render's filesystem is ephemeral -
# the series file is wiped on every redeploy/restart (accepted trade-off).
SERIES_DIR = os.getenv("SERIES_DIR", "series")
SERIES_FILE = os.getenv("SERIES_FILE", os.path.join(SERIES_DIR, "active.json"))
SERIES_MAX_PROMPTS = int(os.getenv("SERIES_MAX_PROMPTS", "50"))        # hard cap on pending prompts
SERIES_SCHEDULER_TICK_SECONDS = int(os.getenv("SERIES_SCHEDULER_TICK_SECONDS", "120"))
SERIES_TIMEZONE = os.getenv("SERIES_TIMEZONE", "Africa/Lagos")         # anchor scheduling + display
SERIES_MAX_PROMPTS_PER_GENERATE = 20   # /series generate <N> upper bound

# Render Configuration
RENDER_FREE_TIER = True

# The exact completion message sent when the last series prompt is used.
SERIES_COMPLETE_MESSAGE = (
    "\u2705 Series complete! All prompts have been used. "
    "Use /series create <title> to start a new series."
)
