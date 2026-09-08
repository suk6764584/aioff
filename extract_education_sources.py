from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from pypdf import PdfReader

from education_db import EducationDB


SUPPORTED_TEXT_EXTENSIONS = {".pdf", ".pptx", ".hwpx", ".txt", ".zip"}


def clean_text(value: str) -> str:
    value = (value or "").replace("\u00a0", " ").replace("\x00", "")
    lines = []
    for line in value.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def chunk_pages(
    pages: list[tuple[int, str]],
    *,
    section: str,
    max_chars: int = 2200,
    overlap_chars: int = 250,
) -> list[dict[str, Any]]:
    """Chunk ordered page/slide text while retaining source page ranges."""
    chunks: list[dict[str, Any]] = []
    buf = ""
    start_page: int | None = None
    end_page: int | None = None

    for page_no, raw_text in pages:
        text = clean_text(raw_text)
        if not text:
            continue
        if start_page is None:
            start_page = page_no
        end_page = page_no
        buf = f"{buf}\n{text}".strip() if buf else text

        while len(buf) >= max_chars:
            cut = buf.rfind("\n", 0, max_chars)
            if cut < max_chars // 2:
                cut = buf.rfind(". ", 0, max_chars)
            if cut < max_chars // 2:
                cut = max_chars
            piece = buf[:cut].strip()
            if piece:
                chunks.append(
                    {
                        "page_start": start_page,
                        "page_end": end_page,
                        "section": section,
                        "text": piece,
                    }
                )
            tail_start = max(0, cut - overlap_chars)
            buf = buf[tail_start:].strip()
            start_page = page_no

    if buf.strip():
        chunks.append(
            {
                "page_start": start_page,
                "page_end": end_page,
                "section": section,
                "text": buf.strip(),
            }
        )
    return chunks


def _rewind(source: Any) -> None:
    seek = getattr(source, "seek", None)
    if callable(seek):
        seek(0)


def _pdf_chunks(source: Any, section: str) -> list[dict[str, Any]]:
    _rewind(source)
    reader = PdfReader(source)
    pages: list[tuple[int, str]] = []
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            pages.append((page_no, page.extract_text() or ""))
        except Exception:
            pages.append((page_no, ""))
    return chunk_pages(pages, section=section)


def _xml_text(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""
    values: list[str] = []
    for elem in root.iter():
        local = elem.tag.rsplit("}", 1)[-1].lower()
        if local == "t" and elem.text:
            text = clean_text(elem.text)
            if text:
                values.append(text)
    return "\n".join(values)


def _numeric_key(name: str) -> tuple[int, str]:
    m = re.search(r"(\d+)", Path(name).stem)
    return (int(m.group(1)) if m else 10**9, name)


def _pptx_chunks(source: Any, section: str) -> list[dict[str, Any]]:
    _rewind(source)
    pages: list[tuple[int, str]] = []
    with zipfile.ZipFile(source) as zf:
        slide_names = sorted(
            [
                name
                for name in zf.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name, flags=re.I)
            ],
            key=_numeric_key,
        )
        for slide_no, name in enumerate(slide_names, start=1):
            pages.append((slide_no, _xml_text(zf.read(name))))
    return chunk_pages(pages, section=section)


def _hwpx_chunks(source: Any, section: str) -> list[dict[str, Any]]:
    _rewind(source)
    pages: list[tuple[int, str]] = []
    with zipfile.ZipFile(source) as zf:
        section_names = sorted(
            [
                name
                for name in zf.namelist()
                if re.fullmatch(r"Contents/section\d+\.xml", name, flags=re.I)
            ],
            key=_numeric_key,
        )
        for section_no, name in enumerate(section_names, start=1):
            pages.append((section_no, _xml_text(zf.read(name))))
    return chunk_pages(pages, section=section)


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _read_all(source: Any) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    _rewind(source)
    return source.read()


