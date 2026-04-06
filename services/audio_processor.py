import os
import logging
import subprocess
import time
from gtts import gTTS
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
            logger.info(f"🎙️ Generating audio for index {index}: '{text[:50]}...'")
            filepath = os.path.join(self.audio_dir, f"scene_{index:03d}.mp3")
            # Generate TTS
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(filepath)
            
            # Get duration using ffprobe
            cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{filepath}\""
            try:
                output = subprocess.check_output(cmd, shell=True).decode().strip()
                duration = float(output)
            except Exception:
                duration = max(3.0, len(text) / 15.0)
            
            return filepath, duration
        except Exception as e:
            logger.error(f"❌ Failed to generate narration {index}: {e}")
            return None, 0

    def merge_audio(self, narration_paths, bg_music_path=None):
        """
        Merges narration files using FFmpeg (ultra-fast & low RAM).
        """
        logger.info(f"🎙️ Merging audio for job {self.job_id}...")
        
        if not narration_paths:
            return None

        final_audio_path = os.path.join(self.audio_dir, "final_audio.mp3")

        try:
            # Create a list file for ffmpeg concat
            list_file_path = os.path.join(self.audio_dir, "concat_list.txt")
            with open(list_file_path, "w") as f:
                for path in narration_paths:
                    abs_path = os.path.abspath(path)
                    logger.info(f"🎵 Adding to merge: {abs_path}")
                    f.write(f"file '{abs_path}'\n")
            
            # Run ffmpeg concat
            cmd = f"ffmpeg -y -f concat -safe 0 -i \"{list_file_path}\" -c copy \"{final_audio_path}\""
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            return final_audio_path
        except Exception as e:
            logger.error(f"❌ Audio merge failed: {e}")
            return None
