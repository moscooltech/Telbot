import os
import subprocess
import logging
from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_videoclips
from config import TEMP_DIR, IMAGE_WIDTH, IMAGE_HEIGHT, FFMPEG_PRESET, FFMPEG_CRF, FFMPEG_THREADS

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.video_dir = os.path.join(self.job_dir, "video")
        os.makedirs(self.video_dir, exist_ok=True)
        # Use dimensions from config
        self.width = IMAGE_WIDTH
        self.height = IMAGE_HEIGHT

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
                # Wrap text if it's too long
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
        """Creates a short video clip for a single image with a LIGHT Ken Burns effect."""
        output_path = os.path.join(self.video_dir, f"clip_{index:03d}.mp4")
        
        # LIGHTWEIGHT Ken Burns:
        # 1. Scale to target size
        # 2. Subtle zoompan (reduced complexity)
        # 3. Use config-driven threads and preset
        cmd = (
            f"ffmpeg -y -loop 1 -i \"{image_path}\" "
            f"-vf \"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,crop={self.width}:{self.height},"
            f"zoompan=z='min(zoom+0.001,1.2)':d={int(duration*25)}:s={self.width}x{self.height},format=yuv420p\" "
            f"-t {duration} -r 25 -c:v libx264 -preset {FFMPEG_PRESET} -crf {FFMPEG_CRF} "
            f"-threads {FFMPEG_THREADS} \"{output_path}\""
        )
        
        logger.info(f"Generating clip {index} with ffmpeg...")
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        return output_path

    def assemble_video(self, clip_paths, audio_path, srt_path):
        """
        Combines clips into a final video with audio and subtitles using FFmpeg.
        ULTRA-OPTIMIZED for 512MB RAM: Bypasses MoviePy entirely for assembly.
        """
        logger.info(f"🎬 Starting ultra-lightweight assembly for job {self.job_id}...")
        
        try:
            # 1. Create a list file for FFmpeg concat demuxer
            list_file = os.path.join(self.video_dir, "clips_list.txt")
            with open(list_file, "w") as f:
                for path in clip_paths:
                    if os.path.exists(path):
                        # Use absolute paths to avoid issues
                        f.write(f"file '{os.path.abspath(path)}'\n")
            
            # 2. Intermediate raw concatenation (no re-encoding, extremely fast and low RAM)
            raw_concat = os.path.join(self.video_dir, "raw_concat.mp4")
            concat_cmd = (
                f"ffmpeg -y -f concat -safe 0 -i \"{list_file}\" -c copy \"{raw_concat}\""
            )
            logger.info("Running fast concatenation...")
            subprocess.run(concat_cmd, shell=True, check=True, capture_output=True)

            # 3. Final Merge: Add Audio + Burn Subtitles + Re-encode with optimized settings
            # We do this in ONE pass to minimize disk I/O and CPU spikes
            final_output = os.path.join(self.job_dir, "final_output.mp4")
            
            # Style optimized for 720p
            subtitle_filter = (
                f"subtitles='{srt_path}':force_style='Alignment=2,FontSize=12,"
                f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,"
                f"Outline=1,Shadow=0,MarginV=30'"
            )
            
            # Construct the final command
            # -shortest ensures the video ends when the shortest stream (usually video) ends
            if audio_path and os.path.exists(audio_path):
                cmd = (
                    f"ffmpeg -y -i \"{raw_concat}\" -i \"{audio_path}\" "
                    f"-vf \"{subtitle_filter}\" "
                    f"-c:v libx264 -preset {FFMPEG_PRESET} -crf {FFMPEG_CRF} "
                    f"-threads {FFMPEG_THREADS} -c:a aac -b:a 128k -shortest \"{final_output}\""
                )
            else:
                cmd = (
                    f"ffmpeg -y -i \"{raw_concat}\" -vf \"{subtitle_filter}\" "
                    f"-c:v libx264 -preset {FFMPEG_PRESET} -crf {FFMPEG_CRF} "
                    f"-threads {FFMPEG_THREADS} \"{final_output}\""
                )

            logger.info("Running final merge and subtitle burn...")
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            
            # Cleanup intermediate raw file immediately to save disk
            if os.path.exists(raw_concat):
                os.remove(raw_concat)
            
            return final_output

        except Exception as e:
            logger.error(f"❌ Ultra-lightweight assembly failed: {e}")
            raise e
