import os
import asyncio
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# Telegram credentials
api_id = int(os.getenv("TG_API_ID"))
api_hash = os.getenv("TG_API_HASH")
session_string = os.getenv("TG_SESSION_STRING")

# Supabase credentials
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(supabase_url, supabase_key)

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

            async for message in client.iter_messages(channel, limit=5):
                if not message.text:
                    continue

                external_id = f"{channel}:{message.id}"

                # Проверяем, есть ли уже такой пост
                existing = supabase.table("content_ai.raw_items") \
                    .select("id") \
                    .eq("external_id", external_id) \
                    .execute()

                if existing.data:
                    continue

                data = {
                    "source_id": None,  # позже свяжем с sources
                    "platform": "telegram",
                    "external_id": external_id,
                    "url": f"https://t.me/{channel}/{message.id}",
                    "text": message.text,
                    "published_at": message.date.isoformat(),
                    "views": message.views,
                    "reactions": None,
                    "comments": None
                }

                supabase.table("content_ai.raw_items").insert(data).execute()

                print("Saved:", external_id)

asyncio.run(main())
