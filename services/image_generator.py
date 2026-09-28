import os
import re
import requests
import random
import time
import base64
import logging
from typing import List, Optional
from config import (
    POLLINATIONS_API_KEY, BYTEZ_API_KEY, TEMP_DIR, IMAGE_WIDTH, IMAGE_HEIGHT,
    CONSISTENT_SEED, IMAGE_PROMPT_MAX_WORDS, POLLINATIONS_ENHANCE,
    BYTEZ_IMAGE_MODEL, IMAGE_LEGACY_MODEL, IMAGE_TIMEOUT,
    GEMINI_API_KEY, GEMINI_IMAGE_MODELS, GEMINI_IMAGE_ASPECT,
    CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_IMAGE_MODEL,
    CLOUDFLARE_KLEIN_MODELS, IMAGE_NEGATIVE_PROMPT, IMAGE_STYLE_SUFFIX,
    ENABLE_STYLE_SUFFIX,
)

logger = logging.getLogger(__name__)

# Magic-byte sniffing: only trust payloads that are real images
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
# Tiny responses are error pages, not photos
MIN_IMAGE_BYTES = 3000

# Failure caching: a provider that keeps failing is skipped for the rest of the job
# (each ImageGenerator instance is job-scoped) until its cooldown expires.
PROVIDER_COOLDOWN_SECONDS = 600   # 10 min
PROVIDER_FAILURE_THRESHOLD = 2    # consecutive failures before cooldown kicks in


