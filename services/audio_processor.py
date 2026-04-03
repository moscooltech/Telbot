import os
import logging
import subprocess
import time
from gtts import gTTS
from moviepy import AudioFileClip, concatenate_audioclips, CompositeAudioClip
from config import TEMP_DIR, AUDIO_SAMPLE_RATE, SKIP_BACKGROUND_MUSIC

logger = logging.getLogger(__name__)

class AudioProcessor:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.audio_dir = os.path.join(self.job_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)

    def generate_single_narration(self, text, index):
        """Generates a single narration file and returns (path, duration)."""
        try:
            filepath = os.path.join(self.audio_dir, f"scene_{index:03d}.mp3")
            # Generate TTS
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(filepath)
            
            # Get duration using ffprobe (lightweight)
            cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{filepath}\""
            try:
                output = subprocess.check_output(cmd, shell=True).decode().strip()
                duration = float(output)
            except Exception as e:
                logger.warning(f"⚠️ ffprobe failed for {filepath}: {e}")
                duration = max(3.0, len(text) / 15.0)
            
            return filepath, duration
        except Exception as e:
            logger.error(f"❌ Failed to generate narration {index}: {e}")
            return None, 0

    def merge_audio(self, narration_paths, bg_music_path=None):
        """
        Merges narration files and adds background music (if enabled).
        Optimized for Render Free Tier (512MB RAM) using FFmpeg for basic concatenation.
        """
        logger.info(f"🎙️ Merging audio for job {self.job_id}...")
        
        if not narration_paths:
            logger.error("No audio clips found to merge")
            return None

        final_audio_path = os.path.join(self.audio_dir, "final_audio.mp3")

        # OPTIMIZATION: If no background music, use FFmpeg concat demuxer (ultra-fast & low RAM)
        if SKIP_BACKGROUND_MUSIC or not bg_music_path or not os.path.exists(bg_music_path):
            try:
                # Create a list file for ffmpeg concat
                list_file_path = os.path.join(self.audio_dir, "concat_list.txt")
                with open(list_file_path, "w") as f:
                    for path in narration_paths:
                        # FFmpeg needs absolute paths or relative to the list file
                        f.write(f"file '{os.path.abspath(path)}'\n")
                
                # Run ffmpeg concat
                cmd = f"ffmpeg -y -f concat -safe 0 -i \"{list_file_path}\" -c copy \"{final_audio_path}\""
                subprocess.run(cmd, shell=True, check=True, capture_output=True)
                return final_audio_path
            except Exception as concat_err:
                logger.warning(f"⚠️ FFmpeg concat failed, falling back to MoviePy: {concat_err}")

        # FALLBACK: Use MoviePy only if background music is needed or FFmpeg failed
        audio_clips = []
        try:
            for path in narration_paths:
                if os.path.exists(path):
                    clip = AudioFileClip(path, fps=AUDIO_SAMPLE_RATE)
                    audio_clips.append(clip)

            merged_narration = concatenate_audioclips(audio_clips)
            final_audio_clip = merged_narration
            
            if not SKIP_BACKGROUND_MUSIC and bg_music_path and os.path.exists(bg_music_path):
                try:
                    bg_music = AudioFileClip(bg_music_path, fps=AUDIO_SAMPLE_RATE).volumex(0.15)
                    if bg_music.duration < merged_narration.duration:
                        loops = int(merged_narration.duration / bg_music.duration) + 1
                        bg_music = concatenate_audioclips([bg_music] * loops)
                    
                    bg_music = bg_music.subclip(0, merged_narration.duration)
                    final_audio_clip = CompositeAudioClip([merged_narration, bg_music])
                except Exception as music_err:
                    logger.warning(f"⚠️ Failed to add music: {music_err}")

            final_audio_clip.write_audiofile(
                final_audio_path,
                fps=AUDIO_SAMPLE_RATE,
                nbytes=2,
                bitrate="64k",
                logger=None
            )
            
            # Cleanup
            if final_audio_clip != merged_narration:
                merged_narration.close()
            final_audio_clip.close()
            for clip in audio_clips:
                clip.close()
                
            return final_audio_path

        except Exception as e:
            logger.error(f"❌ Audio merge critical failure: {e}")
            for clip in audio_clips:
                try: clip.close() 
                except: pass
            return None
