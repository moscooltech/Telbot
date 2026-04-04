import os
import logging
import uvicorn
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler
from config import TELEGRAM_TOKEN
from bot.handlers import start, generate

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
import asyncio
import aiohttp
...
logger = logging.getLogger(__name__)

async def keep_alive_pinger():
    """Background task to keep Render server awake."""
    url = os.getenv("WEBHOOK_URL", "")
    if not url:
        return
    
    logger.info("📡 Keep-Alive pinger started.")
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        logger.info("💓 Keep-Alive: Ping successful.")
        except Exception as e:
            logger.warning(f"⚠️ Keep-Alive: Ping failed: {e}")
        
        # Ping every 14 minutes (Render sleeps after 15)
        await asyncio.sleep(840)

@app.on_event("startup")
async def on_startup():
    """Tasks to run when the server starts."""
    if not TELEGRAM_TOKEN:
...
    logger.info("🚀 Webhook service is ready!")
    # Start the pinger in the background
    asyncio.create_task(keep_alive_pinger())

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
        # Parse the JSON into a Telegram Update object
        update = Update.de_json(data, bot_app.bot)
        
        # Process the update (this triggers start/generate handlers)
        # These handlers will now correctly spawn background threads for heavy work
        await bot_app.process_update(update)
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return Response(status_code=500)

if __name__ == "__main__":
    # Render binds to 0.0.0.0 and uses the PORT env var
    uvicorn.run(app, host="0.0.0.0", port=PORT)
