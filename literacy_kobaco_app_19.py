from __future__ import annotations

import base64
import mimetypes
import re
import sqlite3
import zipfile
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pypdf import PdfReader

import literacy_kobaco_app_18 as previous

app = previous.app
base = previous.base
flow = previous.flow

BASE_DIR = Path(__file__).resolve().parent
EDU_DB = BASE_DIR / "data" / "education" / "education.db"
EDU_FILES = (BASE_DIR / "data" / "education" / "files").resolve()
_EDU_THUMB_CACHE: dict[int, tuple[bytes, str]] = {}
_EDU_FOCUS_CACHE: dict[int, dict] = {}

_ACTIVITY_TERMS = (
    "생각 열기", "생각해", "함께 생각", "생각해 볼", "왜", "무엇", "어떻게",
    "마음", "상황", "활동", "실천", "문제", "퀴즈", "적어", "써 보", "골라", "선택",
)


def _education_case(case_id: str) -> dict:
    found = flow.CASE_BY_ID.get(case_id)
    if not found or not str(case_id).startswith("education_"):
        raise HTTPException(404, "교육자료를 찾을 수 없습니다.")
    return found[1]


def _safe_local_path(raw: str) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        resolved = path.resolve()
    except Exception:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    if EDU_FILES != resolved and EDU_FILES not in resolved.parents:
        return None
    return resolved


