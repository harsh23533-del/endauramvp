"""
Quick script to find a working free model on OpenRouter.
Run: python test_models.py
"""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.environ.get("OPENROUTER_API_KEY")
if not api_key:
    print("OPENROUTER_API_KEY not found in .env")
    exit(1)

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

candidates = [
    "google/gemma-3-27b-it:free",
    "google/gemma-2-9b-it:free",
    "nvidia/nemotron-3-super-120b:free",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "deepseek/deepseek-chat-v3.1:free",
    "microsoft/mai-ds-r1:free",
]

for model in candidates:
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=20,
            messages=[{"role": "user", "content": "Say OK"}],
        )
        content = response.choices[0].message.content
        print(f"WORKS  : {model}  -> {content!r}")
    except Exception as e:
        print(f"FAILED : {model}  -> {str(e)[:100]}")