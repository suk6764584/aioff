from __future__ import annotations

import json
import math
import sqlite3
import struct
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "education" / "education.db"


def _pack_vector(values: Iterable[float]) -> bytes:
    vals = [float(v) for v in values]
    return struct.pack(f"<{len(vals)}f", *vals)


def _unpack_vector(blob: bytes | None) -> list[float]:
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return -1.0
    return dot / (na * nb)


class EducationDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or DEFAULT_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS materials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                year TEXT NOT NULL DEFAULT '',
                material_type TEXT NOT NULL DEFAULT '',
                topics_json TEXT NOT NULL DEFAULT '[]',
                source_url TEXT NOT NULL DEFAULT '',
                list_page INTEGER,
                collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                download_url TEXT NOT NULL DEFAULT '',
                action_raw TEXT NOT NULL DEFAULT '',
                local_path TEXT NOT NULL DEFAULT '',
                sha256 TEXT NOT NULL DEFAULT '',
                byte_size INTEGER,
                mime_type TEXT NOT NULL DEFAULT '',
                extraction_status TEXT NOT NULL DEFAULT 'pending',
                extraction_error TEXT NOT NULL DEFAULT '',
                UNIQUE(material_id, filename, download_url)
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
                attachment_id INTEGER REFERENCES attachments(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                section TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                topics_json TEXT NOT NULL DEFAULT '[]',
                title TEXT NOT NULL DEFAULT '',
                embedding_model TEXT NOT NULL DEFAULT '',
                embedding_dim INTEGER,
                embedding BLOB,
                UNIQUE(attachment_id, chunk_index)
            );

            CREATE INDEX IF NOT EXISTS idx_materials_target ON materials(target);
            CREATE INDEX IF NOT EXISTS idx_materials_year ON materials(year);
            CREATE INDEX IF NOT EXISTS idx_chunks_material ON chunks(material_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_target ON chunks(target);
            CREATE INDEX IF NOT EXISTS idx_chunks_embedding_model ON chunks(embedding_model);

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                text,
                title,
                target,
                topics,
                content=''
            );
            """
        )
        self.conn.commit()

    def upsert_material(self, row: dict[str, Any]) -> int:
        topics_json = json.dumps(row.get("topics") or [], ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO materials(source_key,title,target,year,material_type,topics_json,source_url,list_page,updated_at)
            VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(source_key) DO UPDATE SET
              title=excluded.title,
              target=excluded.target,
              year=excluded.year,
              material_type=excluded.material_type,
              topics_json=excluded.topics_json,
              source_url=excluded.source_url,
              list_page=excluded.list_page,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                row["source_key"], row["title"], row.get("target", ""), row.get("year", ""),
                row.get("material_type", ""), topics_json, row.get("source_url", ""), row.get("list_page"),
            ),
        )
        material_id = self.conn.execute("SELECT id FROM materials WHERE source_key=?", (row["source_key"],)).fetchone()[0]
        self.conn.commit()
        return int(material_id)

    def upsert_attachment(self, material_id: int, row: dict[str, Any]) -> int:
        self.conn.execute(
            """
            INSERT INTO attachments(material_id,filename,download_url,action_raw,local_path,sha256,byte_size,mime_type,extraction_status,extraction_error)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(material_id,filename,download_url) DO UPDATE SET
              action_raw=excluded.action_raw,
              local_path=CASE WHEN excluded.local_path<>'' THEN excluded.local_path ELSE attachments.local_path END,
              sha256=CASE WHEN excluded.sha256<>'' THEN excluded.sha256 ELSE attachments.sha256 END,
              byte_size=COALESCE(excluded.byte_size, attachments.byte_size),
              mime_type=CASE WHEN excluded.mime_type<>'' THEN excluded.mime_type ELSE attachments.mime_type END,
              extraction_status=excluded.extraction_status,
              extraction_error=excluded.extraction_error
            """,
            (
                material_id, row.get("filename", ""), row.get("download_url", ""), row.get("action_raw", ""),
                row.get("local_path", ""), row.get("sha256", ""), row.get("byte_size"), row.get("mime_type", ""),
                row.get("extraction_status", "pending"), row.get("extraction_error", ""),
            ),
        )
        attachment_id = self.conn.execute(
            "SELECT id FROM attachments WHERE material_id=? AND filename=? AND download_url=?",
            (material_id, row.get("filename", ""), row.get("download_url", "")),
        ).fetchone()[0]
        self.conn.commit()
        return int(attachment_id)

    def replace_chunks(self, material_id: int, attachment_id: int, chunks: list[dict[str, Any]], *, title: str, target: str, topics: list[str]) -> None:
        old_ids = [r[0] for r in self.conn.execute("SELECT id FROM chunks WHERE attachment_id=?", (attachment_id,)).fetchall()]
        for chunk_id in old_ids:
            self.conn.execute("DELETE FROM chunks_fts WHERE rowid=?", (chunk_id,))
        self.conn.execute("DELETE FROM chunks WHERE attachment_id=?", (attachment_id,))
        topics_json = json.dumps(topics, ensure_ascii=False)
        topics_text = " ".join(topics)
        for idx, chunk in enumerate(chunks):
            cur = self.conn.execute(
                """
                INSERT INTO chunks(material_id,attachment_id,chunk_index,page_start,page_end,section,text,target,topics_json,title)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    material_id, attachment_id, idx, chunk.get("page_start"), chunk.get("page_end"),
                    chunk.get("section", ""), chunk["text"], target, topics_json, title,
                ),
            )
            chunk_id = int(cur.lastrowid)
            self.conn.execute(
                "INSERT INTO chunks_fts(rowid,text,title,target,topics) VALUES(?,?,?,?,?)",
                (chunk_id, chunk["text"], title, target, topics_text),
            )
        self.conn.commit()

    def set_attachment_extraction(self, attachment_id: int, status: str, error: str = "") -> None:
        self.conn.execute(
            "UPDATE attachments SET extraction_status=?, extraction_error=? WHERE id=?",
            (status, error[:2000], attachment_id),
        )
        self.conn.commit()

    def chunks_missing_embeddings(self, model: str, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id,title,text FROM chunks WHERE embedding IS NULL OR embedding_model<>? ORDER BY id"
        params: list[Any] = [model]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def set_chunk_embedding(self, chunk_id: int, model: str, values: list[float]) -> None:
        self.conn.execute(
            "UPDATE chunks SET embedding_model=?, embedding_dim=?, embedding=? WHERE id=?",
            (model, len(values), _pack_vector(values), chunk_id),
        )
        self.conn.commit()

    def search_fts(self, query: str, target: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        tokens = [t for t in query.replace('"', ' ').split() if t]
        if not tokens:
            return []
        match = " OR ".join(f'"{t}"' for t in tokens)
        sql = """
        SELECT c.*, bm25(chunks_fts) AS rank
        FROM chunks_fts
        JOIN chunks c ON c.id=chunks_fts.rowid
        WHERE chunks_fts MATCH ?
        """
        params: list[Any] = [match]
        if target:
            sql += " AND c.target LIKE ?"
            params.append(f"%{target}%")
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def search_vector(self, query_vector: list[float], target: str | None = None, limit: int = 8, model: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id,material_id,attachment_id,chunk_index,page_start,page_end,section,text,target,topics_json,title,embedding_model,embedding FROM chunks WHERE embedding IS NOT NULL"
        params: list[Any] = []
        if target:
            sql += " AND target LIKE ?"
            params.append(f"%{target}%")
        if model:
            sql += " AND embedding_model=?"
            params.append(model)
        rows = []
        for row in self.conn.execute(sql, params).fetchall():
            d = dict(row)
            d["score"] = _cosine(query_vector, _unpack_vector(d.pop("embedding")))
            rows.append(d)
        rows.sort(key=lambda x: x["score"], reverse=True)
        return rows[:limit]

    def status(self) -> dict[str, Any]:
        material_count = self.conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        attachment_count = self.conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
        chunk_count = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        embedded_count = self.conn.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
        unresolved_downloads = self.conn.execute("SELECT COUNT(*) FROM attachments WHERE download_url='' ").fetchone()[0]
        return {
            "path": str(self.path),
            "materials": material_count,
            "attachments": attachment_count,
            "chunks": chunk_count,
            "embedded_chunks": embedded_count,
            "unresolved_downloads": unresolved_downloads,
        }
