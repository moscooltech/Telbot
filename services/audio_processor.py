import os
import logging
import subprocess
import time
import shutil
import asyncio
import edge_tts
from gtts import gTTS
from config import TEMP_DIR, AUDIO_SAMPLE_RATE, SKIP_BACKGROUND_MUSIC

logger = logging.getLogger(__name__)

# Male voices available in edge-tts
MALE_VOICES = {
    "jason": "en-US-JasonNeural",
    "guy": "en-US-GuyNeural",
    "ryan": "en-GB-RyanNeural"
}

class AudioProcessor:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.audio_dir = os.path.join(self.job_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)

    async def _generate_edge_tts(self, text, filepath, voice="en-US-JasonNeural"):
        """Generate audio using edge-tts."""
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(filepath)

    def generate_single_narration(self, text, index):
        """Generates a single narration file and returns (path, duration)."""
        try:
            logger.info(f"🎙️ Generating audio for index {index}: '{text[:50]}...'")
            filepath = os.path.join(self.audio_dir, f"scene_{index:03d}.mp3")
            
            # Use edge-tts with male voice (Jason is a popular male voice)
            voice = MALE_VOICES["jason"]
            logger.info(f"Using voice: {voice}")
            
            try:
                asyncio.run(self._generate_edge_tts(text, filepath, voice))
            except Exception as e:
                logger.warning(f"edge-tts failed: {e}, falling back to gTTS")
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
        Merges narration files and optionally background music.
        Handles cases where narration_paths is empty.
        """
        logger.info(f"🎙️ Merging audio for job {self.job_id}...")
        logger.info(f" narration_paths: {narration_paths}")
        logger.info(f" bg_music_path: {bg_music_path}")
        
        final_audio_path = os.path.join(self.audio_dir, "final_audio.mp3")

        try:
            if not narration_paths and not bg_music_path:
                logger.info("No narration or background music to merge.")
                return None
            
            if not narration_paths and bg_music_path:
                logger.info("Only background music available. Copying background music.")
                shutil.copy(bg_music_path, final_audio_path)
                return final_audio_path

            # If narration_paths exist, proceed with concat
            list_file_path = os.path.join(self.audio_dir, "concat_list.txt")
            with open(list_file_path, "w") as f:
                for path in narration_paths:
                    abs_path = os.path.abspath(path)
                    logger.info(f"🎵 Adding narration to merge: {abs_path}")
                    f.write(f"file '{abs_path}'\n")
            
            # Merge narrations first
            narration_merged_path = os.path.join(self.audio_dir, "narrations_merged.mp3")
            cmd_narration_merge = f"ffmpeg -y -f concat -safe 0 -i \"{list_file_path}\" -c copy \"{narration_merged_path}\""
            logger.info(f"Running: {cmd_narration_merge}")
            result = subprocess.run(cmd_narration_merge, shell=True, capture_output=True)
            if result.returncode != 0:
                logger.error(f"ffmpeg narration merge failed: {result.stderr.decode()}")
                return None
            
            if not os.path.exists(narration_merged_path):
                logger.error(f"Narration merge output not created: {narration_merged_path}")
                return None

            if bg_music_path:
                logger.info("Mixing narrations with background music.")
                # Use a more sophisticated mix if both exist
                cmd_final_mix = (
                    f"ffmpeg -y -i \"{narration_merged_path}\" -i \"{bg_music_path}\" "
                    f"-filter_complex \"[0:a]volume=1.0[a0];[1:a]volume=0.3[a1];[a0][a1]amix=inputs=2:duration=first\" "
                    f"-c:a aac -b:a 128k -shortest \"{final_audio_path}\""
                )
                logger.info(f"Running: {cmd_final_mix}")
                result = subprocess.run(cmd_final_mix, shell=True, capture_output=True)
                if result.returncode != 0:
                    logger.error(f"ffmpeg mix failed: {result.stderr.decode()}")
                    return None
            else:
                logger.info("No background music. Using merged narrations as final audio.")
                shutil.copy(narration_merged_path, final_audio_path)
                
            if not os.path.exists(final_audio_path):
                logger.error(f"Final audio not created: {final_audio_path}")
                return None
                
            return final_audio_path
        except Exception as e:
            logger.error(f"❌ Audio merge failed: {e}")
            return None
