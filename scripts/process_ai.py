import os
import json
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_URL = os.getenv("SUPABASE_DB_URL")

client = OpenAI(api_key=OPENAI_API_KEY)


def fetch_items():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    query = """
    select id, source, url, text, published_at, metrics
    from content_ai.ai_feed
    where published_at >= now() - interval '24 hours'
      and length(text) >= 200
      and text !~* 'голосуем реакциями|правильные ответы|соберем \\d+ реакц'
    order by published_at desc
    limit 300;
    """

    cur.execute(query)
    rows = cur.fetchall()

    columns = [desc[0] for desc in cur.description]
    items = [dict(zip(columns, row)) for row in rows]

    cur.close()
    conn.close()

    return items


def build_prompt(items):
    return f"""
Ты аналитик GeoFAQ.

На основе списка постов выдели:
1) 5 тем дня
2) что растёт (сигналы)
3) идеи для GeoFAQ
4) краткий дайджест

Верни строго JSON:

{{
  "top_topics": [],
  "what_is_growing": [],
  "geofaq_ideas": [],
  "digest": {{
    "title": "",
    "bullets": [],
    "links": []
  }}
}}

Вот данные:
json.dumps(items, ensure_ascii=False, default=str)
"""


def analyze_with_ai(items):
    prompt = build_prompt(items)

    response = client.responses.create(
        model="gpt-4.1",
        response_format={"type": "json_object"},
        input=prompt,
    )

    return json.loads(response.output_text)


def render_markdown(result):
    md = f"# {result['digest']['title']}\n\n"

    for bullet in result["digest"]["bullets"]:
        md += f"- {bullet}\n"

    md += "\n## Ссылки\n"
    for link in result["digest"]["links"]:
        md += f"- {link}\n"

    return md


def save_digest(result_json, digest_md, items_count):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    insert_query = """
    insert into content_ai.digest_runs
    (run_date, window, items_count, model, result_json, digest_md)
    values (%s, interval '24 hours', %s, %s, %s, %s);
    """

    cur.execute(
        insert_query,
        (
            datetime.utcnow().date(),
            items_count,
            "gpt-4.1",
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
        print("No items found")
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
