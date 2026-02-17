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
    raise RuntimeError("OPENAI_API_KEY is missing (set it in .env locally or GitHub Secrets).")
if not DB_URL:
    raise RuntimeError("SUPABASE_DB_URL is missing (set it in .env locally or GitHub Secrets).")

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
        it = dict(zip(cols, row))

        # published_at может быть datetime -> ISO строка
        pa = it.get("published_at")
        if hasattr(pa, "isoformat"):
            it["published_at"] = pa.isoformat()

        # metrics может прийти как dict/None
        if it.get("metrics") is None:
            it["metrics"] = {}

        items.append(it)

    cur.close()
    conn.close()
    return items


def build_prompt(items):
    schema_hint = {
        "date": "YYYY-MM-DD",
        "top_topics": [
            {
                "title": "string",
                "why_now": "string",
                "sources": [{"source": "string", "url": "string", "id": "string"}],
                "keywords": ["string"]
            }
        ],
        "what_is_growing": [
            {
                "signal": "string",
                "evidence": "string",
                "sources": [{"source": "string", "url": "string", "id": "string"}],
                "confidence": 0.0
            }
        ],
        "geofaq_ideas": [
            {
                "idea": "string",
                "format": "question_bank|theory_page|trainer_feature|seo_page|image_task",
                "oge_link": "task_1..30|vpr|olymp|null",
                "why_it_will_work": "string",
                "first_step_tomorrow": "string",
                "inputs_needed": ["string"]
            }
        ],
        "digest": {
            "title": "string",
            "bullets": ["string"],
            "links": [{"title": "string", "url": "string"}]
        }
    }

    return (
        "Ты аналитик GeoFAQ Digest.\n"
        "Твоя задача: по списку материалов за сутки сделать:\n"
        "1) 5 тем дня (top_topics)\n"
        "2) что растёт (what_is_growing)\n"
        "3) идеи для GeoFAQ (geofaq_ideas)\n"
        "4) короткий дайджест (digest)\n\n"
        "ВАЖНО:\n"
        "- НЕЛЬЗЯ выдумывать источники. Каждая тема/сигнал должны ссылаться на входные items.\n"
        "- Возвращай ТОЛЬКО валидный JSON. Без markdown. Без ```.\n"
        "- top_topics ровно 5.\n"
        "- confidence 0..1.\n\n"
        f"Схема результата (пример структуры):\n{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
        f"Сегодняшняя дата (UTC): {datetime.now(timezone.utc).date().isoformat()}\n\n"
        "Вот данные items:\n"
        f"{json.dumps(items, ensure_ascii=False, default=str)}"
    )


def _strip_code_fences(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _repair_json(bad_text: str) -> dict:
    """
    Если модель вернула почти-JSON, просим модель починить.
    """
    repair_prompt = (
        "Исправь текст так, чтобы он стал ВАЛИДНЫМ JSON и СООТВЕТСТВОВАЛ схеме.\n"
        "Верни ТОЛЬКО JSON, без markdown.\n\n"
        f"Текст:\n{bad_text}"
    )
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Return ONLY valid JSON. No markdown."},
            {"role": "user", "content": repair_prompt},
        ],
        temperature=0.0,
    )
    text = _strip_code_fences(resp.choices[0].message.content)
    return json.loads(text)


def analyze_with_ai(items):
    prompt = build_prompt(items)

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Return ONLY valid JSON. No markdown, no code fences."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    text = resp.choices[0].message.content
    text = _strip_code_fences(text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Чиним через второй запрос
        return _repair_json(text)


def render_markdown(result: dict) -> str:
    digest = result.get("digest", {})
    title = digest.get("title") or "GeoFAQ Digest"
    bullets = digest.get("bullets") or []
    links = digest.get("links") or []

    md = f"# {title}\n\n"
    for b in bullets:
        md += f"- {b}\n"

    if links:
        md += "\n## Ссылки\n"
        for l in links:
            if isinstance(l, dict):
                md += f"- {l.get('title','link')}: {l.get('url','')}\n"
            else:
                md += f"- {l}\n"
    return md


def ensure_digest_runs_schema():
    """
    На случай если колонки ещё не добавлены.
    Если у тебя уже миграция выполнена — ничего не сломает (IF NOT EXISTS).
    """
    ddl = """
    alter table content_ai.digest_runs
      add column if not exists run_date date default current_date,
      add column if not exists window interval default interval '24 hours',
      add column if not exists items_count int,
      add column if not exists model text,
      add column if not exists result_json jsonb,
      add column if not exists digest_md text;
    """
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(ddl)
    conn.commit()
    cur.close()
    conn.close()


def save_digest(result_json: dict, digest_md: str, items_count: int):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    insert_query = """
    insert into content_ai.digest_runs
      (run_date, window, items_count, model, result_json, digest_md)
    values
      (%s, interval '24 hours', %s, %s, %s, %s);
    """

    cur.execute(
        insert_query,
        (
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
        print("No items found in last 24h. Exiting.")
        return

    # На всякий случай создаём колонки (не обязательно, но удобно)
    print("Ensuring digest_runs schema...")
    ensure_digest_runs_schema()

    print("Analyzing with AI...")
    result = analyze_with_ai(items)

    print("Rendering markdown...")
    digest_md = render_markdown(result)

    print("Saving to database...")
    save_digest(result, digest_md, len(items))

    print("Done.")


if __name__ == "__main__":
    main()
