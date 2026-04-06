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
           - A 'scene' description: A hyper-detailed visual prompt for an image generator (lighting, camera, textures). An infographic would be a good idea for any scenes that is gor explanation of something. 
           - A 'narration' script: A 15-20 word spoken script that perfectly matches the visual. the narration should be good for a video sn not just some useless words.
        
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
                
                # HYPER-ROBUST JSON EXTRACTION
                # 1. Try to find the first '{' and last '}'
                try:
                    start_idx = content.find('{')
                    end_idx = content.rfind('}') + 1
                    if start_idx != -1 and end_idx != -1:
                        json_str = content[start_idx:end_idx]
                        data = json.loads(json_str)
                    else:
                        raise ValueError("No JSON braces found")
                except:
                    # 2. Fallback to regex-like split if braces fail
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0].strip()
                    data = json.loads(content)

                scenes = data.get("scenes", [])
                narrations = data.get("narrations", [])
                
                # Sync check: ensure we have equal counts
                count = min(len(scenes), len(narrations))
                
                # AGENTIC QUALITY CHECK: 
                # If the AI just echoed the prompt back for all scenes, treat it as a failure
                if count > 0 and all(s.strip().lower() == prompt.strip().lower() for s in narrations):
                    raise Exception("AI echoed the prompt instead of writing a script.")

                if count < MIN_SCENES:
                    raise Exception(f"AI returned too few scenes: {count}")
                
                metadata = {
                    "caption": data.get("caption", f"The Story of {prompt[:20]}"),
                    "hashtags": " ".join(data.get("hashtags", ["#ai", "#learning", "#viral"]))
                }
                
                print(f"✅ AI Director planned {count} unique scenes.")
                return scenes[:count], narrations[:count], metadata
                
            except Exception as e:
                print(f"❌ SceneGenerator failed (Attempt {attempt+1}): {e}")
                if attempt < retry - 1:
                    time.sleep(2)
                else:
                    # DYNAMIC FALLBACK: If AI fails, we write a basic story ourselves 
                    # so it's NOT just the prompt repeating.
                    print("⚠️ Using Dynamic Story Fallback Engine")
                    fallback_scenes = [
                        f"Cinematic shot of {prompt}, perspective {i+1}, highly detailed" 
                        for i in range(MIN_SCENES)
                    ]
                    fallback_narrations = [
                        f"Imagine a world where {prompt} takes center stage. This is part {i+1} of our journey into the unknown."
                        for i in range(MIN_SCENES)
                    ]
                    return fallback_scenes, fallback_narrations, {"caption": prompt, "hashtags": "#ai #viral"}
