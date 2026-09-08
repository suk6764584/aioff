from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from education_db import EducationDB
from news_db import NewsDB


def main() -> int:
    root = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description="Link news to age-specific education chunks by vector similarity")
    p.add_argument("--education-db", default=str(root / "data" / "education" / "education.db"))
    p.add_argument("--news-db", default=str(root / "data" / "news" / "news.db"))
    p.add_argument("--embed-model", default=os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001"))
    p.add_argument("--top-k", type=int, default=3)
    args = p.parse_args()

    edu = EducationDB(args.education_db)
    news = NewsDB(args.news_db)
    articles = news.embedded_articles(args.embed_model)
    if not articles:
        raise SystemExit("No embedded news articles. Run build_news_db.py --embed first.")

    levels = ("초등", "중등", "고등")
    for i, article in enumerate(articles, start=1):
        vec = article["embedding_values"]
        for level in levels:
            matches = edu.search_vector(vec, target=level, limit=args.top_k, model=args.embed_model)
            news.replace_links(article["id"], level, matches)
        if i % 20 == 0:
            print(f"linked {i}/{len(articles)}")

    print(json.dumps({"education": edu.status(), "news": news.status()}, ensure_ascii=False, indent=2))
    edu.close()
    news.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
