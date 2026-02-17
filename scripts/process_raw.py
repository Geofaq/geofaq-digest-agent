import os
import json
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client
from uuid import uuid4

load_dotenv()

openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

supabase = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"]
)

raw_items = supabase.rpc("get_unprocessed_raw").execute()

if not raw_items.data:
    print("Нет новых raw для обработки")
    exit()

for item in raw_items.data:
    raw_id = item["id"]
    text = item["text"]

    print(f"\nОбрабатываем: {raw_id}")

    prompt = f"""
Ты контент-аналитик Telegram.

Проанализируй пост:

{text}

Верни СТРОГО валидный JSON без engagement:

{{
  "theme_cluster": "короткое название темы",
  "content_format": "опрос | факт | интерактив | разбор | подборка",
  "summary": "2-3 предложения",
  "why_worked": "почему это зашло",
  "angle_for_geofaq": "как адаптировать под GeoFAQ"
}}
"""

    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"}
    )

    analysis = response.choices[0].message.content
    data = json.loads(analysis)

    # --- Реальный engagement ---
    views = item["views"] or 0
    reactions = item["reactions"] or 0
    comments = item["comments"] or 0

    engagement = 0
    if views > 0:
        engagement = (reactions + comments * 2) / views

    supabase.schema("content_ai").table("processed_items").insert({
        "id": str(uuid4()),
        "raw_id": raw_id,
        "theme_cluster": data["theme_cluster"],
        "content_format": data["content_format"],
        "engagement_index": engagement,
        "summary": data["summary"],
        "why_worked": data["why_worked"],
        "angle_for_geofaq": data["angle_for_geofaq"]
    }).execute()

    print("Сохранено")

supabase.rpc("auto_select_for_production").execute()
print("Авто-отбор выполнен.")