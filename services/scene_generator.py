import json
import requests
import time
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, MIN_SCENES, MAX_SCENES, VIDEO_DURATION_PER_SCENE, RENDER_FREE_TIER

class SceneGenerator:
    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        self.model = OPENROUTER_MODEL if OPENROUTER_MODEL else "google/gemini-2.0-flash-lite-preview-02-05:free"

    def generate_all(self, prompt, retry=3):
        """
        AI Production Agent: Analyzes prompt and generates a full storyboard script.
        """
        if not self.api_key:
            return [prompt]*MIN_SCENES, [prompt]*MIN_SCENES, {"caption": "No API Key", "hashtags": "#error"}

        system_prompt = f"""
        You are an AI Video Production Agent and Master Director.
        Your goal is to transform the user's idea into a professional, highly detailed multi-scene video script.
        
        Step 1: Analyze the depth of the story.
        Step 2: Decide on the optimal number of scenes between {MIN_SCENES} and {MAX_SCENES}.
        Step 3: For each scene, create:
           - A 'scene' description: A hyper-detailed visual prompt for an image generator (lighting, camera, textures).
           - A 'narration' script: A 15-20 word spoken script that perfectly matches the visual.
        
        Style Detection: If the user provides a style like [Anime] or [Cinematic], apply it strictly.
        
        Output format: JSON ONLY.
        {{
          "total_scenes": number,
          "scenes": ["visual prompt 1", "visual prompt 2", ...],
          "narrations": ["narration script 1", "narration script 2", ...],
          "caption": "Viral hook",
          "hashtags": ["tag1", "tag2"]
        }}
        """
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "Video Agent Bot"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User Story/Idea: {prompt}"}
            ]
        }
        
        for attempt in range(retry):
            try:
                response = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                content = response.json()['choices'][0]['message']['content']
                
                # Robust JSON extraction (removes markdown code blocks if AI adds them)
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                data = json.loads(content)
                scenes = data.get("scenes", [])
                narrations = data.get("narrations", [])
                
                # Sync check: ensure we have equal counts
                count = min(len(scenes), len(narrations))
                if count < MIN_SCENES:
                    raise Exception(f"AI returned too few scenes: {count}")
                
                metadata = {
                    "caption": data.get("caption", "Amazing story!"),
                    "hashtags": " ".join(data.get("hashtags", ["#fyp", "#viral"]))
                }
                
                print(f"✅ AI Director planned {count} scenes.")
                return scenes[:count], narrations[:count], metadata
                
            except Exception as e:
                print(f"❌ SceneGenerator failed (Attempt {attempt+1}): {e}")
                if "content" in locals(): print(f"Raw AI Output: {content[:200]}...")
                if attempt < retry - 1:
                    time.sleep(2)
                else:
                    # Robust fallback: use prompt but repeat it to ensure video length isn't 3s
                    fallback_scenes = [f"{prompt}, high quality cinematic scene {i}" for i in range(MIN_SCENES)]
                    fallback_narrations = [f"Scene {i+1}: {prompt[:50]}..." for i in range(MIN_SCENES)]
                    return fallback_scenes, fallback_narrations, {"caption": prompt[:30], "hashtags": "#viral"}
