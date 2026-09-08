from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from education_db import EducationDB

BASE_URL = "https://xn--2z1b40gs9nlqcf0n.kr"
LIST_URL = BASE_URL + "/front/archive/archiveMainList.do"
DEFAULT_TARGETS = ("초등", "중등", "고등")
USER_AGENT = "AI-OFF-Education-RAG/1.0 (+https://aioff-ai.duckdns.org/)"

_EXT_RE = re.compile(r"\.(pdf|zip|hwp|hwpx|doc|docx|ppt|pptx|xls|xlsx|txt)(?:$|\?)", re.I)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def lines_of(node) -> list[str]:
    return [norm(x) for x in node.get_text("\n", strip=True).splitlines() if norm(x)]


def value_between(lines: list[str], label: str, next_labels: tuple[str, ...]) -> str:
    try:
        i = lines.index(label)
    except ValueError:
        return ""
    vals: list[str] = []
    for x in lines[i + 1:]:
        if x in next_labels or any(x.startswith(y) for y in next_labels):
            break
        vals.append(x)
    return norm(" / ".join(vals))


def value_from_text(text: str, label: str, next_label: str) -> str:
    m = re.search(rf"{re.escape(label)}\s*(.*?)\s*{re.escape(next_label)}", text, re.S)
    return norm(m.group(1)) if m else ""


def material_containers(soup: BeautifulSoup):
    """Find one DOM container per list item without depending on site CSS classes.

    The archive page nests the field labels quite deeply.  The previous parser only
    walked nine ancestors from the `제작년도` text node, which can stop before the
    actual item container and therefore return zero items even though the labels are
    present in the response.  Walk farther and select the smallest ancestor that
    contains exactly one complete metadata set.
    """
    seen: set[int] = set()
    containers = []
    label_re = re.compile(r"^(?:대상|제작년도|자료유형|주제)$")

    for text_node in soup.find_all(string=lambda s: bool(s and label_re.search(norm(str(s))))):
        node = text_node.parent
        best = None
        for _ in range(24):
            if node is None or getattr(node, "name", None) in ("html", "body"):
                break
            lines = lines_of(node)
            # Exact line counts distinguish a single list item from the whole list,
            # which contains the same labels many times.
            if (
                lines.count("대상") == 1
                and lines.count("제작년도") == 1
                and lines.count("자료유형") == 1
                and lines.count("주제") == 1
            ):
                best = node
                break
            node = node.parent
        if best is None:
            continue
        marker = id(best)
        if marker not in seen:
            seen.add(marker)
            containers.append(best)
    return containers


def action_from_anchor(a) -> tuple[str, str]:
    href = norm(a.get("href") or "")
    onclick = norm(a.get("onclick") or "")
    data_url = norm(a.get("data-url") or a.get("data-href") or a.get("data-download-url") or "")
    raw = data_url or href or onclick
    url = ""
    for candidate in (data_url, href):
        if candidate and not candidate.lower().startswith("javascript:") and candidate != "#":
            if any(k in candidate.lower() for k in ("download", "filedown", "file.do", "attach", "atch")) or _EXT_RE.search(candidate):
                url = urljoin(BASE_URL, candidate)
                break
    return url, raw


