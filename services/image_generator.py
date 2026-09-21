import os
import requests
import random
import time
import logging
from typing import List, Optional
from config import (
    POLLINATIONS_API_KEY, TEMP_DIR, IMAGE_WIDTH, IMAGE_HEIGHT,
    IMAGE_MODELS, CONSISTENT_SEED, IMAGE_PROMPT_MAX_WORDS,
)

logger = logging.getLogger(__name__)


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

        os.makedirs(self.image_dir, exist_ok=True)

    def _clean_prompt(self, prompt: str) -> str:
        """Clean and limit prompt length for stability across free APIs."""
        prompt = (prompt or "").strip()
        prompt = prompt.replace(",", "").replace('"', "").replace("'", "")
        words = prompt.split()
        return " ".join(words[:IMAGE_PROMPT_MAX_WORDS])

    def _build_prompt(self, scene_prompt: str) -> str:
        """Fuse scene description with the job-wide style bible for coherence."""
        prompt = self._clean_prompt(scene_prompt)
        if self.style_bible:
            style_words = self._clean_prompt(self.style_bible)
            prompt = f"{prompt}, {style_words}"
        return f"{prompt}, high quality, detailed, professional, 4k"

    def generate_image(self, prompt: str, index: int, retry: int = 2) -> Optional[str]:
        """Generates a single image using Pollinations with style consistency."""
        enhanced_prompt = self._build_prompt(prompt)
        filepath = os.path.join(self.image_dir, f"scene_{index:03d}.jpg")

        logger.info("[Scene %s] Generating image: %s...", index, enhanced_prompt[:60])

        headers = {}
        if POLLINATIONS_API_KEY:
            headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"

        for model in IMAGE_MODELS:
            for attempt in range(1, retry + 1):
                try:
                    params = {
                        "model": model,
                        "width": self.width,
                        "height": self.height,
                        "nologo": "true",
                        "enhance": "true",
                    }
                    if self.base_seed is not None:
                        # Same seed + same style bible -> one coherent look
                        params["seed"] = (self.base_seed + index) % 1000000

                    url = f"https://gen.pollinations.ai/image/{requests.utils.quote(enhanced_prompt)}"
                    response = requests.get(url, params=params, headers=headers, timeout=60)

                    if response.status_code == 200 and len(response.content) > 5000:
                        with open(filepath, "wb") as f:
                            f.write(response.content)
                        logger.info("[Scene %s] Success with model %s!", index, model)
                        return filepath
                    else:
                        logger.warning(
                            "[Scene %s] Model %s attempt %s returned %s",
                            index, model, attempt, response.status_code,
                        )
                except Exception as e:
                    logger.warning("[Scene %s] Model %s attempt %s failed: %s", index, model, attempt, e)
                    time.sleep(1)

        logger.error("[Scene %s] Image generation failed.", index)
        return None

    def generate_all_images(self, scenes: List[str]) -> List[str]:
        """Generates images for all scenes with fallback logic."""
        logger.info("Starting generation for %s scenes...", len(scenes))
        image_paths = []

        for i, scene in enumerate(scenes):
            path = self.generate_image(scene, i)
            if path:
                image_paths.append(path)

            # Avoid hitting rate limits on free APIs
            time.sleep(0.5)

        if not image_paths:
            raise Exception("All image generation attempts failed.")

        return image_paths
