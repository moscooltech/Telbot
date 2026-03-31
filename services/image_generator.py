import os
import requests
import random
import time
import base64
from typing import List, Optional, Dict, Any
from config import POLLINATIONS_URL, POLLINATIONS_API_KEY, TEMP_DIR, BYTEZ_API_KEY, BYTEZ_MODEL


class ImageGenerator:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        self.image_dir = os.path.join(self.job_dir, "images")

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
        Generates a single image using Pollinations with fallback to Bytez.
        """
        clean_prompt = self._clean_prompt(prompt)
        filepath = os.path.join(self.image_dir, f"scene_{index:03d}.jpg")

        # 1. TRY POLLINATIONS (Primary - Free and Fast)
        print(f"🖼️ [Scene {index}] Attempting Pollinations AI...")
        
        # Format URL for requests params handling
        base_url = POLLINATIONS_URL.format(prompt=requests.utils.quote(clean_prompt))
        
        headers = {}
        if POLLINATIONS_API_KEY:
            headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"

        for attempt in range(1, retry + 1):
            try:
                params = {
                    "model": "flux",
                    "width": 1080,
                    "height": 1920,
                    "seed": random.randint(0, 1000000),
                    "nologo": "true"
                }
                
                response = requests.get(base_url, params=params, headers=headers, timeout=45)
                
                if response.status_code == 200 and len(response.content) > 5000:
                    with open(filepath, "wb") as f:
                        f.write(response.content)
                    print(f"✅ [Scene {index}] Pollinations success!")
                    return filepath
                else:
                    print(f"⚠️ [Scene {index}] Pollinations attempt {attempt} returned status {response.status_code} or small file.")
            except Exception as e:
                print(f"⚠️ [Scene {index}] Pollinations attempt {attempt} failed: {e}")
                time.sleep(1)

        # 2. FALLBACK TO BYTEZ (Secondary)
        if BYTEZ_API_KEY:
            print(f"🖼️ [Scene {index}] Falling back to Bytez SDK...")
            try:
                from bytez import Bytez
                
                # Initialize SDK
                sdk = Bytez(BYTEZ_API_KEY)
                # Load the specified model
                model = sdk.model(BYTEZ_MODEL)
                
                # Run with input prompt
                # Note: The SDK returns a results object with .error and .output
                results = model.run(clean_prompt)
                
                if results.error:
                    raise Exception(f"Bytez SDK Error: {results.error}")
                
                output = results.output
                if output:
                    # Handle possible output formats (URL or Base64)
                    if isinstance(output, str):
                        if output.startswith("http"):
                            img_res = requests.get(output, timeout=30)
                            img_data = img_res.content
                        elif "," in output: # Base64 URI
                            img_data = base64.b64decode(output.split(",")[1])
                        else: # Raw base64
                            img_data = base64.b64decode(output)
                    else:
                        # Sometimes SDKs return bytes directly
                        img_data = output
                        
                    with open(filepath, "wb") as f:
                        f.write(img_data)
                    print(f"✅ [Scene {index}] Bytez SDK success!")
                    return filepath
            except Exception as e:
                print(f"❌ [Scene {index}] Bytez SDK fallback failed: {e}")

        print(f"🚫 [Scene {index}] Image generation completely failed.")
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
