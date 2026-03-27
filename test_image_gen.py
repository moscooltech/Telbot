import os
import requests
from config import POLLINATIONS_URL, TEMP_DIR
import random

def test_image_generation():
    print("🎨 Testing Image Generation via Pollinations AI...")
    
    # Create test directory
    test_job_id = "test_image_gen"
    test_dir = os.path.join(TEMP_DIR, test_job_id)
    os.makedirs(test_dir, exist_ok=True)
    
    # Test prompt
    prompt = "A futuristic cyberpunk city with neon lights and flying cars, high resolution, 8k"
    enhanced_prompt = f"Cinematic, ultra-detailed, highly atmospheric: {prompt}"
    seed = random.randint(0, 1000000)
    
    # Construct URL
    url = POLLINATIONS_URL.format(prompt=requests.utils.quote(enhanced_prompt), seed=seed)
    print(f"🔗 Request URL: {url}")
    
    filepath = os.path.join(test_dir, "test_scene.jpg")
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        with open(filepath, "wb") as f:
            f.write(response.content)
            
        file_size = os.path.getsize(filepath)
        print(f"✅ Image generated successfully!")
        print(f"📂 Saved to: {filepath}")
        print(f"📊 File size: {file_size / 1024:.2f} KB")
        
        if file_size > 0:
            print("🚀 Image generation is CONFIRMED working.")
            return True
        else:
            print("❌ Image file is empty.")
            return False
            
    except Exception as e:
        print(f"❌ Image generation failed: {e}")
        return False

if __name__ == "__main__":
    test_image_generation()