def parse_card(card, page_index: int) -> dict:
    lines = lines_of(card)
    if not lines:
        return {}

    full_text = norm(card.get_text(" ", strip=True))
    if not all(label in full_text for label in ("대상", "제작년도", "자료유형", "주제")):
        return {}

    # Image alt is the most stable title source on both list/grid markup.
    img = card.find("img", alt=True)
    title = norm(img.get("alt") if img else "")
    if not title:
        try:
            target_idx = lines.index("대상")
        except ValueError:
            target_idx = len(lines)
        title_candidates = [x for x in lines[:target_idx] if x not in ("리스트형", "갤러리형")]
        title = title_candidates[-1] if title_candidates else ""

    target = value_between(lines, "대상", ("제작년도",)) or value_from_text(full_text, "대상", "제작년도")
    year = value_between(lines, "제작년도", ("자료유형",)) or value_from_text(full_text, "제작년도", "자료유형")
    material_type = value_between(lines, "자료유형", ("주제",)) or value_from_text(full_text, "자료유형", "주제")
    topics_text = value_between(lines, "주제", ("조회수", "자세히보기", "다운로드"))
    if not topics_text:
        m = re.search(r"주제\s*(.*?)\s*(?:조회수|자세히보기|다운로드)", full_text, re.S)
        topics_text = norm(m.group(1)) if m else ""
    topics = re.findall(r"#[^\s#/]+", topics_text)

    if not title or not target or not year:
        return {}

    detail_url = ""
    attachments = []
    for a in card.find_all("a"):
        text = norm(a.get_text(" ", strip=True))
        href = norm(a.get("href") or "")
        onclick = norm(a.get("onclick") or "")
        combined = " ".join((text, href, onclick)).lower()
        if not detail_url and ("자세히보기" in text or ("archive" in combined and ("view" in combined or "detail" in combined))):
            if href and not href.lower().startswith("javascript:") and href != "#":
                detail_url = urljoin(BASE_URL, href)
        filename = text
        if _EXT_RE.search(filename) or any(k in combined for k in ("download", "filedown")):
            download_url, raw = action_from_anchor(a)
            if not filename or not _EXT_RE.search(filename):
                parent_text = norm(a.parent.get_text(" ", strip=True)) if a.parent else ""
                m = re.search(r"([^/\\]+\.(?:pdf|zip|hwp|hwpx|docx?|pptx?|xlsx?|txt))", parent_text, re.I)
                if m:
                    filename = m.group(1)
            attachments.append({"filename": filename or "attachment", "download_url": download_url, "action_raw": raw})

    filenames = [x for x in lines if _EXT_RE.search(x)]
    for filename in filenames:
        if not any(a["filename"] == filename for a in attachments):
            attachments.append({"filename": filename, "download_url": "", "action_raw": ""})

    key_src = "|".join((title, target, year, material_type))
    source_key = hashlib.sha1(key_src.encode("utf-8")).hexdigest()
    return {
        "source_key": source_key,
        "title": title,
        "target": target,
        "year": year,
        "material_type": material_type,
        "topics": topics,
        "source_url": detail_url or f"{LIST_URL}?pageIndex={page_index}",
        "list_page": page_index,
        "attachments": attachments,
    }


def crawl_materials(session: requests.Session, max_pages: int = 40) -> list[dict]:
    all_rows: dict[str, dict] = {}
    previous_signature = None
    for page in range(1, max_pages + 1):
        r = session.get(LIST_URL, params={"pageIndex": page}, timeout=30)
        r.raise_for_status()
        # Let BeautifulSoup honor the charset declared by the page instead of
        # depending on requests/chardet's guess for Korean text.
        soup = BeautifulSoup(r.content, "html.parser")
        cards = material_containers(soup)
        rows = [parse_card(c, page) for c in cards]
        rows = [x for x in rows if x.get("title")]
        signature = tuple(x["source_key"] for x in rows)
        if not rows:
            if page == 1:
                raw_text = soup.get_text(" ", strip=True)
                print(
                    "DEBUG: first page produced no rows; "
                    f"status={r.status_code}, bytes={len(r.content)}, "
                    f"requests_encoding={r.encoding!r}, apparent_encoding={r.apparent_encoding!r}, "
                    f"has_education_room={'교육자료실' in raw_text}, "
                    f"has_year_label={'제작년도' in raw_text}, "
                    f"candidate_cards={len(cards)}",
                    file=sys.stderr,
                )
            break
        if signature == previous_signature:
            break
        previous_signature = signature
        for row in rows:
            all_rows[row["source_key"]] = row
        print(f"page {page}: {len(rows)} items / cumulative {len(all_rows)}")
        time.sleep(0.25)
    return list(all_rows.values())


