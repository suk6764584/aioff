from __future__ import annotations

import html
import re
import sqlite3
from typing import Literal
from urllib.parse import urljoin

import requests
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

import auth_proto as auth
import literacy_kobaco_app_10 as tutor_source
import literacy_kobaco_app_21 as previous

app = previous.app
base = previous.base
flow = previous.flow


# ---------------------------------------------------------------------------
# AiSAC thumbnails
# ---------------------------------------------------------------------------
_AISAC_THUMB_CACHE: dict[str, tuple[bytes, str] | None] = {}
_AISAC_SEARCH_URL = "https://aisac.kobaco.co.kr/site/main/advideo/list_all_top"
_IMAGE_ATTR_RE = re.compile(r"(?:src|data-src|data-original)=[\"']([^\"']+)[\"']", re.I)
_IMAGE_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
_BG_IMAGE_RE = re.compile(r"url\([\"']?([^\"')]+)[\"']?\)", re.I)


def _aisac_image_score(url: str, distance: int) -> int:
    lower = url.lower()
    if any(x in lower for x in ("logo", "icon", "btn_", "button", "search", "close", "kakao", "common/", "loading", "blank")):
        return -10000
    score = max(0, 7000 - distance) // 100
    if any(x in lower for x in ("thumb", "thumbnail", "adv", "video", "upload", "file", "archive")):
        score += 35
    if re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", lower):
        score += 20
    return score


