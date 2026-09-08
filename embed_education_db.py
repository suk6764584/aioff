from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from education_db import EducationDB


DEFAULT_DB = Path(__file__).resolve().parent / "data" / "education" / "education.db"
DEFAULT_ENV = Path(__file__).resolve().parent / ".env"
DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIM = 768


def load_simple_env(path: Path) -> None:
    """Load simple KEY=VALUE entries without overwriting existing environment variables."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def embed_batch(client, types, model: str, dim: int, texts: list[str], retries: int) -> list[list[float]]:
    delay = 2.0
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            result = client.models.embed_content(
                model=model,
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=dim,
                ),
            )
            embeddings = list(result.embeddings or [])
            if len(embeddings) != len(texts):
                raise RuntimeError(
                    f"embedding count mismatch: expected {len(texts)}, got {len(embeddings)}"
                )
            vectors = [list(item.values or []) for item in embeddings]
            bad = [i for i, vector in enumerate(vectors) if len(vector) != dim]
            if bad:
                raise RuntimeError(
                    f"embedding dimension mismatch at batch indexes {bad[:5]} (expected {dim})"
                )
            return vectors
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            print(
                f"embed retry {attempt}/{retries - 1}: {type(exc).__name__}: {exc}; "
                f"sleep {delay:.1f}s"
            )
            time.sleep(delay)
            delay = min(delay * 2, 30.0)
    assert last_error is not None
    raise last_error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Embed existing AI OFF education chunks without recrawling or rebuilding the source DB"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--env", default=str(DEFAULT_ENV))
    parser.add_argument("--model", default="")
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0, help="embed only N pending chunks (0=all)")
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--sleep", type=float, default=0.20, help="pause between successful batches")
    args = parser.parse_args()

    load_simple_env(Path(args.env))
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("ERROR: GEMINI_API_KEY is missing from environment/.env")

    model = (
        args.model.strip()
        or os.getenv("GEMINI_EMBED_MODEL", "").strip()
        or DEFAULT_MODEL
    )
    if args.batch_size < 1:
        raise SystemExit("ERROR: --batch-size must be >= 1")
    if args.dim < 1:
        raise SystemExit("ERROR: --dim must be >= 1")

    from google import genai
    from google.genai import types

    db = EducationDB(args.db)
    total_chunks = int(db.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    if total_chunks == 0:
        db.close()
        raise SystemExit("ERROR: no education chunks found; run extraction first")

    limit = args.limit if args.limit > 0 else None
    rows = db.chunks_missing_embeddings(model, limit=limit)
    already = int(
        db.conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL AND embedding_model=? AND embedding_dim=?",
            (model, args.dim),
        ).fetchone()[0]
    )

    print("=== EDUCATION EMBEDDING START ===")
    print("db            :", Path(args.db).resolve())
    print("model         :", model)
    print("dimension     :", args.dim)
    print("total chunks  :", total_chunks)
    print("already ready :", already)
    print("pending run   :", len(rows))

    if not rows:
        final = db.status()
        db.close()
        print("\n=== EDUCATION EMBEDDING AUDIT ===")
        print("embedded this run : 0")
        print("db status         :", final)
        print("result            : PASS")
        return 0

    client = genai.Client(api_key=api_key)
    completed = 0
    for start in range(0, len(rows), args.batch_size):
        batch = rows[start : start + args.batch_size]
        vectors = embed_batch(
            client,
            types,
            model,
            args.dim,
            [row["text"] for row in batch],
            args.retries,
        )
        for row, vector in zip(batch, vectors):
            db.set_chunk_embedding(int(row["id"]), model, vector)
        completed += len(batch)
        print(f"embedded {completed}/{len(rows)}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    ready = int(
        db.conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL AND embedding_model=? AND embedding_dim=?",
            (model, args.dim),
        ).fetchone()[0]
    )
    missing = int(
        db.conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NULL OR embedding_model<>? OR embedding_dim<>?",
            (model, args.dim),
        ).fetchone()[0]
    )
    wrong_dim = int(
        db.conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL AND embedding_model=? AND embedding_dim<>?",
            (model, args.dim),
        ).fetchone()[0]
    )
    final = db.status()
    db.close()

    print("\n=== EDUCATION EMBEDDING AUDIT ===")
    print("embedded this run :", completed)
    print("ready model/dim    :", ready)
    print("missing/mismatch   :", missing)
    print("wrong dimension    :", wrong_dim)
    print("db status          :", final)

    if args.limit > 0 and len(rows) >= args.limit:
        print("result             : PARTIAL (limited run)")
        return 0
    if ready != total_chunks or missing != 0 or wrong_dim != 0:
        print("result             : FAIL")
        return 2
    print("result             : PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
