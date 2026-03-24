import os
import asyncio
import time
import shutil
from telegram import Update
from telegram.ext import ContextTypes
from services.scene_generator import SceneGenerator
from services.image_generator import ImageGenerator
from services.audio_processor import AudioProcessor
from services.video_processor import VideoProcessor
from config import TEMP_DIR, MUSIC_DIR

# Global queue for jobs
queue = asyncio.Queue()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! Send /generate <your story prompt> to create a viral video.")

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please provide a prompt! Example: /generate A futuristic city in Nigeria.")
        return
        
    prompt = " ".join(context.args)
    job_id = f"{update.message.from_user.id}_{int(time.time())}"
    
    # Inform user and add to queue
    await update.message.reply_text(f"🚀 Job received! Adding to queue... ID: {job_id}")
    await queue.put((update, prompt, job_id))

async def process_queue():
    """Worker task to process jobs one by one."""
    while True:
        update, prompt, job_id = await queue.get()
        try:
            await run_generation(update, prompt, job_id)
        except Exception as e:
            print(f"Job {job_id} failed: {e}")
            await update.message.reply_text(f"❌ Generation failed: {str(e)}")
        finally:
            queue.task_done()
            # Clean up temp files
            job_dir = os.path.join(TEMP_DIR, job_id)
            if os.path.exists(job_dir):
                shutil.rmtree(job_dir)

async def run_generation(update: Update, prompt: str, job_id: str):
    status_msg = await update.message.reply_text("🧠 Generating scenes...")
    
    # 1. Generate Scenes
    sg = SceneGenerator()
    scenes = sg.generate_scenes(prompt)
    if not scenes:
        raise Exception("Failed to generate scenes.")
    
    await status_msg.edit_text(f"🖼️ Generated {len(scenes)} scenes. Creating images...")
    
    # 2. Generate Images
    ig = ImageGenerator(job_id)
    image_paths = ig.generate_all_images(scenes)
    if not image_paths:
        raise Exception("Failed to generate images.")
        
    await status_msg.edit_text("🎙️ Images done. Generating narration...")
    
    # 3. Generate Audio
    ap = AudioProcessor(job_id)
    narration_paths, durations = ap.generate_narration(scenes)
    
    # Pick first bg music if exists
    bg_music = None
    if os.path.exists(MUSIC_DIR):
        musics = [os.path.join(MUSIC_DIR, f) for f in os.listdir(MUSIC_DIR) if f.endswith(".mp3")]
        if musics:
            bg_music = musics[0]
            
    final_audio = ap.merge_audio(narration_paths, bg_music)
    
    await status_msg.edit_text("🎬 Assembling video (this may take a minute)...")
    
    # 4. Generate Video
    vp = VideoProcessor(job_id)
    srt_path = vp.generate_srt(scenes, durations)
    
    clip_paths = []
    for i, (img_path, dur) in enumerate(zip(image_paths, durations)):
        clip = vp.create_scene_video(img_path, dur, i)
        clip_paths.append(clip)
        
    final_video = vp.assemble_video(clip_paths, final_audio, srt_path)
    
    # 5. Generate Metadata
    metadata = sg.generate_viral_metadata(prompt, " ".join(scenes[:3]))
    caption = metadata.get("caption", "")
    hashtags = metadata.get("hashtags", "")
    
    await status_msg.edit_text("✅ Video complete! Uploading...")
    
    # 6. Send Result
    with open(final_video, "rb") as video:
        await update.message.reply_video(
            video=video,
            caption=f"{caption}\n\n{hashtags}",
            supports_streaming=True
        )
    
    await status_msg.delete()
