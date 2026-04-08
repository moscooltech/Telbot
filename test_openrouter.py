import os
import requests
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

def test_openrouter():
    api_key = os.getenv("OPENROUTER_API_KEY")
    model = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-lite-preview-02-05:free")

    if not api_key:
        print("❌ Error: OPENROUTER_API_KEY not found in environment variables.")
        return

    print(f"Testing OpenRouter with model: {model}")
    print(f"API Key (first 5 chars): {api_key[:5]}...")

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "OpenRouter Test Script"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Say hello and tell me what model you are."}
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            print("✅ Success!")
            print(f"Response: {content}")
        else:
            print(f"❌ Failed with status code {response.status_code}")
            print(f"Response body: {response.text}")
            
            if response.status_code == 401:
                print("\n💡 Suggestion: A 401 error usually means your API key is invalid or has expired.")
                print("Make sure there are no leading or trailing spaces in your .env file.")

    except Exception as e:
        print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    test_openrouter()
