"""
Background scheduler for the content series feature.

Runs as an asyncio task alongside the Render keep-alive pinger. Every tick it:
1. Loads series/active.json (tolerant of corruption/absence).
2. Checks enabled + pending prompts + due time (SeriesManager.is_due).
3. Respects MAX_CONCURRENT_JOBS=1 via a shared busy flag: if a job is running,
   the due run simply waits and fires right after the slot frees (queue order
   preserved) - next_run is not advanced.
4. Sends a one-time catch-up notice when a slot was missed while the bot was
   down (Render restart), then generates.
5. Spawns the generation in a background thread (same pattern as the manual
   approve button) so the event loop stays free.

Automated runs SKIP the script preview / approval buttons and go straight to
generation, reusing SceneGenerator + run_generation_sync.
"""
import asyncio
import logging
import threading

from config import SERIES_SCHEDULER_TICK_SECONDS
from services.series_manager import SeriesManager, REASON_OK
from bot import series_runner  # bot/series_runner.py; handlers re-export for compat

logger = logging.getLogger(__name__)

_scheduler_started = False


def start_scheduler(bot_app):
    """Idempotently start the scheduler loop as an asyncio task on the bot's
    event loop (webhook mode) or the running loop (polling mode)."""
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    try:
        loop = bot_app.bot.loop if bot_app is not None else asyncio.get_event_loop()
        loop.create_task(_scheduler_loop())
        logger.info("📅 Series scheduler started (tick every %ss).",
                    SERIES_SCHEDULER_TICK_SECONDS)
    except Exception as e:
        _scheduler_started = False
        logger.error("Failed to start series scheduler: %s", e)


async def _scheduler_loop():
    manager = SeriesManager()
    while True:
        try:
            await _tick(manager)
        except asyncio.CancelledError:
            logger.info("📅 Series scheduler stopped.")
            raise
        except Exception as e:
            # Never let one bad tick kill the loop.
            logger.error("Series scheduler tick error: %s", e, exc_info=True)
        await asyncio.sleep(SERIES_SCHEDULER_TICK_SECONDS)


async def _tick(manager):
    data = manager.load()
    due, reason = manager.is_due(data)
    if not due:
        if reason != REASON_OK and data is not None:
            logger.debug("Series not due: %s", reason)
        return

    # Missed-slot catch-up notice (once per overdue next_run): send the notice,
    # then pull next_run forward to now so it is not repeated on later ticks.
    if manager.is_missed_slot(data):
        series_runner.notify_missed_slot(data)
        manager.clear_missed_slot(data)
        manager.save(data)

    # Job-slot guard: if a generation is already running, wait for it to finish.
    # The run then fires on the next tick with next_run untouched (still overdue).
    if series_runner.is_busy():
        logger.info("Series run due but a job is running - waiting for idle slot.")
        return

    prompt = manager.pop_next(data)
    if prompt is None:
        return  # defensive: is_due already checked pending

    # Persist immediately: prompt is out of the queue while its video renders.
    manager.mark_run_started(data)
    manager.save(data)

    k, n = manager.run_position(data)
    series_runner.launch_series_run(manager, data, prompt, k=k, n=n)
