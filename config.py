import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# OpenRouter API Key (Free tier)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "google/gemini-2.0-flash-lite-preview-02-05:free"

# Directories
TEMP_DIR = "temp"
ASSETS_DIR = "assets"
MUSIC_DIR = "assets/music"
FONTS_DIR = "assets/fonts"

# Image Generation - OPTIMIZED FOR 512MB RAM
POLLINATIONS_URL = "https://gen.pollinations.ai/image/{prompt}"
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
IMAGE_WIDTH = 720      # Reduced from 1080 (saves 33% memory)
IMAGE_HEIGHT = 1280    # Reduced from 1920 (saves 33% memory)

# Bytez fallback configuration (if used)
BYTEZ_API_KEY = os.getenv("BYTEZ_API_KEY", "")
BYTEZ_MODEL = "stabilityai/stable-diffusion-xl-base-1.0"

# Video Settings - AGENTIC PLANNING
MIN_SCENES = 8                      # Minimum scenes for 40s+
MAX_SCENES = 15                     # Maximum scenes for RAM safety
VIDEO_DURATION_PER_SCENE = 6        # Targeted seconds per scene
ASPECT_RATIO = "9:16"               # TikTok format

# FFmpeg Optimization for Free Tier
FFMPEG_PRESET = "veryfast"          # 40% faster encoding
FFMPEG_CRF = 22                     # Quality (0-51, 22 is good)
FFMPEG_THREADS = 2                  # Limit CPU threads

# Audio Settings - NARRATION ONLY (NO BACKGROUND MUSIC)
AUDIO_BITRATE = "64k"               # Low bitrate for TTS
AUDIO_SAMPLE_RATE = 22050           # Sufficient for TTS
SKIP_BACKGROUND_MUSIC = True        # Disable background music

# Memory Management
MAX_MEMORY_MB = 380                 # Safety threshold
CLEANUP_INTERVAL = 5                # Clean every N scenes
ENABLE_MEMORY_MONITORING = True

# Queue settings
MAX_CONCURRENT_JOBS = 1             # ONE JOB AT A TIME
JOB_TIMEOUT_SECONDS = 600           # 10 minutes max

# Render Configuration
RENDER_FREE_TIER = True
