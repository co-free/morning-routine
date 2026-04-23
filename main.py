"""
朝刊ダイジェスト - 個人事業用
毎朝7:00 JST にSlackへ配信

配信内容：
1. 今日の予定（Googleカレンダー）
2. 国内ニュース（NHK・日経・朝日・毎日等）
3. AIニュース（TechCrunch・The Verge・Anthropic等）
4. 中学受験理科トピック（気象庁・国立天文台・理科系RSS）
"""

import os
import json
import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import requests

# ─── 設定 ───────────────────────────────────────────────
JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY_STR = NOW.strftime("%Y年%-m月%-d日（%a）").replace(
    "Mon", "月").replace("Tue", "火").replace("Wed", "水").replace(
    "Thu", "木").replace("Fri", "金").replace("Sat", "土").replace("Sun", "日")
TOMORROW = NOW + timedelta(days=1)
TOMORROW_STR = TOMORROW.strftime("%Y年%-m月%-d日（%a）").replace(
    "Mon", "月").replace("Tue", "火").replace("Wed", "水").replace(
    "Thu", "木").replace("Fri", "金").replace("Sat", "土").replace("Sun", "日")

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
GCAL_API_KEY = os.environ.get("GCAL_API_KEY", "")
GCAL_IDS = os.environ.get("GCAL_IDS", "").split(",")  # カンマ区切りで複数カレンダー

SEEN_FILE = Path("data/seen.json")
MAX_ARTICLES_PER_CATEGORY = 4
MAX_PER_SOURCE = 2

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── RSSソース定義 ──────────────────────────────────────
RSS_SOURCES = [
    # 【国内ニュース】
    {"url": "https://www3.nhk.or.jp/rss/news/cat0.xml",       "category": "domestic", "name": "NHK"},
    {"url": "https://www3.nhk.or.jp/rss/news/cat4.xml",       "category": "domestic", "name": "NHK科学"},
    {"url": "https://www3.nhk.or.jp/rss/news/cat6.xml",       "category": "domestic", "name": "NHK政治"},
    {"url": "https://feeds.japan.cnet.com/rss/cnet/all.rdf",  "category": "domestic", "name": "CNET Japan"},
    {"url": "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml", "category": "domestic", "name": "ITmedia"},
    {"url": "https://www.asahi.com/rss/asahi/newsheadlines.rdf", "category": "domestic", "name": "朝日新聞"},
    {"url": "https://mainichi.jp/rss/etc/mainichi-flash.rss",  "category": "domestic", "name": "毎日新聞"},
    {"url": "https://www.yomiuri.co.jp/feed/",                 "category": "domestic", "name": "読売新聞"},

    # 【AIニュース】
    {"url": "https://techcrunch.com/category/artificial-intelligence/feed/", "category": "ai", "name": "TechCrunch AI",
     "keywords": ["AI", "LLM", "GPT", "Claude", "Gemini", "artificial intelligence", "machine learning", "OpenAI", "Anthropic", "Google", "Meta AI"]},
    {"url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "category": "ai", "name": "The Verge AI",
     "keywords": ["AI", "LLM", "model", "OpenAI", "Anthropic", "Google", "Meta", "chatbot"]},
    {"url": "https://feeds.feedburner.com/venturebeat/SZYF",   "category": "ai", "name": "VentureBeat AI",
     "keywords": ["AI", "LLM", "generative", "model", "OpenAI", "Anthropic", "Claude", "Gemini"]},
    {"url": "https://gigazine.net/news/rss_2.0/",              "category": "ai", "name": "GIGAZINE AI",
     "keywords": ["AI", "人工知能", "ChatGPT", "Claude", "Gemini", "LLM", "生成AI", "OpenAI", "Anthropic"],
     "excludes": ["マラソン", "風呂", "食べ物", "グルメ", "映画", "アニメ", "ゲーム", "スポーツ", "ファッション"]},
    {"url": "https://japan.zdnet.com/rss/index.rdf",           "category": "ai", "name": "ZDNet Japan AI",
     "keywords": ["AI", "人工知能", "生成AI", "LLM", "ChatGPT", "Claude", "Gemini"]},
    {"url": "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml",   "category": "ai", "name": "ITmedia AI+"},

    # 【中学受験理科トピック：天文・気象・自然科学】
    {"url": "https://www.astroarts.co.jp/article/rss.rdf",    "category": "rika", "name": "アストロアーツ"},
    {"url": "https://www.nao.ac.jp/atom.xml",                  "category": "rika", "name": "国立天文台"},
    {"url": "https://www.jaxa.jp/rss/topics_j.rdf",           "category": "rika", "name": "JAXA"},
    {"url": "https://scienceportal.jst.go.jp/feed/",          "category": "rika", "name": "サイエンスポータル"},
    {"url": "https://natgeo.nikkeibp.co.jp/atcl/rss/all.rdf", "category": "rika", "name": "ナショジオ"},
    {"url": "https://www.nhk.or.jp/rss/science-human.rss",    "category": "rika", "name": "NHK科学"},
]

