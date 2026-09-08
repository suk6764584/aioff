from __future__ import annotations

import posixpath
import re
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

import auth_proto as auth
import literacy_kobaco_app_19 as education_source
import literacy_kobaco_app_20 as previous

app = previous.app
base = previous.base
flow = previous.flow


# 교육자료는 특정 제목이나 페이지를 하드코딩하지 않는다.
# 1) 학생용/활동용 원문을 고른다.
# 2) 그림·사진·표를 봐야 풀 수 있는 활동이면 그 실제 자료를 같이 보여준다.
# 3) 화면에 없는 자료를 봐야만 풀 수 있는 문제는 출제하지 않는다.
# 4) 텍스트 자료는 원문을 그대로 복사하지 않고, 원문이 뒷받침하는 학습 내용으로 재구성한다.

_STUDENT_FILE_TERMS = (
    "학생용", "학습지", "활동지", "워크북", "교재", "학습자료", "활동자료", "실습",
)
_TEACHER_FILE_TERMS = (
    "교사용", "지도서", "교수학습", "수업지도", "지도안", "강사용", "매뉴얼",
)
_ACTIVITY_TERMS = (
    "생각 열기", "생각열기", "생각 펼치기", "생각펼치기", "생각 키우기", "생각키우기",
    "함께 생각", "다음 상황", "활동", "실천", "찾아보", "골라보", "선택해", "비교해",
    "이야기해", "말해보", "적어보", "써보", "확인해", "판단해", "해볼까요", "해봅시다",
)
_TEACHER_TEXT_TERMS = (
    "수업 전개 흐름", "수업전개흐름", "학습 목표", "학습목표", "교수·학습", "교수학습",
    "수업 개요", "수업개요", "지도상의 유의", "교사용", "지도서", "성취기준", "교육과정",
    "관련 교과", "교과 연계", "교과연계", "차시", "핵심역량", "평가기준",
)
_META_TERMS = (
    "목차", "차례", "발간사", "머리말", "참고문헌", "집필진", "연구진", "발행처", "ISBN", "CIP",
)
_PROMPT_TERMS = (
    "왜", "무엇", "어떻게", "어떤", "찾아보", "골라보", "선택해", "비교해", "이야기해",
    "말해보", "적어보", "써보", "생각해", "확인해", "판단해", "해볼까요", "해봅시다",
)
_VISUAL_DEPENDENT_TERMS = (
    "아래 표", "아래의 표", "위의 표", "그림", "사진", "이미지", "장면", "화면", "말풍선",
    "가로", "세로", "대각선", "연결해", "선을 그", "빈칸", "위에서 찾", "다음 상황을 보고",
)
_TABLE_CODE_RE = re.compile(r"\[[0-9]{1,2}[가-힣A-Za-z]+[0-9\-~.]+\]")
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")

_SOURCE_CACHE: dict[int, dict] = {}
_VISUAL_CACHE: dict[int, dict | None] = {}
_PACK_CACHE: dict[tuple[int, str, int], dict] = {}


class EducationStudyDraft(BaseModel):
    activity_title: str = ""
    reading: list[str] = []
    questions: list[str] = []


def _clean_text(value: str) -> str:
    value = str(value or "").replace("\u00a0", " ").replace("？", "?")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _clean_lines(value: str) -> list[str]:
    out: list[str] = []
    for raw in _clean_text(value).splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" \t-•·")
        if len(line) < 5 or re.fullmatch(r"\d{1,3}", line):
            continue
        if line not in out:
            out.append(line)
    return out


def _is_prompt(line: str) -> bool:
    if "?" in line:
        return True
    return any(term in line for term in _PROMPT_TERMS) and 8 <= len(line) <= 220