def school_materials(rows: list[dict], targets: tuple[str, ...]) -> list[dict]:
    out = []
    for row in rows:
        target = row.get("target", "")
        if any(t in target for t in targets):
            out.append(row)
    return out


def safe_filename(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip(" .")
    return value[:180] or "attachment"


def download_attachment(session: requests.Session, row: dict, out_dir: Path) -> dict:
    url = row.get("download_url", "")
    if not url:
        return {**row, "extraction_status": "unresolved", "extraction_error": "download URL not resolved from list page"}
    filename = safe_filename(row.get("filename") or Path(urlparse(url).path).name or "attachment")
    path = out_dir / filename
    if path.exists() and path.stat().st_size > 0:
        data_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        return {**row, "local_path": str(path), "sha256": data_hash, "byte_size": path.stat().st_size, "mime_type": mimetypes.guess_type(path.name)[0] or ""}
    with session.get(url, stream=True, timeout=90, allow_redirects=True) as r:
        r.raise_for_status()
        disposition = r.headers.get("Content-Disposition", "")
        m = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.I)
        if m:
            try:
                from urllib.parse import unquote
                header_name = safe_filename(unquote(m.group(1).strip('"')))
                if header_name:
                    path = out_dir / header_name
            except Exception:
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        size = 0
        with path.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
    return {**row, "local_path": str(path), "sha256": h.hexdigest(), "byte_size": size, "mime_type": mimetypes.guess_type(path.name)[0] or r.headers.get("Content-Type", "")}


def chunk_pages(page_texts: list[tuple[int, str]], max_chars: int = 2200, overlap_chars: int = 250) -> list[dict]:
    chunks = []
    buf = ""
    start_page = None
    end_page = None
    for page_no, text in page_texts:
        text = norm(text)
        if not text:
            continue
        if start_page is None:
            start_page = page_no
        end_page = page_no
        if buf:
            buf += "\n"
        buf += text
        while len(buf) >= max_chars:
            cut = buf.rfind(". ", 0, max_chars)
            if cut < max_chars // 2:
                cut = buf.rfind("\n", 0, max_chars)
            if cut < max_chars // 2:
                cut = max_chars
            piece = buf[:cut].strip()
            if piece:
                chunks.append({"page_start": start_page, "page_end": end_page, "text": piece, "section": ""})
            tail_start = max(0, cut - overlap_chars)
            buf = buf[tail_start:].strip()
            start_page = page_no
    if buf.strip():
        chunks.append({"page_start": start_page, "page_end": end_page, "text": buf.strip(), "section": ""})
    return chunks


def extract_pdf(path: Path) -> list[dict]:
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if norm(text):
            pages.append((i, text))
    return chunk_pages(pages)


def extract_attachment(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix == ".txt":
        return chunk_pages([(1, path.read_text(encoding="utf-8", errors="ignore"))])
    if suffix == ".zip":
        tmp_dir = path.parent / (path.stem + "_unzipped")
        tmp_dir.mkdir(exist_ok=True)
        out: list[dict] = []
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name
                if not name.lower().endswith((".pdf", ".txt")):
                    continue
                target = tmp_dir / safe_filename(name)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                out.extend(extract_attachment(target))
        return out
    raise ValueError(f"unsupported extraction type: {suffix}")


def embed_chunks(db: EducationDB, api_key: str, model: str, batch_size: int = 16) -> None:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    rows = db.chunks_missing_embeddings(model)
    print(f"embedding pending: {len(rows)} chunks")
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        contents = [x["text"] for x in batch]
        result = client.models.embed_content(
            model=model,
            contents=contents,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=768),
        )
        embeddings = list(result.embeddings or [])
        if len(embeddings) != len(batch):
            raise RuntimeError(f"embedding count mismatch: {len(embeddings)} != {len(batch)}")
        for row, emb in zip(batch, embeddings):
            db.set_chunk_embedding(row["id"], model, list(emb.values))
        print(f"embedded {min(start + batch_size, len(rows))}/{len(rows)}")
        time.sleep(0.15)


