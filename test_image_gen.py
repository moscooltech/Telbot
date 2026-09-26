import os
import shutil
from config import TEMP_DIR
from services.image_generator import ImageGenerator

def test_image_generation():
    print("🎨 Testing image generation fallback chain (keyless Pollinations legacy first)...")

    test_job_id = "test_image_gen"
    test_dir = os.path.join(TEMP_DIR, test_job_id)
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir, exist_ok=True)

    ig = ImageGenerator(test_job_id, style_bible="cinematic, ultra-detailed, highly atmospheric")
    print(f"🔗 Provider chain: {[name for name, _, _ in ig._provider_chain()]}")

    results = []
    prompts = [
        "A futuristic cyberpunk city with neon lights and flying cars",
        "A golden retriever puppy playing in autumn leaves",
    ]
    for i, prompt in enumerate(prompts):
        filepath = ig.generate_image(prompt, i)
        if filepath and os.path.exists(filepath):
            size = os.path.getsize(filepath)
            magic_ok = open(filepath, "rb").read(3) == b"\xff\xd8\xff"
            print(f"✅ Scene {i}: {size/1024:.1f} KB | JPEG magic: {magic_ok} | {filepath}")
            results.append(magic_ok and size > 3000)
        else:
            print(f"❌ Scene {i}: generation failed")
            results.append(False)

    shutil.rmtree(test_dir, ignore_errors=True)
    return all(results)

if __name__ == "__main__":
    ok = test_image_generation()
    print("🚀 Image generation CONFIRMED working." if ok else "❌ Image generation FAILED.")
    raise SystemExit(0 if ok else 1)