def _source_prompts(text: str) -> list[str]:
    out: list[str] = []
    for line in _clean_lines(text):
        lower = line.lower()
        if any(term.lower() in lower for term in _TEACHER_TEXT_TERMS + _META_TERMS):
            continue
        if not _is_prompt(line):
            continue
        line = re.sub(r"^\s*\d+\s*[.)]\s*", "", line).strip()
        if line and line not in out:
            out.append(line)
        if len(out) >= 5:
            break
    return out


def _section_role_score(section: str) -> int:
    text = str(section or "").lower()
    score = sum(80 for term in _STUDENT_FILE_TERMS if term.lower() in text)
    score -= sum(105 for term in _TEACHER_FILE_TERMS if term.lower() in text)
    return score


def _chunk_score(row: sqlite3.Row) -> tuple[int, list[str]]:
    text = _clean_text(row["text"] or "")
    lower = text.lower()
    prompts = _source_prompts(text)
    score = _section_role_score(str(row["section"] or ""))
    score += len(prompts) * 45
    score += sum(13 for term in _ACTIVITY_TERMS if term in text)
    score -= sum(60 for term in _TEACHER_TEXT_TERMS if term.lower() in lower)
    score -= sum(70 for term in _META_TERMS if term.lower() in lower)
    score -= min(8, len(_TABLE_CODE_RE.findall(text))) * 18
    if 180 <= len(text) <= 5000:
        score += 18
    if not prompts and not any(term in text for term in _ACTIVITY_TERMS):
        score -= 35
    return score, prompts


