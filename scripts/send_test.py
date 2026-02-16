import os
import requests

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("NOTES_CHAT_ID")

url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

payload = {
    "chat_id": CHAT_ID,
    "text": "🚀 GeoFAQ Digest Agent подключён и работает через GitHub Actions."
}

response = requests.post(url, json=payload)
print(response.text)
