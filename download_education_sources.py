from __future__ import annotations

import argparse
import hashlib
import mimetypes
import shutil
from collections import Counter
from pathlib import Path

import requests

import build_education_db as build
from education_db import EducationDB


MEDIA_METADATA_ONLY = {".mp4"}


def download_source(session: requests.Session, row: dict, out_dir: Path) -> dict:
    """Download one archive attachment while preserving the filename shown by the source page."""
    url = str(row.get("download_url") or "").strip()
    if not url:
        return {
            **row,
            "extraction_status": "unresolved",
            "extraction_error": "download URL is empty",
        }

    source_name = build.safe_filename(str(row.get("filename") or "attachment"))
    suffix = Path(source_name).suffix.lower()
    if suffix in MEDIA_METADATA_ONLY:
        return {
            **row,
            "extraction_status": "metadata_only",
            "extraction_error": "video source retained as metadata only for RAG",
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / source_name
    if path.exists() and path.stat().st_size > 0:
        return {
            **row,
            "local_path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "byte_size": path.stat().st_size,
            "mime_type": mimetypes.guess_type(path.name)[0] or "",
            "extraction_status": "downloaded",
            "extraction_error": "",
        }

    with session.get(url, stream=True, timeout=120, allow_redirects=True) as response:
        response.raise_for_status()
        content_type = str(response.headers.get("Content-Type") or "")
        disposition = str(response.headers.get("Content-Disposition") or "")
        if "text/html" in content_type.lower() and "attachment" not in disposition.lower():
            raise RuntimeError(f"unexpected HTML response from file endpoint: {url}")

        digest = hashlib.sha256()
        size = 0
        with path.open("wb") as fh:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                digest.update(chunk)
                size += len(chunk)

    if size <= 0:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"empty download: {url}")

    return {
        **row,
        "local_path": str(path),
        "sha256": digest.hexdigest(),
        "byte_size": size,
        "mime_type": mimetypes.guess_type(path.name)[0] or content_type,
        "extraction_status": "downloaded",
        "extraction_error": "",
    }


def reset_generated_data(db_path: Path, files_dir: Path) -> None:
    for candidate in (
        db_path,
        Path(str(db_path) + "-wal"),
        Path(str(db_path) + "-shm"),
    ):
        candidate.unlink(missing_ok=True)
    if files_dir.exists():
        shutil.rmtree(files_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download AI OFF school-target education source files")
    parser.add_argument("--reset", action="store_true", help="remove the generated education DB/files before rebuilding")
    parser.add_argument("--db", default=str(Path(__file__).resolve().parent / "data" / "education" / "education.db"))
    parser.add_argument("--files-dir", default=str(Path(__file__).resolve().parent / "data" / "education" / "files"))
    parser.add_argument("--max-pages", type=int, default=40)
    args = parser.parse_args()

    db_path = Path(args.db)
    files_dir = Path(args.files_dir)
    if args.reset:
        reset_generated_data(db_path, files_dir)

    session = requests.Session()
    session.headers.update({
        "User-Agent": build.USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    })

    all_rows = build.crawl_materials(session, args.max_pages)
    rows = build.school_materials(all_rows, build.DEFAULT_TARGETS)
    if len(all_rows) < 350 or len(rows) < 130:
        raise SystemExit(f"ERROR: crawl gate failed: all={len(all_rows)}, school={len(rows)}")

    db = EducationDB(db_path)
    extension_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    attachment_count = 0

    for idx, row in enumerate(rows, start=1):
        material_id = db.upsert_material(row)
        material_dir = files_dir / f"{material_id:04d}_{build.safe_filename(row['title'])[:80]}"
        for attachment in row.get("attachments") or []:
            attachment_count += 1
            item = dict(attachment)
            try:
                item = download_source(session, item, material_dir)
            except Exception as exc:
                item["extraction_status"] = "download_error"
                item["extraction_error"] = f"{type(exc).__name__}: {exc}"
            db.upsert_attachment(material_id, item)
            status_counts[str(item.get("extraction_status") or "pending")] += 1
            extension_counts[Path(str(item.get("filename") or "")).suffix.lower() or "(none)"] += 1
        if idx % 10 == 0:
            print(f"processed {idx}/{len(rows)}")

    status = db.status()
    db.close()

    print("\n=== EDUCATION SOURCE DOWNLOAD ===")
    print(f"all materials       : {len(all_rows)}")
    print(f"school materials    : {len(rows)}")
    print(f"attachment records  : {attachment_count}")
    print("status counts       :", dict(sorted(status_counts.items())))
    print("extension counts    :", dict(sorted(extension_counts.items())))
    print("db status           :", status)

    if status_counts.get("download_error", 0) or status_counts.get("unresolved", 0):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
