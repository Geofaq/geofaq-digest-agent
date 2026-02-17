import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
import asyncio

load_dotenv()

TG_API_ID = int(os.environ["TG_API_ID"])
TG_API_HASH = os.environ["TG_API_HASH"]
TG_SESSION_STRING = os.environ["TG_SESSION_STRING"]
TARGET_CHANNEL = os.environ["REPORT_CHANNEL"]
REPORT_FILE = os.environ["REPORT_FILE"]

async def main():
    async with TelegramClient(StringSession(TG_SESSION_STRING), TG_API_ID, TG_API_HASH) as client:
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        chunks = [content[i:i+4000] for i in range(0, len(content), 4000)]

        for chunk in chunks:
            await client.send_message(TARGET_CHANNEL, chunk)

asyncio.run(main())