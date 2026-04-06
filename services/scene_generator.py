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
        AI Production Agent: Writes a full professional script and plans explainer visuals.
        """
        if not self.api_key:
            return [prompt]*MIN_SCENES, [prompt]*MIN_SCENES, {"caption": "No Key", "hashtags": "#error"}

        system_prompt = f"""
        You are a Professional AI Video Producer and Lead Educator.
        Your task: Convert the user's prompt into a high-quality educational/viral video script.
        
        Step 1: Write a deep, narrative script (NOT a summary).
        Step 2: Divide it into {MIN_SCENES} to {MAX_SCENES} logical scenes.
        Step 3: For each scene, provide:
           - "spoken_script": A 20-30 word professional narration.
           - "visual_prompt": A visual description. IMPORTANT: For technical topics, use Infographics, 3D Diagrams, Textual Overlays, or Explainer Visuals. 
             Example: "An infographic showing a decision tree growing into a forest, high quality digital art, labels: RandomForest."
        
        Output format: JSON ONLY.
        {{
          "scenes": [
            {{
              "spoken_script": "The actual words to be said",
              "visual_prompt": "Hyper-detailed visual description"
            }},
            ...
          ],
          "caption": "Viral hook",
          "hashtags": ["tag1", "tag2"]
        }}
        """
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Title": "Video Explainer Agent"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Topic: {prompt}"}
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
                
                # Hyper-robust JSON extraction
                try:
                    start_idx = content.find('{')
                    end_idx = content.rfind('}') + 1
                    data = json.loads(content[start_idx:end_idx])
                except:
                    if "```json" in content:
                        data = json.loads(content.split("```json")[1].split("```")[0])
                    else:
                        data = json.loads(content)

                raw_scenes = data.get("scenes", [])
                if len(raw_scenes) < MIN_SCENES:
                    raise Exception("AI script too short")

                visuals = [s.get("visual_prompt", "") for s in raw_scenes]
                narrations = [s.get("spoken_script", "") for s in raw_scenes]
                
                # LAZY RESPONSE CHECK: If narration is just the prompt repeated, fail and retry
                if any(prompt.strip().lower() in n.strip().lower() and len(n) < len(prompt) + 10 for n in narrations):
                    raise Exception("AI Director was lazy and echoed the prompt. Retrying...")

                metadata = {
                    "caption": data.get("caption", prompt[:30]),
                    "hashtags": " ".join(data.get("hashtags", ["#ai", "#education"]))
                }
                
                print(f"✅ AI Director planned {len(visuals)} professional scenes.")
                return visuals, narrations, metadata
                
            except Exception as e:
                print(f"❌ Script Agent Attempt {attempt+1} failed: {e}")
                if attempt < retry - 1:
                    time.sleep(3)
                else:
                    # Dynamic Technical Fallback (ensures it's never just the prompt)
                    fallback_visuals = [f"Educational infographic about {prompt}, phase {i+1}" for i in range(MIN_SCENES)]
                    fallback_narrations = [f"This step explains {prompt}. We analyze the core components to understand the system architecture in detail." for i in range(MIN_SCENES)]
                    return fallback_visuals, fallback_narrations, {"caption": prompt, "hashtags": "#learning"}
