"""
Разведка контента для канала Рыжа: публичные ленты t.me/s/<канал> → посты, снапшоты
просмотров и реакций → посты-выбросы. Вызывается вьюхой content_scout
(эндпоинт /api/content/scout), которую по HTTP+X-Cron-Secret дёргает n8n (Ryzh_Scout).

Таблицы content_* живут в схеме ryzh-content/sql/schema.sql — Django о них не знает
(как reels_* и vocab_*), работаем сырым SQL. LLM здесь не вызывается: из выбросов
темы формулирует n8n и сам кладёт их в ryzh_topics.

Выброс — пост возрастом от 2 до 10 суток, который обогнал медиану своего канала
(посты 2–21 суток) в OUTLIER_X раз по просмотрам ИЛИ по доле реакций. Посты моложе
двух суток не берём: свежий пост ещё не добрал просмотры и выглядит провалом.

Ответ:
{"ok": true,
 "sources": [{"username", "posts", "median_views", "error"}],   # по каждому каналу
 "outliers": [{"source", "post_no", "url", "text", "views", "reactions",
               "score", "posted_at"}]}                          # по убыванию score
"""
import html
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from django.db import connection

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"
PAGES = 2               # t.me/s отдаёт ~20 постов на страницу; двух хватает на 2–3 недели
OUTLIER_X = 1.5         # во сколько раз обогнать медиану канала; при ×2 у 19 доноров
                        # выходило ~1.4 выброса в день — после отсева LLM меньше поста
MIN_REACTIONS = 10      # доля реакций на 3 реакциях — шум
MAX_OUTLIERS = 8        # столько тем LLM разбирает за прогон
NOSIGNAL_PENALTY = 0.5  # штраф к score каналов с подозрением на накрутку


def _get(url):
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=20) as r:
            return r.read().decode("utf-8", "ignore")
    except OSError:
        return ""  # канал недоступен — scout запишет его в report и пойдёт дальше


def _num(s):
    """'12.3K' → 12300, '1,2M' → 1200000, '845' → 845."""
    s = (s or "").strip().replace(" ", "").replace(",", ".")
    mult = {"K": 1e3, "M": 1e6}
    if s and s[-1] in mult:
        return int(float(s[:-1]) * mult[s[-1]])
    return int(float(s or 0))


def _parse(page):
    posts = []
    for blk in page.split('<div class="tgme_widget_message_wrap')[1:]:
        pid = re.search(r'data-post="[^"/]+/(\d+)"', blk)
        views = re.search(r'tgme_widget_message_views">([^<]+)<', blk)
        when = re.search(r'<time datetime="([^"]+)"', blk)
        if not (pid and views and when):
            continue  # служебные сообщения и посты без счётчика
        txt = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', blk, re.S)
        text = ""
        if txt:
            text = re.sub(r"<br\s*/?>", "\n", txt.group(1))
            text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        reactions = sum(_num(x) for x in re.findall(
            r'tgme_reaction[^>]*>.*?</i>\s*([\d.,KM]+)', blk, re.S))
        posts.append({
            "post_no": int(pid.group(1)),
            "views": _num(views.group(1)),
            "reactions": reactions,
            "posted_at": datetime.fromisoformat(when.group(1)),
            "text": text,
            "has_photo": "tgme_widget_message_photo" in blk,
        })
    return posts


def fetch_channel(username):
    """Последние ~PAGES*20 постов канала. Пустой список — канал не отдал ленту."""
    posts = _parse(_get(f"https://t.me/s/{username}"))
    for _ in range(PAGES - 1):
        if not posts:
            break
        older = _parse(_get(f"https://t.me/s/{username}?before={min(p['post_no'] for p in posts)}"))
        if not older:
            break
        posts = older + posts
    return {p["post_no"]: p for p in posts}.values()  # страницы иногда перекрываются


def _age_days(p, now):
    return (now - p["posted_at"]).total_seconds() / 86400


def find_outliers(posts, now, signal=True):
    """Выбросы канала: (пост, score). Медиана — по постам 2–21 суток."""
    aged = [p for p in posts if 2 <= _age_days(p, now) <= 21 and p["views"]]
    if len(aged) < 5:
        return [], None  # мало данных — медиана врёт
    med_views = statistics.median(p["views"] for p in aged)
    med_rr = statistics.median(p["reactions"] / p["views"] for p in aged)
    out = []
    for p in aged:
        if _age_days(p, now) > 10:
            continue
        x_views = p["views"] / med_views if med_views else 0
        x_rr = (p["reactions"] / p["views"]) / med_rr if med_rr and p["reactions"] >= MIN_REACTIONS else 0
        score = max(x_views, x_rr)
        if score >= OUTLIER_X:
            out.append((p, round(score * (1 if signal else NOSIGNAL_PENALTY), 2)))
    return out, med_views


def _save(cur, username, posts, now):
    for p in posts:
        cur.execute(
            """INSERT INTO content_source_posts (source, post_no, posted_at, text, has_photo)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (source, post_no) DO UPDATE SET text = EXCLUDED.text""",
            [username, p["post_no"], p["posted_at"], p["text"], p["has_photo"]])
        cur.execute(
            """INSERT INTO content_post_snapshots (source, post_no, captured_at, views, reactions)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            [username, p["post_no"], now, p["views"], p["reactions"]])


def scout():
    now = datetime.now(timezone.utc)
    with connection.cursor() as cur:
        cur.execute("SELECT username, is_own, signal FROM content_sources WHERE active")
        sources = cur.fetchall()

    # сеть — параллельно (20 каналов × 2 страницы последовательно не влезают в таймаут gunicorn)
    with ThreadPoolExecutor(4) as ex:
        fetched = dict(zip([s[0] for s in sources], ex.map(lambda s: list(fetch_channel(s[0])), sources)))

    report, candidates = [], []
    with connection.cursor() as cur:
        for username, is_own, signal in sources:
            posts = fetched[username]
            if not posts:
                report.append({"username": username, "posts": 0, "median_views": None,
                               "error": "лента не отдалась"})
                continue
            _save(cur, username, posts, now)
            if is_own:
                report.append({"username": username, "posts": len(posts), "median_views": None,
                               "error": None})
                continue
            outs, med = find_outliers(posts, now, signal)
            report.append({"username": username, "posts": len(posts), "median_views": med,
                           "error": None})
            candidates += [(username, p, score) for p, score in outs]

        # уже отданные посты второй раз не берём
        fresh = []
        for username, p, score in candidates:
            cur.execute("SELECT offered_at FROM content_source_posts WHERE source = %s AND post_no = %s",
                        [username, p["post_no"]])
            row = cur.fetchone()
            if row and row[0] is None and p["text"]:
                fresh.append((username, p, score))
        fresh.sort(key=lambda c: -c[2])
        fresh = fresh[:MAX_OUTLIERS]
        for username, p, _ in fresh:
            cur.execute("UPDATE content_source_posts SET offered_at = %s WHERE source = %s AND post_no = %s",
                        [now, username, p["post_no"]])

    return {
        "ok": True,
        "sources": report,
        "outliers": [{
            "source": u,
            "post_no": p["post_no"],
            "url": f"https://t.me/{u}/{p['post_no']}",
            "text": p["text"][:2500],
            "views": p["views"],
            "reactions": p["reactions"],
            "score": score,
            "posted_at": p["posted_at"].isoformat(),
        } for u, p, score in fresh],
    }

