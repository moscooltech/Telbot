import asyncio
import logging
import os
from telegram.ext import ApplicationBuilder, CommandHandler
from config import TELEGRAM_TOKEN
from bot.handlers import start, generate, process_queue

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def main():
    if not TELEGRAM_TOKEN:
        print("❌ CRITICAL ERROR: TELEGRAM_TOKEN not found. Make sure to set it in Render environment variables.")
        return

    print("🛠️ Starting bot in Background Worker mode...")

    # Create the application
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(["generate", "gen"], generate))

    # Start the worker task in the background
    print("👷 Starting job queue worker...")
    worker = asyncio.create_task(process_queue())

    # Start the bot
    print("🚀 Bot is live and listening for messages!")
    
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        
        # Keep the bot running until stopped
        try:
            while True:
                await asyncio.sleep(3600) # Sleep for long intervals to save CPU
        except (KeyboardInterrupt, SystemExit):
            print("🛑 Bot stopping...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Bot process terminated.")