def _material_attachments(material_id: int) -> list[dict]:
    if not EDU_DB.exists():
        return []
    conn = sqlite3.connect(EDU_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, filename, local_path, mime_type
            FROM attachments
            WHERE material_id=? AND local_path<>''
            ORDER BY
              CASE
                WHEN LOWER(filename) LIKE '%.pdf' THEN 0
                WHEN LOWER(filename) LIKE '%.zip' THEN 1
                ELSE 2
              END,
              id
            """,
            (int(material_id),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _attachment(attachment_id: int | None) -> dict | None:
    if not attachment_id or not EDU_DB.exists():
        return None
    conn = sqlite3.connect(EDU_DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, material_id, filename, local_path, mime_type FROM attachments WHERE id=?",
            (int(attachment_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _pdf_document(material_id: int) -> Path | None:
    attachments = _material_attachments(material_id)
    for item in attachments:
        path = _safe_local_path(str(item.get("local_path") or ""))
        if path and path.suffix.lower() == ".pdf":
            return path

    cache_dir = BASE_DIR / "data" / "education" / "preview_cache" / f"{material_id:04d}"
    cached = cache_dir / "document.pdf"
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    for item in attachments:
        path = _safe_local_path(str(item.get("local_path") or ""))
        if not path or path.suffix.lower() != ".zip":
            continue
        try:
            with zipfile.ZipFile(path) as zf:
                pdfs = [
                    info for info in zf.infolist()
                    if not info.is_dir()
                    and info.filename.lower().endswith(".pdf")
                    and "__macosx/" not in info.filename.lower()
                ]
                if not pdfs:
                    continue
                pdfs.sort(key=lambda x: (x.filename.count("/"), len(x.filename), x.filename))
                data = zf.read(pdfs[0])
                if not data.startswith(b"%PDF"):
                    continue
                cache_dir.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(data)
                return cached
        except Exception:
            continue
    return None


def _image_media(data: bytes, name: str = "") -> str | None:
    lower = name.lower()
    if data.startswith(b"\x89PNG\r\n\x1a\n") or lower.endswith(".png"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff") or lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if data.startswith(b"GIF8") or lower.endswith(".gif"):
        return "image/gif"
    if (data[:4] == b"RIFF" and b"WEBP" in data[:16]) or lower.endswith(".webp"):
        return "image/webp"
    guessed = mimetypes.guess_type(name)[0] if name else None
    return guessed if guessed and guessed.startswith("image/") else None


def _thumbnail_from_zip(path: Path) -> tuple[bytes, str] | None:
    try:
        with zipfile.ZipFile(path) as zf:
            candidates = [
                info for info in zf.infolist()
                if not info.is_dir()
                and Path(info.filename).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
                and 12_000 <= info.file_size <= 12_000_000
                and "__macosx/" not in info.filename.lower()
            ]
            if not candidates:
                return None
            candidates.sort(
                key=lambda info: (
                    0 if any(x in info.filename.lower() for x in ("표지", "cover", "01", "001")) else 1,
                    -info.file_size,
                    len(info.filename),
                )
            )
            for info in candidates[:20]:
                data = zf.read(info)
                media = _image_media(data, info.filename)
                if media:
                    return data, media
    except Exception:
        return None
    return None


def _thumbnail_from_pdf(path: Path) -> tuple[bytes, str] | None:
    try:
        reader = PdfReader(str(path))
    except Exception:
        return None

    best: tuple[bytes, str] | None = None
    best_size = 0
    for page in reader.pages[:8]:
        try:
            images = list(page.images)
        except Exception:
            continue
        for image in images:
            try:
                data = bytes(image.data)
                name = str(getattr(image, "name", "") or "")
            except Exception:
                continue
            if len(data) < 12_000:
                continue
            media = _image_media(data, name)
            if not media:
                continue
            if len(data) > best_size:
                best = (data, media)
                best_size = len(data)
    return best


def _fallback_thumb(case: dict) -> tuple[bytes, str]:
    title = str(case.get("title") or "리터러시 교육자료")
    target = str(case.get("education_target") or "")
    safe_title = (
        title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
    safe_target = (
        target.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
    <rect width="960" height="540" fill="#eef3fb"/>
    <rect x="42" y="42" width="876" height="456" rx="28" fill="#fff" stroke="#cfd9e8"/>
    <text x="78" y="110" fill="#2864b7" font-family="sans-serif" font-size="24" font-weight="700">리터러시 교육 안내서</text>
    <foreignObject x="78" y="160" width="805" height="230"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:sans-serif;color:#24313f;font-size:34px;font-weight:800;line-height:1.35">{safe_title}</div></foreignObject>
    <text x="78" y="448" fill="#68778a" font-family="sans-serif" font-size="22">{safe_target}</text>
    </svg>'''
    return svg.encode("utf-8"), "image/svg+xml"


def _extract_source_questions(text: str) -> list[str]:
    clean = " ".join(str(text or "").replace("？", "?").split())
    if not clean:
        return []
    raw = re.findall(r"(?:^|(?<=[.!]))\s*([^?]{8,180}\?)", clean)
    out: list[str] = []
    for item in raw:
        q = re.sub(r"\s+", " ", item).strip(" -•·")
        q = re.sub(r"^\d+[.)]\s*", "", q)
        if len(q) < 8 or q in out:
            continue
        out.append(q)
        if len(out) >= 3:
            break
    return out


def _focus_info(material_id: int) -> dict:
    if material_id in _EDU_FOCUS_CACHE:
        return dict(_EDU_FOCUS_CACHE[material_id])
    result = {
        "attachment_id": None,
        "page": None,
        "page_end": None,
        "section": "",
        "text": "",
        "questions": [],
    }
    if not EDU_DB.exists():
        _EDU_FOCUS_CACHE[material_id] = result
        return dict(result)

    conn = sqlite3.connect(EDU_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, attachment_id, page_start, page_end, section, text
            FROM chunks
            WHERE material_id=?
            ORDER BY id
            """,
            (int(material_id),),
        ).fetchall()
    finally:
        conn.close()

    best = None
    best_score = -10**9
    for row in rows:
        text = " ".join(str(row["text"] or "").split())
        if not text:
            continue
        questions = _extract_source_questions(text)
        score = len(questions) * 16
        lower = text.lower()
        score += sum(5 for term in _ACTIVITY_TERMS if term in lower)
        if row["page_start"]:
            score += 4
        if 100 <= len(text) <= 2600:
            score += 3
        if any(x in lower for x in ("목차", "차례", "발간사", "저작권", "참고문헌")):
            score -= 12
        if score > best_score:
            best_score = score
            best = (row, text, questions)

    if best:
        row, text, questions = best
        result = {
            "attachment_id": int(row["attachment_id"]) if row["attachment_id"] else None,
            "page": int(row["page_start"]) if row["page_start"] else None,
            "page_end": int(row["page_end"]) if row["page_end"] else None,
            "section": str(row["section"] or ""),
            "text": text[:900],
            "questions": questions,
        }
    _EDU_FOCUS_CACHE[material_id] = result
    return dict(result)


