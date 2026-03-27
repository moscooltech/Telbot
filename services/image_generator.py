import os
import requests
import random
import time
from config import POLLINATIONS_URL, TEMP_DIR


class ImageGenerator:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        self.image_dir = os.path.join(self.job_dir, "images")

        # Create directories
        os.makedirs(self.image_dir, exist_ok=True)

    def _clean_prompt(self, prompt: str) -> str:
        """
        Cleans and optimizes prompt for Pollinations.
        """
        prompt = prompt.strip()
        prompt = prompt.replace(",", "")
        words = prompt.split()

        # Limit to 12–15 words (important for stability)
        prompt = " ".join(words[:15])

        return prompt

    def generate_image(self, prompt: str, index: int, retry: int = 3) -> str | None:
        """
        Generates a single image using Pollinations with retries.
        """
        print(f"\n🖼️ Generating image for scene {index}...")

        clean_prompt = self._clean_prompt(prompt)
        encoded_prompt = requests.utils.quote(clean_prompt)

        seed = random.randint(0, 1000000)
        url = POLLINATIONS_URL.format(prompt=encoded_prompt, seed=seed)

        filepath = os.path.join(self.image_dir, f"scene_{index:03d}.jpg")

        for attempt in range(1, retry + 1):
            try:
                print(f"🔁 Attempt {attempt} | Prompt: {clean_prompt}")

                response = requests.get(url, timeout=60)

                # Validate response
                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code}")

                if not response.content or len(response.content) < 1000:
                    raise Exception("Empty or invalid image received")

                # Save image
                with open(filepath, "wb") as f:
                    f.write(response.content)

                print(f"✅ Image saved successfully: {filepath}")
                return filepath

            except Exception as e:
                print(f"❌ Attempt {attempt} failed (scene {index}): {e}")
                time.sleep(2)

        print(f"🚫 Failed to generate image after {retry} attempts (scene {index})")
        return None

    def generate_all_images(self, scenes: list[str]) -> list[str]:
        """
        Generates images for all scenes.
        """
        print("\n🎬 Starting image generation for all scenes...")

        image_paths = []

        for i, scene in enumerate(scenes):
            path = self.generate_image(scene, i)

            if path:
                image_paths.append(path)
            else:
                print(f"❌ Skipping scene {i} due to failure")

        if not image_paths:
            raise Exception("❌ Failed to generate any images.")

        print(f"\n✅ Generated {len(image_paths)} images successfully")
        return image_paths