import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# OpenRouter API Key (Free tier)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "openrouter/free" # Or specifically "google/gemini-2.0-flash-lite-preview-02-05:free"

# Bytez API (Fallback)
BYTEZ_API_KEY = os.getenv("BYTEZ_API_KEY", "")
BYTEZ_MODEL = "stabilityai/stable-diffusion-xl-base-1.0" # Good fallback model

# Directories
TEMP_DIR = "temp"
ASSETS_DIR = "assets"
MUSIC_DIR = "assets/music"
FONTS_DIR = "assets/fonts"

# Image Generation
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
POLLINATIONS_URL = "https://gen.pollinations.ai/image/{prompt}"

# Video Settings
VIDEO_DURATION_PER_SCENE = 5 # seconds
ASPECT_RATIO = "9:16" # TikTok format

# Queue settings
MAX_CONCURRENT_JOBS = 1