def main() -> int:
    p = argparse.ArgumentParser(description="Build AI OFF education material DB from 디지털윤리.kr")
    p.add_argument("--target", action="append", dest="targets", help="target filter; may repeat (default: 초등/중등/고등)")
    p.add_argument("--list-only", action="store_true", help="crawl/validate only; do not write DB")
    p.add_argument("--download", action="store_true", help="download resolved attachments")
    p.add_argument("--extract", action="store_true", help="extract/chunk downloaded PDF/TXT/ZIP")
    p.add_argument("--embed", action="store_true", help="embed chunks with Gemini")
    p.add_argument("--db", default=str(Path(__file__).resolve().parent / "data" / "education" / "education.db"))
    p.add_argument("--files-dir", default=str(Path(__file__).resolve().parent / "data" / "education" / "files"))
    p.add_argument("--max-pages", type=int, default=40)
    p.add_argument("--embed-model", default=os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001"))
    args = p.parse_args()

    targets = tuple(args.targets or DEFAULT_TARGETS)
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5"})
    all_rows = crawl_materials(s, args.max_pages)
    rows = school_materials(all_rows, targets)

    print("\n=== CRAWL SUMMARY ===")
    print(f"all materials: {len(all_rows)}")
    print(f"school targets {targets}: {len(rows)}")
    for row in rows[:10]:
        print(f"- [{row['target']}] {row['title']} / {row['year']} / attachments={len(row['attachments'])}")

    if len(all_rows) < 250 or len(rows) < 80:
        print("ERROR: parsed count is unexpectedly low; stop before DB/download.", file=sys.stderr)
        return 2
    if args.list_only:
        return 0

    db = EducationDB(args.db)
    files_dir = Path(args.files_dir)
    files_dir.mkdir(parents=True, exist_ok=True)
    unresolved = 0
    extracted = 0

    for idx, row in enumerate(rows, start=1):
        material_id = db.upsert_material(row)
        material_dir = files_dir / f"{material_id:04d}_{safe_filename(row['title'])[:80]}"
        material_dir.mkdir(parents=True, exist_ok=True)
        for att in row["attachments"]:
            item = dict(att)
            if args.download:
                try:
                    item = download_attachment(s, item, material_dir)
                except Exception as exc:
                    item["extraction_status"] = "download_error"
                    item["extraction_error"] = f"{type(exc).__name__}: {exc}"
            if not item.get("download_url"):
                unresolved += 1
            attachment_id = db.upsert_attachment(material_id, item)
            if args.extract and item.get("local_path"):
                path = Path(item["local_path"])
                try:
                    chunks = extract_attachment(path)
                    db.replace_chunks(material_id, attachment_id, chunks, title=row["title"], target=row["target"], topics=row["topics"])
                    db.set_attachment_extraction(attachment_id, "ok" if chunks else "empty")
                    extracted += len(chunks)
                except Exception as exc:
                    db.set_attachment_extraction(attachment_id, "unsupported" if isinstance(exc, ValueError) else "error", f"{type(exc).__name__}: {exc}")
        if idx % 10 == 0:
            print(f"processed {idx}/{len(rows)}")

    if args.embed:
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            print("WARN: GEMINI_API_KEY missing; embeddings skipped")
        else:
            embed_chunks(db, key, args.embed_model)

    print("\n=== DB STATUS ===")
    print(json.dumps(db.status(), ensure_ascii=False, indent=2))
    print(f"unresolved attachment actions in this crawl: {unresolved}")
    print(f"extracted chunks in this run: {extracted}")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
