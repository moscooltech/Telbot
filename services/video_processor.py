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
        """Creates a short video clip with RANDOM cinematic motion (Ken Burns)."""
        output_path = os.path.join(self.video_dir, f"clip_{index:03d}.mp4")
        import random
        
        # Randomly choose one of 4 motion effects
        # Optimized for 720p and low CPU
        effects = [
            # Zoom In
            f"zoompan=z='min(zoom+0.001,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration*25)}:s={self.width}x{self.height}",
            # Zoom Out
            f"zoompan=z='max(1.3-0.001*on,1.0)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration*25)}:s={self.width}x{self.height}",
            # Pan Left to Right
            f"zoompan=z=1.2:x='if(lte(on,1),(iw-iw/zoom)/2,x+0.5)':y='(ih-ih/zoom)/2':d={int(duration*25)}:s={self.width}x{self.height}",
            # Pan Right to Left
            f"zoompan=z=1.2:x='if(lte(on,1),(iw-iw/zoom),x-0.5)':y='(ih-ih/zoom)/2':d={int(duration*25)}:s={self.width}x{self.height}"
        ]
        chosen_effect = random.choice(effects)

        cmd = (
            f"ffmpeg -y -loop 1 -i \"{image_path}\" "
            f"-vf \"scale={self.width*2}:{self.height*2}:force_original_aspect_ratio=increase,crop={self.width*2}:{self.height*2},"
            f"{chosen_effect},format=yuv420p\" "
            f"-t {duration} -r 25 -c:v libx264 -preset {FFMPEG_PRESET} -crf {FFMPEG_CRF} "
            f"-threads {FFMPEG_THREADS} \"{output_path}\""
        )
        
        logger.info(f"Generating clip {index} with effect...")
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        return output_path

    def assemble_video(self, clip_paths, audio_path, srt_path):
        """
        Combines clips into a final video with audio and BOLD subtitles.
        """
        logger.info(f"🎬 Starting ultra-lightweight assembly for job {self.job_id}...")
        
        try:
            # 1. Create a list file for FFmpeg concat demuxer
            list_file = os.path.join(self.video_dir, "clips_list.txt")
            with open(list_file, "w") as f:
                for path in clip_paths:
                    if os.path.exists(path):
                        f.write(f"file '{os.path.abspath(path)}'\n")
            
            # 2. Intermediate raw concatenation
            raw_concat = os.path.join(self.video_dir, "raw_concat.mp4")
            concat_cmd = (
                f"ffmpeg -y -f concat -safe 0 -i \"{list_file}\" -c copy \"{raw_concat}\""
            )
            subprocess.run(concat_cmd, shell=True, check=True, capture_output=True)

            # 3. Final Merge: Yellow Text + Black Shadow Box (BorderStyle=3)
            final_output = os.path.join(self.job_dir, "final_output.mp4")
            
            # Professional TikTok Style: Yellow text with black box
            subtitle_filter = (
                f"subtitles='{srt_path}':force_style='Alignment=2,FontSize=14,"
                f"PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=3,"
                f"Outline=1,Shadow=1,MarginV=50'"
            )
            
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

            subprocess.run(cmd, shell=True, check=True, capture_output=True)
            if os.path.exists(raw_concat): os.remove(raw_concat)
            return final_output

        except Exception as e:
            logger.error(f"❌ Ultra-lightweight assembly failed: {e}")
            raise e
