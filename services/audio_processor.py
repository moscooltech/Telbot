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

    def generate_narration(self, scenes):
        """
        Generates individual audio files for each scene and returns their filepaths.
        Also returns the duration of each audio file.
        """
        narration_paths = []
        durations = []
        
        for i, scene in enumerate(scenes):
            try:
                filepath = os.path.join(self.audio_dir, f"scene_{i:03d}.mp3")
                tts = gTTS(text=scene, lang='en', slow=False)
                tts.save(filepath)
                
                # Get duration using MoviePy
                audio = AudioFileClip(filepath)
                duration = audio.duration
                audio.close()
                
                narration_paths.append(filepath)
                durations.append(duration)
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
