import os
import asyncio
import logging
import uvicorn
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler
from config import TELEGRAM_TOKEN
from bot.handlers import start, generate, process_queue, set_bot_instance

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load configuration
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", "10000"))

app = FastAPI()

# Bot application initialization
bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
# Add handlers
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

    # CRITICAL: Set the global bot instance for background worker
    set_bot_instance(bot_app.bot)

    # Set the webhook automatically on startup
    if WEBHOOK_URL:
        webhook_path = f"{WEBHOOK_URL}/{TELEGRAM_TOKEN}"
        logger.info(f"🔗 Setting webhook to: {webhook_path}")
        await bot_app.bot.set_webhook(url=webhook_path)
    else:
        logger.warning("⚠️ WEBHOOK_URL is not set. Webhook will not be registered automatically.")

    # Start the persistent background worker
    asyncio.create_task(process_queue())
    logger.info("👷 Background worker active.")
    logger.info("🚀 Webhook service is ready!")

@app.on_event("shutdown")
async def on_shutdown():
    """Cleanup when the server stops."""
    logger.info("🛑 Shutting down server...")
    await bot_app.stop()
    await bot_app.shutdown()

@app.get("/")
async def health_check():
    """Health check endpoint for Render."""
    return {
        "status": "healthy",
        "mode": "webhook",
        "service": "telegram-ai-bot"
    }

@app.post("/{token}")
async def handle_webhook(token: str, request: Request):
    """Receive and process Telegram updates via POST."""
    if token != TELEGRAM_TOKEN:
        logger.warning(f"🚫 Unauthorized token: {token}")
        return Response(status_code=403)
    
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        # Process asynchronously (non-blocking)
        await bot_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
