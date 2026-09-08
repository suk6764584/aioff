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

import education_archive_parser as build
from education_db import EducationDB


MEDIA_METADATA_ONLY = {".mp4", ".mp3", ".wav", ".m4a"}
DETAIL_URL = build.BASE_URL + "/front/archive/archiveDetail.do"
DETAIL_ID_RE = re.compile(r"fn_detail\(\s*['\"](ARC\d+)['\"]\s*\)", re.I)
DETAIL_FILE_RE = re.compile(
    r"\.(pdf|zip|hwp|hwpx|doc|docx|ppt|pptx|xls|xlsx|txt|mp4|mp3|wav|m4a)$",
    re.I,
)


def archive_id_from_card(card) -> str:
    for node in card.find_all(["a", "button"]):
        raw = " ".join(
            (
                str(node.get("href") or ""),
                str(node.get("onclick") or ""),
            )
        )
        match = DETAIL_ID_RE.search(raw)
        if match:
            return match.group(1)
    return ""


def crawl_materials_with_archive_ids(
    session: requests.Session,
    max_pages: int,
) -> list[dict]:
    """Crawl list cards once and use the stable ARC id as the DB source key.

    Thumbnail/image URLs on this archive contain request-varying values, so they
    must never be used as persistent material identity. The ARC id is the
    canonical identity used by the site's own fn_detail() function.
    """
    all_rows: dict[str, dict] = {}
    previous_signature = None

    for page in range(1, max_pages + 1):
        response = session.get(build.LIST_URL, params={"pageIndex": page}, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        cards = build.material_containers(soup)
        page_rows: list[dict] = []

        for card in cards:
            row = build.parse_card(card, page)
            if not row.get("title"):
                continue

            archive_id = archive_id_from_card(card)
            if not archive_id:
                raise RuntimeError(
                    f"stable archive id missing on page {page}: {row['title']}"
                )

            row["archive_id"] = archive_id
            row["source_key"] = archive_id
            row["source_url"] = f"{DETAIL_URL}?searchArchiveId={archive_id}"
            page_rows.append(row)

        signature = tuple(row["archive_id"] for row in page_rows)
        if not page_rows:
            break
        if signature == previous_signature:
            break
        previous_signature = signature

        for row in page_rows:
            all_rows[row["archive_id"]] = row

        print(f"page {page}: {len(page_rows)} items / cumulative {len(all_rows)}")
        time.sleep(0.12)

    return list(all_rows.values())


def download_source(session: requests.Session, row: dict, out_dir: Path) -> dict:
    """Download one archive attachment while preserving the source-page filename."""
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


def remove_db_files(db_path: Path) -> None:
    for candidate in (
        db_path,
        Path(str(db_path) + "-wal"),
        Path(str(db_path) + "-shm"),
    ):
        candidate.unlink(missing_ok=True)


def reset_generated_data(db_path: Path, files_dir: Path) -> None:
    remove_db_files(db_path)
    if files_dir.exists():
        shutil.rmtree(files_dir)


def discover_detail_attachments(
    session: requests.Session,
    archive_id: str,
) -> list[dict]:
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

        by_url[download_url] = {
            "filename": filename,
            "download_url": download_url,
            "action_raw": raw,
        }

    return list(by_url.values())


def merge_attachments(existing: list[dict], discovered: list[dict]) -> tuple[list[dict], int]:
    merged = [dict(x) for x in existing]
    added = 0

    for item in discovered:
        url = str(item.get("download_url") or "")
        filename = str(item.get("filename") or "")

        match = None
        if url:
            match = next(
                (x for x in merged if str(x.get("download_url") or "") == url),
                None,
            )
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
) -> tuple[int, int, int]:
    detail_pages = 0
    detail_errors = 0
    added_total = 0

    for idx, row in enumerate(rows, start=1):
        archive_id = str(row.get("archive_id") or "")
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


def prune_orphan_material_dirs(files_dir: Path, valid_ids: set[int]) -> int:
    """Remove only top-level generated material directories whose numeric id is stale."""
    if not files_dir.exists():
        return 0

    removed = 0
    for path in files_dir.iterdir():
        if not path.is_dir():
            continue
        match = re.match(r"^(\d{4})_", path.name)
        if not match:
            continue
        material_id = int(match.group(1))
        if material_id not in valid_ids:
            shutil.rmtree(path)
            removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download AI OFF school-target education source files"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="remove generated education DB and downloaded files before rebuilding",
    )
    parser.add_argument(
        "--rebuild-db",
        action="store_true",
        help="rebuild only the education DB while preserving already downloaded files",
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

    if args.reset and args.rebuild_db:
        raise SystemExit("ERROR: use only one of --reset or --rebuild-db")

    db_path = Path(args.db)
    files_dir = Path(args.files_dir)
    if args.reset:
        reset_generated_data(db_path, files_dir)
    elif args.rebuild_db:
        remove_db_files(db_path)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": build.USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
        }
    )

    all_rows = crawl_materials_with_archive_ids(session, args.max_pages)
    rows = build.school_materials(all_rows, build.DEFAULT_TARGETS)
    if len(all_rows) < 350 or len(rows) < 130:
        raise SystemExit(
            f"ERROR: crawl gate failed: all={len(all_rows)}, school={len(rows)}"
        )

    detail_pages, detail_added, detail_errors = enrich_from_detail_pages(session, rows)

    db = EducationDB(db_path)
    extension_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    attachment_count = 0
    valid_material_ids: set[int] = set()

    for idx, row in enumerate(rows, start=1):
        material_id = db.upsert_material(row)
        valid_material_ids.add(material_id)
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

    pruned_dirs = 0
    if args.rebuild_db and not detail_errors and not status_counts.get("download_error", 0):
        pruned_dirs = prune_orphan_material_dirs(files_dir, valid_material_ids)

    print("\n=== EDUCATION SOURCE DOWNLOAD ===")
    print(f"all materials             : {len(all_rows)}")
    print(f"school materials          : {len(rows)}")
    print(f"detail pages enriched     : {detail_pages}")
    print(f"detail-only files added   : {detail_added}")
    print(f"detail enrichment errors  : {detail_errors}")
    print(f"attachment records        : {attachment_count}")
    print("status counts             :", dict(sorted(status_counts.items())))
    print("extension counts          :", dict(sorted(extension_counts.items())))
    print(f"stale material dirs pruned: {pruned_dirs}")
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
