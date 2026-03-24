import json
import requests
import time
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

class SceneGenerator:
    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        self.model = "google/gemini-2.0-flash-lite-preview-02-05:free" # Fast and free

    def generate_all(self, prompt):
        """
        Generates both scenes and viral metadata in a single API call.
        Returns a tuple: (scenes, metadata)
        """
        print(f"🧠 Prompting AI for scenes and metadata: \"{prompt[:30]}...\"")
        
        system_prompt = """
        You are an AI video screenwriter and social media expert.
        Convert the user story into 8-10 cinematic scenes for a TikTok video.
        Also generate a viral caption and relevant hashtags.
        
        Output format: JSON ONLY with these keys:
        - "scenes": List of 8-10 visual scene descriptions (1-2 sentences each).
        - "caption": Catchy TikTok hook (max 20 words).
        - "hashtags": List of 8-12 viral hashtags (include #naijatiktok, #viral).
        
        Ensure "scenes" descriptions are highly detailed for an image generator.
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
        
        try:
            start_time = time.time()
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=45
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            
            data = json.loads(content)
            scenes = data.get("scenes", [])
            metadata = {
                "caption": data.get("caption", "Amazing story!"),
                "hashtags": " ".join(data.get("hashtags", ["#fyp", "#viral"]))
            }
            
            print(f"✅ AI generated {len(scenes)} scenes in {time.time() - start_time:.2f}s")
            return scenes, metadata
            
        except Exception as e:
            print(f"❌ Error in SceneGenerator: {e}")
            # Fallback
            return [prompt], {"caption": prompt[:20], "hashtags": "#viral #fyp"}
