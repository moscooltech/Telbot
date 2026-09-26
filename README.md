# 🤖 AI Viral Video Generator Bot (100% Free)

A fully automated Telegram bot that transforms a text prompt into a viral-ready TikTok/Reels video: coherent AI images, natural narration with **frame-accurate karaoke subtitles**, and a viral caption — all on free tiers, tuned for Render's free 512MB container.

---

## ✨ How It Works (Pipeline)

1. **Script (2-pass, aligned)** — the LLM first writes a *story spine* (motive, style bible, beats, hook, CTA), then writes every scene **from that spine** so scenes never drift off-topic. A cheap reviewer pass scores each scene 1–10 against the motive and auto-rewrites weak ones.
2. **Approval** — you get a script preview with ✅ Proceed / 🔄 Regenerate buttons.
3. **Images** — Pollinations (Flux) via a 3-provider fallback chain: keyless legacy endpoint → keyed gen.pollinations.ai → Bytez (SDXL), with the **style bible + one consistent seed per job** so all scenes look like one video. Works with zero image-API keys.
4. **Voice** — edge-tts (`en-US-AndrewMultilingualNeural` by default, configurable via `TTS_VOICE`/`TTS_RATE`), with loudness normalization (-14 LUFS) and gTTS fallback. **Real word-level timings** are captured from the TTS engine.
5. **Video** — per-scene clips with **TikTok-style karaoke subtitles**: words appear in 2–3 word chunks and the current word highlights **in perfect sync with the voice** (timings come from the TTS engine itself, not estimates). Bold font, safe-zone positioning, static-subtitle fallback if libass ever fails.
6. **Assembly** — stream-copy concat (≈0 RAM) + audio mux, uploaded to Telegram with caption + hashtags.

## 🚀 Setup Guide

### Phase 1: API Keys (Free)

| Key | Where | Required |
|---|---|---|
| `TELEGRAM_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` | ✅ |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com/) (free tier: gpt-oss-120b) | recommended |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com/) (free tier: gemini-2.5-flash) | recommended |
| `POLLINATIONS_API_KEY` | [pollinations.ai](https://pollinations.ai/) — images work without a key too (keyless legacy endpoint is primary; key adds gen.pollinations.ai models as fallback) | optional |
| `BYTEZ_API_KEY` | [bytez.com](https://bytez.com/) — optional last-resort image fallback (SDXL) and LLM fallback | optional |
| `BYTEZ_API_KEY` | [bytez.com](https://bytez.com/) — LLM fallback (gemma-2-9b) | optional |

At least one LLM key is required; all four are chained with automatic fallback.

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

## 🛠️ Technical Notes

- **JSON mode** is enabled on Groq/Gemini for reliable script output, with brace-slicing extraction as backup.
- **Fonts**: the Docker image ships DejaVu fonts; libass resolves the bold face automatically. Drop a `.ttf` in `assets/fonts/` to override.
- **RAM safety**: 720×1280 renders, 1 concurrent job, stream-copy assembly, per-clip 90–120s timeouts.
- **Tuning**: `SUBTITLE_WORDS_PER_CHUNK` (2), `SUBTITLE_FONT_SIZE` (54), `SUBTITLE_MARGIN_V` (210), `TTS_RATE` (+5%) — see `.env.example`.
- **Optional offline TTS**: set `ENABLE_PIPER=true` + `PIPER_VOICE_PATH` to add a Piper fallback between edge-tts and gTTS.
- Background music: drop `.mp3` files in `assets/music/` (mixed at 30% volume).

## ⚠️ Free Tier Notes

- Render free instances sleep after 15 min idle; the bot self-pings every 14 min, but a cold start needs a moment.
- One video is generated at a time globally to stay within the 512MB limit.
- Groq free tier: 30 req/min, 1,000 req/day (gpt-oss-120b replaced Llama 3.3 on 2026-08-16).

## 📜 License

Open source. Tweak the prompts in `services/scene_generator.py` to change the video style.
