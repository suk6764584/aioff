from __future__ import annotations

import json
import math
import sqlite3
import struct
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "news" / "news.db"


def _pack_vector(values: Iterable[float]) -> bytes:
    vals = [float(v) for v in values]
    return struct.pack(f"<{len(vals)}f", *vals)


def _unpack_vector(blob: bytes | None) -> list[float]:
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else -1.0


class NewsDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or DEFAULT_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self):
        self.conn.close()

    def _init_schema(self):
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                publisher TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                matched_queries_json TEXT NOT NULL DEFAULT '[]',
                topic_tags_json TEXT NOT NULL DEFAULT '[]',
                embedding_model TEXT NOT NULL DEFAULT '',
                embedding_dim INTEGER,
                embedding BLOB,
                collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
            CREATE INDEX IF NOT EXISTS idx_articles_embedding_model ON articles(embedding_model);

            CREATE TABLE IF NOT EXISTS education_links (
                news_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                level TEXT NOT NULL,
                education_chunk_id INTEGER NOT NULL,
                education_title TEXT NOT NULL DEFAULT '',
                education_target TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(news_id, level, education_chunk_id)
            );
            """
        )
        self.conn.commit()

    def upsert_article(self, row: dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO articles(source_key,title,publisher,published_at,url,summary,matched_queries_json,topic_tags_json,updated_at)
            VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(source_key) DO UPDATE SET
              title=excluded.title,
              publisher=excluded.publisher,
              published_at=excluded.published_at,
              url=excluded.url,
              summary=excluded.summary,
              matched_queries_json=excluded.matched_queries_json,
              topic_tags_json=excluded.topic_tags_json,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                row["source_key"], row["title"], row.get("publisher", ""), row.get("published_at", ""),
                row["url"], row.get("summary", ""), json.dumps(row.get("matched_queries") or [], ensure_ascii=False),
                json.dumps(row.get("topic_tags") or [], ensure_ascii=False),
            ),
        )
        article_id = self.conn.execute("SELECT id FROM articles WHERE source_key=?", (row["source_key"],)).fetchone()[0]
        self.conn.commit()
        return int(article_id)

    def missing_embeddings(self, model: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT id,title,summary FROM articles WHERE embedding IS NULL OR embedding_model<>? ORDER BY id", (model,)
        ).fetchall()]

    def set_embedding(self, article_id: int, model: str, values: list[float]) -> None:
        self.conn.execute(
            "UPDATE articles SET embedding_model=?,embedding_dim=?,embedding=? WHERE id=?",
            (model, len(values), _pack_vector(values), article_id),
        )
        self.conn.commit()

    def embedded_articles(self, model: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id,title,publisher,published_at,url,summary,topic_tags_json,embedding_model,embedding FROM articles WHERE embedding IS NOT NULL"
        params: list[Any] = []
        if model:
            sql += " AND embedding_model=?"
            params.append(model)
        out = []
        for row in self.conn.execute(sql, params).fetchall():
            d = dict(row)
            d["embedding_values"] = _unpack_vector(d.pop("embedding"))
            out.append(d)
        return out

    def replace_links(self, news_id: int, level: str, rows: list[dict[str, Any]]) -> None:
        self.conn.execute("DELETE FROM education_links WHERE news_id=? AND level=?", (news_id, level))
        for row in rows:
            self.conn.execute(
                "INSERT INTO education_links(news_id,level,education_chunk_id,education_title,education_target,score) VALUES(?,?,?,?,?,?)",
                (news_id, level, row["id"], row.get("title", ""), row.get("target", ""), float(row["score"])),
            )
        self.conn.commit()

    def status(self) -> dict[str, Any]:
        articles = self.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        embedded = self.conn.execute("SELECT COUNT(*) FROM articles WHERE embedding IS NOT NULL").fetchone()[0]
        links = self.conn.execute("SELECT COUNT(*) FROM education_links").fetchone()[0]
        return {"path": str(self.path), "articles": articles, "embedded_articles": embedded, "education_links": links}
