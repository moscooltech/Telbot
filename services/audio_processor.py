import os
import asyncio
import logging
import subprocess
import shutil

import edge_tts
from gtts import gTTS

from config import (
    TEMP_DIR, AUDIO_SAMPLE_RATE, ENABLE_LOUDNORM,
    TTS_VOICE, TTS_RATE, TTS_VOLUME, ENABLE_PIPER, PIPER_VOICE_PATH,
)

logger = logging.getLogger(__name__)


class AudioProcessor:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.audio_dir = os.path.join(self.job_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)
        self.timings_path = os.path.join(self.audio_dir, "word_timings.json")

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

    def generate_single_narration(self, text, index):
        """
        Generates a single narration file.
        Returns (path, duration, word_timings) where word_timings is a list of
        {"text", "start", "end"} dicts aligned to this file's audio, or None.
        """
        try:
            logger.info("Generating audio for index %s: '%s...'", index, text[:50])

            mp3_filepath = os.path.join(self.audio_dir, f"scene_{index:03d}.mp3")
            word_timings = None

            if os.path.exists(mp3_filepath):
                os.remove(mp3_filepath)

            try:
                # edge-tts outputs mp3 natively; stream to file and capture WordBoundary events
                words = asyncio.run(self._generate_edge_tts(text, mp3_filepath, TTS_VOICE))
                if not os.path.exists(mp3_filepath) or os.path.getsize(mp3_filepath) == 0:
                    raise Exception("edge-tts produced no audio")
                if words:
                    word_timings = words
            except Exception as e:
                logger.warning("edge-tts failed: %s, trying Piper fallback", e)

                if ENABLE_PIPER and PIPER_VOICE_PATH and os.path.exists(PIPER_VOICE_PATH):
                    try:
                        import shlex
                        wav_filepath = os.path.join(self.audio_dir, f"scene_{index:03d}.wav")
                        shell_cmd = f"echo {shlex.quote(text)} | piper --model {shlex.quote(PIPER_VOICE_PATH)} --output_file {shlex.quote(wav_filepath)}"
                        proc = subprocess.run(["bash", "-c", shell_cmd], capture_output=True, timeout=60)
                        if proc.returncode == 0 and os.path.exists(wav_filepath) and os.path.getsize(wav_filepath) > 0:
                            # Convert wav to mp3 to keep the pipeline uniform
                            conv = self._run_ffmpeg([
                                "ffmpeg", "-y", "-i", wav_filepath, "-codec:a", "libmp3lame",
                                "-b:a", AUDIO_BITRATE, mp3_filepath
                            ])
                            if conv.returncode == 0:
                                os.remove(wav_filepath)
                            else:
                                mp3_filepath = wav_filepath  # use wav as-is
                        else:
                            raise Exception("piper failed: " + proc.stderr.decode()[:200])
                    except Exception as pe:
                        logger.warning("Piper fallback failed: %s, falling back to gTTS", pe)
                        tts = gTTS(text=text, lang="en", slow=False)
                        tts.save(mp3_filepath)
                else:
                    tts = gTTS(text=text, lang="en", slow=False)
                    tts.save(mp3_filepath)

            if not os.path.exists(mp3_filepath):
                raise Exception("Audio file not created after all TTS attempts")

            # Get duration using ffprobe (list-form argv, no shell)
            try:
                output = subprocess.check_output([
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", mp3_filepath
                ]).decode().strip()
                duration = float(output)
            except Exception:
                duration = max(3.0, len(text) / 15.0)

            # Normalizing per scene keeps loudness consistent when clips are concatenated
            if ENABLE_LOUDNORM:
                self._loudnorm(mp3_filepath)

            return mp3_filepath, duration, word_timings

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
            cmd_narration_merge = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file_path,
                "-c", "copy", narration_merged_path
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
