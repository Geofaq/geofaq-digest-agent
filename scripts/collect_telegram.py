import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_string = os.getenv("TG_SESSION_STRING")

channels = [
    "magellan_geo",
    "ege100_geo",
    "magellan_oge",
    "geoalina",
    "geograf_v",
    "scienceofcities",
    "zalivgeografa",
    "geotask",
    "cartetika_channel",
    "URBAN_MASH"
]

async def main():
    async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
        for channel in channels:
            print(f"\n--- {channel} ---")
            async for message in client.iter_messages(channel, limit=3):
                if message.text:
                    print(message.text[:200])
                    print("------")

asyncio.run(main())