RIKA_KEYWORDS = [
    "地震", "津波", "火山", "噴火", "台風", "大雨", "洪水", "土砂", "竜巻",
    "天文", "星", "惑星", "彗星", "流星", "月食", "日食", "オーロラ", "太陽",
    "宇宙", "探査機", "ロケット", "ISS", "気候", "温暖化", "生態系", "絶滅",
    "化石", "恐竜", "深海", "プレート", "マグマ", "環境", "気象", "天気",
]

# ─── Googleカレンダー取得 ────────────────────────────────
def fetch_google_calendar():
    """今日・明日の予定をGoogleカレンダーから取得（APIキー方式）"""
    if not GCAL_API_KEY or not GCAL_IDS[0]:
        log.warning("GCAL設定なし。カレンダーをスキップします。")
        return {"today": [], "tomorrow": []}

    def _fetch_day(day: datetime) -> list:
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        day_end   = day.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        events = []
        for cal_id in GCAL_IDS:
            cal_id = cal_id.strip()
            if not cal_id:
                continue
            url = (
                f"https://www.googleapis.com/calendar/v3/calendars/{requests.utils.quote(cal_id, safe='')}"
                f"/events?key={GCAL_API_KEY}"
                f"&timeMin={requests.utils.quote(day_start)}"
                f"&timeMax={requests.utils.quote(day_end)}"
                f"&singleEvents=true&orderBy=startTime"
            )
            try:
                res = requests.get(url, timeout=10)
                res.raise_for_status()
                items = res.json().get("items", [])
                for item in items:
                    start = item.get("start", {})
                    time_str = start.get("dateTime", start.get("date", ""))
                    if "T" in time_str:
                        dt = datetime.fromisoformat(time_str).astimezone(JST)
                        time_label = dt.strftime("%-H:%M")
                    else:
                        time_label = "終日"
                    events.append({
                        "title": item.get("summary", "（タイトルなし）"),
                        "time": time_label,
                        "calendar": cal_id,
                    })
                log.info(f"カレンダー {cal_id} ({day.date()}): {len(items)}件取得")
            except Exception as e:
                log.error(f"カレンダー取得エラー {cal_id}: {e}")
        events.sort(key=lambda x: ("99:99" if x["time"] == "終日" else x["time"]))
        return events

    return {
        "today":    _fetch_day(NOW),
        "tomorrow": _fetch_day(TOMORROW),
    }


# ─── RSS収集 ────────────────────────────────────────────
def fetch_rss(source):
    try:
        feed = feedparser.parse(source["url"])
        articles = []
        source_count = 0
        for entry in feed.entries[:30]:
            if source_count >= MAX_PER_SOURCE:
                break
            title = entry.get("title", "")
            link  = entry.get("link", "")
            summary = entry.get("summary", "")[:300]

            # キーワードフィルタ
            keywords = source.get("keywords", [])
            if keywords:
                text = title + summary
                if not any(kw.lower() in text.lower() for kw in keywords):
                    continue

            # 除外キーワード
            excludes = source.get("excludes", [])
            if excludes and any(ex in title for ex in excludes):
                continue

            # 理科カテゴリ：理科関連キーワードが含まれるもののみ
            if source["category"] == "rika":
                if not any(kw in title + summary for kw in RIKA_KEYWORDS):
                    continue

            articles.append({
                "title": title,
                "link": link,
                "summary": summary,
                "category": source["category"],
                "source": source["name"],
            })
            source_count += 1
        return articles
    except Exception as e:
        log.error(f"RSS取得エラー {source['name']}: {e}")
        return []


def collect_all_articles():
    all_articles = []
    for source in RSS_SOURCES:
        articles = fetch_rss(source)
        all_articles.extend(articles)
        log.info(f"{source['name']}: {len(articles)}件")
    return all_articles


# ─── 重複排除 ────────────────────────────────────────────
def url_hash(url):
    return hashlib.md5(url.encode()).hexdigest()

def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()).get("seen", []))
    return set()

def save_seen(seen):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    cutoff = NOW - timedelta(days=7)
    SEEN_FILE.write_text(json.dumps({"seen": list(seen)[-500:]}, ensure_ascii=False, indent=2))

def deduplicate(articles, seen):
    result = []
    for a in articles:
        h = url_hash(a["link"])
        if h not in seen:
            seen.add(h)
            result.append(a)
    return result


