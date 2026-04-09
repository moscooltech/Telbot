import os
import threading
import time
import shutil
import logging
import gc
from telegram import Update
from telegram.ext import ContextTypes
from services.scene_generator import SceneGenerator
from services.image_generator import ImageGenerator
from services.audio_processor import AudioProcessor
from services.video_processor import VideoProcessor
from config import TEMP_DIR, MUSIC_DIR, VIDEO_DURATION_PER_SCENE
from utils.telegram_api import TelegramAPI

# Configure logging
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Hello {user_name}! I am your AI Video Creator.\n\n"
        "Send /generate (or /gen) followed by a story prompt to create a viral video.\n\n"
        "Example: `/gen A story about a lost astronaut on a neon planet.`",
        parse_mode="Markdown"
    )

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /generate command."""
    if not context.args:
        await update.message.reply_text("❌ Please provide a prompt!")
        return
        
    # 1. EXTRACT ONLY PRIMITIVE DATA
    prompt_parts = []
    video_format = "narration" # Default format

    # Parse arguments for format
    i = 0
    while i < len(context.args):
        arg = context.args[i]
        if arg == "--format" and i + 1 < len(context.args):
            format_value = context.args[i+1].lower()
            if format_value in ["narration", "description"]:
                video_format = format_value
                i += 2 # Consume --format and its value
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
    
    # Inform user immediately via the normal async context
    await update.message.reply_text(
        f"🚀 **Job Received!**
Your video is being processed in the background.
**ID:** `{job_id}`
**Format:** `{video_format.capitalize()}`", 
        parse_mode="Markdown"
    )
    
    # 2. PASS CLEAN ARGUMENTS INTO A THREAD
    # We use threading.Thread for heavy work to avoid blocking the event loop
    # and to bypass async-bound object issues.
    thread = threading.Thread(
        target=run_generation_sync,
        args=(chat_id, prompt, job_id, video_format)
    )
    thread.start()
    logger.info(f"Started background thread for job {job_id} with format {video_format}")

def run_generation_sync(chat_id, prompt, job_id, video_format):
    """
    Synchronous background function that accepts only primitive arguments.
    Uses TelegramAPI for manual communication.
    """
    logger.info(f"📥 Processing job {job_id} in background thread with format {video_format}...")
    
    # 3. REFACTOR BACKGROUND FUNCTION TO USE MANUAL API
    status_data = TelegramAPI.send_message(
        chat_id=chat_id, 
        text="🧠 **Step 1/5:** Generating story and scenes..."
    )
    status_msg_id = status_data.get("message_id") if status_data else None
    
    try:
        # --- PHASE 1: SCENES ---
        sg = SceneGenerator()
        scenes, narrations, metadata = sg.generate_all(prompt)
        if not scenes:
            raise Exception("Failed to generate scenes.")
        
        if status_msg_id:
            TelegramAPI.edit_message(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=f"🖼️ **Step 2/5:** Generated {len(scenes)} scenes.
Creating high-quality images..."
            )
        
        # --- PHASE 2: IMAGES ---
        ig = ImageGenerator(job_id)
        image_paths = []
        for i, scene in enumerate(scenes):
            path = ig.generate_image(scene, i)
            if path:
                image_paths.append(path)
                # Update progress occasionally
                if i > 0 and i % 3 == 0 and status_msg_id:
                    TelegramAPI.edit_message(
                        chat_id=chat_id,
                        message_id=status_msg_id,
                        text=f"🖼️ **Step 2/5:** Creating images... ({i}/{len(scenes)})"
                    )

        if not image_paths:
            raise Exception("Failed to generate any images.")
            
        if status_msg_id:
            TelegramAPI.edit_message(chat_id=chat_id, message_id=status_msg_id, text="🎙️ **Step 3/5:** Generating AI narration...")
        
        # --- PHASE 3: AUDIO ---
        ap = AudioProcessor(job_id)
        narration_paths = []
        durations = []
        
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
                        text=f"🎙️ **Step 3/5:** Generating AI narration... ({i+1}/{num_narrations})"
                    )
                path, dur = ap.generate_single_narration(narration_text, i)
                if path:
                    narration_paths.append(path)
                    durations.append(dur)
            
            if not narration_paths and video_format == "narration": # Only raise if narration expected
                raise Exception("Failed to generate narration files.")
        else: # video_format == "description"
            logger.info("Skipping narration audio generation for 'description' format.")
            # Set durations to match images for video processing, even without narration audio
            # Assuming a default duration per scene for description videos if no narration audio is used
            durations = [VIDEO_DURATION_PER_SCENE] * len(image_paths)

        bg_music = None
        if os.path.exists(MUSIC_DIR):
            musics = [os.path.join(MUSIC_DIR, f) for f in os.listdir(MUSIC_DIR) if f.endswith(".mp3")]
            if musics:
                bg_music = musics[0]
        
        if status_msg_id:
            TelegramAPI.edit_message(chat_id=chat_id, message_id=status_msg_id, text="🎵 **Step 3/5:** Finalizing audio mix...")
        
        # --- PHASE 3b: AUDIO MERGE WITH ERROR HANDLING ---
        try:
            logger.info(f"Starting audio merge for job {job_id}...")
            final_audio = ap.merge_audio(narration_paths, bg_music) # merge_audio needs to handle empty narration_paths
            
            if not final_audio and (narration_paths or bg_music): # Only raise if audio was expected
                raise Exception("Audio merge returned None - no audio file was created")
            
            if final_audio and not os.path.exists(final_audio): # Check if file exists if returned
                raise Exception(f"Audio file does not exist after merge: {final_audio}")
            
            logger.info(f"✅ Audio merge completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Audio processing failed: {e}", exc_info=True)
            if status_msg_id:
                TelegramAPI.edit_message(
                    chat_id=chat_id,
                    message_id=status_msg_id,
                    text=f"❌ **Step 3 Failed:** Audio processing error

`{str(e)[:100]}`"
                )
            raise Exception(f"Step 3 (Audio Merge) failed: {e}")
        
        # --- PHASE 4: VIDEO ---
        vp = VideoProcessor(job_id)
        
        # Determine which text to use for video overlay
        if video_format == "narration":
            # unique_narrations would have been set in PHASE 3 if video_format was narration
            text_for_video_overlay = unique_narrations
            srt_text_source = unique_narrations[:len(image_paths)] # For SRT generation
        else: # video_format == "description"
            text_for_video_overlay = scenes # Use the scene descriptions (visuals from SceneGenerator)
            srt_text_source = scenes[:len(image_paths)] # For SRT generation, or skip if not desired

        # Ensure text_for_video_overlay matches image_paths length
        if len(text_for_video_overlay) > len(image_paths):
            text_for_video_overlay = text_for_video_overlay[:len(image_paths)]
        
        # Ensure durations matches image_paths length
        if len(durations) < len(image_paths):
            # Fill with default duration if not enough durations (e.g., for description format)
            durations.extend([VIDEO_DURATION_PER_SCENE] * (len(image_paths) - len(durations)))
        elif len(durations) > len(image_paths):
            durations = durations[:len(image_paths)]

        # Generate SRT (if needed for captions, even if not audio narration)
        # Note: durations will be empty for description format, so srt_path won't contain durations
        srt_path = vp.generate_srt(srt_text_source, durations)

        clip_paths = []
        num_clips = len(image_paths)
        for i, (img_path, dur, scene_text) in enumerate(zip(image_paths, durations, text_for_video_overlay)):
            if status_msg_id:
                TelegramAPI.edit_message(
                    chat_id=chat_id, 
                    message_id=status_msg_id,
                    text=f"🎬 **Step 4/5:** Processing video clips... ({i+1}/{num_clips})"
                )
            clip = vp.create_scene_video(img_path, dur, i, scene_text) # Pass selected text
            clip_paths.append(clip)
            
        if status_msg_id:
            TelegramAPI.edit_message(chat_id=chat_id, message_id=status_msg_id, text="🏗️ **Step 4/5:** Finalizing video assembly (this may take a minute)...")
        
        # Free up memory before heavy FFmpeg render
        gc.collect()
            
        final_video = vp.assemble_video(clip_paths, final_audio, srt_path)
        
        # --- PHASE 5: UPLOAD ---
        if status_msg_id:
            TelegramAPI.edit_message(chat_id=chat_id, message_id=status_msg_id, text="✅ **Step 5/5:** Uploading to Telegram...")
        
        caption = metadata.get("caption", "AI Generated Video")
        hashtags = metadata.get("hashtags", "#ai #video")
        
        # 4. SEND RESULT MANUALLY VIA TELEGRAM API
        result = TelegramAPI.send_video(
            chat_id=chat_id,
            video_path=final_video,
            caption=f"{caption}

{hashtags}"
        )
        
        if result and status_msg_id:
            TelegramAPI.delete_message(chat_id, status_msg_id)
            
        logger.info(f"✨ Job {job_id} finished successfully!")

    except Exception as e:
        logger.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
        TelegramAPI.send_message(
            chat_id=chat_id,
            text=f"❌ **Generation failed:** {str(e)}
Please try again."
        )
    finally:
        # Clean up temp files
        job_dir = os.path.join(TEMP_DIR, job_id)
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir)
        logger.info(f"🧹 Cleaned up job: {job_id}")