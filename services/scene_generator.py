import json
import re
import time
import logging
from config import (
    MIN_SCENES, MAX_SCENES,
    ENABLE_RELEVANCE_CHECK, RELEVANCE_MIN_SCORE, MAX_SCENE_REWRITES,
    ENABLE_PROMPT_POLISH, MIN_CAPTION_CHARS,
    ENABLE_LLM_IMAGE_MODES, IMAGE_MODES, IMAGE_MODE_DEFAULT,
)
from services.llm_service import LLMService

logger = logging.getLogger(__name__)


def mode_directive_help():
    """Instructions letting the script LLM choose a non-photo render mode.

    Some scenes are simply the wrong image as a photograph - an illustration, a
    design/specification sheet, an exploded (item decomposition) view, a
    technical schematic or a typographic poster. The LLM prefixes such a scene's
    image prompt with ONE inline directive and
    ``ImageGenerator._resolve_mode`` picks it up per scene.

    Returns "" when the feature is disabled, so the prompts degrade to exactly
    the previous text.
    """
    if not ENABLE_LLM_IMAGE_MODES:
        return ""
    modes = ", ".join("/" + m for m in IMAGE_MODES if m != IMAGE_MODE_DEFAULT)
    return (
        "Render modes (use sparingly): if - and only if - a realistic photograph "
        "would be the wrong image for a scene, start that scene's image prompt "
        "with exactly ONE directive so the renderer switches style: " + modes + ". "
        "Pick the single best fit (/illustration drawn art, /design design or "
        "specification sheet, /decompose exploded view or item decomposition, "
        "/diagram technical schematic, /poster graphic poster with typography). "
        "Words and labels ARE wanted in /design, /decompose, /diagram and "
        "/poster prompts, and must stay out of photorealistic ones. "
        "Most scenes need NO directive and stay photorealistic. Never invent a "
        "directive and never use more than one per prompt."
    )


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


def extract_json(content):
    """Hyper-robust JSON extraction from LLM output."""
    try:
        start_idx = content.find('{')
        end_idx = content.rfind('}') + 1
        return json.loads(content[start_idx:end_idx])
    except Exception:
        pass
    if "```json" in content:
        return json.loads(content.split("```json")[1].split("```")[0])
    return json.loads(content)


