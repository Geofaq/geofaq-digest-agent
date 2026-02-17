import os
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# -----------------------------
# Определяем дату отчёта
# -----------------------------
if len(sys.argv) > 1:
    report_date = sys.argv[1]
else:
    report_date = datetime.utcnow().date().isoformat()

date_start = datetime.fromisoformat(report_date).replace(tzinfo=timezone.utc)
date_end = date_start + timedelta(days=1)

# -----------------------------
# Получаем raw за день
# -----------------------------
raw_today = (
    sb.schema("content_ai")
      .table("raw_items")
      .select("id", count="exact")
      .gte("published_at", date_start.isoformat())
      .lt("published_at", date_end.isoformat())
      .execute()
)

raw_count = raw_today.count or 0

# -----------------------------
# Получаем processed
# -----------------------------
processed_query = (
    sb.schema("content_ai")
      .table("processed_items")
      .select("engagement_index, theme_cluster, content_format, summary, raw_id")
      .execute()
)

processed_filtered = []

for item in processed_query.data:

    raw = (
        sb.schema("content_ai")
          .table("raw_items")
          .select("published_at, url, text")
          .eq("id", item["raw_id"])
          .single()
          .execute()
    )

    published = datetime.fromisoformat(
        raw.data["published_at"].replace("Z", "+00:00")
    )

    if date_start <= published < date_end:
        item["url"] = raw.data["url"]
        item["text"] = raw.data["text"]
        processed_filtered.append(item)

# -----------------------------
# Средний engagement
# -----------------------------
values = [
    x["engagement_index"]
    for x in processed_filtered
    if x["engagement_index"] is not None
]

avg_engagement = round(sum(values) / len(values), 4) if values else 0

# -----------------------------
# Топ-5
# -----------------------------
top_posts = sorted(
    processed_filtered,
    key=lambda x: x["engagement_index"] or 0,
    reverse=True
)[:5]

# -----------------------------
# Формируем отчёт
# -----------------------------
report = f"""# Daily Report — {report_date}

## 📊 Общие цифры
- Постов собрано: {raw_count}
- Проанализировано: {len(processed_filtered)}
- Средний engagement: {avg_engagement}

## 🔥 Топ-5 постов
"""

for i, post in enumerate(top_posts, 1):

    full_text = post["text"] or ""
    preview = full_text[:500] + "..." if len(full_text) > 500 else full_text

    report += f"""
---

### {i}. {post['theme_cluster']}

**Формат:** {post['content_format']}  
**Engagement:** {round(post['engagement_index'],4)}  

🔗 [Открыть пост]({post['url']})

**Краткий анализ:**  
{post['summary']}

**Фрагмент текста:**  
{preview}

"""

# -----------------------------
# Сохраняем файл
# -----------------------------
os.makedirs("reports", exist_ok=True)

filename = f"reports/{report_date}_daily.md"

with open(filename, "w", encoding="utf-8") as f:
    f.write(report)

print(f"Daily report saved: {filename}")