def _focus_pdf(material_id: int, focus: dict) -> Path | None:
    item = _attachment(focus.get("attachment_id"))
    path = _safe_local_path(str((item or {}).get("local_path") or ""))
    if path and path.suffix.lower() == ".pdf":
        return path

    if path and path.suffix.lower() == ".zip":
        section = str(focus.get("section") or "")
        wanted = section.split(" :: ")[-1].replace("\\", "/") if ".pdf" in section.lower() else ""
        cache_dir = BASE_DIR / "data" / "education" / "preview_cache" / f"{material_id:04d}"
        cached = cache_dir / "focus.pdf"
        try:
            with zipfile.ZipFile(path) as zf:
                pdfs = [
                    info for info in zf.infolist()
                    if not info.is_dir() and info.filename.lower().endswith(".pdf") and "__macosx/" not in info.filename.lower()
                ]
                if wanted:
                    exact = [x for x in pdfs if x.filename.replace("\\", "/").endswith(wanted)]
                    if exact:
                        pdfs = exact
                if pdfs:
                    pdfs.sort(key=lambda x: (x.filename.count("/"), len(x.filename), x.filename))
                    data = zf.read(pdfs[0])
                    if data.startswith(b"%PDF"):
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        cached.write_bytes(data)
                        return cached
        except Exception:
            pass

    return _pdf_document(material_id)


