import os
import requests
from dotenv import load_dotenv
import json

load_dotenv()
api_key = os.getenv("GOOGLE_AI_STUDIO_KEY")

# Will test a few variants since 3.5 flash might be an alias or misnomer for 1.5 flash
models = ["gemini-3.5-flash", "gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash"]

with open("raw_error_output.txt", "w") as f:
    for m in models:
        f.write(f"\n--- Testing model: {m} ---\n")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        data = {
            "contents": [{"parts":[{"text": "Hello"}]}]
        }
        try:
            response = requests.post(url, headers=headers, json=data)
            f.write(f"Status Code: {response.status_code}\n")
            f.write("Raw Error Body (or success):\n")
            f.write(response.text + "\n")
            if response.status_code != 200:
                f.write("Headers:\n")
                f.write(json.dumps(dict(response.headers), indent=2) + "\n")
        except Exception as e:
            f.write(f"Exception: {e}\n")
