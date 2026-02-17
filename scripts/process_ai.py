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

        pa = item.get("published_at")
        if hasattr(pa, "isoformat"):
            item["published_at"] = pa.isoformat()

        if item.get("metrics") is None:
            item["metrics"] = {}

        items.append(item)

    cur.close()
    conn.close()
    return items


def build_prompt(items):
    # Явно фиксируем схему, чтобы digest был объектом, а не строкой
    schema = {
        "top_topics": "array(5)",
        "what_is_growing": "array",
        "geofaq_ideas": "array",
        "digest": {
            "title": "string",
            "bullets": "array(string)",
            "links": "array({title,url})"
        }
    }

    return (
        "Ты аналитик GeoFAQ.\n"
        "На основе списка материалов за сутки сформируй:\n"
        "1) top_topics — РОВНО 5 тем дня\n"
        "2) what_is_growing — сигналы роста/всплески\n"
        "3) geofaq_ideas — идеи для контента GeoFAQ\n"
        "4) digest — объект с title/bullets/links\n\n"
        "Верни строго валидный JSON. Без markdown. Без ```.\n"
        "digest ОБЯЗАТЕЛЬНО должен быть объектом, не строкой.\n\n"
        f"Схема:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"Дата (UTC): {datetime.now(timezone.utc).date().isoformat()}\n\n"
        f"Items:\n{json.dumps(items, ensure_ascii=False, default=str)}"
    )


def clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def repair_json(bad_text: str) -> dict:
    repair_prompt = (
        "Исправь текст так, чтобы он стал валидным JSON и соответствовал схеме.\n"
        "Верни только JSON, без markdown.\n\n"
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
        data = json.loads(text)
    except json.JSONDecodeError:
        data = repair_json(text)

    return data


def ensure_list(x):
    """Нормализуем к list."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    # если строка — сделаем список из одного пункта
    if isinstance(x, str):
        return [x.strip()] if x.strip() else []
    return []


def render_markdown(result):
    # result может быть dict, но делаем безопасно
    if not isinstance(result, dict):
        return "# GeoFAQ Digest\n\n- (Ошибка формата результата: не dict)\n"

    digest = result.get("digest", {})

    # digest может быть строкой (как у тебя). Обрабатываем.
    if isinstance(digest, str):
        title = "GeoFAQ Digest"
        bullets = [digest.strip()] if digest.strip() else []
        links = []
    elif isinstance(digest, dict):
        title = digest.get("title") or "GeoFAQ Digest"
        bullets = ensure_list(digest.get("bullets"))
        links = ensure_list(digest.get("links"))
    else:
        title = "GeoFAQ Digest"
        bullets = []
        links = []

    md = f"# {title}\n\n"
    if bullets:
        for b in bullets:
            md += f"- {b}\n"
    else:
        md += "- (Пустой дайджест)\n"

    # links: ожидаем список dict({title,url}), но допускаем строки
    if links:
        md += "\n## Ссылки\n"
        for l in links:
            if isinstance(l, dict):
                t = (l.get("title") or "link").strip()
                u = (l.get("url") or "").strip()
                if u:
                    md += f"- {t}: {u}\n"
            elif isinstance(l, str) and l.strip():
                md += f"- {l.strip()}\n"

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
