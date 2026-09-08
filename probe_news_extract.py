from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import timezone
from pathlib import Path
from urllib.parse import quote_plus

import requests

DEFAULT_QUERIES = [
    "디지털 윤리 학생",
    "미디어 리터러시 학생",
    "딥페이크 학생",
    "생성형 AI 교육 학생",
    "허위정보 가짜뉴스 청소년",
    "사이버폭력 학생",
    "개인정보 청소년 SNS",
]

TOPIC_RULES = {
    "딥페이크": ("딥페이크", "deepfake"),
    "생성형AI": ("생성형 ai", "생성형ai", "챗gpt", "chatgpt", "인공지능"),
    "허위정보": ("허위정보", "가짜뉴스", "허위 조작", "허위조작", "팩트체크"),
    "사이버폭력": ("사이버폭력", "악성댓글", "온라인 괴롭힘", "사이버불링"),
    "개인정보": ("개인정보", "프라이버시", "정보유출"),
    "SNS": ("sns", "소셜미디어", "틱톡", "인스타그램", "유튜브"),
    "저작권": ("저작권", "표절", "무단전재"),
    "정보판별": ("정보 판별", "정보판별", "검증", "팩트체크"),
}

USER_AGENT = "AI-OFF-News-Probe/1.0 (+https://aioff-ai.duckdns.org/)"


def norm(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def google_news_rss(query: str, days: int) -> str:
    q = quote_plus(f"{query} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"


def topic_tags(title: str, summary: str) -> list[str]:
    text = (title + " " + summary).lower()
    out: list[str] = []
    for tag, needles in TOPIC_RULES.items():
        if any(n.lower() in text for n in needles):
            out.append(tag)
    return out


def parse_feed(xml_text: str, query: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    rows: list[dict] = []
    for item in root.findall(".//item"):
        title = norm(item.findtext("title") or "")
        link = norm(item.findtext("link") or "")
        description = norm(item.findtext("description") or "")
        pub_date = norm(item.findtext("pubDate") or "")
        source_el = item.find("source")
        publisher = norm(source_el.text if source_el is not None and source_el.text else "")
        if not title or not link:
            continue

        try:
            dt = email.utils.parsedate_to_datetime(pub_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            published_at = dt.astimezone(timezone.utc).isoformat()
        except Exception:
            published_at = pub_date

        source_key = hashlib.sha1((title + "|" + link).encode("utf-8")).hexdigest()
        rows.append({
            "source_key": source_key,
            "title": title,
            "publisher": publisher,
            "published_at": published_at,
            "url": link,
            "summary": description,
            "matched_queries": [query],
            "topic_tags": topic_tags(title, description),
        })
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description="Probe latest-news extraction without touching any DB")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--query", action="append", dest="queries")
    p.add_argument("--sample", type=int, default=30)
    p.add_argument("--out", default="/tmp/aioff_news_probe.json")
    args = p.parse_args()

    queries = args.queries or DEFAULT_QUERIES
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})

    merged: dict[str, dict] = {}
    query_counts: dict[str, int] = {}

    for query in queries:
        url = google_news_rss(query, args.days)
        r = session.get(url, timeout=30)
        r.raise_for_status()
        rows = parse_feed(r.text, query)
        query_counts[query] = len(rows)
        print(f"query '{query}': {len(rows)}")

        for row in rows:
            old = merged.get(row["source_key"])
            if old:
                old["matched_queries"] = sorted(set(old["matched_queries"] + row["matched_queries"]))
                old["topic_tags"] = sorted(set(old["topic_tags"] + row["topic_tags"]))
            else:
                merged[row["source_key"]] = row
        time.sleep(0.2)

    items = sorted(merged.values(), key=lambda x: x.get("published_at") or "", reverse=True)
    publishers: dict[str, int] = {}
    tags: dict[str, int] = {}
    for item in items:
        publishers[item["publisher"] or "(unknown)"] = publishers.get(item["publisher"] or "(unknown)", 0) + 1
        for tag in item["topic_tags"]:
            tags[tag] = tags.get(tag, 0) + 1

    payload = {
        "days": args.days,
        "query_counts": query_counts,
        "unique_articles": len(items),
        "publisher_counts": dict(sorted(publishers.items(), key=lambda x: (-x[1], x[0]))),
        "topic_tag_counts": dict(sorted(tags.items(), key=lambda x: (-x[1], x[0]))),
        "items": items,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== NEWS PROBE SUMMARY ===")
    print("unique articles:", len(items))
    print("output:", out)
    print("top publishers:", list(payload["publisher_counts"].items())[:10])
    print("topic tags:", payload["topic_tag_counts"])

    print("\n=== NEWS SAMPLE ===")
    for i, item in enumerate(items[: max(0, args.sample)], start=1):
        print(f"[{i}] {item['published_at']} | {item['publisher']} | {item['title']}")
        print("    tags   :", ", ".join(item["topic_tags"]) or "-")
        print("    queries:", ", ".join(item["matched_queries"]))
        print("    summary:", item["summary"][:280])
        print("    url    :", item["url"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