def _find_aisac_thumbnail(title: str) -> tuple[bytes, str] | None:
    title = str(title or "").strip()
    if not title:
        return None
    if title in _AISAC_THUMB_CACHE:
        return _AISAC_THUMB_CACHE[title]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
    }
    try:
        response = requests.get(
            _AISAC_SEARCH_URL,
            params={"kwdVal": title, "listType": "list", "pageSize": 12},
            headers=headers,
            timeout=8,
        )
        response.raise_for_status()
        text = response.text
        pos = text.find(html.unescape(title))
        if pos < 0:
            compact = re.sub(r"\s+", "", html.unescape(title))
            compact_html = re.sub(r"\s+", "", html.unescape(text))
            compact_pos = compact_html.find(compact)
            pos = compact_pos if compact_pos >= 0 else len(text) // 2

        start = max(0, pos - 18000)
        end = min(len(text), pos + 18000)
        segment = text[start:end]
        local_title_pos = max(0, pos - start)
        candidates: list[tuple[int, str]] = []
        for match in _IMAGE_TAG_RE.finditer(segment):
            attr = _IMAGE_ATTR_RE.search(match.group(0))
            if not attr:
                continue
            raw_url = html.unescape(attr.group(1).strip())
            if raw_url and not raw_url.startswith("data:"):
                absolute = urljoin(response.url, raw_url)
                candidates.append((_aisac_image_score(absolute, abs(match.start() - local_title_pos)), absolute))
        for match in _BG_IMAGE_RE.finditer(segment):
            raw_url = html.unescape(match.group(1).strip())
            if raw_url and not raw_url.startswith("data:"):
                absolute = urljoin(response.url, raw_url)
                candidates.append((_aisac_image_score(absolute, abs(match.start() - local_title_pos)), absolute))

        candidates.sort(key=lambda x: x[0], reverse=True)
        seen: set[str] = set()
        for score, image_url in candidates:
            if score < 0 or image_url in seen:
                continue
            seen.add(image_url)
            try:
                image = requests.get(image_url, headers={**headers, "Referer": response.url}, timeout=8)
                image.raise_for_status()
                media = str(image.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                data = image.content
                if media.startswith("image/") and len(data) >= 8000:
                    result = (data, media)
                    _AISAC_THUMB_CACHE[title] = result
                    return result
            except Exception:
                continue
    except Exception as exc:
        base.core.logger.warning("AiSAC thumbnail lookup failed: %s", type(exc).__name__)

    _AISAC_THUMB_CACHE[title] = None
    return None


def _aisac_fallback_svg(title: str) -> bytes:
    safe = html.escape(str(title or "AiSAC 광고"))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
      <rect width="1280" height="720" fill="#ece8e1"/>
      <rect x="48" y="48" width="1184" height="624" rx="28" fill="#fff" stroke="#d8d0c6"/>
      <text x="92" y="126" font-family="sans-serif" font-size="30" font-weight="800" fill="#356fe8">KOBACO AiSAC</text>
      <foreignObject x="92" y="190" width="1080" height="300"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:sans-serif;color:#292521;font-size:50px;font-weight:850;line-height:1.25">{safe}</div></foreignObject>
      <text x="92" y="606" font-family="sans-serif" font-size="24" fill="#7c746c">원본 광고 썸네일을 불러오지 못했습니다.</text>
    </svg>'''.encode("utf-8")


base._remove_route("/api/aioff-aisac-thumb/{case_id}", "GET")


@app.get("/api/aioff-aisac-thumb/{case_id}")
def aioff_aisac_thumb(case_id: str):
    found = flow.CASE_BY_ID.get(case_id)
    if not found or not str(case_id).startswith("kobaco_aisac_"):
        raise HTTPException(404, "AiSAC 광고 사례를 찾을 수 없습니다.")
    case = found[1]
    result = _find_aisac_thumbnail(str(case.get("title") or ""))
    if result:
        data, media = result
        return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=3600"})
    return Response(
        _aisac_fallback_svg(str(case.get("title") or "")),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=600"},
    )


# ---------------------------------------------------------------------------
# Education case pool
# ---------------------------------------------------------------------------
_TEACHER_TITLE_TERMS = ("교사용", "지도서", "강사용", "수업지도", "지도안", "교수학습")
_ADULT_TARGET_TERMS = ("교사", "교직원", "학부모", "보호자", "성인", "대학생")


def _education_profile_score(case: dict, user: dict | None) -> int | None:
    title = str(case.get("title") or "")
    if any(term in title for term in _TEACHER_TITLE_TERMS):
        return None
    if not user:
        return 1

    level = str(user.get("school_level") or "")
    grade = int(user.get("grade") or 0)
    raw = str(case.get("education_target") or "")
    target = re.sub(r"[\s·ㆍ,/()\-]", "", raw)
    if any(term in target for term in _ADULT_TARGET_TERMS):
        return None

    elementary = any(term in target for term in ("초등", "초등학생", "초등학교"))
    middle = any(term in target for term in ("중등", "중학생", "중학교", "중고등", "중고생"))
    high = any(term in target for term in ("고등", "고등학생", "고등학교", "중고등", "중고생"))
    youth = any(term in target for term in ("청소년", "학생"))

    if level == "초":
        if not elementary or middle or high:
            return None
        score = 8
        text = f"{raw} {title}"
        if grade <= 3 and any(x in text for x in ("저학년", "1~3", "1-3", "1·2·3")):
            score += 4
        elif grade >= 4 and any(x in text for x in ("고학년", "4~6", "4-6", "4·5·6")):
            score += 4
        return score
    if level == "중":
        if middle:
            return 9 if not high else 8
        if youth and not elementary:
            return 5
        return None
    if level == "고":
        if high:
            return 9 if not middle else 8
        if youth and not elementary:
            return 5
        return None
    return 1


base._remove_route("/api/aioff-education-cases", "GET")


@app.get("/api/aioff-education-cases")
def aioff_education_cases(request: Request):
    user = auth.current_user(request.cookies.get(auth.COOKIE_NAME))
    ranked: list[tuple[int, int, str, dict]] = []
    for case in flow.CASE_LIBRARY.get("deepfake", []):
        if not str(case.get("id") or "").startswith("education_"):
            continue
        score = _education_profile_score(case, user)
        if score is None:
            continue
        embedded = int(case.get("education_embedded_chunk_count") or 0)
        year = str(case.get("education_year") or "")
        ranked.append((score, embedded, year, case))
    ranked.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    items = [flow._public_case(item[3]) for item in ranked[:40]]
    return {"logged_in": bool(user), "count": len(items), "items": items}


# ---------------------------------------------------------------------------
# Grade-adaptive education card generation
# ---------------------------------------------------------------------------
_ADAPTIVE_PACK_CACHE: dict[tuple[int, str, int], dict] = {}
_EDUCATION_CONTEXT_CACHE: dict[int, str] = {}


class EducationReadingDraft(BaseModel):
    activity_title: str = ""
    reading: list[str] = []


class EducationQuestionDraft(BaseModel):
    questions: list[str] = []


def _learning_level_rules(user: dict | None) -> tuple[str, int]:
    level = str((user or {}).get("school_level") or "")
    grade = int((user or {}).get("grade") or 0)
    if level == "초" and grade <= 3:
        return (
            "초등 1~3학년 수준. 짧고 구체적인 말로 설명한다. 한 질문에는 한 가지 생각만 묻고, "
            "생활 속 행동이나 눈에 보이는 상황을 중심으로 묻는다. 어려운 추상어·전문용어를 피한다. "
            "학생이 1~2문장으로 답할 수 있게 한다.",
            2,
        )
    if level == "초":
        return (
            "초등 4~6학년 수준. 쉬운 말로 사실과 의견, 원인과 결과를 구분하게 한다. "
            "자료에서 근거를 하나 찾거나 이유를 1~3문장으로 설명할 수 있는 질문으로 만든다.",
            3,
        )
    if level == "중":
        return (
            "중학생 수준. 단순 기억보다 원인·결과, 사실·해석, 출처와 근거를 연결하게 한다. "
            "비교하거나 이유를 설명하는 질문을 포함하고 2~4문장 답변이 적절한 난이도로 만든다.",
            3,
        )
    if level == "고":
        return (
            "고등학생 수준. 근거의 신뢰성, 주장과 전제, 대안적 해석, 상관과 인과 같은 판단 요소를 다룬다. "
            "자료에 근거한 비판적 설명이나 반론 검토가 가능하도록 하고 3~6문장 답변이 적절한 난이도로 만든다.",
            3,
        )
    return ("학생 수준에 맞는 쉬운 표현을 사용하고, 자료 근거를 바탕으로 생각하게 한다.", 3)


def _reading_plan(user: dict | None) -> tuple[int, int, str]:
    level = str((user or {}).get("school_level") or "")
    grade = int((user or {}).get("grade") or 0)
    if level == "초" and grade <= 3:
        return 3, 4, "각 문단은 1~2개의 짧은 문장으로 쓴다."
    if level == "초":
        return 4, 5, "각 문단은 2~3문장으로 쓰고 어려운 용어는 쉬운 말로 풀어쓴다."
    if level == "중":
        return 5, 6, "배경, 핵심 개념, 원인·영향, 판단 기준을 필요한 만큼 나누어 설명한다."
    if level == "고":
        return 5, 7, "핵심 개념뿐 아니라 근거, 한계, 위험, 적용 맥락까지 원문이 제공하는 범위에서 충분히 설명한다."
    return 4, 6, "학생이 원문을 따로 열지 않아도 학습할 수 있을 만큼 충분히 설명한다."


def _expanded_education_context(source: dict) -> str:
    material_id = int(source.get("material_id") or 0)
    if material_id in _EDUCATION_CONTEXT_CACHE:
        return _EDUCATION_CONTEXT_CACHE[material_id]

    fallback = str(source.get("context") or source.get("text") or "").strip()
    db_path = previous.education_source.EDU_DB
    if not material_id or not db_path.exists():
        return fallback

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, attachment_id, page_start, page_end, section, text
            FROM chunks
            WHERE material_id=? AND TRIM(text)<>''
            ORDER BY id
            """,
            (material_id,),
        ).fetchall()
        conn.close()
    except Exception as exc:
        base.core.logger.warning("Expanded education context failed: %s", type(exc).__name__)
        return fallback

    if not rows:
        return fallback

    selected_id = int(source.get("row_id") or 0)
    selected_attachment = int(source.get("attachment_id") or 0)
    candidates = [
        row for row in rows
        if not selected_attachment or int(row["attachment_id"] or 0) == selected_attachment
    ] or rows

    seed = str(source.get("text") or "")
    ranked: list[tuple[int, sqlite3.Row]] = []
    for row in candidates:
        text = str(row["text"] or "").strip()
        if not text:
            continue
        distance = abs(int(row["id"]) - selected_id) if selected_id else 0
        score = max(0, 90 - distance * 8)
        if int(row["id"]) == selected_id:
            score += 220
        try:
            chunk_score, _ = previous._chunk_score(row)
            score += max(-90, min(180, int(chunk_score)))
        except Exception:
            pass
        try:
            score += min(140, previous._text_overlap_score(seed, text) * 3)
        except Exception:
            pass
        ranked.append((score, row))

    ranked.sort(key=lambda item: item[0], reverse=True)
    chosen: dict[int, sqlite3.Row] = {}
    if selected_id:
        for row in candidates:
            if abs(int(row["id"]) - selected_id) <= 4:
                chosen[int(row["id"])] = row
    for _, row in ranked:
        chosen[int(row["id"])] = row
        if len(chosen) >= 16:
            break

    parts: list[str] = []
    total = 0
    for row_id in sorted(chosen):
        row = chosen[row_id]
        text = re.sub(r"\s+", " ", str(row["text"] or "")).strip()
        if not text or text in parts:
            continue
        page = row["page_start"]
        prefix = f"[원문 {page}쪽] " if page else "[원문] "
        piece = prefix + text
        if total + len(piece) > 22000 and parts:
            break
        parts.append(piece)
        total += len(piece)

    context = "\n\n".join(parts).strip() or fallback
    _EDUCATION_CONTEXT_CACHE[material_id] = context
    return context


def _fallback_questions(count: int, reading: list[str]) -> list[str]:
    if not reading:
        return ["읽어보기에서 확인한 내용을 자신의 말로 한 문장으로 정리해보세요."]
    bank = [
        "읽어보기에서 가장 중요하다고 생각한 내용을 하나 골라 자신의 말로 설명해보세요.",
        "읽어보기에서 그 판단을 뒷받침하는 근거를 하나 찾아 설명해보세요.",
        "읽어보기의 내용을 실제 디지털 생활에 적용한다면 무엇을 조심하거나 확인해야 할지 적어보세요.",
    ]
    return bank[:max(1, count)]


def _make_adaptive_study_pack(case: dict, source: dict, user: dict | None, visual: dict | None) -> dict:
    material_id = int(source.get("material_id") or 0)
    level = str((user or {}).get("school_level") or case.get("education_target") or "")
    grade = int((user or {}).get("grade") or 0)
    cache_key = (material_id, level, grade)
    if cache_key in _ADAPTIVE_PACK_CACHE:
        return dict(_ADAPTIVE_PACK_CACHE[cache_key])

    visual_available = visual is not None
    visual_required = previous._visual_required(source)
    fallback = previous._fallback_study(case, source, visual_available)
    level_rules, question_count = _learning_level_rules(user)
    min_paragraphs, max_paragraphs, paragraph_rule = _reading_plan(user)
    profile = f"{level} {grade}학년" if grade else (level or "학생")
    original_questions = "\n".join(f"- {q}" for q in source.get("prompts", [])) or "- 없음"
    expanded_context = _expanded_education_context(source)

    reading_prompt = f"""다음 공식 디지털 리터러시 교육자료를 학생이 실제로 읽을 학습 내용으로 재구성하라.

학생: {profile}
학년별 난이도 규칙: {level_rules}
자료명: {case.get('title', '')}
원문 파일: {source.get('source_name', '')}
시각 자료가 화면에 함께 표시되는가: {'예' if visual_available else '아니오'}

[관련 원문 묶음]
{expanded_context[:22000]}

[원문 활동문 - 학습 목적을 파악하는 참고용]
{original_questions}

작성 규칙:
1. 원문이 뒷받침하는 사실·개념·사례만 사용하고 내용을 새로 만들지 않는다.
2. 학생이 원문 PDF를 따로 열지 않아도 이 화면의 읽어보기만으로 뒤의 질문을 풀 수 있을 만큼 필요한 배경과 개념을 충분히 제공한다.
3. 핵심 몇 문장만 남기는 과도한 요약을 하지 않는다. 원문에 배경, 특징, 원인, 영향, 위험, 주의점, 사례, 판단 기준이 있으면 학습 주제와 관련된 내용을 빠뜨리지 말고 연결해서 설명한다.
4. reading은 {min_paragraphs}~{max_paragraphs}개 문단으로 작성한다. {paragraph_rule}
5. 원문을 순서대로 복사하지 말고 학생 수준에 맞게 구조화하되, 중요한 구체 내용은 보존한다.
6. 페이지·차시·파일명·목차·교사용 지시·성취기준 같은 편집 정보는 학생용 문단에서 제외한다.
7. 화면에 없는 그림·표를 본 것처럼 설명하지 않는다. 시각자료는 보조자료일 뿐, 읽어보기 자체가 학습에 필요한 정보를 제공해야 한다.
8. activity_title은 파일 종류가 아니라 실제 학습 주제를 쓴다.
9. 'AI가 정리했다', '모델', 'RAG', '생성' 같은 표현을 쓰지 않는다.
10. 이 단계에서는 질문을 만들지 않는다.

JSON 스키마에 맞춰 반환하라."""

    try:
        reading_draft, _ = base.core.generate_structured_with_fallback(
            reading_prompt,
            EducationReadingDraft,
            max_output_tokens=1700,
        )
        reading = [str(x).strip() for x in reading_draft.reading if str(x).strip()][:max_paragraphs]
        title = str(reading_draft.activity_title or "").strip()
        if len(reading) < min_paragraphs:
            raise ValueError("education_reading_too_short")
    except Exception as exc:
        base.core.logger.warning("Education reading generation failed: %s", type(exc).__name__)
        reading = [str(x).strip() for x in fallback.get("reading", []) if str(x).strip()]
        title = str(fallback.get("activity_title") or case.get("title") or "").strip()

    if not reading:
        raw = re.sub(r"\s+", " ", expanded_context).strip()
        reading = [raw[:1800]] if raw else ["이 자료에서 확인할 수 있는 내용을 살펴보세요."]

    visible_reading = "\n\n".join(f"{i + 1}. {text}" for i, text in enumerate(reading))
    question_prompt = f"""다음은 학생 화면에 실제로 표시될 '읽어보기' 내용이다. 이 내용만 읽은 학생이 답할 수 있는 질문을 만들어라.

학생: {profile}
학년별 난이도 규칙: {level_rules}
학습 주제: {title or case.get('title', '')}

[학생 화면에 실제 표시되는 읽어보기]
{visible_reading}

[원문 활동문 - 교육적 목적과 사고 유형만 참고]
{original_questions}

질문 작성 규칙:
1. questions는 정확히 {question_count}개를 만든다.
2. 질문의 사실 근거와 정답에 필요한 정보는 반드시 위 '읽어보기' 안에 있어야 한다. 원문 PDF에만 있고 화면에 표시되지 않은 내용을 알아야 풀 수 있는 질문은 절대 만들지 않는다.
3. 원문 활동문은 질문의 목적과 사고 유형만 참고한다. 원문 활동문에만 등장하는 사실·용어·사례를 학생이 안다고 가정하지 않는다.
4. 시각자료가 화면에 있더라도 답의 핵심은 읽어보기만으로 가능해야 한다. 그림·표를 봐야만 맞힐 수 있는 문제는 만들지 않는다.
5. 한 질문에는 한 가지 핵심 사고만 요구한다. '무엇이며 왜 그런가'처럼 서로 다른 요구를 한 문장에 몰아넣지 않는다.
6. 단순 문장 복사보다 이해, 비교, 근거 찾기, 적용 중 학생 수준에 맞는 사고를 요구한다.
7. 읽어보기에 답 문장이 그대로 있더라도 질문 표현을 그대로 복제하지 말고 학생이 자기 말로 설명하게 한다.
8. 질문끼리 같은 내용을 반복하지 않는다.

JSON 스키마에 맞춰 반환하라."""

    try:
        question_draft, _ = base.core.generate_structured_with_fallback(
            question_prompt,
            EducationQuestionDraft,
            max_output_tokens=700,
        )
        questions = [str(x).strip() for x in question_draft.questions if str(x).strip()][:question_count]
        if len(questions) < question_count:
            raise ValueError("education_questions_incomplete")
    except Exception as exc:
        base.core.logger.warning("Education question generation failed: %s", type(exc).__name__)
        questions = _fallback_questions(question_count, reading)

    pack = {
        "activity_title": title or str(case.get("title") or "").strip(),
        "reading": reading,
        "questions": questions,
        "visual_kind": (visual or {}).get("kind", ""),
        "visual_available": visual_available,
        "visual_required": visual_required,
        "source_name": source.get("source_name", ""),
        "page": (visual or {}).get("page") or source.get("page_start") or "",
        "student_level": profile,
    }
    _ADAPTIVE_PACK_CACHE[cache_key] = dict(pack)
    return pack


base._remove_route("/api/education-learning/{case_id}", "GET")


@app.get("/api/education-learning/{case_id}")
def aioff_education_learning(case_id: str, request: Request):
    case = previous.education_source._education_case(case_id)
    source = previous._select_source(case)
    visual = previous._build_visual(source)
    user = auth.current_user(request.cookies.get(auth.COOKIE_NAME))
    return {"ok": True, "pack": _make_adaptive_study_pack(case, source, user, visual)}


# ---------------------------------------------------------------------------
# Semantic tutor: understand intent first, then judge.
# ---------------------------------------------------------------------------
class AioffTutorChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    lesson_id: str | None = None
    current_question: str = Field(default="", max_length=1000)
    question_attempt: int = Field(default=1, ge=1, le=20)


class TutorDecision(BaseModel):
    verdict: Literal["pass", "clarify", "retry"]
    response: str = Field(min_length=1, max_length=2200)


def _tutor_level_rules(user: dict | None) -> str:
    level = str((user or {}).get("school_level") or "")
    grade = int((user or {}).get("grade") or 0)
    if level == "초" and grade <= 3:
        return "초등 1~3학년: 1~2개의 짧은 문장으로 말한다. 쉬운 일상어를 쓰고 한 번에 한 가지만 묻는다."
    if level == "초":
        return "초등 4~6학년: 쉬운 말로 2~3문장 피드백을 주고, 이유나 근거 하나를 자기 말로 설명하게 한다."
    if level == "중":
        return "중학생: 2~4문장으로 학생의 논리를 요약하고 사실·해석·원인·결과 중 필요한 한 요소를 점검한다."
    if level == "고":
        return "고등학생: 3~5문장으로 논리와 근거의 연결을 평가하고 전제·대안적 해석까지 필요할 때 점검한다."
    return "학생 수준에 맞는 짧고 자연스러운 피드백을 준다."


def _education_tutor_prompt(req: AioffTutorChatRequest, sid: str, case: dict, user: dict | None) -> str:
    source = previous._select_source(case)
    visual = previous._build_visual(source)
    pack = _make_adaptive_study_pack(case, source, user, visual)
    evidence = "\n\n".join(str(x) for x in pack.get("reading", []) if str(x).strip())[:10000]
    question = str(req.current_question or case.get("opening_question") or "").strip()
    prior = base.core.messages(sid, 18)
    history = "\n".join(f"{'학생' if m['role']=='user' else '튜터'}: {m['content']}" for m in prior)
    level = str((user or {}).get("school_level") or "")
    grade = int((user or {}).get("grade") or 0)
    profile = f"{level} {grade}학년" if grade else (level or "학생")
    level_rule = _tutor_level_rules(user)

    process_hint = (
        "오답이면 정답 내용을 말하지 말고, 학생이 질문에서 놓친 요구사항이 무엇인지 한 가지만 확인하게 한다."
        if req.question_attempt <= 1
        else "오답이 반복되면 정답 키워드 대신 '질문을 한 부분씩 다시 읽기', '읽어보기에서 근거 문장을 찾아보기' 같은 사고 절차만 제안한다."
    )

    return f'''너는 디지털 리터러시 수업의 대화형 튜터다. 가장 중요한 일은 정답 키워드를 맞히게 하는 것이 아니라 학생이 실제로 무슨 뜻으로 답했는지 이해하는 것이다.

학생 수준: {profile}
수준별 피드백 규칙: {level_rule}
자료명: {case.get('title') or '-'}
현재 문항: {question or '(문항 정보 없음)'}
이번 문항 시도 횟수: {req.question_attempt}
학생의 이번 답변: {req.message}

[학생 화면에 실제 표시된 읽어보기]
{evidence or '(표시된 읽어보기 없음)'}

[이전 대화]
{history or '(없음)'}

반드시 이 순서로 판단한다.
1. 학생의 짧은 표현, 생략, 일상어를 문맥에 맞게 가장 합리적으로 해석한다.
2. 학생이 사용한 단어가 읽어보기 표현과 달라도 개념적으로 같은 뜻인지 본다. 키워드 일치 여부로 채점하지 않는다.
3. 현재 문항이 실제로 요구하는 핵심 사고가 무엇인지 확인한 뒤, 학생 답이 그 사고에 닿아 있는지 본다.
4. 의견·해석형 문항에는 하나의 정답 문구를 강요하지 않는다. 근거가 있고 질문에 맞는 다른 해석도 인정한다.
5. 판정 근거는 학생 화면에 실제 표시된 읽어보기와 현재 질문으로 제한한다. 원문 PDF에는 있지만 읽어보기에 표시되지 않은 내용을 학생이 모른다는 이유로 감점하거나 다시 묻지 않는다.

verdict 기준:
- pass: 학생의 의도가 질문 핵심에 개념적으로 맞고 화면에 표시된 읽어보기와 모순되지 않는다. 짧거나 표현이 거칠어도 의미가 충분히 전달되면 통과한다.
- clarify: 학생 답이 맞는 방향으로 해석될 가능성이 높지만 너무 짧거나 모호해서 뜻을 확정하기 어렵다. 이때는 오답 처리하지 않는다.
- retry: 학생의 뜻을 최대한 호의적으로 해석해도 질문과 무관하거나 화면에 표시된 읽어보기와 명확히 모순되거나 핵심 요구를 잘못 이해했다.

clarify일 때:
- 학생이 이미 쓴 표현을 그대로 받아서 그 말의 뜻을 자기 말로 조금만 풀어 달라고 묻는다.
- 정답에 필요한 새 키워드, 예시, 원인, 피해 유형을 먼저 알려주지 않는다.
- 예: '네가 말한 A가 여기서는 어떤 뜻인지 한 문장만 더 설명해줄래?'처럼 묻는다.

retry일 때:
- 정답 방향을 내용으로 떠먹이지 않는다.
- {process_hint}
- 학생이 쓰지 않은 정답 후보나 예시를 먼저 나열하지 않는다.

pass일 때:
- 먼저 '네 답을 이런 뜻으로 이해했다'고 학생 의도를 짧게 바꿔 말한다.
- 왜 질문에 맞는 판단인지 화면에 표시된 읽어보기를 기준으로 짧게 설명한다.
- 다음 문항을 새로 만들지 않는다. 화면에서 다음 문항으로 넘어간다.

금지:
- 정답 문구를 유도하기 위해 같은 질문을 표현만 바꿔 반복하기
- 학생이 말하지 않은 정답 키워드를 힌트라는 이름으로 먼저 제시하기
- 읽어보기 문장과 단어가 다르다는 이유만으로 retry 하기
- 학생 답의 의미를 해석하지 않고 누락 키워드만 검사하기
- 화면에 표시되지 않은 PDF 원문 지식을 요구하기

response에는 학생에게 보여줄 자연스러운 말만 작성하고 verdict 이름이나 모델명은 쓰지 않는다.'''


base._remove_route("/api/chat-stream", "POST")


@app.post("/api/chat-stream")
def aioff_chat_stream(req: AioffTutorChatRequest, request: Request):
    sid = req.session_id or str(base.core.uuid.uuid4())
    lesson_id = req.lesson_id if req.lesson_id in base.LESSONS else base._get_lesson_id(sid)
    if lesson_id not in base.LESSONS:
        raise HTTPException(400, "먼저 학습 주제를 선택해 주세요.")
    base._save_lesson(sid, lesson_id)
    case_id = flow._get_case_id(sid)
    found = flow.CASE_BY_ID.get(case_id) if case_id else None
    if not found or found[0] != lesson_id:
        raise HTTPException(400, "선택한 사례를 다시 확인해 주세요.")

    if not str(case_id).startswith("education_"):
        return tutor_source.kobaco_ai_chat_stream(req)

    user = auth.current_user(request.cookies.get(auth.COOKIE_NAME))
    prompt = _education_tutor_prompt(req, sid, found[1], user)
    try:
        decision, provider = base.core.generate_structured_with_fallback(
            prompt,
            TutorDecision,
            max_output_tokens=700,
        )
    except Exception as exc:
        base.core.logger.warning("Education tutor evaluation failed: %s", type(exc).__name__)
        raise HTTPException(502, "학습 답변 평가에 실패했습니다. 잠시 후 다시 시도해 주세요.")

    text = str(decision.response or "").strip()
    base.core.save_chat_exchange(sid, req.message, text)
    base.core.logger.info(
        "Education tutor provider=%s verdict=%s case=%s",
        provider,
        decision.verdict,
        case_id,
    )
    return Response(
        text,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Session-Id": sid,
            "X-AIOFF-Provider": provider,
            "X-AIOFF-Verdict": decision.verdict,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# UI layer
# ---------------------------------------------------------------------------
def _render_index_aioff_ui():
    page = previous._render_index_kobaco_v21()
    patch = r'''
<style>
main{width:calc(100% - 24px)!important;max-width:1800px!important;margin:0 auto!important;padding:28px 0 42px!important}
.workspace,.study-paper{width:100%!important;max-width:none!important}
.study-paper>.paper-head .mode-label{display:none!important}
.aioff-auth-dock.aioff-auth-global{position:fixed!important;top:18px!important;right:22px!important;z-index:10020!important;display:inline-flex!important}

.chat-case-option{padding:0 0 13px!important;overflow:hidden!important}
.chat-case-option>b,.chat-case-option>small{display:block!important;margin-left:14px!important;margin-right:14px!important;text-align:left!important}
.chat-case-option>b{margin-top:0!important}.chat-case-option>small{margin-top:5px!important}
.education-guide-preview-v19,.kobaco-picker-media,.topic-preview{width:100%!important;height:230px!important;min-height:230px!important;margin:0 0 12px!important;border-radius:0!important}
.kobaco-picker-media img,.aioff-aisac-preview img{display:block!important;width:100%!important;height:100%!important;object-fit:cover!important}
.education-guide-preview-v19{background:#eee9e1!important;overflow:hidden!important}
.education-guide-preview-v19 iframe{position:absolute!important;left:0!important;top:0!important;width:calc(100% + 18px)!important;height:calc(100% + 18px)!important;border:0!important;display:block!important;background:#fff!important;pointer-events:none!important}
.education-guide-preview-v19 .edu-chip{z-index:3!important}
.aioff-aisac-preview{position:relative;overflow:hidden;background:#eee9e1}
.aioff-aisac-preview:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 55%,rgba(0,0,0,.20));pointer-events:none}
.aisac-player-shell{height:clamp(440px,62vh,760px)!important;max-height:760px!important;min-height:440px!important}
.aisac-player-frame{width:100%!important;height:100%!important}

.aioff-learning-columns{display:grid;grid-template-columns:minmax(0,1fr) clamp(320px,24vw,430px);min-height:calc(100vh - 150px)}
.aioff-learning-columns>.chat-area{min-width:0;padding:18px 20px 18px 24px!important;border-right:1px solid var(--line)}
.aioff-learning-columns .chat{height:calc(100vh - 205px)!important;min-height:760px!important;max-height:none!important;padding-bottom:18px!important}
.aioff-composer-side{min-width:0;display:flex;flex-direction:column;background:#fffdf9}
.aioff-composer-side-head{padding:18px 18px 14px;border-bottom:1px solid var(--line)}
.aioff-composer-side-head strong{display:block;margin-bottom:4px;font-size:15px;color:var(--ink)}
.aioff-composer-side-head>span{display:block;font-size:11px;line-height:1.5;color:var(--muted)}
.aioff-side-question{margin-top:12px;padding:12px 13px;border:1px solid #eadbc8;border-radius:10px;background:#fff8ee}
.aioff-side-question small{display:block;margin-bottom:5px;font-size:10px;font-weight:850;color:#9a5b30}
.aioff-side-question b{display:block;font-size:13px;line-height:1.55;color:#332b25}
.aioff-composer-side .composer-wrap{flex:1;min-height:0;display:flex;flex-direction:column;padding:16px 18px 18px!important}
.aioff-composer-side .composer{flex:1;min-height:0;display:flex!important;flex-direction:column!important;align-items:stretch!important;gap:12px!important;border-top:0!important;padding-top:0!important}
.aioff-composer-side .composer textarea{flex:1;width:100%!important;min-height:560px!important;max-height:none!important;resize:none!important;padding:16px!important;border-radius:12px!important;line-height:1.65!important;background:#fff!important}
.aioff-composer-side .send-btn{align-self:flex-end;min-width:96px;height:46px!important}
.aioff-composer-side .chat-status{margin-top:8px!important}

.education-study-v21{max-width:none!important;width:100%!important}
.education-study-v21-visual iframe{height:clamp(620px,72vh,920px)!important}
.education-study-v21-visual img{width:100%!important;max-height:900px!important;object-fit:contain!important}
.education-study-v21-questions ol{padding-left:0!important;list-style:none!important}
.education-study-v21-questions li{display:none!important}
.education-study-v21-questions li.aioff-current-question{display:block!important;margin:0!important}
.education-study-v21-questions h4{display:flex!important;align-items:center!important;justify-content:space-between!important;gap:10px!important}
.aioff-question-progress{font-size:10px;font-weight:800;color:#9b6d4d}

@media(max-width:1180px){main{width:calc(100% - 20px)!important}.aioff-learning-columns{grid-template-columns:minmax(0,1fr) 320px}.aioff-composer-side .composer textarea{min-height:500px!important}.education-guide-preview-v19,.kobaco-picker-media,.topic-preview{height:205px!important;min-height:205px!important}.aisac-player-shell{height:clamp(380px,56vh,620px)!important;min-height:380px!important}}
@media(max-width:900px){main{width:100%!important;padding-left:12px!important;padding-right:12px!important}.aioff-learning-columns{display:block;min-height:0}.aioff-learning-columns>.chat-area{border-right:0;padding:16px!important}.aioff-learning-columns .chat{height:680px!important;min-height:680px!important}.aioff-composer-side{border-top:1px solid var(--line)}.aioff-composer-side .composer textarea{min-height:220px!important}.education-study-v21-visual iframe{height:520px!important}.education-guide-preview-v19,.kobaco-picker-media,.topic-preview{height:170px!important;min-height:170px!important}.aisac-player-shell{height:clamp(260px,46vh,430px)!important;min-height:260px!important}}
</style>
<script>
(() => {
  let activeEducationCard=null;
  let activeQuestions=[];
  let activeQuestionIndex=0;
  let questionAttempts=[];
  let lastContextCaseId='';
  const nativeFetch=window.fetch.bind(window);

  function installGlobalAuthDock(){
    const dock=document.querySelector('.aioff-auth-dock');
    if(!dock) return;
    if(dock.parentElement!==document.body) document.body.appendChild(dock);
    dock.classList.add('aioff-auth-global');
  }

  function installWideLearningLayout(){
    installGlobalAuthDock();
    const paper=document.querySelector('.study-paper');
    if(!paper || paper.querySelector('.aioff-learning-columns')) return;
    paper.querySelector(':scope > .paper-head .mode-label')?.remove();
    const chatArea=paper.querySelector(':scope > .chat-area');
    const composerWrap=paper.querySelector(':scope > .composer-wrap');
    if(!chatArea || !composerWrap) return;
    const columns=document.createElement('div');
    columns.className='aioff-learning-columns';
    paper.insertBefore(columns,chatArea);
    columns.appendChild(chatArea);
    const side=document.createElement('aside');
    side.className='aioff-composer-side';
    side.innerHTML='<div class="aioff-composer-side-head"><strong>생각 적기</strong><span>현재 질문 하나에 답해보세요.</span><div class="aioff-side-question" data-aioff-side-question style="display:none"><small data-aioff-side-progress></small><b data-aioff-side-text></b></div></div>';
    side.appendChild(composerWrap);
    columns.appendChild(side);
    const textarea=composerWrap.querySelector('textarea');
    if(textarea){textarea.placeholder='현재 질문에 대한 생각을 적어보세요.';textarea.setAttribute('aria-label','현재 질문에 대한 답변 입력')}
  }

  function clearEducationQuestionState(){
    activeEducationCard=null;activeQuestions=[];activeQuestionIndex=0;questionAttempts=[];
    const side=document.querySelector('[data-aioff-side-question]');if(side)side.style.display='none';
    const sideProgress=document.querySelector('[data-aioff-side-progress]');if(sideProgress)sideProgress.textContent='';
    const sideText=document.querySelector('[data-aioff-side-text]');if(sideText)sideText.textContent='';
    const textarea=document.getElementById('input');if(textarea)textarea.placeholder='자료를 보고 생각한 내용을 적어보세요.';
  }

  function observedCaseId(){try{return String(inlineCaseId||'')}catch(e){return ''}}
  function observedLessonId(){try{return String(inlineLessonId||selectedLesson||'')}catch(e){return ''}}
  function caseData(lessonId,caseId){
    const rows=Array.isArray(fixedTopicCases?.[lessonId])?fixedTopicCases[lessonId]:[];
    return rows.find(c=>String(c?.id||'')===String(caseId||''))||null;
  }
  function syncNonEducationQuestion(lessonId,caseId){
    clearEducationQuestionState();
    const c=caseData(lessonId,caseId);if(!c)return;
    const qs=Array.isArray(c.opening_questions)?c.opening_questions.filter(Boolean):[];
    const q=String(c.opening_question||qs[0]||'').trim();if(!q)return;
    const side=document.querySelector('[data-aioff-side-question]');
    const sideProgress=document.querySelector('[data-aioff-side-progress]');
    const sideText=document.querySelector('[data-aioff-side-text]');
    if(side&&sideProgress&&sideText){side.style.display='block';sideProgress.textContent='현재 사례 질문';sideText.textContent=q}
    const textarea=document.getElementById('input');if(textarea)textarea.placeholder='현재 사례 질문에 대한 생각을 적어보세요.';
  }
  function syncCurrentCaseContext(){
    const caseId=observedCaseId();if(caseId===lastContextCaseId)return;
    lastContextCaseId=caseId;
    if(!caseId){clearEducationQuestionState();return}
    if(caseId.startsWith('education_')){clearEducationQuestionState();return}
    syncNonEducationQuestion(observedLessonId(),caseId);
  }

  const previewBeforeAioff=window.fixedPreview;
  if(typeof previewBeforeAioff==='function'){
    window.fixedPreview=function(c){
      const id=String(c?.id||'');
      if(id.startsWith('education_')){
        const target=c.education_target||'';const year=c.education_year||'';
        return `<div class="education-guide-preview-v19"><iframe src="/api/education-file/${encodeURIComponent(id)}#page=1&toolbar=0&navpanes=0&scrollbar=0&view=Fit" title="${esc(c.title||'교육자료')} 표지" loading="lazy"></iframe><span class="edu-chip">${esc([target,year].filter(Boolean).join(' · '))}</span></div>`;
      }
      if(id.startsWith('kobaco_aisac_')) return `<div class="kobaco-picker-media aioff-aisac-preview"><img src="/api/aioff-aisac-thumb/${encodeURIComponent(id)}" alt="${esc(c.title||'AiSAC 광고')} 썸네일" loading="lazy"></div>`;
      return previewBeforeAioff(c);
    };
  }

  const chooserBeforeAioff=window.showCaseChooser;
  if(typeof chooserBeforeAioff==='function'){
    window.showCaseChooser=async function(lessonId){
      clearEducationQuestionState();lastContextCaseId='';
      if(lessonId!=='deepfake') return chooserBeforeAioff(lessonId);
      try{
        const r=await nativeFetch('/api/aioff-education-cases',{credentials:'same-origin'});
        const data=r.ok?await r.json():{};
        if(!data.logged_in || !Array.isArray(data.items) || data.items.length<3) return chooserBeforeAioff(lessonId);
        fixedTopicCases.deepfake=data.items;
        delete fixedSamples.deepfake;
        selectedLesson=lessonId;inlineLessonId=lessonId;inlineCaseId=null;sessionId=null;
        resetInlineState();fixedSample(lessonId);
        chat.innerHTML=fixedPickerHtml(lessonId);bindCaseButtons(lessonId);
        input.placeholder='위에서 사례를 먼저 선택해 주세요.';input.disabled=true;send.disabled=true;finish.disabled=true;
        stageText.textContent='사례를 선택하세요';chat.scrollTop=0;
      }catch(e){return chooserBeforeAioff(lessonId)}
    };
  }

  const startCaseBeforeAioff=window.startCase;
  if(typeof startCaseBeforeAioff==='function'){
    window.startCase=async function(lessonId,caseId){
      const id=String(caseId||'');
      if(!id.startsWith('education_')) clearEducationQuestionState();
      const result=await startCaseBeforeAioff(lessonId,caseId);
      lastContextCaseId=id;
      if(!id.startsWith('education_')) syncNonEducationQuestion(lessonId,id);
      return result;
    };
  }

  function updateQuestionUI(state=''){
    if(!activeEducationCard || !activeQuestions.length) return;
    const items=[...activeEducationCard.querySelectorAll('.education-study-v21-questions li')];
    items.forEach((li,i)=>li.classList.toggle('aioff-current-question',i===activeQuestionIndex));
    const heading=activeEducationCard.querySelector('.education-study-v21-questions h4');
    if(heading){
      let progress=heading.querySelector('.aioff-question-progress');
      if(!progress){progress=document.createElement('span');progress.className='aioff-question-progress';heading.appendChild(progress)}
      const tail=state==='clarify'?' · 뜻을 조금 더 설명해보기':state==='retry'?' · 다시 검토해보기':'';
      progress.textContent=`${activeQuestionIndex+1} / ${activeQuestions.length}${tail}`;
    }
    const side=document.querySelector('[data-aioff-side-question]');
    const sideProgress=document.querySelector('[data-aioff-side-progress]');
    const sideText=document.querySelector('[data-aioff-side-text]');
    if(side&&sideProgress&&sideText){
      side.style.display='block';
      const tail=state==='clarify'?' · 네가 쓴 말의 뜻을 조금 더 설명해보세요':state==='retry'?' · 답을 다시 검토해보세요':'';
      sideProgress.textContent=`질문 ${activeQuestionIndex+1} / ${activeQuestions.length}${tail}`;
      sideText.textContent=activeQuestions[activeQuestionIndex]||'';
    }
    const textarea=document.getElementById('input');
    if(textarea) textarea.placeholder=`질문 ${activeQuestionIndex+1}에 대한 생각을 적어보세요.`;
  }

  function installSequentialQuestions(){
    const cards=[...document.querySelectorAll('.education-study-v21[data-loaded="1"]')];
    if(!cards.length) return;
    const card=cards[cards.length-1];
    if(card===activeEducationCard && card.dataset.aioffSeq==='1') return;
    const questions=[...card.querySelectorAll('.education-study-v21-questions li')].map(li=>(li.textContent||'').trim()).filter(Boolean);
    if(!questions.length) return;
    activeEducationCard=card;activeQuestions=questions;activeQuestionIndex=0;questionAttempts=new Array(questions.length).fill(0);card.dataset.aioffSeq='1';updateQuestionUI('');
  }

  function applyTutorVerdict(verdict){
    if(!activeEducationCard || !activeQuestions.length) return;
    if(verdict==='pass'){
      if(activeQuestionIndex<activeQuestions.length-1){activeQuestionIndex+=1;updateQuestionUI('')}
      else{
        const p=document.querySelector('[data-aioff-side-progress]');if(p)p.textContent=`질문 ${activeQuestions.length} / ${activeQuestions.length} · 답변 완료`;
        const t=document.querySelector('[data-aioff-side-text]');if(t)t.textContent='모든 문항을 마쳤습니다.';
      }
    }else if(verdict==='clarify') updateQuestionUI('clarify');
    else if(verdict==='retry') updateQuestionUI('retry');
  }

  window.fetch=async function(resource,init){
    const url=typeof resource==='string'?resource:String(resource?.url||'');
    let educationChat=false;
    const currentCaseId=observedCaseId();
    if(url.includes('/api/chat-stream') && currentCaseId.startsWith('education_') && activeEducationCard?.isConnected && activeQuestions.length && init && typeof init.body==='string'){
      try{
        const body=JSON.parse(init.body);
        questionAttempts[activeQuestionIndex]=(questionAttempts[activeQuestionIndex]||0)+1;
        body.current_question=activeQuestions[activeQuestionIndex]||'';
        body.question_attempt=questionAttempts[activeQuestionIndex];
        init={...init,body:JSON.stringify(body)};
        educationChat=true;
      }catch(e){}
    }
    const response=await nativeFetch(resource,init);
    if(educationChat){
      const verdict=(response.headers.get('X-AIOFF-Verdict')||'').toLowerCase();
      if(verdict) setTimeout(()=>applyTutorVerdict(verdict),120);
    }
    return response;
  };

  function scan(){installGlobalAuthDock();installWideLearningLayout();syncCurrentCaseContext();installSequentialQuestions()}
  installGlobalAuthDock();installWideLearningLayout();scan();
  new MutationObserver(scan).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['data-loaded']});
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def aioff_ui_index():
    return HTMLResponse(_render_index_aioff_ui())
