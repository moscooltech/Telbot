import json
import requests
import time
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

class SceneGenerator:
    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        self.model = "google/gemini-2.0-flash-lite-preview-02-05:free" # Strongest free model as of now

    def generate_scenes(self, prompt):
        """
        Converts a user prompt into 8-12 cinematic scenes.
        Returns a list of scene descriptions.
        """
        system_prompt = """
        You are a screenwriter. Your task is to turn a user story into 8-10 cinematic scenes for a 60-second video.
        Each scene description MUST:
        - Be visually descriptive and detailed for an image generator.
        - Be 1-2 sentences max.
        - Maintain visual continuity.
        - Be in English.
        - Format the output as a JSON array of strings only.
        
        Example Output:
        ["A lone wolf howling at the silver moon on a snowy mountain peak.", "The wolf runs through a dark, frozen pine forest."]
        """
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://telbot.local", # Required by OpenRouter
            "X-Title": "Video Generator Bot"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User Prompt: {prompt}"}
            ]
        }
        
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            
            # Extract JSON array if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "[" in content:
                content = content[content.find("["):content.rfind("]")+1]
            
            scenes = json.loads(content)
            return scenes
        except Exception as e:
            print(f"Error generating scenes: {e}")
            # Fallback simple scene generation if needed
            return [prompt] # Basic fallback

    def generate_viral_metadata(self, prompt, scenes_summary):
        """Generates viral caption and hashtags."""
        system_prompt = """
        Generate a viral TikTok-style caption and hashtags for a video about: {prompt}
        Caption: Max 20 words, hook-based, emojis.
        Hashtags: 8-12 tags including #fyp, #viral, #naijatiktok, #lagoslife.
        Output format: JSON with "caption" and "hashtags" keys.
        """
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt.format(prompt=prompt)},
                {"role": "user", "content": f"Scenes Summary: {scenes_summary}"}
            ]
        }
        
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=20
            )
            content = response.json()['choices'][0]['message']['content']
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            return json.loads(content)
        except:
            return {
                "caption": f"Watch this amazing story! {prompt[:20]}...",
                "hashtags": "#fyp #viral #naijatiktok #lagoslife #storytelling"
            }
