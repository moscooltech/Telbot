import os
from gtts import gTTS
import subprocess
from config import TEMP_DIR

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
            filepath = os.path.join(self.audio_dir, f"scene_{i:03d}.mp3")
            tts = gTTS(text=scene, lang='en', slow=False)
            tts.save(filepath)
            
            # Get duration using ffprobe
            duration = self.get_duration(filepath)
            
            narration_paths.append(filepath)
            durations.append(duration)
            
        return narration_paths, durations

    def get_duration(self, filepath):
        """Returns the duration of an audio file in seconds."""
        cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {filepath}"
        try:
            output = subprocess.check_output(cmd, shell=True).decode().strip()
            return float(output)
        except:
            return 5.0 # Fallback

    def merge_audio(self, narration_paths, bg_music_path=None):
        """
        Merges narration files and adds background music.
        """
        # Create a list file for FFmpeg
        list_file = os.path.join(self.audio_dir, "audio_list.txt")
        with open(list_file, "w") as f:
            for path in narration_paths:
                f.write(f"file '{os.path.abspath(path)}'\n")
        
        merged_narration = os.path.join(self.audio_dir, "merged_narration.mp3")
        # Concatenate audio
        cmd = f"ffmpeg -y -f concat -safe 0 -i {list_file} -c copy {merged_narration}"
        subprocess.run(cmd, shell=True, check=True)
        
        if bg_music_path and os.path.exists(bg_music_path):
            final_audio = os.path.join(self.audio_dir, "final_audio.mp3")
            # Mix with background music (lower volume)
            cmd = f"ffmpeg -y -i {merged_narration} -stream_loop -1 -i {bg_music_path} -filter_complex \"[0:a]volume=1.0[v];[1:a]volume=0.15[m];[v][m]amix=inputs=2:duration=first\" {final_audio}"
            subprocess.run(cmd, shell=True, check=True)
            return final_audio
            
        return merged_narration
