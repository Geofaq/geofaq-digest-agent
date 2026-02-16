import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

# Telegram
TG_API_ID = int(os.environ["TG_API_ID"])
TG_API_HASH = os.environ["TG_API_HASH"]
TG_SESSION_STRING = os.environ["TG_SESSION_STRING"]

# Supabase
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

CHANNELS = [
    "magellan_geo",
    "ege100_geo",
    "magellan_oge",
    "geoalina",
    "geograf_v",
    "scienceofcities",
    "zalivgeografa",
    "geotask",
    "cartetika_channel",
    "URBAN_MASH",
]

async def main():
    async with TelegramClient(StringSession(TG_SESSION_STRING), TG_API_ID, TG_API_HASH) as client:
        for channel in CHANNELS:
            print(f"\n--- {channel} ---")

            async for msg in client.iter_messages(channel, limit=10):
                if not msg.message:
                    continue

                external_id = f"{channel}:{msg.id}"

                # ✅ ВАЖНО: используем schema("content_ai")
                exists = (
                    sb.schema("content_ai")
                      .table("raw_items")
                      .select("id")
                      .eq("platform", "telegram")
                      .eq("external_id", external_id)
                      .limit(1)
                      .execute()
                )
                if exists.data:
                    continue

                row = {
                    "source_id": None,  # MVP: можно null
                    "platform": "telegram",
                    "external_id": external_id,
                    "url": f"https://t.me/{channel}/{msg.id}",
                    "text": msg.message,
                    "published_at": msg.date.isoformat(),
                    "views": msg.views,
                    "reactions": None,
                    "comments": None,
                }

                sb.schema("content_ai").table("raw_items").insert(row).execute()
                print("Saved:", external_id)

asyncio.run(main())
