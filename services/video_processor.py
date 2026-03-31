import os
import subprocess
import logging
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip, concatenate_videoclips
from config import TEMP_DIR

logger = logging.getLogger(__name__)

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
        # Optimized for quality and speed
        # We scale to 1080x1920 first, then zoom
        cmd = (
            f"ffmpeg -y -loop 1 -i \"{image_path}\" "
            f"-vf \"scale=w=1080:h=1920,zoompan=z='min(zoom+0.0015,1.5)':d={int(duration*25)}:s=1080x1920,format=yuv420p\" "
            f"-t {duration} -r 25 -c:v libx264 -preset fast -crf 20 \"{output_path}\""
        )
        subprocess.run(cmd, shell=True, check=True)
        return output_path

    def assemble_video(self, clip_paths, audio_path, srt_path):
        """Combines clips into a final video with audio and subtitles using MoviePy."""
        logger.info(f"🎬 Starting robust assembly for job {self.job_id}...")
        
        clips = []
        for path in clip_paths:
            try:
                if not os.path.exists(path):
                    logger.warning(f"⚠️ Clip not found at {path}, skipping...")
                    continue
                
                # Load and resize to 1080x1920 (9:16)
                clip = VideoFileClip(path).resize(newsize=(1080, 1920))
                # Add a subtle 0.5s fade transition between clips
                clip = clip.crossfadein(0.5)
                clips.append(clip)
            except Exception as e:
                logger.error(f"❌ Failed to load clip {path}: {e}")
                continue

        if not clips:
            raise Exception("No valid video clips found for assembly.")

        try:
            # Concatenate all clips with crossfade transitions
            final_video_clip = concatenate_videoclips(clips, method="compose")

            # Load audio (narration + music)
            if audio_path and os.path.exists(audio_path):
                audio_clip = AudioFileClip(audio_path)
                # Trim audio if it's longer than the video
                if audio_clip.duration > final_video_clip.duration:
                    audio_clip = audio_clip.subclip(0, final_video_clip.duration)
                final_video_clip = final_video_clip.set_audio(audio_clip)

            # Define output path
            raw_video = os.path.join(self.video_dir, "assembled_no_subs.mp4")
            
            # Export final video (using multiple threads for speed)
            final_video_clip.write_videofile(
                raw_video,
                codec="libx264",
                audio_codec="aac",
                fps=25,
                threads=4,
                logger=None # Disable verbose output
            )

            # Final step: Burn subtitles using FFmpeg (since TextClip needs ImageMagick)
            # Alignment=2 is bottom center
            final_output = os.path.join(self.job_dir, "final_output.mp4")
            subtitle_filter = f"subtitles='{srt_path}':force_style='Alignment=2,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=40'"
            
            cmd = (
                f"ffmpeg -y -i \"{raw_video}\" "
                f"-vf \"{subtitle_filter}\" "
                f"-c:v libx264 -preset fast -crf 18 -c:a copy \"{final_output}\""
            )
            subprocess.run(cmd, shell=True, check=True)

            # Close clips to free memory
            for c in clips:
                c.close()
            final_video_clip.close()
            
            return final_output

        except Exception as e:
            logger.error(f"❌ Assembly failed: {e}")
            raise e
