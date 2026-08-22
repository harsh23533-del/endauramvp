"""
Fetches OpenRouter's live model list and prints only the free
text-generation models with their exact slugs.
"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("OPENROUTER_API_KEY")
resp = requests.get(
    "https://openrouter.ai/api/v1/models",
    headers={"Authorization": f"Bearer {api_key}"},
)
data = resp.json()["data"]

print(f"Total models: {len(data)}\n")
print("FREE text models:\n")

for m in data:
    pricing = m.get("pricing", {})
    prompt_price = pricing.get("prompt", "1")
    completion_price = pricing.get("completion", "1")
    modality = m.get("architecture", {}).get("modality", "")

    is_free = prompt_price == "0" and completion_price == "0"
    is_text = "text->text" in modality or modality == "text"

    if is_free and is_text:
        print(m["id"])