class ImageGenerator:
    def __init__(self, job_id: str, style_bible: str = "") -> None:
        self.job_id = job_id
        self.job_dir = os.path.join(TEMP_DIR, job_id)
        self.image_dir = os.path.join(self.job_dir, "images")
        self.width = IMAGE_WIDTH
        self.height = IMAGE_HEIGHT
        self.style_bible = (style_bible or "").strip()
        # One seed per job keeps the visual identity stable across all scenes
        self.base_seed = random.randint(0, 999999) if CONSISTENT_SEED else None
        # key -> {"fails": int, "cooldown_until": epoch seconds}
        self._provider_stats = {}
        # "name (model)" -> how many final images this provider actually delivered
        self.provider_usage = {}

        os.makedirs(self.image_dir, exist_ok=True)

    def _clean_prompt(self, prompt: str) -> str:
        """Sanitize prompt: strip quotes/newlines, collapse whitespace, cap length.
        Commas are kept — they are how image models parse subject/setting/lighting layers."""
        prompt = (prompt or "").strip()
        prompt = re.sub(r"[\"'`\n\r]+", " ", prompt)
        prompt = re.sub(r"\s+", " ", prompt).strip(" ,")
        if IMAGE_PROMPT_MAX_WORDS > 0:
            words = prompt.split()
            prompt = " ".join(words[:IMAGE_PROMPT_MAX_WORDS])
        return prompt

    def _build_prompt(self, scene_prompt: str) -> str:
        """Fuse scene description with the job-wide style bible for coherence."""
        prompt = self._clean_prompt(scene_prompt)
        if self.style_bible:
            style_words = self._clean_prompt(self.style_bible)
            prompt = f"{prompt}, {style_words}"
        # The photo-style suffix is appended AFTER word capping so it is never
        # truncated away — it is what keeps generic models from drifting cartoonish.
        if ENABLE_STYLE_SUFFIX and IMAGE_STYLE_SUFFIX:
            prompt = f"{prompt}, {self._clean_prompt(IMAGE_STYLE_SUFFIX)}"
        return f"{prompt}, high quality, detailed, professional, 4k"

    @staticmethod
    def _is_image(response: requests.Response) -> bool:
        """A success only counts as an actual picture: HTTP 200, plausible size, real image magic bytes."""
        if response.status_code != 200:
            return False
        content = response.content
        if len(content) < MIN_IMAGE_BYTES:
            return False
        return content[:3] == JPEG_MAGIC or content[:8] == PNG_MAGIC[:8]

    # ------------------------------------------------------------------
    # Provider 1: Cloudflare Workers AI — photorealistic models on a generous
    # free tier (10,000 Neurons/day). FLUX.2 klein (newest, best prompt
    # adherence, multipart input) first, then SDXL as JSON fallback.
    # Native width/height support -> true 9:16 output.
    # ------------------------------------------------------------------
    @staticmethod
    def _is_klein(model: str) -> bool:
        """FLUX.2 klein models use a different API: multipart form data, guidance
        instead of num_steps, and a 256-1920 size range (no negative prompt field)."""
        return model in CLOUDFLARE_KLEIN_MODELS or "/flux-2" in model

    def _generate_cloudflare(self, prompt: str, seed: Optional[int], model: str,
                             timeout: int) -> bytes:
        url = (f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
               f"/ai/run/{model}")
        headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}

        if self._is_klein(model):
            # FLUX.2 klein requires multipart form data (documented in the Workers AI
            # changelog). Output comes back as JSON {"image": "<base64>"}.
            # width/height are clamped to the documented 256-1920 range.
            width = max(256, min(1920, self.width))
            height = max(256, min(1920, self.height))
            data = {
                "prompt": prompt[:2048],
                "width": str(width),
                "height": str(height),
            }
            if seed is not None:
                data["seed"] = str(seed)
            if IMAGE_NEGATIVE_PROMPT:
                # Not an official klein parameter; harmless as a hint unless the
                # API starts rejecting unknown fields (then set IMAGE_NEGATIVE_PROMPT="")
                data["negative_prompt"] = IMAGE_NEGATIVE_PROMPT
            response = requests.post(url, data=data, headers=headers, timeout=timeout)
        else:
            # SDXL / other JSON-input models.
            payload = {
                "prompt": prompt[:2048],
                "width": self.width,
                "height": self.height,
                "num_steps": 12,
                "negative_prompt": IMAGE_NEGATIVE_PROMPT,
            }
            if seed is not None:
                payload["seed"] = seed
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)

        if response.status_code != 200:
            raise Exception(f"cloudflare returned {response.status_code}: {response.text[:200]}")

        # Binary responses come as a raw image stream; JSON responses carry base64.
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            data = response.json()
            if not data.get("success", True):
                raise Exception(f"cloudflare error: {str(data.get('errors'))[:200]}")
            result = data.get("result", {})
            b64 = result.get("image") if isinstance(result, dict) else None
            if not b64:
                raise Exception("cloudflare response had no image data")
            return base64.b64decode(b64)

        raw = response.content
        if not (raw[:3] == JPEG_MAGIC or raw[:8] == PNG_MAGIC[:8]):
            raise Exception("cloudflare stream was not a valid image")
        return raw

    # ------------------------------------------------------------------
    # Provider 2: legacy image.pollinations.ai — keyless, free, always works,
    # but serves its weak "sana" model (cartoonish look). Safety net only.
    # ------------------------------------------------------------------
    def _generate_pollinations_legacy(self, prompt: str, seed: Optional[int], model: str,
                                      timeout: int) -> bytes:
        params = {
            "width": self.width,
            "height": self.height,
            "nologo": "true",
            "model": model,
        }
        if POLLINATIONS_ENHANCE:
            params["enhance"] = "true"
        if seed is not None:
            params["seed"] = seed

        url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}"
        response = requests.get(url, params=params, timeout=timeout)
        if not self._is_image(response):
            raise Exception(
                f"legacy returned {response.status_code} / {len(response.content)}B"
            )
        return response.content

    # ------------------------------------------------------------------
    # Provider 3: Gemini (Nano Banana) — photorealistic, but image models have
    # ZERO free-tier API quota (text is free, images are not). Skipped on 429s
    # by the cooldown logic; useful only with a paid key. REST shape:
    # POST /v1beta/models/{model}:generateContent with responseModalities
    # [TEXT, IMAGE]; the image comes back as inlineData base64 PNG.
    # ------------------------------------------------------------------
    def _generate_gemini(self, prompt: str, seed: Optional[int], model: str,
                         timeout: int) -> bytes:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {"aspectRatio": GEMINI_IMAGE_ASPECT},
            },
        }
        response = requests.post(
            url, json=payload,
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        if response.status_code != 200:
            raise Exception(f"gemini {model} returned {response.status_code}: {response.text[:200]}")

        data = response.json()
        image_bytes = None
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    image_bytes = base64.b64decode(inline["data"])
                    break
            if image_bytes:
                break
        if not image_bytes:
            # Surface refusal/blocked reasons so failures are diagnosable
            reason = (data.get("candidates") or [{}])[0].get("finishReason", "no image part")
            raise Exception(f"gemini {model} returned no image ({reason})")
        return image_bytes

    # ------------------------------------------------------------------
    # Provider 4: gen.pollinations.ai — needs POLLINATIONS_API_KEY, richer models
    # ------------------------------------------------------------------
    def _generate_pollinations_gen(self, prompt: str, seed: Optional[int], model: str,
                                   timeout: int) -> bytes:
        params = {
            "model": model,
            "width": self.width,
            "height": self.height,
            "nologo": "true",
            "enhance": "true" if POLLINATIONS_ENHANCE else "false",
        }
        if seed is not None:
            params["seed"] = seed

        url = f"https://gen.pollinations.ai/image/{requests.utils.quote(prompt)}"
        response = requests.get(
            url, params=params,
            headers={"Authorization": f"Bearer {POLLINATIONS_API_KEY}"},
            timeout=timeout,
        )
        if not self._is_image(response):
            raise Exception(
                f"gen returned {response.status_code} / {len(response.content)}B"
            )
        return response.content

    # ------------------------------------------------------------------
    # Provider 5: Bytez — free-tier keyed fallback (SDXL)
    # ------------------------------------------------------------------
    def _generate_bytez(self, prompt: str, seed: Optional[int], model: Optional[str],
                        timeout: int) -> bytes:
        url = f"https://api.bytez.com/models/v2/{BYTEZ_IMAGE_MODEL}"
        payload = {"prompt": prompt}
        if seed is not None:
            payload["seed"] = seed
        response = requests.post(
            url, json=payload,
            headers={"Authorization": f"Key {BYTEZ_API_KEY}"},
            timeout=timeout,
        )
        if response.status_code != 200:
            raise Exception(f"bytez returned {response.status_code}")

        data = response.json()
        b64 = data.get("output") or data.get("output_base64") or data.get("image")
        if not b64:
            raise Exception("bytez response had no image data")
        return base64.b64decode(b64)

    def _provider_key(self, provider_name: str, model: Optional[str]) -> str:
        return f"{provider_name}:{model or ''}"

    def _mark_provider_failure(self, key: str) -> None:
        stats = self._provider_stats.setdefault(key, {"fails": 0, "cooldown_until": 0.0})
        stats["fails"] += 1
        if stats["fails"] >= PROVIDER_FAILURE_THRESHOLD:
            stats["cooldown_until"] = time.time() + PROVIDER_COOLDOWN_SECONDS
            logger.warning("Provider %s is cooling down for %ss after %s failures.",
                           key, PROVIDER_COOLDOWN_SECONDS, stats["fails"])

    @staticmethod
    def _chain_plan() -> List[tuple]:
        """The configured provider fallback order, ignoring cooldown state.
        Used both by generate_image() (filtered + bound by _provider_chain) and by
        the /status command (shown as-is, no instance needed).
        Each entry: (name, method_name, model or None) — method_name is resolved to
        a bound method by _provider_chain so no temp dirs are created for /status."""
        chain: List[tuple] = []
        if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN:
            # Cloudflare FIRST when credentials exist: confirmed working in
            # production, free tier (~300 images/day), and the FLUX.2 klein
            # models beat everything else here on photorealism. Chain klein
            # (multipart input) then SDXL (JSON) as in-family fallbacks.
            for klein in CLOUDFLARE_KLEIN_MODELS:
                chain.append(("cloudflare", "_generate_cloudflare", klein))
            chain.append(("cloudflare", "_generate_cloudflare", CLOUDFLARE_IMAGE_MODEL))
        if POLLINATIONS_API_KEY:
            # Keyed Pollinations Flux — solid photorealistic backup. Free-tier
            # limits (402) fall through automatically.
            # NOTE: "turbo" is a stale alias on this endpoint (400 Invalid model); the
            # valid alternatives verified via gen.pollinations.ai/models are "z-image-turbo"
            # (tongyi-mai/z-image-turbo) and "flux-2-pro".
            for model in ("flux", "z-image-turbo"):
                chain.append(("pollinations-gen", "_generate_pollinations_gen", model))
        if GEMINI_API_KEY:
            # Photorealistic but zero free-tier quota -> usually 429s; the cooldown
            # logic skips it for the rest of the job after two failures.
            for model in GEMINI_IMAGE_MODELS:
                chain.append(("gemini", "_generate_gemini", model.strip()))
        # Keyless Pollinations serves "sana" (weak/cartoonish model) but always works —
        # kept near the end as the guaranteed safety net.
        chain.append(
            ("pollinations-legacy", "_generate_pollinations_legacy", IMAGE_LEGACY_MODEL)
        )
        if BYTEZ_API_KEY:
            chain.append(("bytez", "_generate_bytez", None))
        return chain

    def _provider_chain(self) -> List[tuple]:
        """Ordered fallback chain with providers in failure cooldown skipped,
        unless that would leave the chain empty."""
        plan = self._chain_plan()
        now = time.time()
        healthy = [
            entry for entry in plan
            if self._provider_stats.get(self._provider_key(entry[0], entry[2]), {}).get("cooldown_until", 0) < now
        ]
        chosen = healthy or plan  # last-ditch: if everything is cooling down, try everything
        return [(name, getattr(self, method_name), model) for name, method_name, model in chosen]

    def generate_image(self, prompt: str, index: int, retry: int = 2) -> Optional[str]:
        """Generates a single image, trying every provider in the fallback chain."""
        enhanced_prompt = self._build_prompt(prompt)
        filepath = os.path.join(self.image_dir, f"scene_{index:03d}.jpg")

        logger.info("[Scene %s] Generating image: %s...", index, enhanced_prompt[:60])

        seed = (self.base_seed + index) % 1000000 if self.base_seed is not None else None
        chain = self._provider_chain()
        if not chain:
            logger.error("[Scene %s] No image providers configured.", index)
            return None

        last_error = ""
        for attempt in range(1, retry + 1):
            for provider_name, provider_fn, model in chain:
                key = self._provider_key(provider_name, model)
                try:
                    # Legacy tier is rate limited (~1 req / 15s); space out requests.
                    time.sleep(3)
                    image_bytes = provider_fn(enhanced_prompt, seed, model, timeout=IMAGE_TIMEOUT)
                    with open(filepath, "wb") as f:
                        f.write(image_bytes)
                    self._provider_stats[key] = {"fails": 0, "cooldown_until": 0.0}
                    usage_key = f"{provider_name} ({model})" if model else provider_name
                    self.provider_usage[usage_key] = self.provider_usage.get(usage_key, 0) + 1
                    logger.info("[Scene %s] Success with %s (%s) attempt %s -> %s!",
                                index, provider_name, model, attempt, filepath)
                    return filepath
                except Exception as e:
                    last_error = f"{provider_name}: {e}"
                    self._mark_provider_failure(key)
                    logger.warning("[Scene %s] %s attempt %s failed: %s",
                                   index, provider_name, attempt, e)

        logger.error("[Scene %s] Image generation failed. Last error: %s", index, last_error)
        return None

    def provider_summary_text(self, total: int, ok: int) -> str:
        """Compact winner line, e.g. "10/10 scenes OK | winners: pollinations-gen (flux) x10".
        Shown in Render logs and in the Telegram completion message."""
        if not self.provider_usage:
            return f"{ok}/{total} scenes OK | no provider delivered an image"
        parts = [f"{name} x{count}" for name, count in
                 sorted(self.provider_usage.items(), key=lambda kv: -kv[1])]
        return f"{ok}/{total} scenes OK | winners: " + ", ".join(parts)

    def _log_provider_summary(self, total: int, ok: int) -> None:
        """One-line job summary of which provider/model actually produced the images,
        so the winning provider is obvious in Render logs."""
        summary = self.provider_summary_text(total, ok)
        if not self.provider_usage:
            logger.warning("[Job %s] Image summary: %s", self.job_id, summary)
        else:
            logger.info("[Job %s] Image summary: %s", self.job_id, summary)

    def generate_all_images(self, scenes: List[str]) -> List[str]:
        """Generates images for all scenes with fallback logic."""
        logger.info("Starting generation for %s scenes...", len(scenes))
        image_paths = []

        for i, scene in enumerate(scenes):
            path = self.generate_image(scene, i)
            if path:
                image_paths.append(path)

        self._log_provider_summary(len(scenes), len(image_paths))

        if not image_paths:
            raise Exception("All image generation attempts failed.")

        return image_paths
