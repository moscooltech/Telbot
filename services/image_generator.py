import os
import re
import requests
import random
import time
import base64
import logging
from typing import List, Optional
from config import (
    POLLINATIONS_API_KEY, BYTEZ_API_KEY, TEMP_DIR, IMAGE_WIDTH, IMAGE_HEIGHT,
    CONSISTENT_SEED, IMAGE_PROMPT_MAX_WORDS, POLLINATIONS_ENHANCE,
    BYTEZ_IMAGE_MODEL, IMAGE_LEGACY_MODEL, IMAGE_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Magic-byte sniffing: only trust payloads that are real images
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# Tiny responses are error pages, not photos
MIN_IMAGE_BYTES = 3000

# Failure caching: a provider that keeps failing is skipped for the rest of the job
# (each ImageGenerator instance is job-scoped) until its cooldown expires.
PROVIDER_COOLDOWN_SECONDS = 600   # 10 min
PROVIDER_FAILURE_THRESHOLD = 2    # consecutive failures before cooldown kicks in


class ImageGenerator:
    def __init__(self, job_id: str, style_bible: str = "") -> None:
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        self.image_dir = os.path.join(self.job_dir, "images")
        self.width = IMAGE_WIDTH
        self.height = IMAGE_HEIGHT
        self.style_bible = (style_bible or "").strip()
        # One seed per job keeps the visual identity stable across all scenes
        self.base_seed = random.randint(0, 999999) if CONSISTENT_SEED else None
        # key -> {"fails": int, "cooldown_until": epoch seconds}
        self._provider_stats = {}

        os.makedirs(self.image_dir, exist_ok=True)

    def _clean_prompt(self, prompt: str) -> str:
        """Sanitize prompt: strip quotes/newlines, collapse whitespace, cap length.
        Commas are kept — they are how image models parse subject/setting/lighting layers."""
        prompt = (prompt or "").strip()
        prompt = re.sub(r"[\"'`\n\r]+", " ", prompt)
        prompt = re.sub(r"\s+", " ", prompt).strip(" ,")
        if IMAGE_PROMPT_MAX_WORDS > 0:
            words = prompt.split()
            prompt = " ".join(words[:IMAGE_PROMPT_MAX_WORDS])
        return prompt

    def _build_prompt(self, scene_prompt: str) -> str:
        """Fuse scene description with the job-wide style bible for coherence."""
        prompt = self._clean_prompt(scene_prompt)
        if self.style_bible:
            style_words = self._clean_prompt(self.style_bible)
            prompt = f"{prompt}, {style_words}"
        return f"{prompt}, high quality, detailed, professional, 4k"

    @staticmethod
    def _is_image(response: requests.Response) -> bool:
        """A success only counts as an actual picture: HTTP 200, plausible size, real image magic bytes."""
        if response.status_code != 200:
            return False
        content = response.content
        if len(content) < MIN_IMAGE_BYTES:
            return False
        return content[:3] == JPEG_MAGIC or content[:8] == PNG_MAGIC[:8]

    # ------------------------------------------------------------------
    # Provider 1: legacy image.pollinations.ai — keyless, free, still alive
    # (gen.pollinations.ai started requiring an API key for every model and
    # dropped "flux-dev"; this legacy endpoint kept working without one.)
    # ------------------------------------------------------------------
    def _generate_pollinations_legacy(self, prompt: str, seed: Optional[int], model: str,
                                      timeout: int) -> bytes:
        params = {
            "width": self.width,
            "height": self.height,
            "nologo": "true",
            "model": model,
        }
        if POLLINATIONS_ENHANCE:
            params["enhance"] = "true"
        if seed is not None:
            params["seed"] = seed

        url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}"
        response = requests.get(url, params=params, timeout=timeout)
        if not self._is_image(response):
            raise Exception(
                f"legacy returned {response.status_code} / {len(response.content)}B"
            )
        return response.content

    # ------------------------------------------------------------------
    # Provider 2: gen.pollinations.ai — needs POLLINATIONS_API_KEY, richer models
    # ------------------------------------------------------------------
    def _generate_pollinations_gen(self, prompt: str, seed: Optional[int], model: str,
                                   timeout: int) -> bytes:
        params = {
            "model": model,
            "width": self.width,
            "height": self.height,
            "nologo": "true",
            "enhance": "true" if POLLINATIONS_ENHANCE else "false",
        }
        if seed is not None:
            params["seed"] = seed

        url = f"https://gen.pollinations.ai/image/{requests.utils.quote(prompt)}"
        response = requests.get(
            url, params=params,
            headers={"Authorization": f"Bearer {POLLINATIONS_API_KEY}"},
            timeout=timeout,
        )
        if not self._is_image(response):
            raise Exception(
                f"gen returned {response.status_code} / {len(response.content)}B"
            )
        return response.content

    # ------------------------------------------------------------------
    # Provider 3: Bytez — free-tier keyed fallback (SDXL)
    # ------------------------------------------------------------------
    def _generate_bytez(self, prompt: str, seed: Optional[int], model: Optional[str],
                        timeout: int) -> bytes:
        url = f"https://api.bytez.com/models/v2/{BYTEZ_IMAGE_MODEL}"
        payload = {"prompt": prompt}
        if seed is not None:
            payload["seed"] = seed
        response = requests.post(
            url, json=payload,
            headers={"Authorization": f"Key {BYTEZ_API_KEY}"},
            timeout=timeout,
        )
        if response.status_code != 200:
            raise Exception(f"bytez returned {response.status_code}")

        data = response.json()
        b64 = data.get("output") or data.get("output_base64") or data.get("image")
        if not b64:
            raise Exception("bytez response had no image data")
        return base64.b64decode(b64)

    def _provider_key(self, provider_name: str, model: Optional[str]) -> str:
        return f"{provider_name}:{model or ''}"

    def _mark_provider_failure(self, key: str) -> None:
        stats = self._provider_stats.setdefault(key, {"fails": 0, "cooldown_until": 0.0})
        stats["fails"] += 1
        if stats["fails"] >= PROVIDER_FAILURE_THRESHOLD:
            stats["cooldown_until"] = time.time() + PROVIDER_COOLDOWN_SECONDS
            logger.warning("Provider %s is cooling down for %ss after %s failures.",
                           key, PROVIDER_COOLDOWN_SECONDS, stats["fails"])

    def _provider_chain(self) -> List[tuple]:
        """Ordered fallback chain: keyless first, then keyed providers.
        Each entry: (name, callable(prompt, seed, model, timeout) -> bytes, model or None).
        Providers in failure cooldown are skipped, unless that would leave the chain empty."""
        chain = [
            ("pollinations-legacy", self._generate_pollinations_legacy, IMAGE_LEGACY_MODEL),
        ]
        if POLLINATIONS_API_KEY:
            # Order matters: retry with a fresh generation when one fails; models listed first win.
            for model in ("flux", "turbo"):
                chain.append(("pollinations-gen", self._generate_pollinations_gen, model))
        if BYTEZ_API_KEY:
            chain.append(("bytez", self._generate_bytez, None))

        now = time.time()
        healthy = [
            entry for entry in chain
            if self._provider_stats.get(self._provider_key(entry[0], entry[2]), {}).get("cooldown_until", 0) < now
        ]
        return healthy or chain  # last-ditch: if everything is cooling down, try everything

    def generate_image(self, prompt: str, index: int, retry: int = 2) -> Optional[str]:
        """Generates a single image, trying every provider in the fallback chain."""
        enhanced_prompt = self._build_prompt(prompt)
        filepath = os.path.join(self.image_dir, f"scene_{index:03d}.jpg")

        logger.info("[Scene %s] Generating image: %s...", index, enhanced_prompt[:60])

        seed = (self.base_seed + index) % 1000000 if self.base_seed is not None else None
        chain = self._provider_chain()
        if not chain:
            logger.error("[Scene %s] No image providers configured.", index)
            return None

        last_error = ""
        for attempt in range(1, retry + 1):
            for provider_name, provider_fn, model in chain:
                key = self._provider_key(provider_name, model)
                try:
                    # Legacy tier is rate limited (~1 req / 15s); space out requests.
                    time.sleep(3)
                    image_bytes = provider_fn(enhanced_prompt, seed, model, timeout=IMAGE_TIMEOUT)
                    with open(filepath, "wb") as f:
                        f.write(image_bytes)
                    self._provider_stats[key] = {"fails": 0, "cooldown_until": 0.0}
                    logger.info("[Scene %s] Success with %s (%s) attempt %s!",
                                index, provider_name, model, attempt)
                    return filepath
                except Exception as e:
                    last_error = f"{provider_name}: {e}"
                    self._mark_provider_failure(key)
                    logger.warning("[Scene %s] %s attempt %s failed: %s",
                                   index, provider_name, attempt, e)

        logger.error("[Scene %s] Image generation failed. Last error: %s", index, last_error)
        return None

    def generate_all_images(self, scenes: List[str]) -> List[str]:
        """Generates images for all scenes with fallback logic."""
        logger.info("Starting generation for %s scenes...", len(scenes))
        image_paths = []

        for i, scene in enumerate(scenes):
            path = self.generate_image(scene, i)
            if path:
                image_paths.append(path)

        if not image_paths:
            raise Exception("All image generation attempts failed.")

        return image_paths