def _focus_images_from_pdf(path: Path, page_no: int | None) -> list[tuple[bytes, str]]:
    try:
        reader = PdfReader(str(path))
    except Exception:
        return []
    if not reader.pages:
        return []

    base_index = max(0, min(len(reader.pages) - 1, int(page_no or 1) - 1))
    page_indexes = [base_index]
    if base_index > 0:
        page_indexes.append(base_index - 1)
    if base_index + 1 < len(reader.pages):
        page_indexes.append(base_index + 1)

    for idx in page_indexes:
        found: list[tuple[bytes, str]] = []
        try:
            images = list(reader.pages[idx].images)
        except Exception:
            images = []
        for image in images:
            try:
                data = bytes(image.data)
                name = str(getattr(image, "name", "") or "")
            except Exception:
                continue
            if len(data) < 10_000:
                continue
            media = _image_media(data, name)
            if media:
                found.append((data, media))
        if found:
            found.sort(key=lambda x: len(x[0]), reverse=True)
            biggest = len(found[0][0])
            useful = [x for x in found if len(x[0]) >= max(10_000, biggest // 5)]
            return useful[:4]
    return []


def _focus_montage(images: list[tuple[bytes, str]], fallback: tuple[bytes, str]) -> tuple[bytes, str]:
    if not images:
        return fallback
    if len(images) == 1:
        return images[0]

    images = images[:4]
    cols = 2 if len(images) >= 3 else 1
    rows = (len(images) + cols - 1) // cols
    width = 1000
    height = 650 if rows == 1 else 900
    cell_w = width / cols
    cell_h = height / rows
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="#f4f1eb"/>']
    for i, (data, media) in enumerate(images):
        row = i // cols
        col = i % cols
        x = col * cell_w + 8
        y = row * cell_h + 8
        w = cell_w - 16
        h = cell_h - 16
        encoded = base64.b64encode(data).decode("ascii")
        parts.append(
            f'<image x="{x}" y="{y}" width="{w}" height="{h}" preserveAspectRatio="xMidYMid meet" href="data:{media};base64,{encoded}"/>'
        )
    parts.append("</svg>")
    return "".join(parts).encode("utf-8"), "image/svg+xml"


def _apply_focus_to_cases() -> None:
    for case in flow.CASE_LIBRARY.get("deepfake", []):
        if not str(case.get("id") or "").startswith("education_"):
            continue
        material_id = int(case.get("education_material_id") or 0)
        if not material_id:
            continue
        focus = _focus_info(material_id)
        case["education_focus_page"] = focus.get("page") or ""
        case["education_focus_text"] = focus.get("text") or ""
        case["education_source_questions"] = focus.get("questions") or []
        questions = [str(x).strip() for x in (focus.get("questions") or []) if str(x).strip()]
        if questions:
            case["opening_questions"] = questions[:3]
            case["opening_question"] = questions[0]


_apply_focus_to_cases()

_OLD_PUBLIC_CASE_V19 = flow._public_case


def _public_case_v19(case):
    data = dict(_OLD_PUBLIC_CASE_V19(case))
    if str(case.get("id") or "").startswith("education_"):
        for key in ("education_focus_page", "education_focus_text", "education_source_questions"):
            data[key] = case.get(key, "")
    return data


flow._public_case = _public_case_v19


for path in ("/api/education-file/{case_id}", "/api/education-thumb/{case_id}", "/api/education-focus/{case_id}"):
    base._remove_route(path, "GET")


@app.get("/api/education-file/{case_id}")
def education_file_v19(case_id: str):
    case = _education_case(case_id)
    material_id = int(case.get("education_material_id") or 0)
    path = _pdf_document(material_id)
    if not path:
        raise HTTPException(404, "브라우저에서 바로 볼 수 있는 PDF 원문이 없습니다.")
    return FileResponse(path, media_type="application/pdf", headers={"Content-Disposition": "inline"})


@app.get("/api/education-thumb/{case_id}")
def education_thumb_v19(case_id: str):
    case = _education_case(case_id)
    material_id = int(case.get("education_material_id") or 0)
    if material_id in _EDU_THUMB_CACHE:
        data, media = _EDU_THUMB_CACHE[material_id]
        return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=3600"})

    result: tuple[bytes, str] | None = None
    attachments = _material_attachments(material_id)
    for item in attachments:
        path = _safe_local_path(str(item.get("local_path") or ""))
        if path and path.suffix.lower() == ".zip":
            result = _thumbnail_from_zip(path)
            if result:
                break
    if not result:
        pdf = _pdf_document(material_id)
        if pdf:
            result = _thumbnail_from_pdf(pdf)
    if not result:
        result = _fallback_thumb(case)

    _EDU_THUMB_CACHE[material_id] = result
    data, media = result
    return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/education-focus/{case_id}")
def education_focus_v19(case_id: str):
    case = _education_case(case_id)
    material_id = int(case.get("education_material_id") or 0)
    focus = _focus_info(material_id)
    pdf = _focus_pdf(material_id, focus)
    fallback = _EDU_THUMB_CACHE.get(material_id) or _fallback_thumb(case)
    if pdf:
        images = _focus_images_from_pdf(pdf, focus.get("page"))
        data, media = _focus_montage(images, fallback)
    else:
        data, media = fallback
    return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=1800"})


def _render_index_kobaco_v19():
    page = previous._render_index_kobaco_v18()
    patch = r'''
<style>
/* LOGIN OFF=회색 점, LOGIN ON=파란 점. ON일 때 로그아웃 버튼은 바로 아래에 붙인다. */
.aioff-auth-state:before{display:none!important}
.aioff-login-indicator{display:inline-block;width:7px;height:7px;border-radius:50%;flex:0 0 7px;background:#aaa39a;margin-right:6px;vertical-align:1px}
.aioff-auth-dock.is-on .aioff-login-indicator{background:#2f75e8}
.aioff-auth-state{display:inline-flex!important;align-items:center!important}
.aioff-auth-dock.is-on .aioff-auth-links{position:static!important;width:auto!important;height:auto!important;padding:6px 0 0!important;margin:0!important;display:flex!important;justify-content:flex-end!important;background:transparent!important;border:0!important;box-shadow:none!important}
.aioff-auth-dock.is-on .aioff-auth-links button,.aioff-auth-dock.is-on .aioff-auth-links button:first-of-type{min-width:78px!important;height:34px!important;padding:0 13px!important;border:1px solid #cfc7bc!important;border-radius:8px!important;background:#f7f3ed!important;color:#514b45!important;font-size:11px!important;font-weight:800!important}

/* 학교 자동완성은 select와 같은 정렬/화살표를 사용한다. */
.aioff-school-search.aioff-school-combobox{position:relative!important;display:block!important;width:100%!important}
.aioff-school-search.aioff-school-combobox:after{content:"";position:absolute;right:16px;top:20px;width:7px;height:7px;border-right:1.5px solid #302c28;border-bottom:1.5px solid #302c28;transform:rotate(45deg);pointer-events:none;z-index:3}
.aioff-school-search.aioff-school-combobox.is-open:after{transform:translateY(4px) rotate(225deg)}
#aioff-school-name{width:100%!important;height:42px!important;min-height:42px!important;box-sizing:border-box!important;padding:0 42px 0 12px!important;margin:0!important;line-height:40px!important;border-radius:8px!important;background:#fff!important}
.aioff-school-search.aioff-school-combobox.is-open #aioff-school-name{border-bottom-left-radius:0!important;border-bottom-right-radius:0!important;border-color:#bdb4a9!important}
#aioff-school-results{left:0!important;right:0!important;top:41px!important;width:100%!important;box-sizing:border-box!important;margin:0!important;max-height:250px!important;padding:0!important;overflow-y:auto!important;border:1px solid #bdb4a9!important;border-top:0!important;border-radius:0 0 8px 8px!important;background:#fff!important;box-shadow:0 9px 22px rgba(35,29,23,.14)!important}
#aioff-school-results:not(.open){display:none!important}#aioff-school-results.open{display:block!important}#aioff-school-results.open:before{display:none!important}
#aioff-school-results .aioff-school-result{display:block!important;width:100%!important;min-height:48px!important;box-sizing:border-box!important;margin:0!important;padding:8px 12px!important;border:0!important;border-bottom:1px solid #ece5dc!important;border-radius:0!important;background:#fff!important;text-align:left!important;color:#2f2b27!important;line-height:1.25!important}
#aioff-school-results .aioff-school-result:hover,#aioff-school-results .aioff-school-result.is-active{background:#f2f5fa!important}
#aioff-school-results .aioff-school-result b{display:block!important;margin:0 0 3px!important;font-size:12px!important}#aioff-school-results .aioff-school-result small{display:block!important;margin:0!important;font-size:10px!important;color:#756e67!important}

/* 교육자료 선택 카드 */
.education-guide-preview-v19{height:142px;margin:-10px -10px 9px;position:relative;overflow:hidden;border-radius:7px;background:#e8edf5;border:1px solid #d3dbe7}
.education-guide-preview-v19 img{width:100%;height:100%;display:block;object-fit:cover;background:#eef3fb}
.education-guide-preview-v19 .edu-chip{position:absolute;left:8px;bottom:8px;max-width:calc(100% - 16px);padding:4px 7px;border-radius:6px;background:rgba(22,31,43,.78);color:#fff;font-size:8px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* 선택 후에는 PDF 전체가 아니라 실제 활동 장면 + 자료 속 질문만 보여준다. */
.education-learning-card{border:1px solid #d9d2c9;border-radius:9px;background:#fff;overflow:hidden}
.education-learning-head{padding:13px 15px;background:#f7f9fc;border-bottom:1px solid #dfe5ee}.education-learning-head small{display:block;font-size:8px;color:#66758a;margin-bottom:4px}.education-learning-head b{font-size:14px;line-height:1.4}
.education-focus-stage{padding:12px;background:#f2f0ec;border-bottom:1px solid #ded8d0}.education-focus-stage img{display:block;width:100%;max-height:520px;object-fit:contain;margin:0 auto;background:#fff;border-radius:7px}
.education-focus-label{padding:9px 14px 0;background:#fff;font-size:9px;font-weight:900;color:#74685d}
.education-source-questions{padding:10px 16px 14px;background:#fff8ef;border-bottom:1px solid #eadfce}.education-source-questions small{display:block;font-size:9px;color:#8a6b4f;font-weight:900;margin-bottom:7px}.education-source-questions ol{margin:0;padding-left:20px}.education-source-questions li{font-size:12px;line-height:1.6;color:#332b25;margin:4px 0;font-weight:750}
.education-focus-excerpt{padding:11px 15px;background:#fff;border-bottom:1px solid #e8e1d8}.education-focus-excerpt small{display:block;font-size:8px;color:#7a7067;margin-bottom:5px;font-weight:850}.education-focus-excerpt p{margin:0;font-size:10px;line-height:1.55;color:#5e554d;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.education-learning-meta{display:flex;gap:6px;flex-wrap:wrap;padding:10px 14px;background:#faf8f4;border-bottom:1px solid #e7e0d7}.education-learning-meta span{padding:5px 8px;border:1px solid #ded6cb;border-radius:999px;background:#fff;font-size:9px;color:#645c54}
.education-learning-actions{display:flex;gap:8px;padding:10px 14px 13px;flex-wrap:wrap}.education-learning-actions a{display:inline-flex;padding:7px 10px;border-radius:7px;text-decoration:none;font-size:9px;font-weight:850;background:#26221f;color:#fff!important}.education-learning-actions a.alt{background:#fff;color:#2d2925!important;border:1px solid #cfc6ba}
</style>
<script>
(() => {
  const dock=document.querySelector('.aioff-auth-dock');
  const state=dock?.querySelector('.aioff-auth-state');
  if(dock&&state){
    const prev=dock.previousElementSibling;
    if(prev && !(prev.textContent||'').trim()){
      const r=prev.getBoundingClientRect();
      if(r.width<=16 && r.height<=16) prev.style.display='none';
    }
    if(!state.querySelector('.aioff-login-indicator')){
      const dot=document.createElement('span');
      dot.className='aioff-login-indicator';dot.setAttribute('aria-hidden','true');state.prepend(dot);
    }
  }

  const schoolInput=document.getElementById('aioff-school-name');
  const schoolWrap=schoolInput?.closest('.aioff-school-search');
  const schoolBox=document.getElementById('aioff-school-results');
  if(schoolInput&&schoolWrap&&schoolBox){
    schoolWrap.classList.add('aioff-school-combobox');schoolInput.setAttribute('autocomplete','off');schoolInput.setAttribute('role','combobox');schoolInput.setAttribute('aria-autocomplete','list');schoolInput.setAttribute('aria-controls','aioff-school-results');schoolInput.setAttribute('spellcheck','false');
    function syncOpen(){const open=schoolBox.classList.contains('open');schoolWrap.classList.toggle('is-open',open);schoolInput.setAttribute('aria-expanded',open?'true':'false')}
    syncOpen();new MutationObserver(syncOpen).observe(schoolBox,{attributes:true,attributeFilter:['class']});
  }

  const educationPool19=Array.isArray(fixedTopicCases?.deepfake)?[...fixedTopicCases.deepfake]:[];
  function strictLevelMatch(c,user){
    const target=String(c?.education_target||'').replace(/\s+/g,'');
    const level=user?.school_level||'';
    const hasElementary=/(초등|초등학생|초등학교)/.test(target)||target==='초';
    const hasMiddle=/(중등|중학생|중학교)/.test(target)||target==='중';
    const hasHigh=/(고등|고등학생|고등학교)/.test(target)||target==='고';
    const hasAdult=/(학부모|보호자|교사|교직원)/.test(target);
    if(level==='초') return hasElementary&&!hasMiddle&&!hasHigh&&!hasAdult;
    if(level==='중') return hasMiddle&&!hasElementary&&!hasHigh&&!hasAdult;
    if(level==='고') return hasHigh&&!hasElementary&&!hasMiddle&&!hasAdult;
    return false;
  }
  function gradePriority(c,user){
    const text=`${c?.education_target||''} ${c?.title||''}`;const grade=Number(user?.grade||0);
    if(user?.school_level==='초'){if(grade<=3&&/(저학년|1.?3학년|1~3학년)/.test(text))return 6;if(grade>=4&&/(고학년|4.?6학년|4~6학년)/.test(text))return 6;if(/초등/.test(text))return 3}
    if(user?.school_level==='중'&&/(중등|중학생|중학교)/.test(text))return 3;
    if(user?.school_level==='고'&&/(고등|고등학생|고등학교)/.test(text))return 3;
    return 1;
  }
  const chooserBeforeV19=window.showCaseChooser;
  window.showCaseChooser=async function(lessonId){
    if(lessonId!=='deepfake')return chooserBeforeV19(lessonId);
    try{
      const r=await fetch('/api/auth/me',{credentials:'same-origin'});const data=r.ok?await r.json():{};const user=data.logged_in?data.user:null;
      if(user){
        const strict=educationPool19.filter(c=>strictLevelMatch(c,user)).map((c,i)=>({c,i,s:gradePriority(c,user)})).sort((a,b)=>b.s-a.s||a.i-b.i).map(x=>x.c);
        fixedTopicCases.deepfake=strict;delete fixedSamples.deepfake;
      }
    }catch(e){}
    return chooserBeforeV19(lessonId);
  };

  const previewBeforeV19=window.fixedPreview;
  window.fixedPreview=function(c){
    const id=String(c?.id||'');if(!id.startsWith('education_'))return previewBeforeV19(c);
    const target=c.education_target||'';const year=c.education_year||'';
    return `<div class="education-guide-preview-v19"><img src="/api/education-thumb/${encodeURIComponent(id)}" alt="${esc(c.title||'교육자료')} 썸네일" loading="lazy"><span class="edu-chip">${esc([target,year].filter(Boolean).join(' · '))}</span></div>`;
  };

  const mediaBeforeV19=window.caseMedia;
  window.caseMedia=function(c){
    const id=String(c?.id||'');if(!id.startsWith('education_'))return mediaBeforeV19(c);
    const rows={};(c.data_rows||[]).forEach(r=>rows[String(r.label||'')]=String(r.value||''));
    let questions=Array.isArray(c.education_source_questions)?c.education_source_questions.filter(Boolean):[];
    if(!questions.length){
      const q=c.opening_question||(Array.isArray(c.opening_questions)?c.opening_questions[0]:'')||'위 활동 장면을 보고 자료에서 직접 확인한 내용과 자신의 생각을 나누어 적어보세요.';
      questions=[q];
    }
    const qhtml=questions.slice(0,3).map(q=>`<li>${esc(q)}</li>`).join('');
    const focusText=String(c.education_focus_text||'').trim();
    const page=c.education_focus_page?` · 원문 ${esc(String(c.education_focus_page))}쪽 부근`:'';
    const excerpt=focusText?`<div class="education-focus-excerpt"><small>이 활동과 함께 추출된 원문${page}</small><p>${esc(focusText)}</p></div>`:'';
    const source=c.source_url?`<a class="alt" href="${esc(c.source_url)}" target="_blank" rel="noopener">공식 자료 페이지 ↗</a>`:'';
    return `<div class="chat-case-media"><div class="education-learning-card"><div class="education-learning-head"><small>리터러시 교육 안내서 · 활동 한 장면</small><b>${esc(c.title||'디지털윤리 교육자료')}</b></div><div class="education-focus-stage"><img src="/api/education-focus/${encodeURIComponent(id)}" alt="${esc(c.title||'교육자료')} 활동 장면"></div><div class="education-focus-label">전체 파일을 펼치지 않고, 이 자료에서 문제와 연결된 활동 장면만 보여줍니다.</div><div class="education-source-questions"><small>자료 속 문제</small><ol>${qhtml}</ol></div>${excerpt}<div class="education-learning-meta"><span>대상 ${esc(rows['대상']||'-')}</span><span>${esc(rows['연도']||'연도 -')}</span><span>${esc(rows['자료유형']||'자료유형 -')}</span></div><div class="education-learning-actions"><a href="/api/education-file/${encodeURIComponent(id)}" target="_blank" rel="noopener">원문 전체 보기 ↗</a>${source}</div></div></div>`;
  };
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v19():
    return HTMLResponse(_render_index_kobaco_v19())
