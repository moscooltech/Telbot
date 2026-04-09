import json
import re
import requests
import time
from config import MIN_SCENES, MAX_SCENES, VIDEO_DURATION_PER_SCENE, RENDER_FREE_TIER
from services.llm_service import LLMService

def clean_narration(text):
    """Clean and fix common punctuation issues in generated text."""
    if not text:
        return text
    
    print(f"CLEAN_NARRATION INPUT: '{text}'")
    
    # Fix "e a c h" -> "each" - when single letters appear consecutively as separate words
    words = text.split()
    cleaned = []
    i = 0
    while i < len(words):
        # Check if we have 2+ consecutive single-letter words
        if i + 1 < len(words) and len(words[i]) == 1 and words[i].isalpha():
            sequence = [words[i]]
            j = i + 1
            while j < len(words) and len(words[j]) == 1 and words[j].isalpha():
                sequence.append(words[j])
                j += 1
            
            # If we found 2+ single letters in a row, join them
            if len(sequence) >= 2:
                joined = ''.join(sequence)
                print(f"JOINED sequence: '{sequence}' -> '{joined}'")
                cleaned.append(joined)
                i = j
                continue
        
        cleaned.append(words[i])
        i += 1
    
    text = ' '.join(cleaned)
    print(f"CLEAN_NARRATION OUTPUT: '{text}'")
    
    # Fix missing spaces between words (e.g., "andgood" -> "and good")
    connectors = ['and', 'or', 'the', 'a', 'an', 'is', 'are', 'was', 'were', 'to', 'of', 'in', 'on', 'at', 'by', 'for', 'with', 'from', 'that', 'this', 'it', 'as', 'be', 'have', 'has', 'had', 'but', 'not', 'you', 'we', 'they', 'can', 'will', 'do', 'does', 'did']
    for word in connectors:
        text = re.sub(rf'{word}([a-z])', f'{word} \\1', text, flags=re.IGNORECASE)
        text = re.sub(rf'([a-z]){word}', f'\\1 {word}', text, flags=re.IGNORECASE)
    
    # Fix spacing around punctuation
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*,\s*', ', ', text)
    text = re.sub(r'\s*\.\s*', '. ', text)
    text = re.sub(r'\.([A-Z])', r'. \1', text)
    
    return text.strip()

class SceneGenerator:
    def __init__(self):
        self.llm = LLMService()

    def generate_all(self, prompt, retry=3):
        """
        AI Production Agent: Writes a full professional script and plans explainer visuals.
        """
        system_prompt = f"""
You are a Professional AI Video Producer. Your task: Convert the user's prompt into a high-quality educational/viral video script.

Requirements:
- Write a UNIQUE narration for EACH of the {MIN_SCENES} to {MAX_SCENES} scenes.
- Each scene must follow a strict "Narration" and "Description" format.
- "narration": What is spoken. Must be 20-30 words of natural, engaging text with proper grammar and punctuation.
- "description": What is shown visually. Detailed scene description for an image generator.
- NEVER include "scene 1", "scene 2", "step 1", or any numbering in the narration.
- Use proper punctuation: periods, commas, and capital letters after periods.
- Scene 1: Strong hook.
- Scene 2-7: Educational/story content.
- Scene 8: Call to action.

Output JSON ONLY:
{{
  "scenes": [
    {{
      "narration": "...",
      "description": "..."
    }}
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
                    json_str = content[start_idx:end_idx]
                    data = json.loads(json_str)
                except Exception as e:
                    print(f"JSON extraction failed: {e}")
                    if "```json" in content:
                        data = json.loads(content.split("```json")[1].split("```")[0])
                    else:
                        data = json.loads(content)

                raw_scenes = data.get("scenes", [])
                if len(raw_scenes) < MIN_SCENES:
                    raise Exception("AI script too short")

                # Debug: print raw narrations before cleaning
                print(f"DEBUG raw narrations: {raw_scenes[0].get('narration', '')}")

                # Map the new keys: narration and description
                visuals = [s.get("description", s.get("visual_prompt", "")) for s in raw_scenes]
                narrations = [clean_narration(s.get("narration", s.get("spoken_script", ""))) for s in raw_scenes]

                # Debug: print cleaned narrations
                print(f"DEBUG cleaned narrations: {narrations[0]}")
                
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
