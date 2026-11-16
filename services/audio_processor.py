import os
import asyncio
import logging
import subprocess
import shutil

import edge_tts
from gtts import gTTS

from config import (
    TEMP_DIR, AUDIO_SAMPLE_RATE, AUDIO_BITRATE, ENABLE_LOUDNORM,
    TTS_VOICE, TTS_RATE, TTS_VOLUME, ENABLE_PIPER, PIPER_VOICE_PATH,
)

logger = logging.getLogger(__name__)


class AudioProcessor:
    # ONE video = ONE voice. These three engines sound like three different
    # people, so the first line that renders pins the engine for the whole job:
    # a scene-by-scene fallback (edge-tts on one line, gTTS on the next) is what
    # made the narrator's voice change part-way through a video.
    ENGINE_EDGE = "edge-tts"
    ENGINE_PIPER = "piper"
    ENGINE_GTTS = "gTTS"

    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.audio_dir = os.path.join(self.job_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)
        self.timings_path = os.path.join(self.audio_dir, "word_timings.json")
        # Pinned by the first successful line; never changes for the rest of the job.
        self.engine = None
        # engine -> lines voiced, so a fallback voice is reported instead of silent.
        self.engine_usage = {}

    async def _generate_edge_tts(self, text, filepath, voice=TTS_VOICE):
        """Generate audio with edge-tts while capturing real word-level timing events."""
        communicate = edge_tts.Communicate(
            text, voice,
            rate=TTS_RATE,
            volume=TTS_VOLUME,
            boundary="WordBoundary",  # opt-in since edge-tts 7.x (default is SentenceBoundary)
        )

        words = []  # list of {"text", "start", "end"} in seconds

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                with open(filepath, "ab") as f:
                    f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk.get("offset", 0) / 1e7     # 100-ns ticks -> seconds
                duration = chunk.get("duration", 0) / 1e7
                word_text = chunk.get("text", "")
                if word_text and duration > 0:
                    words.append({
                        "text": word_text,
                        "start": round(start, 3),
                        "end": round(start + duration, 3),
                    })

        return words

    def _run_ffmpeg(self, cmd):
        result = subprocess.run(cmd, capture_output=True)
        return result

    @staticmethod
    def estimate_duration(text):
        """Rough spoken length of a line in seconds (~150 wpm) - used both as the
        ffprobe fallback and to size the silence filler for an unvoiced scene."""
        return max(3.0, len(text or "") / 15.0)

    def _probe_duration(self, filepath, text):
        """Real audio length via ffprobe, falling back to the wpm estimate."""
        try:
            output = subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", filepath,
            ]).decode().strip()
            return float(output)
        except Exception:
            return self.estimate_duration(text)

    def generate_silence(self, duration, index):
        """Write an mp3 of pure silence for a scene whose TTS failed.

        Keeping the scene (silent) preserves the script: its picture and karaoke
        subtitles still play, and the concatenated narration track stays aligned
        with the clips. Returns None when ffmpeg cannot produce the file, in which
        case the caller drops the scene instead.
        """
        filepath = os.path.join(self.audio_dir, f"scene_{index:03d}_silence.mp3")
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"anullsrc=r={AUDIO_SAMPLE_RATE}:cl=mono",
            "-t", f"{max(1.0, float(duration)):.2f}",
            "-c:a", "libmp3lame", "-b:a", AUDIO_BITRATE, filepath,
        ]
        try:
            result = self._run_ffmpeg(cmd)
            if result.returncode == 0 and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                logger.info("Generated %.1fs of silence for unvoiced scene %s.", duration, index)
                return filepath
            logger.warning("Silence generation failed for scene %s: %s",
                           index, (result.stderr or b"")[:200])
        except Exception as e:
            logger.warning("Silence generation error for scene %s: %s", index, e)
        return None

    # ------------------------------------------------------------------
    # Engines - each one returns (path, word_timings) or raises
    # ------------------------------------------------------------------
    def _synthesize_edge(self, text, filepath):
        """edge-tts with the configured TTS_VOICE (the intended voice)."""
        words = asyncio.run(self._generate_edge_tts(text, filepath, TTS_VOICE))
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            raise Exception("edge-tts produced no audio")
        return filepath, (words or None)

    def _synthesize_piper(self, text, filepath):
        """Optional offline Piper voice (ENABLE_PIPER + a .onnx model)."""
        import shlex
        wav_filepath = os.path.splitext(filepath)[0] + ".wav"
        shell_cmd = (
            f"echo {shlex.quote(text)} | piper --model "
            f"{shlex.quote(PIPER_VOICE_PATH)} --output_file {shlex.quote(wav_filepath)}"
        )
        proc = subprocess.run(["bash", "-c", shell_cmd], capture_output=True, timeout=60)
        if proc.returncode != 0 or not os.path.exists(wav_filepath) or os.path.getsize(wav_filepath) == 0:
            raise Exception("piper failed: " + proc.stderr.decode()[:200])
        conv = self._run_ffmpeg([
            "ffmpeg", "-y", "-i", wav_filepath, "-codec:a", "libmp3lame",
            "-b:a", AUDIO_BITRATE, filepath,
        ])
        if conv.returncode == 0 and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            os.remove(wav_filepath)
            return filepath, None
        os.remove(filepath) if os.path.exists(filepath) else None
        return wav_filepath, None  # keep the wav rather than lose the line

    def _synthesize_gtts(self, text, filepath):
        """gTTS - the keyless last resort, and a clearly different voice."""
        gTTS(text=text, lang="en", slow=False).save(filepath)
        if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
            raise Exception("gTTS produced no audio")
        return filepath, None

    def _chain(self, engine=None):
        """(name, method) engines to try, in order.

        A pinned engine is returned ALONE: falling through to another engine
        part-way through a video is exactly what changed the voice after a scene.
        With nothing pinned, the intended voice is tried first, then the optional
        offline Piper voice, then gTTS.
        """
        candidates = [(self.ENGINE_EDGE, self._synthesize_edge)]
        if ENABLE_PIPER and PIPER_VOICE_PATH and os.path.exists(PIPER_VOICE_PATH):
            candidates.append((self.ENGINE_PIPER, self._synthesize_piper))
        candidates.append((self.ENGINE_GTTS, self._synthesize_gtts))
        pinned = engine or self.engine
        if pinned:
            return [pair for pair in candidates if pair[0] == pinned]
        return candidates

    def voice_note(self):
        """Completion-message line, and ONLY when the job did not use the
        configured edge-tts voice for every line - a silent voice swap is what
        makes a video sound like it has a second narrator."""
        if not self.engine_usage or set(self.engine_usage) == {self.ENGINE_EDGE}:
            return ""
        parts = ", ".join(f"{name} x{count}" for name, count in
                          sorted(self.engine_usage.items(), key=lambda kv: -kv[1]))
        return f"🎙️ voice: {parts} (configured: {self.ENGINE_EDGE} / {TTS_VOICE})"

    def reset_voice(self):
        """Forget the pinned voice so the next line chooses again.

        Used to re-voice a WHOLE script when the first pass had to fall back to
        a different engine: the fallback voice is a last resort, not the default,
        so the configured voice gets one clean attempt at every line.
        """
        self.engine = None
        self.engine_usage = {}

    def generate_single_narration(self, text, index, engine=None):
        """Generate one scene's narration.

        ``engine`` pins the TTS engine for this line. The caller passes the job's
        pinned engine (``self.engine``) for every line after the first, so the
        voice stays the same from scene 1 to the last; ``None`` lets the first
        line choose the best available engine.

        Returns (path, duration, word_timings), or (None, 0, None) on failure.
        """
        try:
            pinned = engine or self.engine
            logger.info("Generating audio for scene %s with %s: '%s...'",
                        index, pinned or "auto", (text or "")[:50])

            filepath = os.path.join(self.audio_dir, f"scene_{index:03d}.mp3")
            if os.path.exists(filepath):
                os.remove(filepath)

            last_error = ""
            for name, synthesize in self._chain(pinned):
                # The AUTO line decides the job's voice, so give the preferred
                # engine a second chance before settling for another voice.
                for attempt in range(1, 2 if pinned else 3):
                    try:
                        path, word_timings = synthesize(text, filepath)
                        if not os.path.exists(path) or os.path.getsize(path) == 0:
                            raise Exception(f"{name} produced no audio")

                        # Normalize loudness FIRST: loudnorm rewrites (and can
                        # pad/resample) the file, so probing before it measured a
                        # duration the concatenated track would not have - the
                        # clips then drifted ahead of their own narration.
                        if ENABLE_LOUDNORM:
                            self._loudnorm(path)
                        duration = self._probe_duration(path, text)

                        if self.engine is None:
                            self.engine = name
                            logger.info("Job %s: voice pinned to %s for the whole video.",
                                        self.job_id, name)
                        self.engine_usage[name] = self.engine_usage.get(name, 0) + 1
                        return path, duration, word_timings
                    except Exception as e:
                        last_error = f"{name}: {e}"
                        logger.warning("Scene %s: %s attempt %s failed: %s",
                                       index, name, attempt, e)

            logger.error("Scene %s could not be voiced: %s", index, last_error)
            return None, 0, None

        except Exception as e:
            logger.error("Failed to generate narration %s: %s", index, e)
            return None, 0, None

    def _loudnorm(self, filepath):
        """Two-pass loudness normalization to ~ -14 LUFS (streaming standard)."""
        try:
            tmp = filepath + ".norm.mp3"
            cmd = [
                "ffmpeg", "-y", "-i", filepath,
                "-af", f"loudnorm=I=-14:TP=-1.5:LRA=11",
                "-ar", str(AUDIO_SAMPLE_RATE), "-b:a", "64k", tmp,
            ]
            result = self._run_ffmpeg(cmd)
            if result.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                os.replace(tmp, filepath)
                return True
            logger.warning("loudnorm failed for %s: %s", filepath, result.stderr.decode()[:200])
            if os.path.exists(tmp):
                os.remove(tmp)
            return False
        except Exception as e:
            logger.warning("loudnorm error for %s: %s", filepath, e)
            return False

    def merge_audio(self, narration_paths, bg_music_path=None):
        """
        Merges narration files and optionally background music.
        Handles cases where narration_paths is empty.
        """
        logger.info("Merging audio for job %s...", self.job_id)

        final_audio_path = os.path.join(self.audio_dir, "final_audio.mp3")

        try:
            if not narration_paths and not bg_music_path:
                logger.info("No narration or background music to merge.")
                return None

            if not narration_paths and bg_music_path:
                logger.info("Only background music available. Copying background music.")
                shutil.copy(bg_music_path, final_audio_path)
                return final_audio_path

            # If narration_paths exist, proceed with concat
            list_file_path = os.path.join(self.audio_dir, "concat_list.txt")
            with open(list_file_path, "w") as f:
                for path in narration_paths:
                    abs_path = os.path.abspath(path)
                    f.write(f"file '{abs_path}'\n")

            # Merge narrations first
            narration_merged_path = os.path.join(self.audio_dir, "narrations_merged.mp3")
            # Re-encode instead of stream-copying: a job can mix segment formats
            # (edge-tts 24 kHz, gTTS 32 kbps, silence filler 22050 Hz), and the
            # concat demuxer with "-c copy" assumes every segment has identical
            # codec parameters - it glitches or drifts when they differ, which
            # pulls the narration out of sync with the clips.
            cmd_narration_merge = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file_path,
                "-ac", "1", "-ar", str(AUDIO_SAMPLE_RATE),
                "-c:a", "libmp3lame", "-b:a", AUDIO_BITRATE, narration_merged_path
            ]
            result = self._run_ffmpeg(cmd_narration_merge)
            if result.returncode != 0:
                logger.error("ffmpeg narration merge failed: %s", result.stderr.decode()[:300])
                return None

            if not os.path.exists(narration_merged_path):
                logger.error("Narration merge output not created: %s", narration_merged_path)
                return None

            if bg_music_path:
                logger.info("Mixing narrations with background music.")
                cmd_final_mix = [
                    "ffmpeg", "-y", "-i", narration_merged_path, "-i", bg_music_path,
                    "-filter_complex",
                    "[0:a]volume=1.0[a0];[1:a]volume=0.3[a1];[a0][a1]amix=inputs=2:duration=first",
                    "-c:a", "aac", "-b:a", "128k", "-shortest", final_audio_path
                ]
                result = self._run_ffmpeg(cmd_final_mix)
                if result.returncode != 0:
                    logger.error("ffmpeg mix failed: %s", result.stderr.decode()[:300])
                    return None
            else:
                logger.info("No background music. Using merged narrations as final audio.")
                shutil.copy(narration_merged_path, final_audio_path)

            if not os.path.exists(final_audio_path):
                logger.error("Final audio not created: %s", final_audio_path)
                return None

            return final_audio_path
        except Exception as e:
            logger.error("Audio merge failed: %s", e)
            return None
