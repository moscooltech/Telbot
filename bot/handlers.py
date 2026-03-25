import os
import asyncio
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

# Configure logging
logger = logging.getLogger(__name__)

# Global queue for jobs
queue = asyncio.Queue()

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
        await update.message.reply_text("❌ Please provide a prompt! Example: /generate A futuristic city in Nigeria.")
        return
        
    prompt = " ".join(context.args)
    job_id = f"{update.message.from_user.id}_{int(time.time())}"
    
    # Inform user and add to queue
    await update.message.reply_text(f"🚀 **Job Received!**\nYour video is being added to the queue.\n**ID:** `{job_id}`", parse_mode="Markdown")
    await queue.put((update, prompt, job_id))

async def process_queue():
    """Worker task to process jobs one by one."""
    logger.info("👷 Worker task started and waiting for jobs...")
    while True:
        update, prompt, job_id = await queue.get()
        logger.info(f"📥 Processing job: {job_id}")
        try:
            await run_generation(update, prompt, job_id)
        except Exception as e:
            logger.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
            try:
                await update.message.reply_text(f"❌ **Generation failed:** {str(e)}\nPlease try again with a different prompt.", parse_mode="Markdown")
            except:
                pass
        finally:
            queue.task_done()
            # Clean up temp files
            job_dir = os.path.join(TEMP_DIR, job_id)
            if os.path.exists(job_dir):
                shutil.rmtree(job_dir)
            logger.info(f"🧹 Cleaned up job: {job_id}")

async def run_generation(update: Update, prompt: str, job_id: str):
    """Main generation logic with progress updates."""
    status_msg = await update.message.reply_text("🧠 **Step 1/5:** Generating story and scenes...", parse_mode="Markdown")
    
    # 1. Generate Scenes & Metadata
    logger.info(f"[{job_id}] Generating scenes...")
    sg = SceneGenerator()
    scenes, metadata = sg.generate_all(prompt)
    if not scenes:
        raise Exception("Failed to generate scenes from AI.")
    
    await status_msg.edit_text(f"🖼️ **Step 2/5:** Generated {len(scenes)} scenes.\nCreating high-quality images...", parse_mode="Markdown")
    logger.info(f"[{job_id}] Generating {len(scenes)} images...")
    
    # 2. Generate Images
    ig = ImageGenerator(job_id)
    image_paths = []
    for i, scene in enumerate(scenes):
        if i > 0:
            await status_msg.edit_text(f"🖼️ **Step 2/5:** Creating images... ({i}/{len(scenes)})", parse_mode="Markdown")
        path = ig.generate_image(scene, i)
        if path:
            image_paths.append(path)
        else:
            logger.warning(f"[{job_id}] Failed image for scene {i}, skipping.")

    if not image_paths:
        raise Exception("Failed to generate any images.")
        
    await status_msg.edit_text("🎙️ **Step 3/5:** Images done. Generating AI narration...", parse_mode="Markdown")
    logger.info(f"[{job_id}] Generating narration...")
    
    # 3. Generate Audio
    ap = AudioProcessor(job_id)
    narration_paths, durations = ap.generate_narration(scenes[:len(image_paths)])
    
    # Pick first bg music if exists
    bg_music = None
    if os.path.exists(MUSIC_DIR):
        musics = [os.path.join(MUSIC_DIR, f) for f in os.listdir(MUSIC_DIR) if f.endswith(".mp3")]
        if musics:
            bg_music = musics[0]
            
    final_audio = ap.merge_audio(narration_paths, bg_music)
    logger.info(f"[{job_id}] Audio processing complete.")
    
    await status_msg.edit_text("🎬 **Step 4/5:** Assembling video (this may take a minute)...", parse_mode="Markdown")
    logger.info(f"[{job_id}] Assembling video clips...")
    
    # 4. Generate Video
    vp = VideoProcessor(job_id)
    srt_path = vp.generate_srt(scenes[:len(image_paths)], durations)
    
    clip_paths = []
    for i, (img_path, dur) in enumerate(zip(image_paths, durations)):
        logger.info(f"[{job_id}] Processing clip {i+1}/{len(image_paths)}")
        clip = vp.create_scene_video(img_path, dur, i)
        clip_paths.append(clip)
        
    final_video = vp.assemble_video(clip_paths, final_audio, srt_path)
    logger.info(f"[{job_id}] Video assembly complete: {final_video}")
    
    caption = metadata.get("caption", "")
    hashtags = metadata.get("hashtags", "")
    
    await status_msg.edit_text("✅ **Step 5/5:** Video complete! Uploading to Telegram...", parse_mode="Markdown")
    
    # 5. Send Result
    logger.info(f"[{job_id}] Uploading final video...")
    with open(final_video, "rb") as video:
        await update.message.reply_video(
            video=video,
            caption=f"{caption}\n\n{hashtags}",
            supports_streaming=True
        )
    
    await status_msg.delete()
    logger.info(f"✨ Job {job_id} finished successfully!")
