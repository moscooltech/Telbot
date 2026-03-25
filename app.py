import os
import asyncio
import logging
import uvicorn
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler
from config import TELEGRAM_TOKEN
from bot.handlers import start, generate, process_queue

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load WEBHOOK_URL from env
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "10000"))

app = FastAPI()

# Bot application initialization
bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
# Add handlers (keeping existing /start and /generate)
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("generate", generate))

@app.on_event("startup")
async def on_startup():
    """Tasks to run when the server starts."""
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN is missing!")
        return

    # Initialize and start the bot application
    await bot_app.initialize()
    await bot_app.start()
    
    # Set the webhook
    if WEBHOOK_URL:
        webhook_path = f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}"
        logger.info(f"🔗 Setting webhook to: {webhook_path}")
        await bot_app.bot.set_webhook(url=webhook_path)
    else:
        logger.warning("⚠️ WEBHOOK_URL is not set. Webhook will not be registered automatically.")

    # Start the background worker for AI generation
    asyncio.create_task(process_queue())
    logger.info("👷 Background worker started.")
    logger.info("🚀 Webhook service is ready!")

@app.on_event("shutdown")
async def on_shutdown():
    """Cleanup when the server stops."""
    logger.info("🛑 Shutting down server...")
    await bot_app.stop()
    await bot_app.shutdown()

@app.get("/")
async def health_check():
    """Simple health status endpoint."""
    return {
        "status": "healthy",
        "service": "telegram-ai-bot",
        "mode": "webhook"
    }

@app.post("/{token}")
async def handle_webhook(token: str, request: Request):
    """Receive and process Telegram updates."""
    if token != TELEGRAM_TOKEN:
        logger.warning(f"🚫 Unauthorized attempt with token: {token}")
        return Response(status_code=403)
    
    try:
        # Get JSON data from request
        data = await request.json()
        # Parse update
        update = Update.de_json(data, bot_app.bot)
        # Process the update asynchronously without blocking the webhook response
        await bot_app.process_update(update)
        return {"status": "processed"}
    except Exception as e:
        logger.error(f"❌ Error processing update: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    # Render binds to 0.0.0.0 and uses the PORT env var
    uvicorn.run(app, host="0.0.0.0", port=PORT)
