# 🤖 AI Viral Video Generator Bot (100% Free)

A fully automated Telegram bot that transforms a text prompt into a viral-ready TikTok/Reels video with cinematic images, narration, background music, and burned-in subtitles.

---

## 🚀 Step-by-Step Setup Guide

### Phase 1: Get Your API Keys (Free)

#### 1. Create your Telegram Bot
1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the instructions to name your bot.
3. **Copy the API Token** provided (e.g., `123456789:ABCdefGHI...`). This is your `TELEGRAM_TOKEN`.

#### 2. Get your OpenRouter API Key
1. Go to [OpenRouter.ai](https://openrouter.ai/).
2. Create a free account.
3. Go to **Keys** -> **Create Key**.
4. **Copy your API Key**. This is your `OPENROUTER_API_KEY`. (OpenRouter provides free access to models like Gemini Flash 2.0).

---

### Phase 2: Prepare Your Code
1. **Create a GitHub Repository**: Create a new private or public repository on GitHub.
2. **Upload these Files**: Upload all the files in this directory (including `Dockerfile`, `main.py`, `requirements.txt`, etc.) to your GitHub repo.
3. **Add Music (Optional)**: If you want background music, upload `.mp3` files into the `assets/music/` folder in your repo.

---

### Phase 3: Host on Render (Free Tier)

Render's "Web Service" free tier allows you to run Docker containers, which is perfect because it handles the FFmpeg installation automatically.

1. **Sign Up/Log In**: Go to [Render.com](https://render.com/).
2. **New Web Service**:
   - Click **"New +"** and select **"Web Service"**.
   - Connect your GitHub account and select the repository you just created.
3. **Configure Settings**:
   - **Name**: Give your service a name (e.g., `my-ai-video-bot`).
   - **Region**: Choose the one closest to you (e.g., Oregon or Frankfurt).
   - **Runtime**: Select **"Docker"**. (This is important! It uses our `Dockerfile`).
   - **Instance Type**: Select **"Free"**.
4. **Add Environment Variables**:
   - Click the **"Advanced"** button or go to the **"Env Vars"** tab.
   - Click **"Add Environment Variable"** and add these two:
     - `TELEGRAM_TOKEN` = `(Your Token from BotFather)`
     - `OPENROUTER_API_KEY` = `(Your Key from OpenRouter)`
5. **Deploy**: Click **"Create Web Service"**. Render will now build the Docker image and start your bot.

---

### Phase 4: Start Using on Telegram

1. Once Render shows **"Live"** in the logs, go to your bot on Telegram.
2. Press **"Start"** or send `/start`.
3. **Generate a Video**:
   - Send: `/generate` or `/gen` followed by `[Your Story Idea]`
   - *Example*: `/gen A short story about a brave cat exploring a neon-lit cyberpunk city.`
4. **Wait for Processing**:
   - The bot will reply with "🧠 Generating scenes...".
   - It will then create images, narration, and finally the video.
   - Since it's running on a free tier, please allow **2-4 minutes** for the full generation.
5. **Receive Output**:
   - You will receive a high-quality **MP4 video** (9:16 format).
   - The message will include a **Viral Caption** and **Optimized Hashtags** ready to be copied to TikTok/Instagram.

---

## 🛠️ Technical Features
- **Pollinations AI**: Used for high-quality, free image generation (No API key needed).
- **gTTS**: Generates natural voiceovers for your story.
- **FFmpeg (Ken Burns)**: Adds professional slow-zoom/pan effects to static images.
- **Subtitles**: Auto-generated and burned into the video for maximum engagement.
- **Queue System**: Process jobs one-by-one to ensure stability on low-resource servers.

## ⚠️ Important Notes
- **Free Tier Sleep**: Render's free tier "sleeps" after 15 minutes of inactivity. If the bot doesn't respond, send `/start` and wait a moment for it to wake up.
- **One Job at a Time**: To prevent crashes on the 512MB RAM limit, the bot processes only one video at a time globally.

## 📜 License
This project is open-source. Feel free to modify the prompts in `services/scene_generator.py` to change the video style!
