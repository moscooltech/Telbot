import json
import requests
import time
from config import MIN_SCENES, MAX_SCENES, VIDEO_DURATION_PER_SCENE, RENDER_FREE_TIER
from services.llm_service import LLMService

class SceneGenerator:
    def __init__(self):
        self.llm = LLMService()

    def generate_all(self, prompt, retry=3):
        """
        AI Production Agent: Writes a full professional script and plans explainer visuals.
        """
        system_prompt = f"""
You are a Professional AI Video Producer and Lead Educator.
Your task: Convert the user's prompt into a high-quality educational/viral video script.

Requirements:
- Write a UNIQUE narration script for EACH of the {MIN_SCENES} to {MAX_SCENES} scenes
- Each narration must be DIFFERENT from the others - never repeat the same phrasing
- NEVER include "scene 1", "scene 2", "step 1", "step 2" or any scene/step numbers in the narration text
- The narration should be pure content/educational text only - no scene references
- Scene 1: Introduce the topic with a hook
- Scene 2-7: Expand with different explanations and examples  
- Scene 8: Conclude with a call to action
- Each spoken_script should be 20-30 words, written as natural spoken text

For visuals, use:
- "visual_prompt": Describe what appears on screen (infographics, diagrams, text overlays)

Output format: JSON ONLY with unique narrations for each scene.
{{
  "scenes": [
    {{
      "spoken_script": "Pure narration content - NO scene/step numbers",
      "visual_prompt": "Visual description for scene 1"
    }},
    {{
      "spoken_script": "Different narration content - NO scene/step numbers",
      "visual_prompt": "Visual description for scene 2"
    }},
    ...
  ],
  "caption": "Viral hook",
  "hashtags": ["tag1", "tag2"]
}}
"""
        
        for attempt in range(retry):
            try:
                content = self.llm.generate_text(
                    system_prompt=system_prompt,
                    user_prompt=f"Topic: {prompt}",
                    timeout=60
                )
                
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
                
                # UNIQUENESS CHECK: Ensure each narration is different
                unique_narrations = set(n.lower().strip() for n in narrations if n)
                if len(unique_narrations) < len(narrations) * 0.7:  # At least 70% should be unique
                    raise Exception("AI Director returned repetitive narrations. Retrying...")

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
                    # Fail gracefully instead of generating fake content
                    raise Exception(f"AI Director failed after {retry} attempts: {e}")
