import os
import subprocess
import logging
import random
import textwrap
import re
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

    def _detect_keywords(self, words):
        """
        Simple keyword detection: words with 4+ chars that are not common connector words.
        Returns set of word indices that should be highlighted.
        """
        connectors = {'the', 'a', 'an', 'and', 'or', 'but', 'is', 'are', 'was', 'were',
                      'in', 'on', 'at', 'to', 'of', 'for', 'with', 'by', 'from', 'that',
                      'this', 'it', 'as', 'be', 'have', 'has', 'had', 'not', 'you', 'we',
                      'they', 'can', 'will', 'do', 'does', 'did', 'its', 'our', 'their'}
        keywords = set()
        for i, word in enumerate(words):
            clean_word = re.sub(r'[^\w]', '', word).lower()
            if len(clean_word) >= 4 and clean_word not in connectors:
                keywords.add(i)
        return keywords

    def _split_words_and_punct(self, text):
        """
        Split text into words while preserving punctuation as separate tokens.
        Returns list of tuples: (word, has_leading_punct, has_trailing_punct)
        """
        tokens = []
        for token in text.split():
            leading = ''
            trailing = ''
            word = token
            if not word[0].isalnum():
                leading = word[0]
                word = word[1:]
            if word and not word[-1].isalnum():
                trailing = word[-1]
                word = word[:-1]
            if word:
                tokens.append((word, leading, trailing))
            else:
                tokens.append(('', leading, trailing))
        return tokens

    def create_scene_video(self, image_path, duration, index, narration, narration_duration=None):
        """
        Creates a short video clip with TikTok-style WORD-BY-WORD ANIMATED SUBTITLES.
        Falls back to simple static subtitles on error.
        """
        output_path = os.path.join(self.video_dir, f"clip_{index:03d}.mp4")
        
        if not narration:
            narration = " "
            
        clean_text = narration.replace("'", "'").replace('"', '"').replace(":", "")
        
        tokens = self._split_words_and_punct(clean_text)
        words = [t[0] for t in tokens]
        original_word_count = len([w for w in words if w])
        
        logger.info(f"Scene {index}: {original_word_count} words, {duration}s duration")
        logger.info(f"Text: {clean_text[:80]}")
        
        use_duration = duration if narration_duration is None else narration_duration
        
        try:
            word_times = self._calculate_word_timing(words, use_duration)
            wrapped_lines = self._wrap_subtitle(clean_text)
            line_count = len(wrapped_lines)
            
            drawtext_filters = self._build_word_animated_filter(
                words, word_times, wrapped_lines, use_duration, line_count
            )
            
            scale_filter = f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,crop={self.width}:{self.height}"
            
            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", image_path,
                "-t", str(use_duration), "-r", "15",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-vf", f"{scale_filter},{drawtext_filters},format=yuv420p",
                "-threads", "1", output_path
            ]
            
            logger.info(f"Rendering scene {index}: {original_word_count} words")
            
            timeout = 120 if original_word_count > 5 else 90
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise Exception(f"FFmpeg timeout after {timeout}s")
            
            if result.returncode != 0:
                err_msg = result.stderr.decode() if result.stderr else 'unknown'
                raise Exception(f"FFmpeg failed: {err_msg[:500]}")
            return output_path
            
        except Exception as e:
            logger.warning(f"Animated subtitles failed: {e}, using simple static")
            return self._create_simple_subtitle_video(image_path, duration, index, clean_text)

    def _create_simple_subtitle_video(self, image_path, duration, index, text):
        """Fallback: simple static subtitles without animation."""
        output_path = os.path.join(self.video_dir, f"clip_{index:03d}.mp4")
        
        wrapped = textwrap.wrap(text, width=20, break_long_words=False)
        wrapped_text = "\\n".join(wrapped)
        
        double_quote_escaped = wrapped_text.replace('"', '\\"')
        drawtext = (
            f"drawtext=text=\"{double_quote_escaped}\":fontcolor=white:fontsize=42:"
            f"x=(w-text_w)/2:y=h*0.65-text_h/2:"
            f"borderw=2:bordercolor=black:"
            f"box=1:boxcolor=black@0.35:boxborderw=12"
        )
        
        scale_filter = f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,crop={self.width}:{self.height}"
        
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", image_path,
            "-t", str(duration), "-r", "15",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            "-vf", f"{scale_filter},{drawtext},format=yuv420p",
            "-threads", "1", output_path
        ]
        
        logger.info(f"Rendering simple static subtitle for scene {index}")
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            err = result.stderr.decode() if result.stderr else 'unknown'
            raise Exception(f"Simple subtitle FFmpeg failed: {err[:300]}")
        return output_path

    def _calculate_word_timing(self, words, duration):
        """
        Calculate timing for each word based on narration duration.
        Distributes time evenly across all words.
        Returns list of (start_time, end_time) tuples.
        """
        valid_words = [w for w in words if w]
        word_count = len(valid_words)
        
        if word_count == 0:
            return [(0, duration)]
        
        base_time_per_word = duration / word_count
        min_time = 0.15
        max_time = 0.6
        time_per_word = max(min_time, min(max_time, base_time_per_word))
        
        word_times = []
        current_time = 0.0
        
        for word in words:
            if not word:
                word_times.append((current_time, current_time))
                continue
                
            start = current_time
            end = min(current_time + time_per_word, duration)
            word_times.append((start, end))
            current_time = end
            
        return word_times

    def _wrap_subtitle(self, text, max_width=25, max_lines=3):
        """
        Wrap subtitle text into multiple lines for mobile viewing.
        Uses simple word boundary wrapping.
        """
        clean = text.strip()
        if not clean:
            return [""]
            
        wrapper = textwrap.TextWrapper(
            width=max_width,
            break_long_words=False,
            break_on_hyphens=False,
            max_lines=max_lines
        )
        lines = wrapper.wrap(clean)
        
        if not lines:
            return [clean[:max_width]]
            
        return [l for l in lines if l]

    def _build_word_animated_filter(self, words, word_times, wrapped_lines, duration, line_count):
        """
        Build FFmpeg drawtext filter for word-by-word animated display.
        Simplified version with proper escaping and hex colors.
        """
        valid_words = [w for w in words if w]
        if not valid_words:
            return "drawtext=text=' ':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=h*0.65"
        
        font_size = 42
        box_padding = 12
        box_color = "black@0.35"
        
        full_text = ' '.join(valid_words)
        
        keyword_indices = set()
        for i, w in enumerate(valid_words):
            if len(w) >= 4 and w.lower() not in {'that', 'this', 'which', 'with', 'from', 'have', 'were', 'been', 'they', 'their'}:
                keyword_indices.add(i)
        
        word_filters = []
        
        for idx, (word, (start, end)) in enumerate(zip(valid_words, word_times[:len(valid_words)])):
            clean_word = re.sub(r'[^\w]', '', word)
            is_keyword = idx in keyword_indices
            fontcolor = "#00FFFF" if is_keyword else "white"
            
            double_escaped = word.replace('"', '\\"')
            
            start_str = f"{start:.2f}"
            end_str = f"{end:.2f}"
            
            dt = (
                f"drawtext=text=\"{double_escaped}\":fontcolor={fontcolor}:fontsize={font_size}:"
                f"x=(w-text_w)/2:y=h*0.65-text_h/2:"
                f"borderw=2:bordercolor=black:"
                f"box=1:boxcolor={box_color}:boxborderw={box_padding}:"
                f"enable='between(t,{start_str},{end_str})'"
            )
            word_filters.append(dt)
        
        double_escaped_full = full_text.replace('"', '\\"')
        
        show_full = (
            f"drawtext=text=\"{double_escaped_full}\":fontcolor=white:fontsize={font_size}:"
            f"x=(w-text_w)/2:y=h*0.65-text_h/2:"
            f"borderw=2:bordercolor=black:"
            f"box=1:boxcolor={box_color}:boxborderw={box_padding}:"
            f"enable='gte(t,{duration * 0.85:.2f})'"
        )
        word_filters.append(show_full)
        
        return ",".join(word_filters)

    def assemble_video(self, clip_paths, audio_path, srt_path):
        """
        Final Assembly: Uses 'Stream Copy' to stitch pre-subtitled clips.
        Uses 0 MB of RAM because no decoding/encoding happens here.
        """
        logger.info(f"Nuclear Stream-Copy Assembly for job {self.job_id}...")
        
        try:
            list_file = os.path.join(self.video_dir, "clips_list.txt")
            with open(list_file, "w") as f:
                for path in clip_paths:
                    if os.path.exists(path):
                        f.write(f"file '{os.path.abspath(path)}'\n")
            
            final_output = os.path.join(self.job_dir, "final_output.mp4")
            
            if audio_path and os.path.exists(audio_path):
                cmd = [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
                    "-i", audio_path,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    "-shortest", "-threads", "1", final_output
                ]
            else:
                cmd = [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
                    "-c", "copy", "-threads", "1", final_output
                ]

            subprocess.run(cmd, check=True, capture_output=True)
            return final_output

        except Exception as e:
            logger.error(f"Nuclear assembly failed: {e}")
            raise e