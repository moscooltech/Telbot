import os
import logging
from gtts import gTTS
from moviepy import AudioFileClip, concatenate_audioclips, CompositeAudioClip
from config import TEMP_DIR

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
        import subprocess
        import time
        try:
            filepath = os.path.join(self.audio_dir, f"scene_{index:03d}.mp3")
            tts = gTTS(text=text, lang='en', slow=False)
            tts.save(filepath)
            
            # Get duration using ffprobe
            cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{filepath}\""
            try:
                output = subprocess.check_output(cmd, shell=True).decode().strip()
                duration = float(output)
            except:
                duration = max(3.0, len(text) / 15.0)
            
            return filepath, duration
        except Exception as e:
            logger.error(f"❌ Failed to generate narration {index}: {e}")
            return None, 0

    def generate_narration(self, scenes):
        """
        Generates individual audio files for each scene and returns their filepaths.
        Also returns the duration of each audio file.
        """
        import subprocess
        narration_paths = []
        durations = []
        
        for i, scene in enumerate(scenes):
            try:
                filepath = os.path.join(self.audio_dir, f"scene_{i:03d}.mp3")
                tts = gTTS(text=scene, lang='en', slow=False)
                tts.save(filepath)
                
                # Get duration using ffprobe (much lighter than MoviePy)
                cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{filepath}\""
                try:
                    output = subprocess.check_output(cmd, shell=True).decode().strip()
                    duration = float(output)
                except:
                    # Fallback to estimate: approx 15 chars per second for speech
                    duration = max(3.0, len(scene) / 15.0)
                
                narration_paths.append(filepath)
                durations.append(duration)
                
                # Small sleep to let the disk catch up
                import time
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"❌ Failed to generate narration for scene {i}: {e}")
                continue
            
        return narration_paths, durations

    def merge_audio(self, narration_paths, bg_music_path=None):
        """
        Merges narration files and adds background music using MoviePy.
        """
        logger.info(f"🎙️ Merging audio for job {self.job_id}...")
        
        audio_clips = []
        for path in narration_paths:
            try:
                if os.path.exists(path):
                    audio_clips.append(AudioFileClip(path))
            except Exception as e:
                logger.error(f"❌ Failed to load audio clip {path}: {e}")

        if not audio_clips:
            return None

        # Concatenate narration clips
        merged_narration = concatenate_audioclips(audio_clips)
        
        final_audio_clip = merged_narration
        
        if bg_music_path and os.path.exists(bg_music_path):
            try:
                bg_music = AudioFileClip(bg_music_path).volumex(0.15)
                
                # Loop background music to match narration duration
                if bg_music.duration < merged_narration.duration:
                    # Use a simple loop approach
                    loops = int(merged_narration.duration / bg_music.duration) + 1
                    bg_music = concatenate_audioclips([bg_music] * loops)
                
                # Trim to match narration length
                bg_music = bg_music.subclip(0, merged_narration.duration)
                
                # Composite narration and music
                final_audio_clip = CompositeAudioClip([merged_narration, bg_music])
            except Exception as e:
                logger.error(f"❌ Failed to add background music: {e}")

        final_audio_path = os.path.join(self.audio_dir, "final_audio.mp3")
        final_audio_clip.write_audiofile(final_audio_path, logger=None)
        
        # Cleanup
        for clip in audio_clips:
            clip.close()
        if final_audio_clip != merged_narration:
            merged_narration.close()
        final_audio_clip.close()
        
        return final_audio_path
