import os
import requests
import random
import time
from config import POLLINATIONS_URL, TEMP_DIR

class ImageGenerator:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(self.job_dir, exist_ok=True)
        self.image_dir = os.path.join(self.job_dir, "images")
        os.makedirs(self.image_dir, exist_ok=True)

    def generate_image(self, prompt, index, retry=3):
        """
        Generates and saves an image for a specific scene index.
        """
        # Enhance prompt for high detail
        enhanced_prompt = f"Cinematic, ultra-detailed, highly atmospheric: {prompt}"
        seed = random.randint(0, 1000000)
        url = POLLINATIONS_URL.format(prompt=requests.utils.quote(enhanced_prompt), seed=seed)
        
        filepath = os.path.join(self.image_dir, f"scene_{index:03d}.jpg")
        
        for attempt in range(retry):
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                with open(filepath, "wb") as f:
                    f.write(response.content)
                return filepath
            except Exception as e:
                print(f"Error on image attempt {attempt+1} for scene {index}: {e}")
                time.sleep(2)
        
        return None

    def generate_all_images(self, scenes):
        """
        Generates images for all scenes and returns their filepaths.
        """
        image_paths = []
        for i, scene in enumerate(scenes):
            path = self.generate_image(scene, i)
            if path:
                image_paths.append(path)
            else:
                print(f"Failed to generate image for scene {i}")
        return image_paths
