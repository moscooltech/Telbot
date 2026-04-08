import os
import requests
import json
import time
from config import (
    GROQ_API_KEY, GEMINI_API_KEY, POLLINATIONS_API_KEY, BYTEZ_API_KEY,
    GROQ_MODEL, GEMINI_MODEL, POLLINATIONS_MODEL, BYTEZ_MODEL
)

class LLMService:
    def __init__(self):
        self.providers = [
            {
                "name": "Groq",
                "url": "https://api.groq.com/openai/v1/chat/completions",
                "key": GROQ_API_KEY,
                "model": GROQ_MODEL
            },
            {
                "name": "Gemini",
                "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                "key": GEMINI_API_KEY,
                "model": GEMINI_MODEL
            },
            {
                "name": "Pollinations",
                "url": "https://gen.pollinations.ai/v1/chat/completions",
                "key": POLLINATIONS_API_KEY,
                "model": POLLINATIONS_MODEL
            },
            {
                "name": "Bytez",
                "url": "https://api.bytez.com/models/v2/openai/v1/chat/completions",
                "key": BYTEZ_API_KEY,
                "model": BYTEZ_MODEL
            }
        ]

    def generate_text(self, system_prompt, user_prompt, temperature=0.7, timeout=60):
        """
        Robust text generation with automatic fallback across multiple providers.
        """
        active_providers = [p for p in self.providers if p["key"]]
        
        if not active_providers:
            raise Exception("No LLM API keys configured. Please add keys to your .env file.")

        last_error = ""
        for provider in active_providers:
            try:
                print(f"尝试使用 {provider['name']} 生成内容...")
                
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

                response = requests.post(
                    provider["url"],
                    headers=headers,
                    json=payload,
                    timeout=timeout
                )
                
                if response.status_code != 200:
                    raise Exception(f"{provider['name']} error {response.status_code}: {response.text}")

                data = response.json()
                content = data['choices'][0]['message']['content']
                
                if not content:
                    raise Exception(f"{provider['name']} returned empty content")
                
                print(f"✅ {provider['name']} 成功生成内容。")
                return content

            except Exception as e:
                last_error = str(e)
                print(f"⚠️ {provider['name']} 失败: {e}")
                continue # Try next provider

        raise Exception(f"All LLM providers failed. Last error: {last_error}")
