import asyncio
import logging
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler
from config import TELEGRAM_TOKEN
from bot.handlers import start, generate, handle_callback

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


async def main():
    if not TELEGRAM_TOKEN:
        print("❌ CRITICAL ERROR: TELEGRAM_TOKEN not found. Make sure to set it in your environment or .env file.")
        return

    print("🛠️ Starting bot in Polling mode (local development)...")
    print("ℹ️ For Render deployment use app.py (webhook mode) instead.")

    # Create the application
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler(["generate", "gen"], generate))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("🚀 Bot is live and listening for messages!")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        # Keep the bot running until stopped
        try:
            while True:
                await asyncio.sleep(3600)  # Sleep for long intervals to save CPU
        except (KeyboardInterrupt, SystemExit):
            print("🛑 Bot stopping...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("🛑 Bot process terminated.")