class SceneGenerator:
    def __init__(self):
        self.llm = LLMService()

    def _generate_spine(self, prompt):
        """Pass 1: story spine that locks every later scene to one core idea."""
        system_prompt = (
            "You are a Creative Director planning a short vertical video.\n"
            "Produce a story spine that keeps every scene locked to one core idea.\n\n"
            "Return JSON ONLY:\n"
            "{\n"
            '  "motive": "one sentence: the core message/purpose of the video",\n'
            '  "style_bible": "one line: the recurring LOOK shared by ALL scenes - art style, color palette, lighting, lens/film character - plus, only if the video follows one person throughout, that person\'s identity (age, build, clothing, hair). Never pin the location, the framing or the camera here: every scene is its own moment, place and shot",\n'
            '  "beats": ["beat 1 summary", "beat 2 summary", "beat 3 summary", "beat 4 summary"],\n'
            '  "hook": "opening hook concept",\n'
            '  "cta": "closing call-to-action concept"\n'
            "}\n"
            "Total under 150 words."
        )
        try:
            content = self.llm.generate_text(
                system_prompt, f"Topic: {prompt}", temperature=0.8, timeout=60, json_mode=True
            )
            data = extract_json(content)
            return {
                "motive": data.get("motive") or prompt,
                "style_bible": data.get("style_bible") or "",
                "beats": data.get("beats") or [],
                "hook": data.get("hook") or "",
                "cta": data.get("cta") or "",
            }
        except Exception as e:
            logger.warning("Spine generation failed (%s); falling back to raw prompt as motive.", e)
            return {"motive": prompt, "style_bible": "", "beats": [], "hook": "", "cta": ""}

    @staticmethod
    def _build_long_caption(caption, spine, topic):
        """Grow a too-short LLM caption to at least MIN_CAPTION_CHARS by layering in
        the story spine: hook, CTA, motive and the topic sentence. Deterministic —
        no extra LLM call, so the caption never blocks the pipeline."""
        caption = (caption or "").strip()
        hook = (spine.get("hook") or "").strip()
        cta = (spine.get("cta") or "").strip()
        motive = (spine.get("motive") or "").strip()
        topic = (topic or "").strip()

        # Layered filler: richest first. None may duplicate what's already there.
        candidates = [hook, cta, motive, topic]
        for extra in candidates:
            if len(caption) >= MIN_CAPTION_CHARS:
                break
            if extra and extra.lower() not in caption.lower():
                caption = f"{caption}\n\n{extra}" if caption else extra

        # Still short (weak spine)? Append descriptive boilerplate tied to the topic.
        if len(caption) < MIN_CAPTION_CHARS:
            filler = (
                f"Watch until the end to see the full story of {topic[:80]}. "
                "Every part of this video — the script, the images, the narration and "
                "the final edit — was created end to end by an AI pipeline. "
                "Follow for more stories like this one."
            )
            if filler.lower() not in caption.lower():
                caption = f"{caption}\n\n{filler}" if caption else filler

        return caption.strip()

    def _generate_scenes(self, prompt, spine, min_s, max_s):
        """Pass 2: full script where every scene is derived from the spine."""
        beats = "; ".join(f"{i + 1}. {b}" for i, b in enumerate(spine["beats"])) or "n/a"
        mode_help = mode_directive_help()
        mode_rule = ("- " + mode_help + "\n") if mode_help else ""
        system_prompt = (
            "You are a Professional AI Video Producer. Write the full script using the story spine below.\n\n"
            "STORY SPINE\n"
            f"Motive: {spine['motive']}\n"
            f"Visual style bible (every scene keeps this look): {spine['style_bible'] or 'invent one consistent style'}\n"
            f"Beat structure: {beats}\n"
            f"Opening hook: {spine['hook']}\n"
            f"Closing call to action: {spine['cta']}\n\n"
            "Requirements:\n"
            f"- Write a UNIQUE narration for EACH of the {min_s} to {max_s} scenes.\n"
            "- Each scene is a NEW moment: move the action forward, and change the location and the camera angle from the previous scene. Never re-describe the picture you just used.\n"
            "- Every scene MUST clearly serve the motive above. Never drift off-topic.\n"
            "- Follow the beat structure: scene 1 is the hook, the last scene is the call to action.\n"
            '- "narration": 20-30 words of natural spoken text, proper grammar/punctuation, no "scene N"/"step N" numbering.\n'
            '- "description": a vivid image-generation prompt for THIS scene\'s own moment. Keep the style bible\'s look, but its subject, place and shot must differ from every other scene; repeat the same character description only while the narration is really about that character.\n'
            + mode_rule
            + '- "caption": a complete, natural social-media post caption for the finished video: '
            f'AT LEAST 200 characters (aim for 250-400) and 3-5 sentences, describing what the video '
            "shows, one surprising detail, and why it is worth watching. NEVER write placeholders "
            "like 'viral hook', 'viral reel' or 'amazing video'.\n\n"
            "Output JSON ONLY:\n"
            '{"scenes": [{"narration": "...", "description": "..."}], "caption": "3-5 sentence post caption of at least 200 characters", "hashtags": ["tag1", "tag2"]}'
        )
        content = self.llm.generate_text(
            system_prompt, f"Topic: {prompt}", temperature=0.7, timeout=90, json_mode=True
        )
        return extract_json(content)

    def _score_scenes(self, motive, scenes):
        """Cheap reviewer pass: score each scene 1-10 against the motive."""
        numbered = "\n".join(
            f"{i + 1}. narration: {s.get('narration', '')} | visual: {s.get('description', '')}"
            for i, s in enumerate(scenes)
        )
        system_prompt = (
            "You are a strict content reviewer. Score how well each scene serves the video's motive.\n"
            "Use integers from 1 (irrelevant) to 10 (perfectly on-topic).\n\n"
            f"Motive: {motive}\n\n"
            "Scenes:\n"
            f"{numbered}\n\n"
            'Output JSON ONLY: {"scores": [10, 9, 8]} — one integer per scene, same order.'
        )
        content = self.llm.generate_text(
            system_prompt, "Score the scenes.", temperature=0.1, timeout=60, json_mode=True
        )
        data = extract_json(content)
        scores = data.get("scores", [])
        return scores if isinstance(scores, list) else []

    def _rewrite_scene(self, motive, spine, scenes, idx):
        """Rewrite one weak scene with neighboring context so it stays coherent."""
        neighbors = []
        for j in (idx - 1, idx + 1):
            if 0 <= j < len(scenes):
                neighbors.append(f"Scene {j + 1}: {scenes[j].get('narration', '')}")
        neighbors_text = "\n".join(neighbors) or "(none)"
        system_prompt = (
            "You are a Professional AI Video Producer. Rewrite ONE weak scene so it clearly serves the motive\n"
            "and flows naturally from its neighboring scenes.\n\n"
            f"Motive: {motive}\n"
            f"Visual style bible: {spine['style_bible']}\n"
            f"Neighboring scenes:\n{neighbors_text}\n\n"
            "Weak scene to rewrite:\n"
            f"narration: {scenes[idx].get('narration', '')}\n"
            f"description: {scenes[idx].get('description', '')}\n\n"
            "Requirements: 20-30 words narration, no numbering, and a description that keeps the style bible's look while showing a DIFFERENT moment, place and camera shot from the neighbouring scenes.\n"
            'Output JSON ONLY: {"narration": "...", "description": "..."}'
        )
        content = self.llm.generate_text(
            system_prompt, "Rewrite the scene.", temperature=0.6, timeout=60, json_mode=True
        )
        return extract_json(content)

    def _polish_visuals(self, spine, scenes):
        """
        Prompt-engineering pass: rewrite every scene description into a
        structured image prompt (subject -> action -> setting -> shot ->
        lighting -> style), locked to the style bible so all images
        look like one coherent video - while still giving each scene its own
        moment, place and camera shot, so the video never becomes one frame
        re-rendered. The LLM may also attach ONE render-mode
        directive to the scenes that are not meant to be photographs.
        """
        mode_help = mode_directive_help()
        mode_rule = ("8. " + mode_help + "\n") if mode_help else ""
        system_prompt = (
            "You are an expert prompt engineer for text-to-image models (Flux, SDXL).\n"
            "For each numbered scene description below, rewrite it into ONE polished image prompt.\n\n"
            f"Style bible (keep this look in EVERY prompt): {spine['style_bible'] or 'invent one consistent style and reuse it'}\n"
            "Motive (what the video is about): " + spine["motive"] + "\n\n"
            "Rules for each prompt:\n"
            "1. One line, comma-separated layers in this order: main subject with concrete details, action/pose, setting/environment, camera shot (e.g. close-up, wide establishing shot, low angle), lighting, art style/mood.\n"
            "2. Every prompt is a DIFFERENT moment of the story: change the place, the action and the camera shot between scenes. Describe the same character identically ONLY while that character is really in the scene, and never repeat the previous prompt's framing or composition.\n"
            "3. Vary the shot list on purpose: across the whole set use a mix of wide establishing shots, medium shots and close-ups, and give consecutive scenes different angles (low, high, over-the-shoulder, detail insert).\n"
            "4. Depict what THIS scene's narration is actually talking about - its objects, action and setting - so the picture presents the spoken line. Never draw the words themselves.\n"
            "5. Visual, concrete language only: no abstract ideas, no narration text, no 'scene N'. Keep words and labels out of photorealistic prompts - they render as garbage.\n"
            "6. 25-45 words. No quotes. No trailing period.\n"
            "7. Every prompt must VISUALIZE the topic, not just show a generic person: include the concrete objects, machinery, data displays or environments the scene is actually about (e.g. for an electricity bill topic: smart meter, AC unit, glowing watt meter, utility bill, power lines, wiring, appliance energy use). A person may appear only while interacting with those objects.\n"
            + mode_rule
            + "\n"
            "Scenes (numbered; the narration is what the scene SAYS, the visual is the current image prompt):\n"
            + "\n".join(
                f"{i + 1}. narration: {s.get('narration', '')} | visual: {s.get('description', '')}"
                for i, s in enumerate(scenes)
            ) + "\n\n"
            'Output JSON ONLY: {"prompts": ["prompt 1", "prompt 2", ...]} — one polished prompt per scene, same order.'
        )
        content = self.llm.generate_text(
            system_prompt, "Polish the image prompts.", temperature=0.4, timeout=90, json_mode=True
        )
        data = extract_json(content)
        polished = data.get("prompts", [])
        if not isinstance(polished, list):
            return None
        return polished

    def generate_all(self, prompt, retry=3):
        """
        AI Production Agent: builds a story spine, writes the script from it,
        then self-checks scene relevance and rewrites weak scenes.
        """
        detected = detect_scene_count(prompt)
        min_s, max_s = detected if detected else (MIN_SCENES, MAX_SCENES)
        logger.info("Scene count window: %s-%s (detected: %s)", min_s, max_s, detected is not None)

        spine = self._generate_spine(prompt)
        last_error = ""

        for attempt in range(retry):
            try:
                data = self._generate_scenes(prompt, spine, min_s, max_s)
                raw_scenes = data.get("scenes", [])

                min_required = min_s if detected else MIN_SCENES
                if len(raw_scenes) < min_required:
                    raise Exception(f"AI script too short: got {len(raw_scenes)}, expected {min_required}")

                visuals = [s.get("description", s.get("visual_prompt", "")) for s in raw_scenes]
                narrations = [clean_narration(s.get("narration", s.get("spoken_script", ""))) for s in raw_scenes]

                # LAZY RESPONSE CHECK: If narration is just the prompt repeated, fail and retry
                if any(prompt.strip().lower() in n.strip().lower() and len(n) < len(prompt) + 10 for n in narrations):
                    raise Exception("AI Director was lazy and echoed the prompt. Retrying...")

                # UNIQUENESS CHECK: Ensure each narration is different
                unique_narrations = set(n.lower().strip() for n in narrations if n)
                if len(unique_narrations) < len(narrations) * 0.7:  # At least 70% should be unique
                    raise Exception("AI Director returned repetitive narrations. Retrying...")

                # RELEVANCE SELF-CHECK: rewrite scenes that drift from the motive (one round)
                if ENABLE_RELEVANCE_CHECK and len(raw_scenes) > 1:
                    try:
                        scores = self._score_scenes(spine["motive"], raw_scenes)
                        weak = [
                            i for i, sc in enumerate(scores[:len(raw_scenes)])
                            if isinstance(sc, (int, float)) and sc < RELEVANCE_MIN_SCORE
                        ][:MAX_SCENE_REWRITES]
                        for idx in weak:
                            logger.info("Scene %s scored low; rewriting against motive...", idx + 1)
                            try:
                                fixed = self._rewrite_scene(spine["motive"], spine, raw_scenes, idx)
                                if fixed.get("narration") and fixed.get("description"):
                                    raw_scenes[idx]["narration"] = clean_narration(fixed["narration"])
                                    raw_scenes[idx]["description"] = fixed["description"]
                                    narrations[idx] = raw_scenes[idx]["narration"]
                                    visuals[idx] = raw_scenes[idx]["description"]
                            except Exception as e:
                                logger.warning("Rewrite of scene %s failed: %s", idx + 1, e)
                    except Exception as e:
                        logger.warning("Relevance check skipped: %s", e)

                # PROMPT POLISH: turn descriptions into structured image prompts (one batch call)
                if ENABLE_PROMPT_POLISH and visuals:
                    try:
                        polished = self._polish_visuals(spine, raw_scenes)
                        if polished:
                            for i in range(min(len(visuals), len(polished))):
                                if isinstance(polished[i], str) and polished[i].strip():
                                    visuals[i] = polished[i].strip()
                    except Exception as e:
                        logger.warning("Prompt polish skipped (falling back to raw descriptions): %s", e)

                # Caption: demand a real post caption; if the LLM still returned a
                # short placeholder, pad it from the richer spine fields until it
                # clears MIN_CAPTION_CHARS (never ship a one-liner caption).
                caption = (data.get("caption") or "").strip()
                if len(caption) < MIN_CAPTION_CHARS:
                    caption = self._build_long_caption(caption, spine, prompt)
                    logger.info("Caption was short (%s chars); padded to %s chars.",
                                len((data.get("caption") or "").strip()), len(caption))

                metadata = {
                    "caption": caption,
                    "hashtags": " ".join(data.get("hashtags", ["#ai", "#education"])),
                    "motive": spine["motive"],
                    "style_bible": spine["style_bible"],
                }

                logger.info("AI Director planned %s on-topic scenes.", len(visuals))
                return visuals, narrations, metadata

            except Exception as e:
                last_error = str(e)
                logger.warning("Script Agent attempt %s failed: %s", attempt + 1, e)
                if attempt < retry - 1:
                    time.sleep(3)
                else:
                    # Fail gracefully instead of generating fake content
                    raise Exception(f"AI Director failed after {retry} attempts: {last_error}")
