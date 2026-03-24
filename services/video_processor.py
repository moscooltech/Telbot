import os
import subprocess
from config import TEMP_DIR

class VideoProcessor:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.video_dir = os.path.join(self.job_dir, "video")
        os.makedirs(self.video_dir, exist_ok=True)

    def generate_srt(self, scenes, durations):
        """Generates a subtitle file from scenes and their durations."""
        srt_path = os.path.join(self.video_dir, "subtitles.srt")
        current_time = 0.0
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, (scene, duration) in enumerate(zip(scenes, durations)):
                start = self._format_srt_time(current_time)
                current_time += duration
                end = self._format_srt_time(current_time)
                
                f.write(f"{i+1}\n")
                f.write(f"{start} --> {end}\n")
                f.write(f"{scene}\n\n")
        return srt_path

    def _format_srt_time(self, seconds):
        """Formats time for SRT files: HH:MM:SS,mmm"""
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    def create_scene_video(self, image_path, duration, index):
        """Creates a short video clip for a single image with Ken Burns effect."""
        output_path = os.path.join(self.video_dir, f"clip_{index:03d}.mp4")
        # FFmpeg zoompan filter for Ken Burns
        # Slow zoom in: zoompan=z='min(zoom+0.0015,1.5)':d=duration:s=1080x1920
        # For mobile 9:16, we need to scale first or crop
        cmd = (
            f"ffmpeg -y -loop 1 -i \"{image_path}\" "
            f"-vf \"scale=w=1080:h=1920,zoompan=z='min(zoom+0.001,1.5)':d={int(duration*25)}:s=1080x1920,format=yuv420p\" "
            f"-t {duration} -r 25 \"{output_path}\""
        )
        subprocess.run(cmd, shell=True, check=True)
        return output_path

    def assemble_video(self, clip_paths, audio_path, srt_path):
        """Combines clips into a final video with audio and subtitles."""
        list_file = os.path.join(self.video_dir, "clips_list.txt")
        with open(list_file, "w") as f:
            for path in clip_paths:
                f.write(f"file '{os.path.abspath(path)}'\n")
        
        raw_video = os.path.join(self.video_dir, "raw_video.mp4")
        # Concatenate clips
        cmd = f"ffmpeg -y -f concat -safe 0 -i \"{list_file}\" -c copy \"{raw_video}\""
        subprocess.run(cmd, shell=True, check=True)
        
        final_video = os.path.join(self.job_dir, "final_output.mp4")
        # Add audio and burn subtitles
        # Note: subtitles filter might need specialized path on some OS
        # Using a simple style for subtitles
        subtitle_filter = f"subtitles='{srt_path}':force_style='Alignment=2,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=0'"
        
        cmd = (
            f"ffmpeg -y -i \"{raw_video}\" -i \"{audio_path}\" "
            f"-vf \"{subtitle_filter}\" "
            f"-c:v libx264 -preset ultrafast -crf 23 -c:a aac -shortest \"{final_video}\""
        )
        subprocess.run(cmd, shell=True, check=True)
        return final_video
