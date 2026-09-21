import logging
import requests
from config import (
    GROQ_API_KEY, GEMINI_API_KEY, POLLINATIONS_API_KEY, BYTEZ_API_KEY,
    GROQ_MODEL, GEMINI_MODEL, POLLINATIONS_MODEL, BYTEZ_LLM_MODEL
)

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        self.providers = [
            {
                "name": "Groq",
                "url": "https://api.groq.com/openai/v1/chat/completions",
                "key": GROQ_API_KEY,
                "model": GROQ_MODEL,
                "json_mode": True,   # supports response_format json_object
            },
            {
                "name": "Gemini",
                "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                "key": GEMINI_API_KEY,
                "model": GEMINI_MODEL,
                "json_mode": True,   # supports response_format json_object
            },
            {
                "name": "Pollinations",
                "url": "https://gen.pollinations.ai/v1/chat/completions",
                "key": POLLINATIONS_API_KEY,
                "model": POLLINATIONS_MODEL,
                "json_mode": False,
            },
            {
                "name": "Bytez",
                "url": "https://api.bytez.com/models/v2/openai/v1/chat/completions",
                "key": BYTEZ_API_KEY,
                "model": BYTEZ_LLM_MODEL,
                "json_mode": False,
            },
        ]

    def generate_text(self, system_prompt, user_prompt, temperature=0.7, timeout=60, json_mode=False):
        """
        Robust text generation with automatic fallback across multiple providers.
        When json_mode=True, providers that support it are asked for strict JSON output.
        """
        active_providers = [p for p in self.providers if p["key"]]

        if not active_providers:
            raise Exception("No LLM API keys configured. Please add keys to your .env file.")

        last_error = ""
        for provider in active_providers:
            try:
                logger.info("Trying %s (%s)...", provider["name"], provider["model"])

                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {provider['key']}"
                }

                payload = {
                    "model": provider["model"],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": temperature
                }
                if json_mode and provider["json_mode"]:
                    payload["response_format"] = {"type": "json_object"}

                response = requests.post(
                    provider["url"],
                    headers=headers,
                    json=payload,
                    timeout=timeout
                )

                if response.status_code != 200:
                    raise Exception(f"{provider['name']} error {response.status_code}: {response.text[:300]}")

                data = response.json()
                content = data['choices'][0]['message']['content']

                if not content:
                    raise Exception(f"{provider['name']} returned empty content")

                logger.info("%s succeeded.", provider["name"])
                return content

            except Exception as e:
                last_error = str(e)
                logger.warning("%s failed: %s", provider["name"], e)
                continue  # Try next provider

        raise Exception(f"All LLM providers failed. Last error: {last_error}")
