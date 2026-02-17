from dotenv import load_dotenv
load_dotenv()

import os
import asyncio
from datetime import datetime, timezone
from telethon import TelegramClient
from telethon.sessions import StringSession
from supabase import create_client

TG_API_ID = int(os.environ["TG_API_ID"])
TG_API_HASH = os.environ["TG_API_HASH"]
TG_SESSION_STRING = os.environ["TG_SESSION_STRING"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

DATE_FROM = datetime(2026, 2, 1, tzinfo=timezone.utc)

async def main():
    async with TelegramClient(StringSession(TG_SESSION_STRING), TG_API_ID, TG_API_HASH) as client:

        # --- Берем каналы из Supabase ---
        sources = (
            sb.schema("content_ai")
              .table("sources")
              .select("url")
              .eq("platform", "telegram")
              .eq("is_active", True)
              .execute()
        )

        if not sources.data:
            print("Нет активных Telegram-источников")
            return

        for source in sources.data:
            url = source["url"]

            # извлекаем username из https://t.me/username
            channel = url.replace("https://t.me/", "").strip()

            print(f"\n--- {channel} ---")

            async for msg in client.iter_messages(channel, reverse=True):
                if not msg.message:
                    continue

                if msg.date < DATE_FROM:
                    continue

                external_id = f"{channel}:{msg.id}"

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

                reactions_count = 0
                if msg.reactions and msg.reactions.results:
                    reactions_count = sum(r.count for r in msg.reactions.results)

                comments_count = 0
                if msg.replies:
                    comments_count = msg.replies.replies or 0

                row = {
                    "source_id": None,
                    "platform": "telegram",
                    "external_id": external_id,
                    "url": f"https://t.me/{channel}/{msg.id}",
                    "text": msg.message,
                    "published_at": msg.date.isoformat(),
                    "views": msg.views or 0,
                    "reactions": reactions_count,
                    "comments": comments_count,
                }

                sb.schema("content_ai").table("raw_items").insert(row).execute()
                print("Saved:", external_id)

asyncio.run(main())