def _extract_source(
    source: Any,
    suffix: str,
    section: str,
    *,
    depth: int = 0,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    """Extract one source without loading large ZIP/PPT members into RAM.

    Archive members are copied to a SpooledTemporaryFile. Small members stay in
    memory and large members spill to disk automatically, preventing the
    MemoryError seen on large PPT ZIP packages.
    """
    suffix = suffix.lower()
    unsupported: Counter[str] = Counter()

    if suffix == ".pdf":
        return _pdf_chunks(source, section), unsupported
    if suffix == ".pptx":
        return _pptx_chunks(source, section), unsupported
    if suffix == ".hwpx":
        return _hwpx_chunks(source, section), unsupported
    if suffix == ".txt":
        text = _decode_text(_read_all(source))
        return chunk_pages([(1, text)], section=section), unsupported
    if suffix != ".zip":
        unsupported[suffix or "(none)"] += 1
        return [], unsupported

    if depth >= 2:
        unsupported[".zip(depth-limit)"] += 1
        return [], unsupported

    _rewind(source)
    chunks: list[dict[str, Any]] = []
    with zipfile.ZipFile(source) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            member = Path(info.filename)
            member_suffix = member.suffix.lower()
            if member_suffix not in SUPPORTED_TEXT_EXTENSIONS:
                unsupported[member_suffix or "(none)"] += 1
                continue

            member_section = f"{section} :: {info.filename}"
            with zf.open(info) as src, tempfile.SpooledTemporaryFile(
                max_size=16 * 1024 * 1024,
                mode="w+b",
            ) as tmp:
                shutil.copyfileobj(src, tmp, length=1024 * 1024)
                tmp.seek(0)
                child_chunks, child_unsupported = _extract_source(
                    tmp,
                    member_suffix,
                    member_section,
                    depth=depth + 1,
                )
            chunks.extend(child_chunks)
            unsupported.update(child_unsupported)

    return chunks, unsupported


def extract_file(path: Path) -> tuple[list[dict[str, Any]], Counter[str]]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_TEXT_EXTENSIONS:
        return [], Counter({suffix or "(none)": 1})
    return _extract_source(path, suffix, path.name)


def reset_chunks(db: EducationDB) -> None:
    """Reset derived chunk/FTS data only; source/material rows stay untouched."""
    db.conn.execute("DELETE FROM chunks")
    db.conn.execute("DROP TABLE IF EXISTS chunks_fts")
    db.conn.execute(
        """
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            text,
            title,
            target,
            topics,
            content=''
        )
        """
    )
    db.conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract and chunk downloaded AI OFF education sources")
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parent / "data" / "education" / "education.db"),
    )
    parser.add_argument("--no-reset-chunks", action="store_true", help="do not clear existing derived chunks first")
    args = parser.parse_args()

    db = EducationDB(args.db)
    if not args.no_reset_chunks:
        reset_chunks(db)

    rows = db.conn.execute(
        """
        SELECT
          a.id AS attachment_id,
          a.material_id,
          a.filename,
          a.local_path,
          a.extraction_status,
          m.title,
          m.target,
          m.topics_json
        FROM attachments a
        JOIN materials m ON m.id=a.material_id
        ORDER BY a.id
        """
    ).fetchall()

    status_counts: Counter[str] = Counter()
    extension_counts: Counter[str] = Counter()
    unsupported_members: Counter[str] = Counter()
    material_ids_with_chunks: set[int] = set()
    empty_samples: list[str] = []
    error_samples: list[str] = []
    chunk_total = 0
    char_total = 0
    downloadable = 0

    for idx, raw in enumerate(rows, start=1):
        row = dict(raw)
        local_path = str(row.get("local_path") or "").strip()
        if not local_path:
            status = str(row.get("extraction_status") or "metadata_only")
            status_counts[status] += 1
            continue

        downloadable += 1
        path = Path(local_path)
        extension_counts[path.suffix.lower() or "(none)"] += 1
        if not path.exists() or path.stat().st_size <= 0:
            db.set_attachment_extraction(row["attachment_id"], "error", "local source file missing or empty")
            status_counts["error"] += 1
            if len(error_samples) < 10:
                error_samples.append(f"{row['title']} | {path}")
            continue

        try:
            chunks, unsupported = extract_file(path)
            unsupported_members.update(unsupported)
            if chunks:
                topics = json.loads(row.get("topics_json") or "[]")
                db.replace_chunks(
                    row["material_id"],
                    row["attachment_id"],
                    chunks,
                    title=row["title"],
                    target=row["target"],
                    topics=topics,
                )
                status = "partial" if unsupported else "ok"
                detail = ""
                if unsupported:
                    detail = "unsupported archive members: " + json.dumps(dict(unsupported), ensure_ascii=False)
                db.set_attachment_extraction(row["attachment_id"], status, detail)
                status_counts[status] += 1
                material_ids_with_chunks.add(int(row["material_id"]))
                chunk_total += len(chunks)
                char_total += sum(len(c.get("text") or "") for c in chunks)
            else:
                status = "unsupported" if unsupported else "empty"
                detail = ""
                if unsupported:
                    detail = "unsupported source/member types: " + json.dumps(dict(unsupported), ensure_ascii=False)
                else:
                    detail = "no extractable text found; PDF may be image-only/scanned"
                db.set_attachment_extraction(row["attachment_id"], status, detail)
                status_counts[status] += 1
                if len(empty_samples) < 10:
                    empty_samples.append(f"{row['title']} | {row['filename']} | {status}")
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            db.set_attachment_extraction(row["attachment_id"], "error", message)
            status_counts["error"] += 1
            if len(error_samples) < 10:
                error_samples.append(f"{row['title']} | {row['filename']} | {message[:240]}")

        if idx % 10 == 0:
            print(f"processed attachments {idx}/{len(rows)}")

    db_status = db.status()
    sample_rows = db.conn.execute(
        """
        SELECT title,section,page_start,page_end,text
        FROM chunks
        ORDER BY id
        LIMIT 5
        """
    ).fetchall()
    db.close()

    print("\n=== EDUCATION EXTRACTION AUDIT ===")
    print(f"attachment records      : {len(rows)}")
    print(f"downloaded/local files  : {downloadable}")
    print("source extensions       :", dict(sorted(extension_counts.items())))
    print("extraction status       :", dict(sorted(status_counts.items())))
    print("unsupported zip members :", dict(sorted(unsupported_members.items())))
    print(f"materials with chunks   : {len(material_ids_with_chunks)}")
    print(f"chunks                   : {chunk_total}")
    print(f"extracted characters     : {char_total}")
    print("db status                :", db_status)

    if empty_samples:
        print("\n=== EMPTY / UNSUPPORTED SAMPLE ===")
        for item in empty_samples:
            print("-", item)

    if error_samples:
        print("\n=== EXTRACTION ERROR SAMPLE ===")
        for item in error_samples:
            print("-", item)

    if sample_rows:
        print("\n=== CHUNK SAMPLE ===")
        for sample in sample_rows:
            text = clean_text(sample["text"])[:220].replace("\n", " / ")
            print(
                f"- {sample['title']} | {sample['section']} | "
                f"p.{sample['page_start']}-{sample['page_end']} | {text}"
            )

    if downloadable and chunk_total == 0:
        return 2
    if status_counts.get("error", 0):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
