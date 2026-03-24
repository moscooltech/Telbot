import asyncio
import logging
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
        print("❌ Error: TELEGRAM_TOKEN not found in .env file.")
        return

    # Create the application
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("generate", generate))

    # Start the worker task in the background
    worker = asyncio.create_task(process_queue())

    # Start the bot
    print("🚀 Bot is running...")
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        
        # Keep the bot running until stopped
        while True:
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Bot stopped.")
