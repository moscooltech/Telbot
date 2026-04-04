import json
import requests
import time
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, NUM_SCENES, VIDEO_DURATION_PER_SCENE, RENDER_FREE_TIER

class SceneGenerator:
    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        # Use the model from config, fallback to gemini-flash if not set
        self.model = OPENROUTER_MODEL if OPENROUTER_MODEL else "google/gemini-2.0-flash-lite-preview-02-05:free"

    def generate_all(self, prompt, retry=3):
        """
        Generates both scenes and viral metadata in a single API call.
        Returns a tuple: (scenes, narrations, metadata)
        """
        if not self.api_key:
            print("⚠️ WARNING: OPENROUTER_API_KEY is missing!")
            return [prompt], [prompt], {"caption": "Error: No API Key", "hashtags": "#error"}

        print(f"🧠 Prompting AI ({self.model}) for scenes: \"{prompt[:30]}...\"")

        
        # Adjust scene target based on Render Free Tier constraints
        target_scenes = NUM_SCENES if RENDER_FREE_TIER else 15
        
        system_prompt = f"""
        You are an AI Video Director and Lead Screenwriter.
        Your task is to analyze the user's prompt and convert it into a short, impactful viral video.
        
        Constraint: Generate EXACTLY {target_scenes} scenes.
        Total target duration: {target_scenes * VIDEO_DURATION_PER_SCENE} seconds.
        
        Guidelines:
        1. Distill the story into {target_scenes} cinematic scenes.
        2. Each "narration" must be roughly {VIDEO_DURATION_PER_SCENE} seconds long when spoken (approx 15-20 words).
        3. Each "scene" must be a highly detailed visual prompt for an image generator.
        
        Output format: JSON ONLY with these keys:
        - "scenes": List of visual scene descriptions (exactly {target_scenes}).
        - "narrations": List of narration scripts (exactly {target_scenes}).
        - "caption": A viral social media caption.
        - "hashtags": A list of viral hashtags.
        """
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://telbot.local",
            "X-Title": "Video Generator Bot"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User Prompt: {prompt}"}
            ],
            "response_format": { "type": "json_object" } # Request JSON specifically
        }
        
        for attempt in range(retry):
            try:
                start_time = time.time()
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                content = response.json()['choices'][0]['message']['content']
                
                data = json.loads(content)
                scenes = data.get("scenes", [])
                narrations = data.get("narrations", scenes) # Fallback to scenes if narrations not present
                metadata = {
                    "caption": data.get("caption", "Amazing story!"),
                    "hashtags": " ".join(data.get("hashtags", ["#fyp", "#viral"]))
                }
                
                print(f"✅ AI generated {len(scenes)} scenes in {time.time() - start_time:.2f}s")
                return scenes, narrations, metadata
                
            except Exception as e:
                print(f"❌ Error in SceneGenerator attempt {attempt+1}: {e}")
                if attempt < retry - 1:
                    time.sleep(2 * (attempt + 1))
                else:
                    # Fallback on final failure
                    return [prompt], [prompt], {"caption": prompt[:20], "hashtags": "#viral #fyp"}