def _select_source(case: dict) -> dict:
    material_id = int(case.get("education_material_id") or 0)
    if material_id in _SOURCE_CACHE:
        return dict(_SOURCE_CACHE[material_id])

    empty = {
        "material_id": material_id,
        "row_id": 0,
        "attachment_id": 0,
        "section": "",
        "page_start": None,
        "page_end": None,
        "text": "",
        "prompts": [],
        "context": "",
        "source_name": "",
    }
    if not material_id or not education_source.EDU_DB.exists():
        _SOURCE_CACHE[material_id] = empty
        return dict(empty)

    conn = sqlite3.connect(education_source.EDU_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, attachment_id, page_start, page_end, section, text
            FROM chunks
            WHERE material_id=? AND TRIM(text)<>''
            ORDER BY id
            """,
            (material_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        _SOURCE_CACHE[material_id] = empty
        return dict(empty)

    ranked: list[tuple[int, sqlite3.Row, list[str]]] = []
    for row in rows:
        score, prompts = _chunk_score(row)
        ranked.append((score, row, prompts))
    ranked.sort(key=lambda x: x[0], reverse=True)
    usable = [x for x in ranked if x[2] or any(term in str(x[1]["text"] or "") for term in _ACTIVITY_TERMS)]
    _, best, prompts = (usable or ranked)[0]

    same_attachment = [
        row for row in rows
        if int(row["attachment_id"] or 0) == int(best["attachment_id"] or 0)
        and abs(int(row["id"]) - int(best["id"])) <= 2
    ]
    context_parts: list[str] = []
    for row in same_attachment:
        text = _clean_text(row["text"] or "")
        if text and text not in context_parts:
            context_parts.append(text)
    context = "\n\n".join(context_parts)[:9000]
    section = str(best["section"] or "")
    source_name = Path(section.split(" :: ")[-1]).name if section else ""
    result = {
        "material_id": material_id,
        "row_id": int(best["id"]),
        "attachment_id": int(best["attachment_id"] or 0),
        "section": section,
        "page_start": best["page_start"],
        "page_end": best["page_end"],
        "text": _clean_text(best["text"] or ""),
        "prompts": prompts,
        "context": context or _clean_text(best["text"] or ""),
        "source_name": source_name,
    }
    _SOURCE_CACHE[material_id] = result
    return dict(result)


def _visual_required(source: dict) -> bool:
    text = " ".join([source.get("text", ""), *source.get("prompts", [])])
    return any(term in text for term in _VISUAL_DEPENDENT_TERMS)


def _tokens(text: str) -> set[str]:
    stop = {"그리고", "합니다", "하세요", "있습니다", "에서는", "것입니다", "여러분", "아래의", "위에서"}
    return {t for t in _TOKEN_RE.findall(_clean_text(text)) if t not in stop}


def _text_overlap_score(seed: str, candidate: str) -> int:
    a = _tokens(seed)
    b = _tokens(candidate)
    if not a or not b:
        return 0
    common = a & b
    return sum(min(8, len(x)) for x in common)


def _attachment_payload(source: dict) -> tuple[str, Path | bytes | None]:
    item = education_source._attachment(source.get("attachment_id"))
    path = education_source._safe_local_path(str((item or {}).get("local_path") or ""))
    if not path:
        return "", None
    suffix = path.suffix.lower()
    if suffix in {".pdf", ".pptx"}:
        return suffix, path
    if suffix != ".zip":
        return suffix, path

    wanted = str(source.get("section") or "").split(" :: ")[-1].replace("\\", "/")
    wanted_suffix = Path(wanted).suffix.lower()
    if wanted_suffix not in {".pdf", ".pptx"}:
        return ".zip", path
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            exact = next((n for n in names if n.replace("\\", "/") == wanted), None)
            if not exact:
                exact = next((n for n in names if n.replace("\\", "/").endswith(wanted)), None)
            if exact:
                return wanted_suffix, zf.read(exact)
    except Exception:
        pass
    return ".zip", path


def _pdf_visual(source: dict, payload: Path | bytes, required: bool) -> dict | None:
    try:
        reader = PdfReader(str(payload) if isinstance(payload, Path) else BytesIO(payload))
    except Exception:
        return None
    if not reader.pages:
        return None

    seed = source.get("text", "")
    best_index = 0
    best_score = -1
    for idx, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        score = _text_overlap_score(seed, text)
        hint = source.get("page_start")
        if hint and abs((idx + 1) - int(hint)) <= 1:
            score += 8
        if any(term in text for term in _VISUAL_DEPENDENT_TERMS):
            score += 14
        if score > best_score:
            best_score = score
            best_index = idx

    page = reader.pages[best_index]
    has_images = False
    try:
        has_images = bool(list(page.images))
    except Exception:
        has_images = False
    if not required and not has_images:
        return None

    writer = PdfWriter()
    writer.add_page(page)
    buf = BytesIO()
    writer.write(buf)
    return {
        "kind": "pdf",
        "media_type": "application/pdf",
        "data": buf.getvalue(),
        "page": best_index + 1,
    }


def _xml_text(data: bytes) -> str:
    try:
        root = ET.fromstring(data)
    except Exception:
        return ""
    values: list[str] = []
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1].lower() == "t" and elem.text:
            values.append(elem.text)
    return "\n".join(values)


def _pptx_visual(source: dict, payload: Path | bytes) -> dict | None:
    try:
        zf = zipfile.ZipFile(str(payload) if isinstance(payload, Path) else BytesIO(payload))
    except Exception:
        return None
    with zf:
        slides = [n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n, re.I)]
        slides.sort(key=lambda n: int(re.search(r"(\d+)", Path(n).stem).group(1)))
        if not slides:
            return None
        seed = source.get("text", "")
        best_name = max(slides, key=lambda n: _text_overlap_score(seed, _xml_text(zf.read(n))))
        slide_root = ET.fromstring(zf.read(best_name))
        embed_ids: list[str] = []
        for elem in slide_root.iter():
            for key, value in elem.attrib.items():
                if key.rsplit("}", 1)[-1] == "embed" and value not in embed_ids:
                    embed_ids.append(value)
        rel_name = posixpath.join(posixpath.dirname(best_name), "_rels", posixpath.basename(best_name) + ".rels")
        rels: dict[str, str] = {}
        if rel_name in zf.namelist():
            rel_root = ET.fromstring(zf.read(rel_name))
            for rel in rel_root:
                rid = rel.attrib.get("Id", "")
                target = rel.attrib.get("Target", "")
                if rid and target:
                    rels[rid] = posixpath.normpath(posixpath.join(posixpath.dirname(best_name), target))
        images: list[tuple[bytes, str]] = []
        for rid in embed_ids:
            name = rels.get(rid, "")
            if not name or name not in zf.namelist():
                continue
            data = zf.read(name)
            if len(data) < 10_000:
                continue
            media = education_source._image_media(data, name)
            if media:
                images.append((data, media))
        if not images:
            media_names = [n for n in zf.namelist() if n.lower().startswith("ppt/media/")]
            media_names.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
            for name in media_names[:6]:
                data = zf.read(name)
                if len(data) < 10_000:
                    continue
                media = education_source._image_media(data, name)
                if media:
                    images.append((data, media))
        if not images:
            return None
        images.sort(key=lambda x: len(x[0]), reverse=True)
        data, media = education_source._focus_montage(images[:4], images[0])
        slide_no = int(re.search(r"(\d+)", Path(best_name).stem).group(1))
        return {"kind": "image", "media_type": media, "data": data, "page": slide_no}


def _build_visual(source: dict) -> dict | None:
    material_id = int(source.get("material_id") or 0)
    if material_id in _VISUAL_CACHE:
        return _VISUAL_CACHE[material_id]
    suffix, payload = _attachment_payload(source)
    required = _visual_required(source)
    result = None
    if payload is not None and suffix == ".pdf":
        result = _pdf_visual(source, payload, required)
    elif payload is not None and suffix == ".pptx":
        result = _pptx_visual(source, payload)
    _VISUAL_CACHE[material_id] = result
    return result


def _fallback_study(case: dict, source: dict, visual_available: bool) -> dict:
    lines = _clean_lines(source.get("text", ""))
    reading: list[str] = []
    for line in lines:
        lower = line.lower()
        if _is_prompt(line) or _TABLE_CODE_RE.search(line):
            continue
        if any(term.lower() in lower for term in _TEACHER_TEXT_TERMS + _META_TERMS):
            continue
        if 18 <= len(line) <= 260 and line not in reading:
            reading.append(line)
        if len(reading) >= 4:
            break

    questions: list[str] = []
    for q in source.get("prompts", []):
        depends = any(term in q for term in _VISUAL_DEPENDENT_TERMS)
        if depends and not visual_available:
            continue
        if any(term in q for term in ("가로", "세로", "대각선", "선을 그", "연결해")):
            if visual_available:
                q = "자료에서 찾은 정보 출처를 몇 가지 적어보세요."
            else:
                continue
        if q not in questions:
            questions.append(q)
        if len(questions) >= 3:
            break
    if not questions:
        questions = [
            "이 자료에서 가장 중요하다고 생각한 내용을 한 가지 적어보세요.",
            "그 내용을 실제 생활에서 어떻게 확인하거나 적용할 수 있을까요?",
        ]
    return {
        "activity_title": str(case.get("title") or "학습 활동"),
        "reading": reading or ["자료의 핵심 내용을 확인하고, 어떤 기준으로 판단해야 하는지 생각해보세요."],
        "questions": questions,
    }


def _make_study_pack(case: dict, source: dict, user: dict | None, visual: dict | None) -> dict:
    material_id = int(source.get("material_id") or 0)
    level = str((user or {}).get("school_level") or case.get("education_target") or "")
    grade = int((user or {}).get("grade") or 0)
    cache_key = (material_id, level, grade)
    if cache_key in _PACK_CACHE:
        return dict(_PACK_CACHE[cache_key])

    visual_available = visual is not None
    visual_required = _visual_required(source)
    fallback = _fallback_study(case, source, visual_available)
    profile = f"{level} {grade}학년" if grade else (level or "학생")
    original_questions = "\n".join(f"- {q}" for q in source.get("prompts", [])) or "- 없음"
    prompt = f"""다음은 디지털 리터러시 교육자료에서 추출한 실제 원문이다.
학생 화면에 바로 사용할 학습 카드로 재구성하라.

학생: {profile}
자료명: {case.get('title', '')}
원문 파일: {source.get('source_name', '')}
시각 자료가 화면에 함께 표시되는가: {'예' if visual_available else '아니오'}
원래 활동이 표·그림·사진 등 시각 자료를 요구하는가: {'예' if visual_required else '아니오'}

[원문]
{source.get('context', '')[:8500]}

[원문에서 찾은 질문/활동문]
{original_questions}

작성 규칙:
1. 원문이 뒷받침하는 내용만 사용한다. 새로운 사실, 수치, 사례를 만들지 않는다.
2. 원문 문장을 순서대로 복사하지 말고, 학생이 이해할 수 있는 설명으로 묶어 2~4개의 reading 문단으로 정리한다.
3. 페이지 번호, 차시 번호, 파일명, 목차, 교사용 지시, 성취기준 같은 편집 정보는 reading에서 빼라.
4. questions는 2~3개로 만든다. 원문 질문의 학습 목적을 최대한 유지하되 웹 화면에서 실제로 답할 수 있게 바꾼다.
5. '가로·세로·대각선으로 선을 그어라', '빈칸에 직접 표시하라'처럼 종이에 손으로 해야 하는 활동은 그대로 내지 말고, 찾은 항목을 글로 적거나 이유를 설명하는 문제로 바꾼다.
6. 시각 자료가 화면에 없으면 '아래 표를 보고', '그림에서 찾아', '위에서 찾은'처럼 보이지 않는 자료를 전제로 한 질문을 절대 만들지 않는다.
7. 시각 자료가 화면에 있으면 그 자료를 관찰해야 답할 수 있는 질문은 허용하되, 화면에 직접 선을 긋거나 표시해야 하는 과제는 내지 않는다.
8. 정답을 미리 알려주지 않는다. 읽어보기는 개념·상황 이해에 필요한 설명이고, 질문은 학생이 직접 생각하게 한다.
9. 'AI가 정리했다', '모델', 'RAG', '생성' 같은 표현은 사용하지 않는다.
10. activity_title은 '학생용 활동지' 같은 파일 종류가 아니라 실제 학습 주제를 한 문장으로 적는다.

JSON 스키마에 맞춰 반환하라."""
    try:
        draft, _ = base.core.generate_structured_with_fallback(
            prompt,
            EducationStudyDraft,
            max_output_tokens=900,
        )
        reading = [str(x).strip() for x in draft.reading if str(x).strip()][:4]
        questions = [str(x).strip() for x in draft.questions if str(x).strip()][:3]
        title = str(draft.activity_title or "").strip()
        if not reading or len(questions) < 2:
            raise ValueError("education_study_draft_incomplete")
        pack = {"activity_title": title or fallback["activity_title"], "reading": reading, "questions": questions}
    except Exception as exc:
        base.core.logger.warning("Education study transformation failed: %s", type(exc).__name__)
        pack = fallback

    pack.update({
        "visual_kind": (visual or {}).get("kind", ""),
        "visual_available": visual_available,
        "visual_required": visual_required,
        "source_name": source.get("source_name", ""),
        "page": (visual or {}).get("page") or source.get("page_start") or "",
    })
    _PACK_CACHE[cache_key] = dict(pack)
    return pack


for route_path in ("/api/education-learning/{case_id}", "/api/education-visual/{case_id}"):
    base._remove_route(route_path, "GET")


@app.get("/api/education-learning/{case_id}")
def education_learning_v21(case_id: str, request: Request):
    case = education_source._education_case(case_id)
    source = _select_source(case)
    visual = _build_visual(source)
    user = auth.current_user(request.cookies.get(auth.COOKIE_NAME))
    return {"ok": True, "pack": _make_study_pack(case, source, user, visual)}


@app.get("/api/education-visual/{case_id}")
def education_visual_v21(case_id: str):
    case = education_source._education_case(case_id)
    source = _select_source(case)
    visual = _build_visual(source)
    if not visual:
        raise HTTPException(404, "표시할 시각 학습자료가 없습니다.")
    return Response(
        visual["data"],
        media_type=visual["media_type"],
        headers={"Cache-Control": "public, max-age=1800", "Content-Disposition": "inline"},
    )


# ---------------------------------------------------------------------------
# 화면 정리
# ---------------------------------------------------------------------------
def _render_index_kobaco_v21():
    page = previous._render_index_kobaco_v20()

    page = re.sub(
        r'\s*<section class="process" aria-label="이용 순서">.*?</section>\s*',
        "\n",
        page,
        count=1,
        flags=re.S,
    )
    hidden_state = '''
    <div id="aioff-hidden-state" hidden aria-hidden="true">
      <div id="process1"></div><div id="process2"></div><div id="process3"></div><div id="process4"></div>
      <span id="stageStep">1 / 4</span><span id="stageText"></span>
      <div id="skills"></div><div id="analysisSummary"></div>
    </div>
    '''
    page = re.sub(
        r'\s*<aside class="study-side">.*?</aside>\s*',
        "\n" + hidden_state + "\n",
        page,
        count=1,
        flags=re.S,
    )

    page = page.replace(
        "주제를 고른 뒤 이 채팅창에서 실제 사례를 선택하고 AI와 판단을 이어갑니다.",
        "자료를 살펴보고 질문에 답하며 판단 기준을 연습합니다.",
    )
    page = re.sub(
        r'<div class="guide-strip">.*?</div>',
        '<div class="guide-strip"><strong>사례를 하나 선택하세요.</strong> 자료를 확인하고 질문에 답해보세요.</div>',
        page,
        count=1,
        flags=re.S,
    )

    patch = r'''
<style>
.workspace{grid-template-columns:minmax(0,1fr)!important;gap:0!important}
.study-paper{width:100%!important;max-width:none!important}
.chat{height:clamp(660px,76vh,960px)!important}
.chat-case-picker{padding:18px!important}
.chat-case-picker-head{margin-bottom:14px!important}
.chat-case-options{gap:14px!important}
.chat-case-option{min-height:292px!important;padding:12px!important}
.topic-preview,.kobaco-picker-media{height:205px!important;min-height:205px!important}
.kobaco-picker-media img{width:100%!important;height:100%!important;object-fit:cover!important}
.education-guide-preview-v19{height:205px!important;min-height:205px!important;margin:-12px -12px 11px!important}
.education-guide-preview-v19 img{width:100%!important;height:100%!important;object-fit:cover!important}

.aioff-school-search.aioff-school-combobox:after{display:none!important}
#aioff-school-toggle-v21{position:absolute;right:1px;top:1px;width:46px;height:40px;border:0;background:transparent;z-index:180;padding:0;cursor:pointer}
#aioff-school-toggle-v21:before{content:"";position:absolute;left:17px;top:13px;width:8px;height:8px;border-right:1.5px solid #302c28;border-bottom:1.5px solid #302c28;transform:rotate(45deg)}
.aioff-school-combobox.is-open #aioff-school-toggle-v21:before{top:18px;transform:rotate(225deg)}

.education-study-v21{border:1px solid #d9d2c9;border-radius:10px;background:#fff;overflow:hidden;max-width:980px;margin:0 auto}
.education-study-v21-head{padding:18px 20px 15px;border-bottom:1px solid #e2dbd2;background:#f8fafc}
.education-study-v21-head small{display:block;margin-bottom:5px;font-size:10px;font-weight:800;color:#58749b}
.education-study-v21-head b{display:block;font-size:20px;line-height:1.45;color:#27231f}
.education-study-v21-status{padding:24px 20px;font-size:12px;color:#746d66}
.education-study-v21-body{padding:20px;background:#fff}
.education-study-v21-visual{margin:0 0 16px;border:1px solid #ddd6cd;border-radius:9px;overflow:hidden;background:#ece8e1}
.education-study-v21-visual iframe{display:block;width:100%;height:560px;border:0;background:#e6e1da}
.education-study-v21-visual img{display:block;width:100%;max-height:620px;object-fit:contain;background:#fff}
.education-study-v21-reading{padding:17px 19px;border:1px solid #e2ddd6;border-radius:9px;background:#fffdf9}
.education-study-v21-reading h4,.education-study-v21-questions h4{margin:0 0 11px;font-size:14px;color:#2d2925}
.education-study-v21-reading p{margin:0 0 11px;font-size:14px;line-height:1.8;color:#403a35}
.education-study-v21-reading p:last-child{margin-bottom:0}
.education-study-v21-questions{margin-top:14px;padding:17px 19px;border:1px solid #eadbc8;border-radius:9px;background:#fff8ee}
.education-study-v21-questions ol{margin:0;padding-left:23px}
.education-study-v21-questions li{margin:9px 0;font-size:14px;line-height:1.7;font-weight:700;color:#342d27}
.education-study-v21-source{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:13px;font-size:10px;color:#857b72}
.education-study-v21-actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.education-study-v21-actions a{display:inline-flex;padding:8px 11px;border:1px solid #cfc6ba;border-radius:7px;background:#fff;color:#2d2925!important;text-decoration:none;font-size:10px;font-weight:800}
@media(max-width:700px){.chat{height:680px!important}.chat-case-option{min-height:230px!important}.topic-preview,.kobaco-picker-media,.education-guide-preview-v19{height:155px!important;min-height:155px!important}.education-study-v21-visual iframe{height:430px}}
</style>
<script>
(() => {
  const input=document.getElementById('aioff-school-name');
  const wrap=input?.closest('.aioff-school-search');
  const box=document.getElementById('aioff-school-results');
  if(input&&wrap&&box&&!document.getElementById('aioff-school-toggle-v21')){
    const toggle=document.createElement('button');
    toggle.type='button';toggle.id='aioff-school-toggle-v21';toggle.setAttribute('aria-label','학교 목록 열기 또는 닫기');
    wrap.appendChild(toggle);
    const closeList=()=>{box.classList.remove('open');wrap.classList.remove('is-open');input.setAttribute('aria-expanded','false');input.blur();};
    const openList=()=>{input.focus({preventScroll:true});input.dispatchEvent(new Event('input',{bubbles:true}));setTimeout(()=>{if(box.children.length){box.classList.add('open');wrap.classList.add('is-open');input.setAttribute('aria-expanded','true');}},80);};
    toggle.addEventListener('pointerdown',e=>{e.preventDefault();e.stopPropagation();if(box.classList.contains('open'))closeList();else openList();});
  }

  try{
    if(typeof educationPool19!=='undefined'&&Array.isArray(educationPool19)){
      const clean=educationPool19.filter(c=>!/(교사용|지도서|교사\s*용|강사용|수업지도|지도안)/.test(String(c?.title||'')));
      if(clean.length>=3) educationPool19.splice(0,educationPool19.length,...clean);
    }
  }catch(e){}

  function cleanPickerCopy(){
    document.querySelectorAll('.chat-case-picker-head span').forEach(el=>{
      const m=(el.textContent||'').match(/전체\s*(\d+)개\s*중\s*3개/);
      if(m) el.textContent=`전체 ${m[1]}개 · 3개 선택`;
    });
  }
  new MutationObserver(cleanPickerCopy).observe(document.body,{childList:true,subtree:true});
  cleanPickerCopy();

  const mediaBeforeV21=window.caseMedia;
  window.caseMedia=function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return mediaBeforeV21(c);
    const source=c.source_url?`<a href="${esc(c.source_url)}" target="_blank" rel="noopener">공식 자료 페이지</a>`:'';
    return `<div class="chat-case-media"><div class="education-study-v21" data-edu-v21="${esc(id)}" data-loaded="0">
      <div class="education-study-v21-head"><small>리터러시 교육 안내서</small><b data-title>${esc(c.title||'학습 활동')}</b></div>
      <div class="education-study-v21-status" data-status>학습 내용을 준비하는 중...</div>
      <div class="education-study-v21-body" data-content style="display:none">
        <div class="education-study-v21-visual" data-visual style="display:none"></div>
        <div class="education-study-v21-reading"><h4>읽어보기</h4><div data-reading></div></div>
        <div class="education-study-v21-questions"><h4>생각해보기</h4><ol data-questions></ol></div>
        <div class="education-study-v21-source" data-source></div>
        <div class="education-study-v21-actions"><a href="/api/education-file/${encodeURIComponent(id)}" target="_blank" rel="noopener">원문 보기</a>${source}</div>
      </div>
    </div></div>`;
  };

  function hideEducationLegacyBlocks(card){
    const chatRoot=document.getElementById('chat');if(!chatRoot)return;
    [...chatRoot.querySelectorAll('div')].forEach(el=>{
      const own=[...el.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join(' ');
      const text=(own||el.textContent||'').trim();
      if(text==='실제 조사·인식 데이터'||text==='생각해 볼 점'){
        const parent=el.parentElement;if(parent&&!parent.contains(card))parent.style.display='none';
      }
    });
  }

  async function hydrate(card){
    if(card.dataset.loaded!=='0') return;
    card.dataset.loaded='loading';
    const id=card.dataset.eduV21;
    const status=card.querySelector('[data-status]');
    try{
      const r=await fetch('/api/education-learning/'+encodeURIComponent(id),{credentials:'same-origin'});
      if(!r.ok) throw new Error('HTTP '+r.status);
      const data=await r.json();const p=data.pack||{};
      if(p.activity_title) card.querySelector('[data-title]').textContent=p.activity_title;
      const visual=card.querySelector('[data-visual]');
      if(p.visual_available&&p.visual_kind==='pdf'){
        visual.innerHTML=`<iframe src="/api/education-visual/${encodeURIComponent(id)}#toolbar=0&navpanes=0&view=FitH" title="학습자료"></iframe>`;visual.style.display='block';
      }else if(p.visual_available&&p.visual_kind==='image'){
        visual.innerHTML=`<img src="/api/education-visual/${encodeURIComponent(id)}" alt="학습자료">`;visual.style.display='block';
      }
      const reading=Array.isArray(p.reading)?p.reading.filter(Boolean):[];
      card.querySelector('[data-reading]').innerHTML=reading.map(x=>`<p>${esc(x)}</p>`).join('');
      const qs=Array.isArray(p.questions)?p.questions.filter(Boolean):[];
      card.querySelector('[data-questions]').innerHTML=qs.map(x=>`<li>${esc(x)}</li>`).join('');
      const ref=[p.source_name||'',p.page?`${p.page}쪽`:'' ].filter(Boolean).join(' · ');
      card.querySelector('[data-source]').textContent=ref?`자료 위치 · ${ref}`:'';
      status.style.display='none';card.querySelector('[data-content]').style.display='block';card.dataset.loaded='1';
      const composer=document.getElementById('input');if(composer)composer.placeholder='자료를 보고 생각한 내용을 적어보세요.';
      hideEducationLegacyBlocks(card);
    }catch(e){status.textContent='학습 내용을 불러오지 못했습니다.';card.dataset.loaded='error';}
  }
  function scan(){document.querySelectorAll('.education-study-v21[data-loaded="0"]').forEach(hydrate)}
  new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});
  scan();
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v21():
    return HTMLResponse(_render_index_kobaco_v21())
