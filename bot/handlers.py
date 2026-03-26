import os
import threading
import time
import shutil
import logging
from telegram import Update
from telegram.ext import ContextTypes
from services.scene_generator import SceneGenerator
from services.image_generator import ImageGenerator
from services.audio_processor import AudioProcessor
from services.video_processor import VideoProcessor
from config import TEMP_DIR, MUSIC_DIR
from utils.telegram_api import TelegramAPI

# Configure logging
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command."""
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Hello {user_name}! I am your AI Video Creator.\n\n"
        "Send /generate followed by a story prompt to create a viral video.\n"
        "Example: `/generate A story about a lost astronaut on a neon planet.`",
        parse_mode="Markdown"
    )

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /generate command."""
    if not context.args:
        await update.message.reply_text("❌ Please provide a prompt!")
        return
        
    # 1. EXTRACT ONLY PRIMITIVE DATA
    prompt = " ".join(context.args)
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    job_id = f"{user_id}_{int(time.time())}"
    
    # Inform user immediately via the normal async context
    await update.message.reply_text(
        f"🚀 **Job Received!**\nYour video is being processed in the background.\n**ID:** `{job_id}`", 
        parse_mode="Markdown"
    )
    
    # 2. PASS CLEAN ARGUMENTS INTO A THREAD
    # We use threading.Thread for heavy work to avoid blocking the event loop
    # and to bypass async-bound object issues.
    thread = threading.Thread(
        target=run_generation_sync,
        args=(chat_id, prompt, job_id)
    )
    thread.start()
    logger.info(f"Started background thread for job {job_id}")

def run_generation_sync(chat_id, prompt, job_id):
    """
    Synchronous background function that accepts only primitive arguments.
    Uses TelegramAPI for manual communication.
    """
    logger.info(f"📥 Processing job {job_id} in background thread...")
    
    # 3. REFACTOR BACKGROUND FUNCTION TO USE MANUAL API
    status_data = TelegramAPI.send_message(
        chat_id=chat_id, 
        text="🧠 **Step 1/5:** Generating story and scenes..."
    )
    status_msg_id = status_data.get("message_id") if status_data else None
    
    try:
        # --- PHASE 1: SCENES ---
        sg = SceneGenerator()
        scenes, metadata = sg.generate_all(prompt)
        if not scenes:
            raise Exception("Failed to generate scenes.")
        
        if status_msg_id:
            TelegramAPI.edit_message(
                chat_id=chat_id,
                message_id=status_msg_id,
                text=f"🖼️ **Step 2/5:** Generated {len(scenes)} scenes.\nCreating high-quality images..."
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
        narration_paths, durations = ap.generate_narration(scenes[:len(image_paths)])
        
        bg_music = None
        if os.path.exists(MUSIC_DIR):
            musics = [os.path.join(MUSIC_DIR, f) for f in os.listdir(MUSIC_DIR) if f.endswith(".mp3")]
            if musics:
                bg_music = musics[0]
                
        final_audio = ap.merge_audio(narration_paths, bg_music)
        
        if status_msg_id:
            TelegramAPI.edit_message(chat_id=chat_id, message_id=status_msg_id, text="🎬 **Step 4/5:** Assembling video (this may take a minute)...")
        
        # --- PHASE 4: VIDEO ---
        vp = VideoProcessor(job_id)
        srt_path = vp.generate_srt(scenes[:len(image_paths)], durations)
        
        clip_paths = []
        for i, (img_path, dur) in enumerate(zip(image_paths, durations)):
            clip = vp.create_scene_video(img_path, dur, i)
            clip_paths.append(clip)
            
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
            caption=f"{caption}\n\n{hashtags}"
        )
        
        if result and status_msg_id:
            TelegramAPI.delete_message(chat_id, status_msg_id)
            
        logger.info(f"✨ Job {job_id} finished successfully!")

    except Exception as e:
        logger.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
        TelegramAPI.send_message(
            chat_id=chat_id,
            text=f"❌ **Generation failed:** {str(e)}\nPlease try again."
        )
    finally:
        # Clean up temp files
        job_dir = os.path.join(TEMP_DIR, job_id)
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir)
        logger.info(f"🧹 Cleaned up job: {job_id}")
