import os
import requests
import random
import time
from typing import List, Optional
from config import POLLINATIONS_API_KEY, TEMP_DIR


class ImageGenerator:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        self.image_dir = os.path.join(self.job_dir, "images")
        self.width = 720
        self.height = 1280

        # Create directories
        os.makedirs(self.image_dir, exist_ok=True)

    def _clean_prompt(self, prompt: str) -> str:
        """
        Cleans and optimizes prompt for image generation.
        """
        prompt = prompt.strip()
        # Remove common problematic characters
        prompt = prompt.replace(",", "").replace('"', "").replace("'", "")
        words = prompt.split()
        # Limit to 20 words for stability across different APIs
        return " ".join(words[:20])

    def generate_image(self, prompt: str, index: int, retry: int = 2) -> Optional[str]:
        """
        Generates a single image using Pollinations with improved prompting.
        """
        clean_prompt = self._clean_prompt(prompt)
        # Enhance prompt for better quality
        enhanced_prompt = f"{clean_prompt}, high quality, detailed, professional, 4k"
        filepath = os.path.join(self.image_dir, f"scene_{index:03d}.jpg")

        print(f"🖼️ [Scene {index}] Generating image for: {clean_prompt[:50]}...")
        
        headers = {}
        if POLLINATIONS_API_KEY:
            headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"

        # Try flux dev for better quality (free tier model)
        models = ["flux-dev", "flux"]
        
        for model in models:
            for attempt in range(1, retry + 1):
                try:
                    # Build URL with proper parameters
                    params = {
                        "model": model,
                        "width": self.width,
                        "height": self.height,
                        "seed": random.randint(0, 1000000),
                        "nologo": "true",
                        "enhance": "true"
                    }
                    
                    url = f"https://gen.pollinations.ai/image/{requests.utils.quote(enhanced_prompt)}"
                    response = requests.get(url, params=params, headers=headers, timeout=60)
                    
                    if response.status_code == 200 and len(response.content) > 5000:
                        with open(filepath, "wb") as f:
                            f.write(response.content)
                        print(f"✅ [Scene {index}] Success with model {model}!")
                        return filepath
                    else:
                        print(f"⚠️ [Scene {index}] Model {model} attempt {attempt} returned {response.status_code}")
                except Exception as e:
                    print(f"⚠️ [Scene {index}] Model {model} attempt {attempt} failed: {e}")
                    time.sleep(1)
        
        print(f"🚫 [Scene {index}] Image generation failed.")
        return None

    def generate_all_images(self, scenes: List[str]) -> List[str]:
        """
        Generates images for all scenes with fallback logic.
        """
        print(f"\n🎬 Starting generation for {len(scenes)} scenes...")
        image_paths = []

        for i, scene in enumerate(scenes):
            path = self.generate_image(scene, i)
            if path:
                image_paths.append(path)
            
            # Avoid hitting rate limits on free APIs
            time.sleep(0.5)

        if not image_paths:
            raise Exception("❌ All image generation attempts failed.")

        return image_paths