# ─── Groq要約 ────────────────────────────────────────────
def groq_summarize(articles_by_category):
    """カテゴリごとに記事リストを渡してまとめて要約"""
    results = {}
    for category, articles in articles_by_category.items():
        if not articles:
            results[category] = []
            continue
        items_text = "\n".join(
            f"- [{a['source']}] {a['title']}\n  {a['summary']}"
            for a in articles[:MAX_ARTICLES_PER_CATEGORY]
        )
        prompt = f"""以下のニュース記事を必ず日本語で要約してください。
英語の記事も全て日本語に翻訳して要約すること。
各記事について以下の形式で出力してください：
- タイトル：日本語に翻訳したタイトル
- 要約：1〜2文で簡潔に（です・ます調）

カテゴリ: {category}
記事:
{items_text}

出力形式（JSONで返してください）:
{{"items": [{{"title": "...", "summary": "...", "source": "..."}}]}}"""

        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                },
                timeout=30,
            )
            content = res.json()["choices"][0]["message"]["content"]
            # JSON抽出
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                # 元のリンクを付与
                link_map = {a["title"]: a["link"] for a in articles}
                for item in data.get("items", []):
                    item["link"] = link_map.get(item["title"], "")
                results[category] = data.get("items", [])
            else:
                results[category] = [{"title": a["title"], "summary": a["summary"], "link": a["link"], "source": a["source"]} for a in articles[:MAX_ARTICLES_PER_CATEGORY]]
        except Exception as e:
            log.error(f"Groq要約エラー ({category}): {e}")
            results[category] = [{"title": a["title"], "summary": a["summary"][:100], "link": a["link"], "source": a["source"]} for a in articles[:MAX_ARTICLES_PER_CATEGORY]]

    return results


# ─── Slackメッセージ構築 ─────────────────────────────────
def build_slack_message(events, summarized):
    blocks = []

    # ヘッダー
    blocks.append({"type": "header", "text": {"type": "plain_text", "text": f"☀️ おはようございます｜{TODAY_STR}"}})
    blocks.append({"type": "divider"})

    # 📅 今日の予定
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*📅 今日の予定*"}})
    today_events = events.get("today", [])
    if today_events:
        event_lines = "\n".join(f"• `{e['time']}` {e['title']}" for e in today_events)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": event_lines}})
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "予定なし"}})

    # 📅 明日の予定
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*📅 明日の予定（{TOMORROW_STR}）*"}})
    tomorrow_events = events.get("tomorrow", [])
    if tomorrow_events:
        event_lines = "\n".join(f"• `{e['time']}` {e['title']}" for e in tomorrow_events)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": event_lines}})
    else:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "予定なし"}})
    blocks.append({"type": "divider"})

    # カテゴリ設定
    categories = [
        ("domestic", "📰 国内ニュース"),
        ("ai",       "🤖 AIニュース"),
        ("rika",     "🔭 理科トピック（中学受験）"),
    ]

    for cat_key, cat_label in categories:
        items = summarized.get(cat_key, [])
        if not items:
            if cat_key == "rika":
                continue  # 理科は該当なしなら非表示
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{cat_label}*\n該当なし"}})
            blocks.append({"type": "divider"})
            continue

        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{cat_label}*"}})
        for i, item in enumerate(items, 1):
            title = item.get("title", "")
            summary = item.get("summary", "")
            link = item.get("link", "")
            source = item.get("source", "")
            link_text = f"<{link}|{title}>" if link else title
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{i}. {link_text}\n　{summary}　_({source})_"}
            })
        blocks.append({"type": "divider"})

    # フッター
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"配信時刻: {NOW.strftime('%H:%M JST')} ｜ python348/morning-routine"}]
    })

    return {"blocks": blocks}


def post_to_slack(message):
    res = requests.post(SLACK_WEBHOOK_URL, json=message, timeout=10)
    if res.status_code == 200:
        log.info("Slack投稿成功")
    else:
        log.error(f"Slack投稿失敗: {res.status_code} {res.text}")
        raise RuntimeError("Slack投稿失敗")


# ─── メイン ─────────────────────────────────────────────
def main():
    log.info(f"=== 朝刊ダイジェスト開始 {NOW.isoformat()} ===")

    # 1. カレンダー取得
    events = fetch_google_calendar()
    log.info(f"予定: 今日{len(events['today'])}件 / 明日{len(events['tomorrow'])}件")

    # 2. RSS収集
    articles = collect_all_articles()
    log.info(f"収集: {len(articles)}件")

    # 3. 重複排除
    seen = load_seen()
    articles = deduplicate(articles, seen)
    log.info(f"重複排除後: {len(articles)}件")

    # 4. カテゴリ別に分類
    by_category = {"domestic": [], "ai": [], "rika": []}
    source_counts = {}
    for a in articles:
        cat = a["category"]
        src = a["source"]
        if cat not in by_category:
            continue
        if source_counts.get((cat, src), 0) >= MAX_PER_SOURCE:
            continue
        if len(by_category[cat]) < MAX_ARTICLES_PER_CATEGORY:
            by_category[cat].append(a)
            source_counts[(cat, src)] = source_counts.get((cat, src), 0) + 1

    # 5. Groq要約
    summarized = groq_summarize(by_category)

    # 6. Slack投稿
    message = build_slack_message(events, summarized)
    post_to_slack(message)

    # 7. 重複排除データ保存
    save_seen(seen)
    log.info("=== 完了 ===")


if __name__ == "__main__":
    main()
