import os
import subprocess
import logging
import random
import textwrap
from config import TEMP_DIR, IMAGE_WIDTH, IMAGE_HEIGHT, FFMPEG_PRESET, FFMPEG_CRF, FFMPEG_THREADS, VIDEO_DURATION_PER_SCENE

logger = logging.getLogger(__name__)

class VideoProcessor:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.video_dir = os.path.join(self.job_dir, "video")
        os.makedirs(self.video_dir, exist_ok=True)
        self.width = IMAGE_WIDTH
        self.height = IMAGE_HEIGHT

    def generate_srt(self, scenes, durations):
        """Generates a subtitle file (kept for reference or external use)."""
        srt_path = os.path.join(self.video_dir, "subtitles.srt")
        current_time = 0.0
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, (scene, duration) in enumerate(zip(scenes, durations)):
                start = self._format_srt_time(current_time)
                current_time += duration
                end = self._format_srt_time(current_time)
                f.write(f"{i+1}\n{start} --> {end}\n{scene}\n\n")
        return srt_path

    def _format_srt_time(self, seconds):
        hrs, mins, secs = int(seconds // 3600), int((seconds % 3600) // 60), int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    def create_scene_video(self, image_path, duration, index, text):
        """
        Creates a short video clip with SUBTITLES BURNED IN.
        Burning at the clip level prevents OOM crashes during final assembly.
        """
        import textwrap
        output_path = os.path.join(self.video_dir, f"clip_{index:03d}.mp4")
        
        # Clean text for FFmpeg drawtext filter
        clean_text = text.replace("'", "").replace(":", "").replace('"', "")
        
        # Auto-wrap: 25 chars per line - adapts to content length
        wrapped_lines = textwrap.wrap(clean_text, width=25)
        
        # Build multi-line text with proper line height
        wrapped_text = "\\n".join(wrapped_lines)
        num_lines = len(wrapped_lines)
        
        # Calculate vertical position - center the block based on number of lines
        # Each line ~50px with fontsize 48, position above bottom
        line_height = 55
        base_y = 200 + (num_lines - 1) * line_height // 2
        
        # Professional subtitles: larger font, white with black outline (stroke)
        # y=center - centers vertically, x=center - centers horizontally
        drawtext_filter = (
            f"drawtext=text='{wrapped_text}':fontcolor=white:fontsize=48:fontfile=bold:"
            f"x=(w-text_w)/2:y=h-th-{base_y}:"
            f"borderw=3:bordercolor=black"
        )

        cmd = (
            f"ffmpeg -y -loop 1 -i \"{image_path}\" "
            f"-t {duration} -r 15 -c:v libx264 -preset ultrafast -crf 26 "
            f"-vf \"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,crop={self.width}:{self.height},"
            f"{drawtext_filter},format=yuv420p\" "
            f"-threads 1 \"{output_path}\""
        )
        
        logger.info(f"Rendering sub-clip {index} with text...")
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        return output_path

    def assemble_video(self, clip_paths, audio_path, srt_path):
        """
        Final Assembly: Uses 'Stream Copy' to stitch pre-subtitled clips.
        Uses 0 MB of RAM because no decoding/encoding happens here.
        """
        logger.info(f"🎬 Nuclear Stream-Copy Assembly for job {self.job_id}...")
        
        try:
            list_file = os.path.join(self.video_dir, "clips_list.txt")
            with open(list_file, "w") as f:
                for path in clip_paths:
                    if os.path.exists(path):
                        f.write(f"file '{os.path.abspath(path)}'\n")
            
            final_output = os.path.join(self.job_dir, "final_output.mp4")
            
            # Key Optimization: -c:v copy
            # We stitch the clips and add audio without re-rendering anything.
            if audio_path and os.path.exists(audio_path):
                cmd = (
                    f"ffmpeg -y -f concat -safe 0 -i \"{list_file}\" -i \"{audio_path}\" "
                    f"-c:v copy -c:a aac -b:a 128k -shortest -threads 1 \"{final_output}\""
                )
            else:
                cmd = (
                    f"ffmpeg -y -f concat -safe 0 -i \"{list_file}\" -c copy \"{final_output}\""
                )

            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            return final_output

        except Exception as e:
            logger.error(f"❌ Nuclear assembly failed: {e}")
            raise e
