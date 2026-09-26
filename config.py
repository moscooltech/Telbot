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
# gen.pollinations.ai now requires an API key (and dropped "flux-dev"); the legacy
# image.pollinations.ai/prompt endpoint is still free & keyless (verified 2026-09-26).
IMAGE_WIDTH = 720      # Reduced from 1080 (saves 33% memory)
IMAGE_HEIGHT = 1280    # Reduced from 1920 (saves 33% memory)
IMAGE_LEGACY_MODEL = "flux"           # model hint on the keyless legacy endpoint
IMAGE_TIMEOUT = 120                   # legacy endpoint can queue for ~45s per image
IMAGE_MIN_BYTES = 3000                # smaller payloads are error pages, not photos
CONSISTENT_SEED = True                # one base seed per job -> coherent look across scenes
IMAGE_PROMPT_MAX_WORDS = 60           # commas structure image prompts; 20 words loses style details

# Prompt engineering pass: rewrite scene descriptions into structured image prompts
ENABLE_PROMPT_POLISH = True

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

# Render Configuration
RENDER_FREE_TIER = True
