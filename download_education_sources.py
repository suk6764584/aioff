from __future__ import annotations

import argparse
import hashlib
import mimetypes
import re
import shutil
import time
from collections import Counter
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import build_education_db as build
from education_db import EducationDB


MEDIA_METADATA_ONLY = {".mp4", ".mp3", ".wav", ".m4a"}
DETAIL_URL = build.BASE_URL + "/front/archive/archiveDetail.do"
DETAIL_ID_RE = re.compile(r"fn_detail\(\s*['\"](ARC\d+)['\"]\s*\)", re.I)
DETAIL_FILE_RE = re.compile(
    r"\.(pdf|zip|hwp|hwpx|doc|docx|ppt|pptx|xls|xlsx|txt|mp4|mp3|wav|m4a)$",
    re.I,
)


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
            "extraction_error": "audio/video source retained as metadata only for RAG",
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


def detail_id_index(session: requests.Session, max_pages: int) -> dict[str, str]:
    """Map the same list-view source_key used by the DB to the archive's stable ARC id."""
    out: dict[str, str] = {}
    previous_signature = None

    for page in range(1, max_pages + 1):
        response = session.get(build.LIST_URL, params={"pageIndex": page}, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        cards = build.material_containers(soup)
        rows = []

        for card in cards:
            row = build.parse_card(card, page)
            if not row.get("source_key"):
                continue

            archive_id = ""
            for node in card.find_all(["a", "button"]):
                raw = " ".join(
                    (
                        str(node.get("href") or ""),
                        str(node.get("onclick") or ""),
                    )
                )
                match = DETAIL_ID_RE.search(raw)
                if match:
                    archive_id = match.group(1)
                    break

            rows.append((row["source_key"], archive_id))

        signature = tuple(key for key, _ in rows)
        if not rows or signature == previous_signature:
            break
        previous_signature = signature

        for key, archive_id in rows:
            if archive_id:
                out[key] = archive_id

        time.sleep(0.12)

    return out


def discover_detail_attachments(
    session: requests.Session,
    archive_id: str,
) -> list[dict]:
    """Read a detail page and return fileDown controls with explicit filenames."""
    response = session.post(
        DETAIL_URL,
        data={"searchArchiveId": archive_id},
        timeout=30,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")

    by_url: dict[str, dict] = {}
    for node in soup.find_all(["button", "a"]):
        onclick = build.norm(node.get("onclick") or "")
        if "filedown(" not in onclick.lower():
            continue

        filename = build.norm(node.get_text(" ", strip=True))
        if not DETAIL_FILE_RE.search(filename):
            continue

        download_url, raw = build.resolve_download_action(node)
        if not download_url:
            continue

        item = {
            "filename": filename,
            "download_url": download_url,
            "action_raw": raw,
        }
        by_url[download_url] = item

    return list(by_url.values())


def merge_attachments(existing: list[dict], discovered: list[dict]) -> tuple[list[dict], int]:
    merged = [dict(x) for x in existing]
    added = 0

    for item in discovered:
        url = str(item.get("download_url") or "")
        filename = str(item.get("filename") or "")

        match = None
        if url:
            match = next((x for x in merged if str(x.get("download_url") or "") == url), None)
        if match is None:
            match = next(
                (
                    x
                    for x in merged
                    if str(x.get("filename") or "") == filename
                    and not str(x.get("download_url") or "")
                ),
                None,
            )

        if match is not None:
            if not match.get("download_url"):
                match["download_url"] = item.get("download_url", "")
            if not match.get("action_raw"):
                match["action_raw"] = item.get("action_raw", "")
            continue

        merged.append(dict(item))
        added += 1

    return merged, added


def enrich_from_detail_pages(
    session: requests.Session,
    rows: list[dict],
    max_pages: int,
) -> tuple[int, int, int]:
    """Enrich every school material from its detail page before download."""
    archive_ids = detail_id_index(session, max_pages)
    detail_pages = 0
    detail_errors = 0
    added_total = 0

    for idx, row in enumerate(rows, start=1):
        archive_id = archive_ids.get(row["source_key"], "")
        if not archive_id:
            detail_errors += 1
            print(f"detail id missing: {row['title']}")
            continue

        try:
            discovered = discover_detail_attachments(session, archive_id)
            row["attachments"], added = merge_attachments(
                row.get("attachments") or [],
                discovered,
            )
            added_total += added
            detail_pages += 1
        except Exception as exc:
            detail_errors += 1
            print(
                f"detail error: {archive_id} | {row['title']} | "
                f"{type(exc).__name__}: {exc}"
            )

        if idx % 20 == 0:
            print(
                f"detail-enriched {idx}/{len(rows)} "
                f"(added attachments={added_total}, errors={detail_errors})"
            )
        time.sleep(0.12)

    return detail_pages, added_total, detail_errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download AI OFF school-target education source files"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="remove the generated education DB/files before rebuilding",
    )
    parser.add_argument(
        "--db",
        default=str(
            Path(__file__).resolve().parent / "data" / "education" / "education.db"
        ),
    )
    parser.add_argument(
        "--files-dir",
        default=str(
            Path(__file__).resolve().parent / "data" / "education" / "files"
        ),
    )
    parser.add_argument("--max-pages", type=int, default=40)
    args = parser.parse_args()

    db_path = Path(args.db)
    files_dir = Path(args.files_dir)
    if args.reset:
        reset_generated_data(db_path, files_dir)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": build.USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
        }
    )

    all_rows = build.crawl_materials(session, args.max_pages)
    rows = build.school_materials(all_rows, build.DEFAULT_TARGETS)
    if len(all_rows) < 350 or len(rows) < 130:
        raise SystemExit(
            f"ERROR: crawl gate failed: all={len(all_rows)}, school={len(rows)}"
        )

    detail_pages, detail_added, detail_errors = enrich_from_detail_pages(
        session,
        rows,
        args.max_pages,
    )

    db = EducationDB(db_path)
    extension_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    attachment_count = 0

    for idx, row in enumerate(rows, start=1):
        material_id = db.upsert_material(row)
        material_dir = (
            files_dir
            / f"{material_id:04d}_{build.safe_filename(row['title'])[:80]}"
        )
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
            extension_counts[
                Path(str(item.get("filename") or "")).suffix.lower() or "(none)"
            ] += 1
        if idx % 10 == 0:
            print(f"processed {idx}/{len(rows)}")

    status = db.status()
    db.close()

    print("\n=== EDUCATION SOURCE DOWNLOAD ===")
    print(f"all materials             : {len(all_rows)}")
    print(f"school materials          : {len(rows)}")
    print(f"detail pages enriched     : {detail_pages}")
    print(f"detail-only files added   : {detail_added}")
    print(f"detail enrichment errors  : {detail_errors}")
    print(f"attachment records        : {attachment_count}")
    print("status counts             :", dict(sorted(status_counts.items())))
    print("extension counts          :", dict(sorted(extension_counts.items())))
    print("db status                 :", status)

    if (
        detail_errors
        or status_counts.get("download_error", 0)
        or status_counts.get("unresolved", 0)
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
