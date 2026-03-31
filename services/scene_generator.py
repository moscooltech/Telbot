import json
import requests
import time
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

class SceneGenerator:
    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        self.model = "google/gemini-2.0-flash-lite-preview-02-05:free" # Fast and free

    def generate_all(self, prompt, retry=3):
        """
        Generates both scenes and viral metadata in a single API call.
        Returns a tuple: (scenes, metadata)
        """
        print(f"🧠 Prompting AI for scenes and metadata: \"{prompt[:30]}...\"")
        
        system_prompt = """
        You are an AI Video Director and Lead Screenwriter.
        Your task is to analyze the user's prompt and determine the "Perfect Length" for the video.
        
        - If the prompt is simple, aim for ~45-60 seconds (approx 12-15 scenes).
        - If the prompt is deep, epic, or complex, aim for 2+ minutes (approx 25-30 scenes).
        
        Guidelines:
        1. Determine the optimal number of scenes to tell the story effectively without rushing or dragging.
        2. Each "narration" must be descriptive and natural, lasting approx 5-7 seconds when spoken.
        3. Each "scene" must be a highly detailed visual prompt for an image generator.
        
        Output format: JSON ONLY with these keys:
        - "estimated_duration_seconds": Your estimate of the total runtime.
        - "scenes": List of visual scene descriptions.
        - "narrations": List of narration scripts (must match the number of scenes).
        - "caption": A viral social media caption.
        - "hashtags": A list of 10+ viral hashtags.
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
