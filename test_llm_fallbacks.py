import os
from dotenv import load_dotenv
from services.llm_service import LLMService

# Load environment variables from .env file
load_dotenv(override=True)

def test_fallbacks():
    print("--- LLM Fallback System Test ---")
    llm = LLMService()
    
    system_prompt = "You are a helpful assistant. Answer in one short sentence."
    user_prompt = "Hello! Who are you?"
    
    try:
        print("\nTesting full fallback chain...")
        result = llm.generate_text(system_prompt, user_prompt)
        print(f"\nFinal Result: {result}")
        print("\n✅ Test passed!")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")

def test_individual_providers():
    print("\n--- Testing Individual Providers ---")
    llm = LLMService()
    
    system_prompt = "You are a helpful assistant. Answer with only the word 'OK'."
    user_prompt = "Test"

    for provider in llm.providers:
        if not provider["key"]:
            print(f"\nSkipping {provider['name']} (No API Key)")
            continue
            
        print(f"\nTesting {provider['name']}...")
        try:
            # Temporarily isolate this provider
            original_providers = llm.providers
            llm.providers = [provider]
            
            result = llm.generate_text(system_prompt, user_prompt)
            print(f"Result from {provider['name']}: {result}")
            
            llm.providers = original_providers
        except Exception as e:
            print(f"❌ {provider['name']} failed: {e}")

if __name__ == "__main__":
    test_fallbacks()
    test_individual_providers()
