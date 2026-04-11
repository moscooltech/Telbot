import json
import re
import requests
import time
from config import MIN_SCENES, MAX_SCENES, VIDEO_DURATION_PER_SCENE, RENDER_FREE_TIER
from services.llm_service import LLMService


def detect_scene_count(prompt):
    """
    Parse user prompt to detect desired scene count.
    Returns: (min_scenes, max_scenes) tuple or None if not specified.
    """
    lower = prompt.lower()
    
    patterns = [
        r'(\d+)\s*(?:scene|clip|image|picture|visual)s?',
        r'(\d+)\s*(?:image|picture|visual)',
        r'(?:use|create|make|generate)\s*(\d+)',
        r'(\d+)\s*(?:long|short)\s*(?:audio|video)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            count = int(match.group(1))
            if 1 <= count <= MAX_SCENES:
                return (max(1, count - 1), min(count + 1, MAX_SCENES))
    
    if 'long audio' in lower or 'single image' in lower or 'one image' in lower:
        return (1, 3)
    elif 'short' in lower or 'quick' in lower:
        return (2, 4)
    
    return None


def clean_narration(text):
    """Clean and fix common punctuation issues in generated text."""
    if not text:
        return text
    
    # Fix "e a c h" -> "each" - only join single letters (1 char) that appear consecutively
    # This catches the main issue without incorrectly joining "us"+"in" = "usin"
    words = text.split()
    cleaned = []
    i = 0
    while i < len(words):
        # Only check single-character words
        if len(words[i]) == 1 and words[i].isalpha():
            # Look ahead for more single letters
            sequence = [words[i]]
            j = i + 1
            while j < len(words) and len(words[j]) == 1 and words[j].isalpha():
                sequence.append(words[j])
                j += 1
            
            # If 2+ single letters in a row, join them
            if len(sequence) >= 2:
                joined = ''.join(sequence)
                cleaned.append(joined)
                i = j
                continue
        
        cleaned.append(words[i])
        i += 1
    
    text = ' '.join(cleaned)
    
    # Fix spacing around punctuation
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*,\s*', ', ', text)
    text = re.sub(r'\s*\.\s*', '. ', text)
    text = re.sub(r'\.([A-Z])', r'. \1', text)
    
    return text.strip()
    
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
        detected = detect_scene_count(prompt)
        if detected:
            min_s, max_s = detected
        else:
            min_s, max_s = MIN_SCENES, MAX_SCENES
        
        system_prompt = f"""
You are a Professional AI Video Producer. Your task: Convert the user's prompt into a high-quality educational/viral video script.

Requirements:
- Write a UNIQUE narration for EACH of the {min_s} to {max_s} scenes.
- Each scene must follow a strict "Narration" and "Description" format.
- "narration": What is spoken. Must be 20-30 words of natural, engaging text with proper grammar and punctuation.
- "description": What is shown visually. Detailed scene description for an image generator.
- NEVER include "scene 1", "scene 2", "step 1", or any numbering in the narration.
- Use proper punctuation: periods, commas, and capital letters after periods.
- Scene 1: Strong hook.
- Last scene: Call to action.

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
        
        print(f"=== Scene count: {min_s}-{max_s} (detected: {detected is not None})")
        
        for attempt in range(retry):
            try:
                content = self.llm.generate_text(
                    system_prompt=system_prompt,
                    user_prompt=f"Topic: {prompt}",
                    timeout=60
                )
                
                # Debug: print raw LLM response
                print(f"=== RAW LLM RESPONSE ===\n{content[:500]}...\n=== END ===")
                
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
                min_required = min_s if detected else MIN_SCENES
                if len(raw_scenes) < min_required:
                    raise Exception(f"AI script too short: got {len(raw_scenes)}, expected {min_required}")

                # Debug: print raw narration before cleaning
                if raw_scenes:
                    raw_narr = raw_scenes[0].get("narration", "")
                    print(f"=== RAW NARRATION (before clean): '{raw_narr}' ===")

                # Map the new keys: narration and description
                visuals = [s.get("description", s.get("visual_prompt", "")) for s in raw_scenes]
                narrations = [clean_narration(s.get("narration", s.get("spoken_script", ""))) for s in raw_scenes]

                # Debug: print cleaned narrations
                print(f"=== CLEANED NARRATION: '{narrations[0]}' ===")
                
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
