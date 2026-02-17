import os
import json
import re
from datetime import datetime, timezone, date

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_URL = os.getenv("SUPABASE_DB_URL")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is missing.")
if not DB_URL:
    raise RuntimeError("SUPABASE_DB_URL is missing.")

client = OpenAI(api_key=OPENAI_API_KEY)

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


FETCH_QUERY = """
select id, source, url, text, published_at, metrics
from content_ai.ai_feed
where published_at >= now() - interval '24 hours'
  and length(text) >= 200
  and text !~* 'голосуем реакциями|правильные ответы|соберем \\d+ реакц'
order by published_at desc
limit 300;
"""


def fetch_items():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute(FETCH_QUERY)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]

    items = []
    for row in rows:
        item = dict(zip(cols, row))

        if hasattr(item.get("published_at"), "isoformat"):
            item["published_at"] = item["published_at"].isoformat()

        if item.get("metrics") is None:
            item["metrics"] = {}

        items.append(item)

    cur.close()
    conn.close()
    return items


def build_prompt(items):
    return (
        "Ты аналитик GeoFAQ.\n"
        "На основе списка материалов за сутки сформируй:\n"
        "1) 5 тем дня (top_topics)\n"
        "2) что растёт (what_is_growing)\n"
        "3) идеи для GeoFAQ (geofaq_ideas)\n"
        "4) короткий дайджест (digest)\n\n"
        "Верни строго валидный JSON. Без markdown.\n\n"
        f"Дата: {datetime.now(timezone.utc).date().isoformat()}\n\n"
        f"Items:\n{json.dumps(items, ensure_ascii=False, default=str)}"
    )


def clean_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()


def repair_json(bad_text):
    repair_prompt = (
        "Исправь текст так, чтобы он стал валидным JSON. "
        "Верни только JSON.\n\n"
        f"{bad_text}"
    )

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Return ONLY valid JSON."},
            {"role": "user", "content": repair_prompt},
        ],
        temperature=0.0,
    )

    fixed = clean_json(resp.choices[0].message.content)
    return json.loads(fixed)


def analyze_with_ai(items):
    prompt = build_prompt(items)

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Return ONLY valid JSON. No markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    text = clean_json(resp.choices[0].message.content)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return repair_json(text)


def render_markdown(result):
    digest = result.get("digest", {})
    title = digest.get("title", "GeoFAQ Digest")
    bullets = digest.get("bullets", [])
    links = digest.get("links", [])

    md = f"# {title}\n\n"

    for b in bullets:
        md += f"- {b}\n"

    if links:
        md += "\n## Ссылки\n"
        for l in links:
            if isinstance(l, dict):
                md += f"- {l.get('title','')}: {l.get('url','')}\n"

    return md


def save_digest(result_json, digest_md, items_count):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    insert_query = """
    insert into content_ai.digest_runs
      (kind, run_date, time_window, items_count, model, result_json, digest_md)
    values
      (%s, %s, interval '24 hours', %s, %s, %s, %s);
    """

    cur.execute(
        insert_query,
        (
            "daily_ai",
            date.today(),
            items_count,
            MODEL,
            json.dumps(result_json, ensure_ascii=False),
            digest_md,
        ),
    )

    conn.commit()
    cur.close()
    conn.close()


def main():
    print("Fetching items...")
    items = fetch_items()
    print(f"Fetched {len(items)} items")

    if not items:
        print("No items found.")
        return

    print("Analyzing with AI...")
    result = analyze_with_ai(items)

    print("Rendering markdown...")
    digest_md = render_markdown(result)

    print("Saving to database...")
    save_digest(result, digest_md, len(items))

    print("Done.")


if __name__ == "__main__":
    main()
