import os
import asyncio
import threading
import time
import shutil
import logging
import gc
import json
import re
from telegram import Update
from telegram.ext import ContextTypes
from services.scene_generator import SceneGenerator, extract_json
from services.image_generator import ImageGenerator
from services.audio_processor import AudioProcessor
from services.video_processor import VideoProcessor
from config import TEMP_DIR, MUSIC_DIR, VIDEO_DURATION_PER_SCENE, SERIES_FILE
import config
from utils.telegram_api import TelegramAPI
from bot import series_runner
from bot.series_runner import is_busy as _job_slot_busy, set_busy as _set_job_busy
from services.series_manager import SeriesManager
from services.series_scheduler import start_scheduler

logger = logging.getLogger(__name__)

# Result of the most recent finished/failed image phase: {"job_id", "summary", "ts"}.
# Module-level so /status works regardless of which webhook thread ran the job.
_last_job_summary = None

# Provider plan captured when /testimage was sent (button index -> plan entry).
_testimage_plan = []

# Fixed photorealistic test prompt: concrete topic objects (meter, AC unit),
# so the test also shows whether a provider renders scenes or just faces.
_TESTIMAGE_PROMPT = (
    "a technician in work clothes inspecting a residential electricity meter box, "
    "air conditioning unit humming on the wall behind, holding a paper utility bill, "
    "outdoor wall, medium shot, natural daylight"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Hello {user_name}! I am your AI Video Creator.\n\n"
        "Send /generate (or /gen) followed by a story prompt to create a viral video.\n\n"
        "Example: `/gen A story about a lost astronaut on a neon planet.`\n\n"
        "Other commands:\n"
        "• /testimage — generate one test image with a provider you pick\n"
        "• /status — provider fallback order + last job summary\n\n"
        "📺 **Content series** (queue + auto-schedule): /series",
        parse_mode="Markdown"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /status command: provider plan + last job's image winners."""
    # Build the provider plan without creating temp dirs (static chain plan).
    plan = ImageGenerator._chain_plan()
    plan_lines = []
    for pos, (name, _fn, model) in enumerate(plan, 1):
        marker = "🥇" if pos == 1 else f"{pos}."
        plan_lines.append(f"{marker} `{name}`" + (f" ({model})" if model else ""))
    plan_text = "\n".join(plan_lines) if plan_lines else "`none configured`"

    lines = ["📊 **Bot Status**", "", "🖼️ **Image provider fallback order:**", plan_text]

    if not any("pollinations-gen" == name for name, _, _ in plan):
        lines.append("")
        lines.append("💡 No `POLLINATIONS_API_KEY` set — images fall back to the "
                     "keyless endpoint (cartoonish model).")

    last = _last_job_summary
    lines.append("")
    if last:
        age = int(time.time() - last["ts"])
        age_text = f"{age // 60}m ago" if age < 86400 else f"{age // 3600}h ago"
        lines.append(f"🎞️ **Last job** ({last['job_id']}, {age_text}):")
        lines.append(f"`{last['summary']}`")
    else:
        lines.append("🎞️ No video generated yet in this run — send /generate to make one!")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def testimage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /testimage: generate ONE image with a provider you pick."""
    global _testimage_plan
    plan = ImageGenerator._chain_plan()
    if not plan:
        await update.message.reply_text(
            "❌ No image providers configured. Add `CLOUDFLARE_ACCOUNT_ID` + "
            "`CLOUDFLARE_API_TOKEN` (recommended) or any other image key.",
            parse_mode="Markdown",
        )
        return
    _testimage_plan = plan

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for idx, (name, _fn, model) in enumerate(plan):
        label = f"{idx + 1}. {name}" + (f" ({model})" if model else "")
        rows.append([InlineKeyboardButton(label[:64], callback_data=f"ti_{idx}")])

    msg = (
        "🧪 **Image Provider Test**\n\n"
        "Pick a provider from the fallback order. It generates ONE image with this prompt:\n"
        f"`{_TESTIMAGE_PROMPT}`\n\n"
        "The photo is sent back here so you can judge quality and topic accuracy "
        "before running a full video."
    )
    await update.message.reply_text(
        msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows)
    )


async def _run_testimage(query, data: str):
    """Generate one test image with the provider picked from the /testimage menu."""
    global _testimage_plan
    try:
        idx = int(data.replace("ti_", ""))
    except ValueError:
        idx = -1
    if not (0 <= idx < len(_testimage_plan)):
        await query.edit_message_text("❌ Test menu expired — send /testimage again.")
        return

    name, _fn, model = _testimage_plan[idx]
    label = name + (f" ({model})" if model else "")
    chat_id = query.message.chat_id
    await query.edit_message_text(f"🧪 Testing **{label}**... (can take up to a minute)")

    result = {"path": None, "summary": "", "error": "", "log": ""}
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    def _worker():
        ig_logger = logging.getLogger("services.image_generator")
        capture = _Capture(level=logging.INFO)
        old_level = ig_logger.level
        ig_logger.addHandler(capture)
        ig_logger.setLevel(logging.INFO)
        try:
            ig = ImageGenerator(f"testimage_{int(time.time())}")
            path = ig.generate_image(_TESTIMAGE_PROMPT, 0)
            result["path"] = path
            result["summary"] = ig.provider_summary_text(1, 1 if path else 0)
        except Exception as e:
            result["error"] = str(e)
        finally:
            ig_logger.removeHandler(capture)
            ig_logger.setLevel(old_level)

    await asyncio.to_thread(_worker)

    # Surface the provider's own failure line(s) so the reason is visible in chat.
    failures = [r for r in records if "failed" in r.lower()]
    result["log"] = failures[-1] if failures else (records[-1] if records else "")

    if result["path"]:
        sent = TelegramAPI.send_photo(
            chat_id=chat_id,
            photo_path=result["path"],
            caption=f"🧪 **{label}**\n{result['summary']}",
        )
        if sent:
            await query.edit_message_text(f"✅ Test complete — **{label}** (photo above ☝️)")
        else:
            await query.edit_message_text(
                f"⚠️ **{label}** produced an image but the upload failed — check the Render logs."
            )
    else:
        err = (result["error"] or result["log"] or "provider returned no image")[:300]
        await query.edit_message_text(
            f"❌ **{label}** failed:\n`{err}`\n\nSend /testimage to try another provider."
        )


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /generate command."""
    if not context.args:
        await update.message.reply_text("❌ Please provide a prompt!")
        return

    # 1. EXTRACT ONLY PRIMITIVE DATA
    prompt_parts = []
    video_format = "narration"  # Default format

    # Parse arguments for format
    i = 0
    while i < len(context.args):
        arg = context.args[i]
        if arg == "--format" and i + 1 < len(context.args):
            format_value = context.args[i + 1].lower()
            if format_value in ["narration", "description"]:
                video_format = format_value
                i += 2  # Consume --format and its value
            else:
                await update.message.reply_text(f"Invalid format: `{format_value}`. Please use `narration` or `description`.")
                return
        else:
            prompt_parts.append(arg)
        i += 1

    if not prompt_parts:
        await update.message.reply_text("❌ Please provide a prompt after the format!")
        return

    prompt = " ".join(prompt_parts)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    job_id = f"{user_id}_{int(time.time())}"

    # Generate scenes and narrations first
    await update.message.reply_text("🧠 Generating script and scenes...")

    try:
        sg = SceneGenerator()
        scenes, narrations, metadata = sg.generate_all(prompt)

        # Build preview message with all narrations
        preview = "📝 **Script Preview:**\n\n"
        for i, (scene, narr) in enumerate(zip(scenes, narrations), 1):
            preview += f"**Scene {i}:**\n{narr}\n\n"

        preview += f"**Caption:** {metadata.get('caption', '')}\n"
        preview += f"**Hashtags:** {metadata.get('hashtags', '')}\n\n"
        preview += "Do you want to proceed with these narrations?"

        # Send preview with confirmation buttons
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [
            [
                InlineKeyboardButton("✅ Proceed", callback_data=f"proceed_{job_id}"),
                InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen_{job_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Store job data for callback
        job_data = {
            "prompt": prompt,
            "video_format": video_format,
            "chat_id": chat_id,
            "scenes": scenes,
            "narrations": narrations,
            "metadata": metadata
        }
        # Save job data to temp file for callback handler
        job_file = os.path.join(TEMP_DIR, f"job_{job_id}.json")
        with open(job_file, "w") as f:
            json.dump(job_data, f)

        await update.message.reply_text(preview, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        await update.message.reply_text(f"❌ Error generating script: {str(e)}")


def run_generation_sync(chat_id, scenes, narrations, metadata, job_id, video_format, series_ctx=None):
    """
    Synchronous background function that uses pre-approved scenes and narrations.
    Uses TelegramAPI for manual communication.

    When series_ctx is set (automated series run), progress messages get a
    "🎬 Series run k/n:" prefix and success/failure update the series file
    (success advances next_run; failure re-inserts the prompt at the head).
    """
    logger.info(f"📥 Processing job {job_id} in background thread with format {video_format}...")

    # Claim the single global job slot (no-op if the series runner already did).
    _set_job_busy(True)
    _run_prefix = ""
    if series_ctx:
        _run_prefix = "🎬 Series run %s/%s: " % (series_ctx.get("k", "?"), series_ctx.get("n", "?"))

    def _status_text(text):
        """Prefix progress/completion messages with the series run label
        ("🎬 Series run k/n:"). No-op for regular /generate jobs."""
        return _run_prefix + text if _run_prefix else text

    status_data = TelegramAPI.send_message(
        chat_id=chat_id,
        text=_status_text("🖼️ **Step 1/5:** Creating high-quality images...")
    )
    status_msg_id = status_data.get("message_id") if status_data else None

    try:
        if not scenes:
            raise Exception("No scenes to process.")

        if status_msg_id:
            TelegramAPI.edit_message(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=_status_text(f"🖼️ **Step 2/5:** Generated {len(scenes)} scenes.\nCreating high-quality images...")
            )

        # --- PHASE 2: IMAGES (with job-wide style bible for visual coherence) ---
        ig = ImageGenerator(job_id, style_bible=metadata.get("style_bible", ""))
        image_paths = []
        failed_scenes = 0
        for i, scene in enumerate(scenes):
            path = ig.generate_image(scene, i)
            if path:
                image_paths.append(path)
            else:
                failed_scenes += 1
            # Update progress occasionally
            if i > 0 and i % 3 == 0 and status_msg_id:
                TelegramAPI.edit_message(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text=_status_text(f"🖼️ **Step 2/5:** Creating images... ({i + 1}/{len(scenes)})")
                )

        # Degrade gracefully: a job can lose some scenes and still ship a good video.
        if not image_paths:
            raise Exception("Failed to generate any images.")
        if failed_scenes:
            logger.warning("Job %s: %s/%s scenes failed image generation.",
                           job_id, failed_scenes, len(scenes))
            if failed_scenes > len(scenes) * (1 - config.IMAGE_MIN_SUCCESS_RATIO):
                raise Exception(
                    f"Image generation quality too low: only {len(image_paths)}/{len(scenes)} "
                    f"scenes succeeded. Please try again."
                )
            if status_msg_id:
                TelegramAPI.edit_message(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text=_status_text(f"⚠️ {failed_scenes} scene(s) failed — continuing with {len(image_paths)}.")
                )

        # Log + remember which provider won, for the completion message later.
        image_summary = ig.provider_summary_text(len(scenes), len(image_paths))
        logger.info("[Job %s] Image summary: %s", job_id, image_summary)
        global _last_job_summary
        _last_job_summary = {"job_id": job_id, "summary": image_summary, "ts": time.time()}

        if status_msg_id:
            TelegramAPI.edit_message(chat_id=chat_id, message_id=status_msg_id,
                                    text=_status_text("🎙️ **Step 3/5:** Generating AI narration..."))

        # --- PHASE 3: AUDIO (captures real word timings from TTS) ---
        ap = AudioProcessor(job_id)
        narration_paths = []
        durations = []
        word_timings_data = []  # one entry per narration (list of {text,start,end} or None)

        if video_format == "narration":
            # Ensure unique narrations per scene
            unique_narrations = []
            seen = set()
            for n in narrations[:len(image_paths)]:
                if n and n not in seen:
                    unique_narrations.append(n)
                    seen.add(n)
                elif n:
                    # Add a variation if repeated
                    unique_narrations.append(f"{n} (part {len(unique_narrations)+1})")

            # Keep narrations aligned 1:1 with the images that were actually produced
            unique_narrations = unique_narrations[:len(image_paths)]

            # Validate narrations before generating audio
            if not unique_narrations:
                raise Exception("No narrations received from AI")

            import re
            scene_step_pattern = re.compile(r'\b(scene|step|phase|part)\s*\d+', re.IGNORECASE)
            for idx, n in enumerate(unique_narrations):
                if not n or not n.strip():
                    raise Exception(f"Narration {idx+1} is empty")
                if scene_step_pattern.search(n):
                    raise Exception(f"Narration {idx+1} contains scene/step reference: '{n[:50]}...'")

            # Check uniqueness (at least 70% should be unique)
            unique_count = len(set(n.lower().strip() for n in unique_narrations if n))
            if unique_count < len(unique_narrations) * 0.7:  # At least 70% should be unique
                raise Exception("AI Director returned repetitive narrations. Retrying...")

            num_narrations = len(unique_narrations)
            for i, narration_text in enumerate(unique_narrations):
                if status_msg_id:
                    TelegramAPI.edit_message(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=_status_text(f"🎙️ **Step 3/5:** Generating AI narration... ({i+1}/{num_narrations})")
                    )
                path, dur, timings = ap.generate_single_narration(narration_text, i)
                if path:
                    narration_paths.append(path)
                    durations.append(dur)
                    word_timings_data.append(timings)

            if not narration_paths:  # Only raise if narration expected
                raise Exception("Failed to generate narration files.")
        else:  # video_format == "description"
            logger.info("Skipping narration audio generation for 'description' format.")
            # Set durations to match images for video processing, even without narration audio
            durations = [VIDEO_DURATION_PER_SCENE] * len(image_paths)
            word_timings_data = [None] * len(image_paths)

        bg_music = None
        if os.path.exists(MUSIC_DIR):
            musics = [os.path.join(MUSIC_DIR, f) for f in os.listdir(MUSIC_DIR) if f.endswith(".mp3")]
            if musics:
                bg_music = musics[0]

        if status_msg_id:
            TelegramAPI.edit_message(chat_id=chat_id, message_id=status_msg_id,
                                    text=_status_text("🎵 **Step 3/5:** Finalizing audio mix..."))

        # --- PHASE 3b: AUDIO MERGE WITH ERROR HANDLING ---
        try:
            logger.info(f"Starting audio merge for job {job_id}...")
            final_audio = ap.merge_audio(narration_paths, bg_music)  # merge_audio handles empty narration_paths

            if not final_audio and (narration_paths or bg_music):  # Only raise if audio was expected
                raise Exception("Audio merge returned None - no audio file was created")

            if final_audio and not os.path.exists(final_audio):
                raise Exception(f"Audio file does not exist after merge: {final_audio}")

            logger.info(f"✅ Audio merge completed successfully")

        except Exception as e:
            logger.error(f"❌ Audio processing failed: {e}", exc_info=True)
            if status_msg_id:
                TelegramAPI.edit_message(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text=_status_text(f"❌ **Step 3 Failed:** Audio processing error\n\n`{str(e)[:100]}`")
                )
            raise Exception(f"Step 3 (Audio Merge) failed: {e}")

        # --- PHASE 4: VIDEO ---
        vp = VideoProcessor(job_id)

        # Determine which text to use for video overlay
        if video_format == "narration":
            text_for_video_overlay = unique_narrations
            srt_text_source = unique_narrations[:len(image_paths)]
        else:  # video_format == "description"
            text_for_video_overlay = scenes  # Use the scene descriptions
            srt_text_source = scenes[:len(image_paths)]

        # Ensure text_for_video_overlay matches image_paths length
        if len(text_for_video_overlay) > len(image_paths):
            text_for_video_overlay = text_for_video_overlay[:len(image_paths)]

        # Ensure durations matches image_paths length
        if len(durations) < len(image_paths):
            durations.extend([VIDEO_DURATION_PER_SCENE] * (len(image_paths) - len(durations)))
        elif len(durations) > len(image_paths):
            durations = durations[:len(image_paths)]

        # Ensure word timings matches image_paths length
        if len(word_timings_data) < len(image_paths):
            word_timings_data.extend([None] * (len(image_paths) - len(word_timings_data)))
        elif len(word_timings_data) > len(image_paths):
            word_timings_data = word_timings_data[:len(image_paths)]

        # Generate SRT (kept for reference/external use)
        srt_path = vp.generate_srt(srt_text_source, durations)

        clip_paths = []
        num_clips = len(image_paths)
        for i, (img_path, dur, scene_text, timings) in enumerate(
            zip(image_paths, durations, text_for_video_overlay, word_timings_data)
        ):
            if status_msg_id:
                # Show more detail: scene number and preview of text
                text_preview = scene_text[:50] + "..." if scene_text and len(scene_text) > 50 else scene_text
                TelegramAPI.edit_message(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text=_status_text(f"🎬 **Step 4/5:** Rendering scene {i+1}/{num_clips}\n📝 \"{text_preview}\"")
                )
            clip = vp.create_scene_video(
                img_path, dur, i, scene_text,
                narration_duration=dur,
                word_timings=timings,
            )
            clip_paths.append(clip)

        if status_msg_id:
            TelegramAPI.edit_message(chat_id=chat_id, message_id=status_msg_id,
                                    text=_status_text("🏗️ **Step 4/5:** Finalizing video assembly (this may take a minute)..."))

        # Free up memory before heavy FFmpeg render
        gc.collect()

        final_video = vp.assemble_video(clip_paths, final_audio, srt_path)

        # --- PHASE 5: UPLOAD ---
        if status_msg_id:
            TelegramAPI.edit_message(chat_id=chat_id, message_id=status_msg_id,
                                    text=_status_text("✅ **Step 5/5:** Uploading to Telegram..."))

        caption = metadata.get("caption", "AI Generated Video")
        hashtags = metadata.get("hashtags", "#ai #video")

        result = TelegramAPI.send_video(
            chat_id=chat_id,
            video_path=final_video,
            caption=f"{caption}\n\n{hashtags}"
        )

        # Turn the status message into a completion summary (winner + failed scenes)
        # instead of deleting it, so the provider choice is visible without Render logs.
        if result and status_msg_id:
            done_lines = [_status_text("✅ **Video ready!**")]
            done_lines.append(f"🖼️ {image_summary}")
            if failed_scenes:
                done_lines.append(f"⚠️ {failed_scenes} scene(s) skipped (image failures).")
            TelegramAPI.edit_message(
                chat_id=chat_id,
                message_id=status_msg_id,
                text="\n".join(done_lines)
            )

        logger.info(f"✨ Job {job_id} finished successfully!")
        if series_ctx:
            series_runner.on_series_success(series_ctx)

    except Exception as e:
        logger.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
        if series_ctx:
            series_runner.on_series_failure(series_ctx, e)
        else:
            TelegramAPI.send_message(
                chat_id=chat_id,
                text=f"❌ **Generation failed:** {str(e)}\nPlease try again."
            )
    finally:
        # Clean up temp files
        job_dir = os.path.join(TEMP_DIR, job_id)
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir)
        _set_job_busy(False)
        logger.info(f"🧹 Cleaned up job: {job_id}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks for approve/regenerate."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    if data.startswith("ti_"):
        await _run_testimage(query, data)
        return

    if data.startswith("sc_"):
        await _handle_series_callback(query, data)
        return

    if data.startswith("proceed_"):
        job_id = data.replace("proceed_", "")
        # Load job data and start processing
        job_file = os.path.join(TEMP_DIR, f"job_{job_id}.json")
        if os.path.exists(job_file):
            with open(job_file, "r") as f:
                job_data = json.load(f)

            scenes = job_data.get("scenes", [])
            narrations = job_data.get("narrations", [])
            metadata = job_data.get("metadata", {})
            video_format = job_data.get("video_format", "narration")

            await query.edit_message_text("🚀 **Starting video generation...**")

            # Run in background thread
            thread = threading.Thread(
                target=run_generation_sync,
                args=(chat_id, scenes, narrations, metadata, job_id, video_format)
            )
            thread.start()
    elif data.startswith("regen_"):
        job_id = data.replace("regen_", "")

        # Load job data and regenerate
        job_file = os.path.join(TEMP_DIR, f"job_{job_id}.json")
        if os.path.exists(job_file):
            with open(job_file, "r") as f:
                job_data = json.load(f)

            prompt = job_data.get("prompt", "")
            video_format = job_data.get("video_format", "narration")

            await query.edit_message_text("🔄 Regenerating script...")

            try:
                sg = SceneGenerator()
                scenes, narrations, metadata = sg.generate_all(prompt)

                # Show new preview
                preview = "📝 **Regenerated Script:**\n\n"
                for i, (scene, narr) in enumerate(zip(scenes, narrations), 1):
                    preview += f"**Scene {i}:**\n{narr}\n\n"

                preview += f"**Caption:** {metadata.get('caption', '')}\n"
                preview += f"**Hashtags:** {metadata.get('hashtags', '')}\n\n"
                preview += "Do you want to proceed with these narrations?"

                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Proceed", callback_data=f"proceed_{job_id}"),
                        InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen_{job_id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                # Update job data with new scenes/narrations
                job_data["scenes"] = scenes
                job_data["narrations"] = narrations
                job_data["metadata"] = metadata
                with open(job_file, "w") as f:
                    json.dump(job_data, f)

                await query.edit_message_text(preview, parse_mode="Markdown", reply_markup=reply_markup)

            except Exception as e:
                await query.edit_message_text(f"❌ Regeneration failed: {str(e)}")


# ===========================================================================
# Content Series commands (/series ...) - see series-unorouter-spec.md
# ===========================================================================

_SERIES_HELP = (
    "📺 **Content Series** — queue prompts and auto-generate videos on a schedule.\n\n"
    "• `/series create <title>` — start a new series\n"
    "• `/series add <prompt text>` — add prompt(s); one per line for multiple\n"
    "• `/series generate <N> <brief>` — AI expands the brief into N prompts\n"
    "• `/series list` — show every queued prompt\n"
    "• `/series schedule <hours>` — auto-generate every N hours\n"
    "• `/series schedule <hours> at HH:MM` — anchor runs to a wall-clock time\n"
    "• `/series pause` / `/series resume`\n"
    "• `/series run` — generate the next prompt now\n"
    "• `/series status` — schedule summary\n"
    "• `/series clear` — delete the series"
)

# Callback scratchpad for the /series generate preview (single-user bot).
_series_generated = {"prompts": [], "fmt": "narration"}


def _parse_series_args(args):
    """Split context.args into (subcommand, rest_tokens, fmt)."""
    sub = args[0].lower() if args else ""
    fmt = "narration"
    rest = []
    i = 1
    while i < len(args):
        if args[i] == "--format" and i + 1 < len(args):
            if args[i + 1].lower() in ("narration", "description"):
                fmt = args[i + 1].lower()
                i += 2
                continue
        rest.append(args[i])
        i += 1
    return sub, rest, fmt


def _series_add_payload(raw_text):
    """Re-extract the /series add argument block from the RAW message text.

    context.args is built with .split(), which collapses newlines — that would
    destroy the one-prompt-per-line multi-add. The raw message text keeps them.
    Also strips a leading/trailing '--format narration|description' flag.
    Returns (payload, fmt)."""
    tokens = raw_text.split(None, 1)
    # Drop the command word; if the next word is the 'add' subcommand, drop it too
    # (so line 1 of a multi-line payload is a real prompt, not the literal 'add').
    tail = tokens[1] if len(tokens) > 1 else ""
    sub_tokens = tail.split(None, 1)
    if sub_tokens and sub_tokens[0].lower() == "add":
        tail = sub_tokens[1] if len(sub_tokens) > 1 else ""
    raw = tail
    fmt = "narration"
    m = re.search(r"(?:^|\s)--format\s+(narration|description)(?=\s|$)", raw)
    if m:
        fmt = m.group(1)
        raw = raw[:m.start()] + " " + raw[m.end():]
    return raw.strip(), fmt


async def series_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single dispatcher for all /series subcommands."""
    args = context.args or []
    sub, rest, fmt = _parse_series_args(args)
    manager = SeriesManager()
    data = manager.load()

    if sub == "" or sub == "help":
        await update.message.reply_text(_SERIES_HELP, parse_mode="Markdown")
        return

    # --- create -----------------------------------------------------------
    if sub == "create":
        title = " ".join(rest).strip()
        if not title:
            await update.message.reply_text("Usage: `/series create <title>`", parse_mode="Markdown")
            return
        if data:
            # Replace only after confirmation (inline button).
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            kb = [[
                InlineKeyboardButton("⚠️ Replace series", callback_data="sc_replace_create"),
                InlineKeyboardButton("❌ Cancel", callback_data="sc_cancel"),
            ]]
            _series_generated["new_title"] = title
            await update.message.reply_text(
                "⚠️ An active series already exists: **%s** (%d prompts).\nReplace it with **%s**?"
                % (data["title"], len(data["prompts"]), title),
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb),
            )
            return
        data = manager.create(title, update.effective_chat.id)
        await update.message.reply_text(
            "✅ Series **%s** created (0 prompts).\nAdd prompts with `/series add <text>` "
            "or `/series generate <N> <brief>`, then set a schedule with `/series schedule <hours>`."
            % title, parse_mode="Markdown")
        return

    # All other subcommands require an existing series.
    if not data:
        await update.message.reply_text(
            "No active series. Create one first: `/series create <title>`", parse_mode="Markdown")
        return

    # --- add --------------------------------------------------------------
    if sub == "add":
        # Raw message text (not context.args): preserves newlines for
        # one-prompt-per-line multi-adds. --format is parsed here instead.
        raw, fmt = _series_add_payload(getattr(update.effective_message, "text", "") or "")
        if not raw:
            await update.message.reply_text(
                "Usage: `/series add <prompt text>` — multi-line text adds one prompt per line.",
                parse_mode="Markdown")
            return
        # Auto-detect multi-line: one prompt per line (blank lines skipped).
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        added, skipped = 0, 0
        for ln in lines:
            ok, reason = manager.add_prompt(data, ln, fmt)
            if ok:
                added += 1
            else:
                skipped += 1
        if added:
            manager.save(data)
        msg = "✅ Added %d prompt(s) (%d/%d queued)." % (
            added, len(data["prompts"]), config.SERIES_MAX_PROMPTS)
        if skipped:
            msg += "\n⚠️ %d skipped — queue is full (cap %d)." % (skipped, config.SERIES_MAX_PROMPTS)
        await update.message.reply_text(msg)
        return

    # --- generate ----------------------------------------------------------
    if sub == "generate":
        if not rest or not rest[0].isdigit():
            await update.message.reply_text(
                "Usage: `/series generate <N> <brief>` (N = 1-%d)" % config.SERIES_MAX_PROMPTS_PER_GENERATE,
                parse_mode="Markdown")
            return
        n = int(rest[0])
        if not 1 <= n <= config.SERIES_MAX_PROMPTS_PER_GENERATE:
            await update.message.reply_text(
                "N must be between 1 and %d." % config.SERIES_MAX_PROMPTS_PER_GENERATE)
            return
        brief = " ".join(rest[1:]).strip()
        if not brief:
            await update.message.reply_text(
                "Usage: `/series generate <N> <brief>` — e.g. `/series generate 10 electricity bill hacks`",
                parse_mode="Markdown")
            return
        room = config.SERIES_MAX_PROMPTS - len(data["prompts"])
        if room <= 0:
            await update.message.reply_text(
                "⚠️ Queue is full (%d/%d). Remove prompts or /series clear first."
                % (len(data["prompts"]), config.SERIES_MAX_PROMPTS))
            return
        n = min(n, room)

        await update.message.reply_text("🧠 Generating %d prompts for **%s**..." % (n, data["title"]),
                                        parse_mode="Markdown")
        try:
            sg = SceneGenerator()
            system_prompt = (
                "You are a content strategist planning a video series.\n"
                "Series title: %s\n"
                "Brief: %s\n\n"
                "Write %d DISTINCT video prompts (ideas) for this series. Each prompt is one\n"
                "concrete, self-contained video idea that fits the series title and builds on the brief.\n"
                "Number them implicitly by list order. No numbering inside the text.\n"
                "Output JSON ONLY: {\"prompts\": [\"prompt 1\", \"prompt 2\", ...]} — exactly %d strings."
                % (data["title"], brief, n, n)
            )
            content = sg.llm.generate_text(system_prompt, "Generate the prompts.", temperature=0.8,
                                           timeout=90, json_mode=True)
            generated = extract_json(content).get("prompts", [])
            generated = [g.strip() for g in generated if isinstance(g, str) and g.strip()][:n]
            if len(generated) < n:
                raise Exception("LLM returned only %d/%d usable prompts." % (len(generated), n))
        except Exception as e:
            await update.message.reply_text("❌ Prompt generation failed: %s" % str(e)[:200])
            return

        _series_generated["prompts"] = generated
        _series_generated["fmt"] = fmt
        preview = "📝 **%d generated prompts** (series: %s):\n\n" % (len(generated), data["title"])
        preview += "\n".join("%d. %s" % (i + 1, g[:90]) for i, g in enumerate(generated))
        preview += "\n\nAdd all of these to the queue?"
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = [[
            InlineKeyboardButton("✅ Add all", callback_data="sc_add_generated"),
            InlineKeyboardButton("❌ Discard", callback_data="sc_cancel"),
        ]]
        await update.message.reply_text(preview, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup(kb))
        return

    # --- list ---------------------------------------------------------------
    if sub == "list":
        await update.message.reply_text(manager.queue_text(data), parse_mode="Markdown")
        return

    # --- status -------------------------------------------------------------
    if sub == "status":
        await update.message.reply_text(manager.summary_text(data), parse_mode="Markdown")
        return

    # --- schedule -------------------------------------------------------------
    if sub == "schedule":
        if not rest or not rest[0].isdigit():
            await update.message.reply_text(
                "Usage: `/series schedule <hours>` or `/series schedule <hours> at HH:MM`\n"
                "Example: `/series schedule 24 at 09:00` (timezone: %s)"
                % config.SERIES_TIMEZONE, parse_mode="Markdown")
            return
        hours = int(rest[0])
        if not 1 <= hours <= 168:
            await update.message.reply_text("Hours must be between 1 and 168.")
            return
        anchor = None
        if len(rest) >= 3 and rest[1].lower() == "at":
            anchor = rest[2].strip()
            if not re.match(r"^\d{1,2}:\d{2}$", anchor):
                await update.message.reply_text(
                    "Time must be HH:MM (24h), e.g. `at 09:00`.", parse_mode="Markdown")
                return
        sched = manager.set_schedule(data, interval_hours=hours, anchor=anchor, enabled=True)
        manager.save(data)

        # Ask: run the next prompt right now, or wait for the first slot?
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = [[
            InlineKeyboardButton("▶️ Generate next prompt now", callback_data="sc_run_now"),
            InlineKeyboardButton("⏰ Wait for first slot", callback_data="sc_wait_slot"),
        ]]
        anchor_txt = (" at " + sched["anchor"]) if sched.get("anchor") else ""
        await update.message.reply_text(
            "⏰ Schedule set: every %dh%s (timezone %s).\nNext run: %s\n\nGenerate the next prompt now?"
            % (hours, anchor_txt, config.SERIES_TIMEZONE, manager.format_next_run(data)),
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return

    # --- pause / resume -------------------------------------------------------
    if sub == "pause":
        manager.pause(data)
        manager.save(data)
        await update.message.reply_text("⏸ Series paused. Next run will fire immediately on resume if overdue.")
        return

    if sub == "resume":
        manager.resume(data)
        manager.save(data)
        await update.message.reply_text(
            "▶️ Series resumed.\nNext run: %s" % manager.format_next_run(data), parse_mode="Markdown")
        return

    # --- run (generate next prompt NOW) -----------------------------------------
    if sub == "run":
        if _job_slot_busy():
            await update.message.reply_text("⏳ A video is already generating — try again when it finishes.")
            return
        prompt = manager.pop_next(data)
        if prompt is None:
            await update.message.reply_text("📭 No pending prompts in the queue.")
            return
        manager.mark_run_started(data)
        manager.save(data)
        await update.message.reply_text("🚀 Starting series run for `%s`..." % prompt["id"],
                                        parse_mode="Markdown")
        k, n = manager.run_position(data)
        series_runner.launch_series_run(manager, data, prompt, k=k, n=n)
        return

    # --- clear --------------------------------------------------------------------
    if sub == "clear":
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = [[
            InlineKeyboardButton("🗑 Delete everything", callback_data="sc_confirm_clear"),
            InlineKeyboardButton("❌ Cancel", callback_data="sc_cancel"),
        ]]
        await update.message.reply_text(
            "⚠️ Delete series **%s** (%d prompts, schedule included)? This cannot be undone."
            % (data["title"], len(data["prompts"])),
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return

    await update.message.reply_text("Unknown subcommand `%s`.\n\n%s" % (sub, _SERIES_HELP),
                                    parse_mode="Markdown")


async def _handle_series_callback(query, data_str: str):
    """Inline button callbacks for the /series command (sc_* prefix)."""
    manager = SeriesManager()
    action = data_str.replace("sc_", "")

    if action == "cancel":
        _series_generated["prompts"] = []
        await query.edit_message_text("Cancelled.")
        return

    if action == "confirm_clear":
        data = manager.load()
        if data:
            title = data["title"]
            try:
                os.remove(SERIES_FILE)
            except OSError:
                pass
            await query.edit_message_text("🗑 Series **%s** deleted." % title, parse_mode="Markdown")
        else:
            await query.edit_message_text("Nothing to delete.")
        return

    if action == "replace_create":
        title = _series_generated.get("new_title", "")
        data = manager.create(title, query.message.chat_id)
        await query.edit_message_text(
            "✅ Series **%s** created (0 prompts). Add prompts with `/series add <text>`."
            % title, parse_mode="Markdown")
        return

    if action == "add_generated":
        data = manager.load()
        if not data:
            await query.edit_message_text("Series was deleted — nothing to add.")
            return
        prompts = _series_generated.get("prompts", [])
        if not prompts:
            await query.edit_message_text("Nothing to add (menu expired — run /series generate again).")
            return
        added = 0
        for p in prompts:
            ok, _ = manager.add_prompt(data, p, _series_generated.get("fmt", "narration"))
            if ok:
                added += 1
        if added:
            manager.save(data)
        _series_generated["prompts"] = []
        await query.edit_message_text(
            "✅ Added %d prompt(s) to **%s** (%d/%d queued)." % (
                added, data["title"], len(data["prompts"]), config.SERIES_MAX_PROMPTS),
            parse_mode="Markdown")
        return

    if action in ("run_now", "wait_slot"):
        data = manager.load()
        if action == "wait_slot":
            if data:
                await query.edit_message_text(
                    "⏰ First run: %s" % manager.format_next_run(data), parse_mode="Markdown")
            else:
                await query.edit_message_text("Series no longer exists.")
            return
        # run_now: generate the next prompt immediately.
        if not data:
            await query.edit_message_text("Series no longer exists.")
            return
        if _job_slot_busy():
            await query.edit_message_text(
                "⏳ A video is already generating — the run will fire at %s."
                % manager.format_next_run(data), parse_mode="Markdown")
            return
        prompt = manager.pop_next(data)
        if prompt is None:
            await query.edit_message_text("📭 No pending prompts in the queue.")
            return
        manager.mark_run_started(data)
        manager.save(data)
        await query.edit_message_text("🚀 Starting series run for `%s`..." % prompt["id"],
                                      parse_mode="Markdown")
        k, n = manager.run_position(data)
        series_runner.launch_series_run(manager, data, prompt, k=k, n=n)
        return

    await query.edit_message_text("Unknown action.")
