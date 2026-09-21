import os
import re
import subprocess
import logging
import textwrap
from config import (
    TEMP_DIR, IMAGE_WIDTH, IMAGE_HEIGHT,
    SUBTITLE_WORDS_PER_CHUNK, SUBTITLE_FONT_SIZE, SUBTITLE_FONT_NAME,
    SUBTITLE_MARGIN_V, SUBTITLE_MARGIN_LR,
)

logger = logging.getLogger(__name__)

# Highlight colors for karaoke effect (ASS uses &H00BBGGRR)
ASS_COLOR_SUNG = "&H0000FFFF"     # yellow  (current/past word)
ASS_COLOR_UNSET = "&H00FFFFFF"    # white   (not yet spoken)
ASS_COLOR_OUTLINE = "&H00000000"  # black outline

FONT_SEARCH_PATHS = [
    os.path.join(TEMP_DIR, "..", "assets", "fonts"),
    "assets/fonts",
    "/usr/share/fonts/truetype/dejavu",
]


class VideoProcessor:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.video_dir = os.path.join(self.job_dir, "video")
        os.makedirs(self.video_dir, exist_ok=True)
        self.width = IMAGE_WIDTH
        self.height = IMAGE_HEIGHT
        self.fontfile = self._find_fontfile()

    # ------------------------------------------------------------------
    # Font handling
    # ------------------------------------------------------------------
    def _find_fontfile(self):
        """Locate a bold TTF for libass. Falls back to fontconfig's default."""
        for base in FONT_SEARCH_PATHS:
            base = os.path.abspath(base)
            if not os.path.isdir(base):
                continue
            for f in os.listdir(base):
                low = f.lower()
                if low.endswith((".ttf", ".otf")) and ("bold" in low or "black" in low):
                    return os.path.join(base, f)
            # Any ttf is better than none
            for f in os.listdir(base):
                if f.lower().endswith((".ttf", ".otf")):
                    return os.path.join(base, f)
        logger.warning("No bundled font found; libass will use fontconfig default.")
        return None

    # ------------------------------------------------------------------
    # Subtitle generation (ASS karaoke)
    # ------------------------------------------------------------------
    @staticmethod
    def _ass_time(seconds):
        """Format seconds as ASS timestamp H:MM:SS.CC."""
        seconds = max(0.0, float(seconds))
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hrs}:{mins:02d}:{secs:05.2f}"

    @staticmethod
    def _ass_escape(text):
        """Escape text for the ASS Dialogue Text field."""
        return (text or "").replace("{", "(").replace("}", ")").replace("\n", " ")

    def _estimate_word_timing(self, words, duration):
        """Fallback timing when no TTS WordBoundary data is available."""
        valid = [w for w in words if w]
        count = len(valid)
        if count == 0:
            return [(0.0, duration)]
        per = duration / count
        times, t = [], 0.0
        for w in words:
            if not w:
                times.append((t, t))
                continue
            start, end = t, min(t + per, duration)
            times.append((start, end))
            t = end
        return times

    def _split_words(self, text):
        """Split text into display tokens, keeping punctuation attached."""
        tokens = []
        for tok in (text or "").split():
            word = re.sub(r'^[^\w]+|[^\w]+$', '', tok) or tok.strip()
            if word:
                tokens.append(word)
        return tokens

    def _build_chunks(self, word_texts, word_times, chunk_size):
        """
        Group consecutive words into karaoke chunks.
        Returns list of dicts: {words: [(text, start, end)], start, end}.
        """
        chunks = []
        current = []
        for word, (start, end) in zip(word_texts, word_times):
            if not word:
                continue
            current.append((word, start, end))
            if len(current) >= chunk_size:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)

        result = []
        for i, chunk in enumerate(chunks):
            start = chunk[0][1]
            end = chunk[-1][2]
            # Hold the chunk briefly so it doesn't blink away instantly,
            # but never overlap the next chunk.
            hold = min(0.12, 0.5 * max(0.0, end - start))
            nxt_start = chunks[i + 1][0][1] if i + 1 < len(chunks) else None
            if nxt_start is not None:
                end = min(end + hold, nxt_start)
            else:
                end = end + hold
            result.append({"words": chunk, "start": start, "end": max(end, start + 0.1)})
        return result

    def _karaoke_tag(self, chunk):
        """
        Build ASS Dialogue text with \\k karaoke tags for a chunk.
        \\k durations are in centiseconds and include the gap BEFORE each word.
        """
        parts = []
        prev = chunk["start"]
        for word, start, _end in chunk["words"]:
            gap_cs = max(0, int(round((start - prev) * 100)))
            dur_cs = max(1, int(round((max(start, _end) - start) * 100)))
            parts.append(f"{{\\k{gap_cs + dur_cs}}}{word}")
            prev = max(start, _end)
        return " ".join(parts)

    def generate_ass(self, scene_text, word_texts, word_times, duration, scene_index):
        """
        Writes a per-scene .ass file with karaoke (word-highlight) subtitles.
        Returns path or None if there is nothing to display.
        """
        chunks = self._build_chunks(word_texts, word_times, SUBTITLE_WORDS_PER_CHUNK)
        if not chunks:
            return None

        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {self.width}\n"
            f"PlayResY: {self.height}\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
            "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Karaoke,{SUBTITLE_FONT_NAME},{SUBTITLE_FONT_SIZE},"
            f"{ASS_COLOR_SUNG},{ASS_COLOR_UNSET},{ASS_COLOR_OUTLINE},&H64000000,"
            f"-1,0,0,0,100,100,0,0,1,3,1,2,{SUBTITLE_MARGIN_LR},{SUBTITLE_MARGIN_LR},{SUBTITLE_MARGIN_V},1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        lines = []
        for chunk in chunks:
            text = self._karaoke_tag(chunk)
            lines.append(
                f"Dialogue: 0,{self._ass_time(chunk['start'])},{self._ass_time(chunk['end'])},"
                f"Karaoke,,0,0,0,,{text}"
            )

        ass_path = os.path.join(self.video_dir, f"subs_{scene_index:03d}.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(header + "\n".join(lines))
        return ass_path

    def _ass_filter_arg(self, ass_path):
        """Escape the .ass path for the subtitles filter argument."""
        rel = os.path.basename(ass_path)  # subprocess runs with cwd=self.video_dir
        rel = rel.replace(":", "\\:").replace("'", "\\'")
        return f"subtitles={rel}:fontsdir={os.path.dirname(self.fontfile) or 'assets/fonts'}"

    # ------------------------------------------------------------------
    # Legacy SRT (kept for reference/external use)
    # ------------------------------------------------------------------
    def generate_srt(self, scenes, durations):
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

    # ------------------------------------------------------------------
    # Scene rendering
    # ------------------------------------------------------------------
    def create_scene_video(self, image_path, duration, index, narration,
                           narration_duration=None, word_timings=None):
        """
        Renders one scene clip with TikTok-style karaoke subtitles:
        - words shown in 2-3 word chunks
        - the current word highlights in yellow as it is spoken (real TTS timing
          when available, estimated otherwise)
        Falls back to simple static subtitles on error.
        """
        output_path = os.path.join(self.video_dir, f"clip_{index:03d}.mp4")
        # ffmpeg runs with cwd=video_dir (so the .ass file is a plain relative path);
        # image and output must therefore be ABSOLUTE paths.
        image_abs = os.path.abspath(image_path)
        output_abs = os.path.abspath(output_path)
        use_duration = duration if narration_duration is None else narration_duration
        clean_text = (narration or " ").strip() or " "

        word_texts = self._split_words(clean_text)
        # Use real TTS timings only when they align 1:1 with display words.
        # (TTS may normalize e.g. "3" -> "three"; mismatched counts fall back to estimates.)
        if word_timings and len(word_timings) == len([w for w in word_texts if w]):
            word_times = [(wt["start"], min(wt["end"], use_duration)) for wt in word_timings]
            logger.info("Scene %s: using REAL TTS word timings (%s words)", index, len(word_timings))
        else:
            word_times = self._estimate_word_timing(word_texts, use_duration)
            logger.info("Scene %s: estimated word timing (%s words)", index, len(word_texts))

        try:
            ass_path = self.generate_ass(clean_text, word_texts, word_times, use_duration, index)
            if not ass_path:
                raise Exception("Empty subtitle track")

            scale_filter = (
                f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
                f"crop={self.width}:{self.height}"
            )

            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", image_abs,
                "-t", str(use_duration), "-r", "15",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-vf", f"{scale_filter},{self._ass_filter_arg(ass_path)},format=yuv420p",
                "-threads", "1", output_abs,
            ]

            timeout = 120 if len(word_texts) > 5 else 90
            logger.info("Rendering scene %s: %s words, %.1fs", index, len(word_texts), use_duration)
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=timeout, cwd=self.video_dir)
            except subprocess.TimeoutExpired:
                raise Exception(f"FFmpeg timeout after {timeout}s")

            if result.returncode != 0:
                err = result.stderr.decode() if result.stderr else "unknown"
                raise Exception(f"FFmpeg (karaoke) failed: {err[-400:]}")

            return output_path

        except Exception as e:
            logger.warning("Karaoke subtitles failed for scene %s: %s — using static fallback", index, e)
            return self._create_simple_subtitle_video(image_path, use_duration, index, clean_text)

    def _create_simple_subtitle_video(self, image_path, duration, index, text):
        """Fallback: simple static subtitles without animation."""
        output_path = os.path.join(self.video_dir, f"clip_{index:03d}.mp4")

        wrapped = textwrap.wrap(text, width=20, break_long_words=False)
        if not wrapped:
            wrapped = [text[:20]] if text else [" "]

        safe_text = " ".join(wrapped).replace(":", "\\:").replace("'", "''").replace("\\", "\\\\")
        drawtext = (
            f"drawtext=text='{safe_text}':fontcolor=white:fontsize=42:"
            f"x=(w-text_w)/2:y=h-{SUBTITLE_MARGIN_V}-text_h/2:"
            f"borderw=2:bordercolor=black:"
            f"box=1:boxcolor=black@0.35:boxborderw=12"
        )

        scale_filter = (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
            f"crop={self.width}:{self.height}"
        )

        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", image_path,
            "-t", str(duration), "-r", "15",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
            "-vf", f"{scale_filter},{drawtext},format=yuv420p",
            "-threads", "1", output_path,
        ]

        logger.info("Rendering simple static subtitle for scene %s", index)
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            err = result.stderr.decode() if result.stderr else "unknown"
            raise Exception(f"Simple subtitle FFmpeg failed: {err[-500:]}")
        return output_path

    # ------------------------------------------------------------------
    # Final assembly
    # ------------------------------------------------------------------
    def assemble_video(self, clip_paths, audio_path, srt_path):
        """
        Final Assembly: uses 'Stream Copy' to stitch pre-subtitled clips.
        Uses ~0 MB of RAM because no decoding/encoding happens here.
        """
        logger.info("Nuclear Stream-Copy Assembly for job %s...", self.job_id)

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
                    "-shortest", "-threads", "1", final_output,
                ]
            else:
                cmd = [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
                    "-c", "copy", "-threads", "1", final_output,
                ]

            subprocess.run(cmd, check=True, capture_output=True)
            return final_output

        except Exception as e:
            logger.error("Nuclear assembly failed: %s", e)
            raise
