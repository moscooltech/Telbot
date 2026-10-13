"""
Automated series run execution + shared job-slot state.

Split from bot/handlers.py so that services/series_scheduler.py can import it
without pulling the whole Telegram handler module into the scheduler (handlers
still re-export these symbols for compatibility).

Run lifecycle:
  pop prompt (scheduler) -> SceneGenerator.generate_all(prompt)   [no preview,
  no approval buttons] -> run_generation_sync(..., series_ctx=...) -> on
  success: advance next_run (+ completion check) / on failure: re-insert the
  prompt at the queue head and notify.

The busy flag implements the single global job slot (MAX_CONCURRENT_JOBS=1):
set for BOTH manual and series generation threads.
"""
import logging
import threading
import time

from config import SERIES_COMPLETE_MESSAGE
from utils.telegram_api import TelegramAPI
from services.image_generator import parse_image_mode
from services.scene_generator import SceneGenerator
from services.series_manager import SeriesManager

logger = logging.getLogger(__name__)

# True while ANY video generation (manual or series) is running. The scheduler
# reads this to honor MAX_CONCURRENT_JOBS=1.
_job_running = False
_job_lock = threading.Lock()


def is_busy():
    return _job_running


def set_busy(busy):
    global _job_running
    with _job_lock:
        _job_running = busy


def notify_missed_slot(data):
    """One-time catch-up notice to the owner when a slot was missed while the
    bot was down (Render restart)."""
    chat_id = data.get("owner_chat_id")
    if chat_id:
        TelegramAPI.send_message(
            chat_id=chat_id,
            text="⏰ Scheduled run was missed (bot was down) — generating now.",
        )


def launch_series_run(manager, data, prompt, k, n):
    """Spawn the automated generation in a background thread.

    The prompt has ALREADY been popped and saved by the scheduler; on failure
    it is re-inserted at the queue head (retry at next slot)."""
    chat_id = data["owner_chat_id"]
    prompt_id = prompt.get("id", "?")
    prompt_text = prompt.get("prompt", "")
    fmt = prompt.get("format", "narration")

    def _worker():
        set_busy(True)
        try:
            _run_series_video(manager, data, prompt, chat_id, prompt_text, fmt, k, n)
        except Exception as e:
            logger.error("Series run for %s crashed: %s", prompt_id, e, exc_info=True)
        finally:
            set_busy(False)

    threading.Thread(target=_worker, name="series-run-%s" % prompt_id, daemon=True).start()


def _run_series_video(manager, data, prompt, chat_id, prompt_text, fmt, k, n):
    prompt_id = prompt.get("id", "?")
    job_id = "series_%s_%d" % (prompt_id, int(time.time()))

    TelegramAPI.send_message(
        chat_id=chat_id,
        text="🎬 **Series run %s/%s** (%s):\n`%s`\n\n🧠 Generating script..." % (
            k, n, data.get("title", "series"), prompt_text[:100]),
    )

    # A leading "/mode" directive in the stored prompt picks the render style for
    # the whole run (e.g. "/decompose how a diesel engine works"); a scene's own
    # description can still override it image by image.
    image_mode, topic = parse_image_mode(prompt_text)

    # Script generation straight to production - NO preview / approval buttons.
    try:
        sg = SceneGenerator()
        scenes, narrations, metadata = sg.generate_all(topic or prompt_text)
    except Exception as e:
        _on_series_failure(manager, data, prompt, chat_id, e)
        return
    if image_mode:
        metadata["image_mode"] = image_mode

    from bot.handlers import run_generation_sync  # late import avoids a cycle
    run_generation_sync(
        chat_id, scenes, narrations, metadata, job_id, fmt,
        series_ctx={
            "manager": manager,
            "data": data,
            "prompt": prompt,
            "k": k,
            "n": n,
            "title": data.get("title", "series"),
        },
    )


def on_series_success(ctx):
    """Called from run_generation_sync's success path when series_ctx is set."""
    manager = ctx["manager"]
    data = ctx["data"]
    chat_id = data["owner_chat_id"]
    manager.mark_run_succeeded(data)
    remaining = manager.pending_prompts(data)
    manager.save(data)
    if not remaining:
        TelegramAPI.send_message(chat_id=chat_id, text=SERIES_COMPLETE_MESSAGE)


def on_series_failure(ctx, error):
    """Failure path: keep the prompt (re-insert at head), notify, retry next slot."""
    manager = ctx["manager"]
    data = ctx["data"]
    chat_id = data["owner_chat_id"]
    prompt = ctx["prompt"]
    manager.reinsert_front(data, prompt)
    manager.mark_run_failed(data, error)
    manager.save(data)
    TelegramAPI.send_message(
        chat_id=chat_id,
        text="❌ **Series run failed:** %s\n🔁 Prompt kept — will retry at the next scheduled slot." % str(error)[:300],
    )


def _on_series_failure(manager, data, prompt, chat_id, error):
    """Failure BEFORE run_generation_sync started (script phase)."""
    prompt_id = prompt.get("id", "?")
    logger.warning("Series script generation failed for %s: %s", prompt_id, error)
    manager.reinsert_front(data, prompt)
    manager.mark_run_failed(data, error)
    manager.save(data)
    TelegramAPI.send_message(
        chat_id=chat_id,
        text="❌ **Series run failed:** %s\n🔁 Prompt kept — will retry at the next scheduled slot." % str(error)[:300],
    )
