from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

import aioff_ui as current

app = current.app
base = current.base
flow = current.flow

ROOT = Path(__file__).resolve().parent
NEWS_SEED = ROOT / "news_seed.json"
_NEWS_META_CACHE: dict[str, dict] = {}
_NEWS_PACK_CACHE: dict[str, dict] = {}
_NEWS_IMAGE_CACHE: dict[str, tuple[bytes, str] | None] = {}


# ---------------------------------------------------------------------------
# News topic: replace the old OTT module with the already-extracted news set.
# ---------------------------------------------------------------------------
def _load_news_seed() -> list[dict]:
    if not NEWS_SEED.exists():
        return []
    try:
        payload = json.loads(NEWS_SEED.read_text(encoding="utf-8"))
        return list(payload.get("events") or [])
    except Exception as exc:
        base.core.logger.warning("news seed load failed: %s", type(exc).__name__)
        return []


def _news_case(event: dict) -> dict:
    event_id = str(event.get("event_id") or "").strip()
    title = str(event.get("title") or "").strip()
    publisher = str(event.get("publisher") or "").strip()
    published_at = str(event.get("published_at") or "").strip()
    url = str(event.get("url") or "").strip()
    summary = str(event.get("summary") or "").strip()
    topics = [str(x).strip() for x in (event.get("topics") or []) if str(x).strip()]
    alternates = list(event.get("alternates") or [])
    article_count = max(1, int(event.get("article_count") or 1))
    topic_text = " · ".join(topics[:3]) or "미디어 리터러시"
    opening_questions = [
        "이 기사 제목에서 바로 확인할 수 있는 사실과, 원문을 더 확인해야 하는 해석이나 추정을 구분해보세요.",
        "이 보도를 믿거나 공유하기 전에 원문에서 가장 먼저 확인해야 할 근거는 무엇인지 설명해보세요.",
        "같은 사건을 다룬 다른 보도가 있다면 어떤 표현이나 근거를 비교해야 판단이 더 정확해지는지 적어보세요.",
    ]
    return {
        "id": f"news_{event_id.lower()}",
        "label": f"최신 뉴스 · {topic_text}",
        "title": title,
        "claim": "기사 제목과 출처만 보고 사건의 전체 맥락이나 원인·책임까지 단정하지 않고, 원문과 다른 보도를 확인하며 사실과 해석을 구분하는 사례입니다.",
        "source_name": publisher or "뉴스 보도",
        "source_url": url,
        "media_type": "image",
        "media_url": f"/api/aioff-news-thumb/news_{event_id.lower()}",
        "media_caption": f"{publisher or '언론사'} · {published_at[:10] if published_at else '게시일 확인 필요'} · 동일 사건 묶음 {article_count}건",
        "opening_question": opening_questions[0],
        "opening_questions": opening_questions,
        "clues": [
            f"기사 제목: {title}",
            f"언론사: {publisher or '확인 필요'}",
            f"게시일: {published_at[:10] if published_at else '확인 필요'}",
            f"동일 사건으로 묶인 기사 수: {article_count}건",
            "제목만으로 확인되지 않는 세부 사실은 원문과 독립된 다른 보도에서 교차 확인해야 합니다.",
        ],
        "resolution": "뉴스 제목은 사건을 압축한 표현이므로 제목만으로 원인·책임·영향을 확정하지 않습니다. 원문에서 근거와 인용 출처를 확인하고, 같은 사건의 다른 보도와 비교해 사실과 해석을 나누는 것이 핵심입니다.",
        "data_rows": [
            {"label": "언론사", "value": publisher or "-"},
            {"label": "게시일", "value": published_at[:10] if published_at else "-"},
            {"label": "주제", "value": topic_text},
            {"label": "동일 사건 기사", "value": f"{article_count}건"},
        ],
        "data_note": "2026 뉴스 수집본을 동일 사건 단위로 정제한 대표기사입니다.",
        "db_tables": ["news_event_clusters"],
        "news_publisher": publisher,
        "news_published_at": published_at,
        "news_summary": summary,
        "news_topics": topics,
        "news_article_count": article_count,
        "news_alternates": alternates,
    }


NEWS_CASES = [_news_case(x) for x in _load_news_seed() if x.get("title") and x.get("url")]
if NEWS_CASES:
    flow.CASE_LIBRARY["ai"] = NEWS_CASES
    flow.CASE_BY_ID.clear()
    flow.CASE_BY_ID.update({
        case["id"]: (lesson_id, case)
        for lesson_id, cases in flow.CASE_LIBRARY.items()
        for case in cases
    })

if "ai" in base.LESSONS:
    base.LESSONS["ai"].update({
        "title": "최신 뉴스에서 사실과 해석 구분하기",
        "short": "실제 최신 뉴스의 제목·출처·게시 시점과 동일 사건 보도를 비교해 사실, 해석, 추가 확인이 필요한 내용을 구분합니다.",
        "source_name": "AI OFF 2026 뉴스 수집·동일사건 정제 데이터",
        "source_url": "",
        "source_role": "실제 뉴스 사례 학습 데이터",
        "source_note": "수집 뉴스는 동일 사건 기사끼리 묶은 뒤 대표기사를 사용하며, 원문과 다른 보도를 함께 확인하는 미디어 리터러시 학습에 사용합니다.",
        "criteria": [
            "제목만으로 사건 전체를 확정하지 않고 원문을 확인한다.",
            "언론사·게시 시점·인용 주체와 근거 출처를 확인한다.",
            "기사에서 직접 확인되는 사실과 기자·제목의 해석 또는 평가를 구분한다.",
            "같은 사건을 다룬 독립된 다른 보도와 표현·근거를 비교한다.",
            "근거가 부족하면 결론을 서두르지 않고 판단을 유보한다.",
        ],
        "skills": ["사실·해석 구분", "출처 확인", "교차검증"],
        "starter": "최신 뉴스 사례를 골라 제목과 원문에서 무엇을 사실로 확인할 수 있는지 살펴봅니다.",
    })


_PUBLIC_CASE_BEFORE_RUNTIME = flow._public_case


def _public_case_runtime(case: dict) -> dict:
    data = dict(_PUBLIC_CASE_BEFORE_RUNTIME(case))
    for key in (
        "opening_question", "opening_questions", "news_publisher", "news_published_at",
        "news_summary", "news_topics", "news_article_count", "news_alternates",
        "data_rows", "data_note", "db_tables", "news_pack",
    ):
        if key in case:
            data[key] = case.get(key)
    return data


flow._public_case = _public_case_runtime


# ---------------------------------------------------------------------------
# Resolve an article page lazily. We only use trusted URLs from news_seed.json.
# ---------------------------------------------------------------------------
def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def _external_link(soup: BeautifulSoup, base_url: str) -> str:
    base_host = (urlparse(base_url).hostname or "").lower()
    if "news.google." not in base_host:
        return base_url
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, str(a.get("href") or ""))
        host = (urlparse(href).hostname or "").lower()
        if not host or "google." in host or host.endswith("gstatic.com"):
            continue
        if href.startswith("http"):
            return href
    return base_url


def _fetch_news_meta(case: dict) -> dict:
    case_id = str(case.get("id") or "")
    if case_id in _NEWS_META_CACHE:
        return dict(_NEWS_META_CACHE[case_id])

    url = str(case.get("source_url") or "")
    result = {
        "url": url,
        "resolved_url": url,
        "description": "",
        "body": "",
        "image": "",
    }
    if not url:
        _NEWS_META_CACHE[case_id] = result
        return dict(result)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    }
    try:
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text[:2_500_000], "html.parser")
        resolved = _external_link(soup, response.url)
        if resolved != response.url:
            try:
                second = requests.get(resolved, headers=headers, timeout=10, allow_redirects=True)
                second.raise_for_status()
                response = second
                soup = BeautifulSoup(response.text[:2_500_000], "html.parser")
            except Exception:
                pass
        result["resolved_url"] = response.url

        for selector in (
            ('meta', {'property': 'og:image'}),
            ('meta', {'name': 'twitter:image'}),
            ('meta', {'property': 'twitter:image'}),
        ):
            node = soup.find(selector[0], attrs=selector[1])
            image = str(node.get("content") or "").strip() if node else ""
            if image:
                result["image"] = urljoin(response.url, image)
                break

        for selector in (
            ('meta', {'property': 'og:description'}),
            ('meta', {'name': 'description'}),
            ('meta', {'name': 'twitter:description'}),
        ):
            node = soup.find(selector[0], attrs=selector[1])
            desc = _clean_text(node.get("content") if node else "")
            if desc and "Google 뉴스" not in desc:
                result["description"] = desc[:1200]
                break

        article = soup.find("article")
        nodes = article.find_all("p") if article else soup.find_all("p")
        paragraphs: list[str] = []
        total = 0
        for p in nodes:
            text = _clean_text(p.get_text(" ", strip=True))
            if len(text) < 45 or text in paragraphs:
                continue
            paragraphs.append(text)
            total += len(text)
            if total >= 5500 or len(paragraphs) >= 18:
                break
        result["body"] = "\n".join(paragraphs)[:6000]
    except Exception as exc:
        base.core.logger.info("news page metadata unavailable for %s: %s", case_id, type(exc).__name__)

    _NEWS_META_CACHE[case_id] = dict(result)
    return dict(result)


def _news_fallback_svg(case: dict) -> bytes:
    title = html.escape(str(case.get("title") or "뉴스 사례"))
    publisher = html.escape(str(case.get("news_publisher") or case.get("source_name") or "NEWS"))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
    <rect width="1280" height="720" fill="#e9edf2"/>
    <rect x="55" y="55" width="1170" height="610" rx="24" fill="#fff" stroke="#cfd6df"/>
    <text x="100" y="135" font-family="sans-serif" font-size="28" font-weight="800" fill="#2f68c7">LATEST NEWS</text>
    <foreignObject x="100" y="205" width="1080" height="300"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:sans-serif;color:#191c20;font-size:46px;font-weight:850;line-height:1.3">{title}</div></foreignObject>
    <text x="100" y="600" font-family="sans-serif" font-size="24" fill="#69717a">{publisher}</text>
    </svg>'''.encode("utf-8")


base._remove_route("/api/aioff-news-thumb/{case_id}", "GET")


@app.get("/api/aioff-news-thumb/{case_id}")
def aioff_news_thumb(case_id: str):
    found = flow.CASE_BY_ID.get(case_id)
    if not found or not str(case_id).startswith("news_"):
        raise HTTPException(404, "뉴스 사례를 찾을 수 없습니다.")
    case = found[1]
    if case_id in _NEWS_IMAGE_CACHE:
        cached = _NEWS_IMAGE_CACHE[case_id]
        if cached:
            data, media = cached
            return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=3600"})
        return Response(_news_fallback_svg(case), media_type="image/svg+xml")

    meta = _fetch_news_meta(case)
    image_url = str(meta.get("image") or "")
    if image_url:
        try:
            image = requests.get(
                image_url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": str(meta.get("resolved_url") or case.get("source_url") or "")},
                timeout=10,
            )
            image.raise_for_status()
            media = str(image.headers.get("content-type") or "").split(";", 1)[0].lower().strip()
            if media.startswith("image/") and len(image.content) >= 6000:
                _NEWS_IMAGE_CACHE[case_id] = (image.content, media)
                return Response(image.content, media_type=media, headers={"Cache-Control": "public, max-age=3600"})
        except Exception:
            pass
    _NEWS_IMAGE_CACHE[case_id] = None
    return Response(_news_fallback_svg(case), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=600"})


# ---------------------------------------------------------------------------
# News reading: use actual article text when retrievable.
# If the article body cannot be resolved, do not invent details.
# ---------------------------------------------------------------------------
class NewsStudyDraft(BaseModel):
    reading: list[str] = []
    questions: list[str] = []


def _news_profile() -> tuple[str, str, int]:
    return (
        "학생",
        "학생이 이해할 수 있는 자연스러운 표현을 사용하고, 기사에 나온 핵심 인물·기관·수치·쟁점은 필요한 범위에서 보존한다.",
        0,
    )


def _news_study_pack(case: dict) -> dict:
    key = str(case.get("id") or "")
    if key in _NEWS_PACK_CACHE:
        return dict(_NEWS_PACK_CACHE[key])

    profile, rules, _ = _news_profile()
    meta = _fetch_news_meta(case)
    description = _clean_text(meta.get("description") or "")
    body = _clean_text(meta.get("body") or "")
    summary = _clean_text(case.get("news_summary") or "")
    if summary == _clean_text(f"{case.get('title','')} {case.get('source_name','')}"):
        summary = ""
    source_text = body or description or summary
    alternates = list(case.get("news_alternates") or [])
    alt_text = "\n".join(
        f"- {x.get('publisher','')} | {x.get('title','')}"
        for x in alternates[:4]
    ) or "- 동일 사건 다른 기사 메타데이터 없음"

    if source_text:
        prompt = f'''다음 실제 뉴스 사례를 {profile}용 미디어 리터러시 학습자료로 재구성하라.
표현 규칙: {rules}

기사 제목: {case.get('title','')}
언론사: {case.get('source_name','')}
게시일: {str(case.get('news_published_at') or '')[:10]}
기사에서 서버가 확인한 텍스트:
{source_text[:6000]}

동일 사건 다른 보도:
{alt_text}

규칙:
1. 위 텍스트가 뒷받침하는 내용만 사용하고 사실을 새로 만들지 않는다.
2. reading은 원문을 읽기 전에 사건의 핵심과 확인 포인트를 이해할 수 있도록 3~5문단으로 쓴다.
3. 기사 내용 자체와 기사 제목의 해석·평가 표현을 구분해 설명한다.
4. 무엇이 아직 원문·공식자료·다른 보도로 확인되어야 하는지도 분명히 쓴다.
5. questions는 정확히 3개. 질문은 reading에 실제 표시되는 내용과 기사 메타데이터만으로 생각할 수 있게 한다.
6. 한 질문에는 한 가지 핵심 사고만 묻고, 정답 키워드 맞히기 문제가 되지 않게 한다.
7. 기사 원문을 보지 않은 학생에게 화면에 없는 세부 사실을 맞히라고 요구하지 않는다.
8. 원문 문장을 길게 복사하지 말고 요약·재구성한다.
JSON으로 반환하라.'''
        try:
            draft, _ = base.core.generate_structured_with_fallback(prompt, NewsStudyDraft, max_output_tokens=1500)
            reading = [_clean_text(x) for x in draft.reading if _clean_text(x)][:5]
            questions = [_clean_text(x) for x in draft.questions if _clean_text(x)][:3]
            if len(reading) >= 2 and len(questions) == 3:
                pack = {"reading": reading, "questions": questions, "resolved_url": meta.get("resolved_url") or case.get("source_url")}
                _NEWS_PACK_CACHE[key] = dict(pack)
                return pack
        except Exception as exc:
            base.core.logger.warning("news study generation failed: %s", type(exc).__name__)

    count = int(case.get("news_article_count") or 1)
    reading = [
        f"이 사례는 {case.get('source_name') or '언론사'}가 {str(case.get('news_published_at') or '')[:10] or '게시일 미확인'}에 보도한 ‘{case.get('title') or ''}’ 기사입니다.",
        "현재 화면에서 확실히 확인할 수 있는 것은 기사 제목, 언론사, 게시 시점입니다. 제목은 사건을 짧게 압축한 표현이므로 원인·책임·영향 같은 세부 내용까지 제목만으로 확정하면 안 됩니다.",
        f"수집 과정에서 이 사건은 같은 사건을 다룬 기사 {count}건 묶음으로 정리되었습니다. 같은 사건을 다른 언론사가 어떤 제목과 근거로 설명하는지 비교하면 사실과 해석을 구분하는 데 도움이 됩니다.",
    ]
    questions = [
        "이 제목에서 현재 바로 확인할 수 있는 정보와 원문을 더 봐야 판단할 수 있는 내용을 나눠보세요.",
        "이 기사를 공유하기 전에 원문에서 가장 먼저 확인하고 싶은 근거 한 가지를 적어보세요.",
        "같은 사건의 다른 기사와 비교할 때 어떤 부분이 서로 같은지 또는 다른지 확인해야 할까요?",
    ]
    pack = {"reading": reading, "questions": questions, "resolved_url": case.get("source_url")}
    _NEWS_PACK_CACHE[key] = dict(pack)
    return pack


# ---------------------------------------------------------------------------
# Case start: news gets a generated first question.
# ---------------------------------------------------------------------------
_ORIGINAL_CASE_START = flow.case_start
base._remove_route("/api/case-start", "POST")


@app.post("/api/case-start")
def runtime_case_start(req: flow.CaseStartRequest, request: Request):
    found = flow.CASE_BY_ID.get(req.case_id)
    if not found or found[0] != req.lesson_id or req.lesson_id not in base.LESSONS:
        raise HTTPException(400, "선택한 학습 사례를 찾을 수 없습니다.")
    if not str(req.case_id).startswith("news_"):
        return _ORIGINAL_CASE_START(req)

    _, case = found
    pack = _news_study_pack(case)
    questions = list(pack.get("questions") or [])
    opening = questions[0] if questions else str(case.get("opening_question") or "기사에서 확인되는 사실과 해석을 구분해보세요.")

    sid = str(base.core.uuid.uuid4())
    base._save_lesson(sid, req.lesson_id)
    flow._save_case(sid, req.case_id)
    with base.core.connect_db() as c:
        c.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)", (sid,))
        c.execute("INSERT INTO messages(session_id, role, content) VALUES(?, 'assistant', ?)", (sid, opening))

    public_case = flow._public_case(case)
    public_case["news_pack"] = pack
    public_case["opening_question"] = opening
    public_case["opening_questions"] = questions
    return {"session_id": sid, "case": public_case, "opening_question": opening}


# ---------------------------------------------------------------------------
# News tutor: semantic response, no keyword chasing.
# ---------------------------------------------------------------------------
_ORIGINAL_CHAT_STREAM = current.aioff_chat_stream
base._remove_route("/api/chat-stream", "POST")


@app.post("/api/chat-stream")
def runtime_chat_stream(req: current.AioffTutorChatRequest, request: Request):
    sid = req.session_id or str(base.core.uuid.uuid4())
    lesson_id = req.lesson_id if req.lesson_id in base.LESSONS else base._get_lesson_id(sid)
    case_id = flow._get_case_id(sid) if sid else None
    found = flow.CASE_BY_ID.get(case_id) if case_id else None
    if not found or not str(case_id).startswith("news_"):
        return _ORIGINAL_CHAT_STREAM(req, request)

    case = found[1]
    pack = _news_study_pack(case)
    profile, _, _ = _news_profile()
    level_rule = "학생의 답을 짧고 자연스럽게 해석하고, 화면에 표시된 근거와 연결해 설명한다."
    reading = "\n".join(f"- {x}" for x in pack.get("reading", []))
    questions = "\n".join(f"- {x}" for x in pack.get("questions", []))
    prior = base.core.messages(sid, 24)
    history = "\n".join(f"{'학생' if m['role']=='user' else '튜터'}: {m['content']}" for m in prior)

    prompt = f'''너는 최신 뉴스를 이용한 디지털 리터러시 튜터다.
대상: {profile}
피드백 규칙: {level_rule}

[기사]
제목: {case.get('title','')}
언론사: {case.get('source_name','')}
게시일: {str(case.get('news_published_at') or '')[:10]}

[학생 화면의 읽어보기]
{reading}

[이 사례의 학습 질문]
{questions}

[이전 대화]
{history}

[학생의 새 답변]
{req.message}

원칙:
1. 학생이 쓴 말의 의도와 의미를 먼저 해석한다. 특정 키워드가 없다는 이유로 오답 처리하지 않는다.
2. 기사 제목과 화면의 읽어보기에서 확인되는 범위만 근거로 삼는다. 화면에 없는 기사 세부 내용을 학생에게 요구하지 않는다.
3. 사실·해석·출처·추가 확인 필요성을 구분하게 돕는다.
4. 학생 답이 타당하면 그 이유를 짧게 인정하고, 위 질문 중 아직 다루지 않은 질문 하나를 자연스럽게 이어간다.
5. 학생 답이 애매하면 학생이 이미 쓴 표현의 뜻을 한 번 더 풀어 달라고 묻는다.
6. 학생 답이 자료와 명확히 어긋나면 정답을 떠먹이지 말고 어떤 부분을 다시 확인해야 하는지 사고 절차만 안내한다.
7. 같은 질문을 말만 바꿔 반복하지 않는다.
8. 답변은 짧고 자연스럽게 쓴다.

verdict는 pass, clarify, retry 중 하나로 판단하고 response에는 학생에게 보여줄 말만 쓴다.'''
    try:
        decision, provider = base.core.generate_structured_with_fallback(prompt, current.TutorDecision, max_output_tokens=700)
    except Exception as exc:
        base.core.logger.warning("news tutor failed: %s", type(exc).__name__)
        raise HTTPException(502, "뉴스 학습 답변 평가에 실패했습니다. 잠시 후 다시 시도해 주세요.")

    text = str(decision.response or "").strip()
    base.core.save_chat_exchange(sid, req.message, text)
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
# Final UI patch: news cards/thumbnails.
# ---------------------------------------------------------------------------
def _render_runtime_index() -> str:
    page = current._render_index_aioff_ui()
    replacements = {
        "청소년·OTT 통계에서 사실과 해석 구분하기": "최신 뉴스에서 사실과 해석 구분하기",
        "연령별 OTT 이용률을 보고 이용·선호·대표성을 혼동하지 않고 조사 조건을 확인합니다.": "실제 최신 뉴스의 제목·출처·게시 시점과 동일 사건 보도를 비교해 사실과 해석을 구분합니다.",
        "KOBACO 성별·연령별 OTT 이용비율 및 2025 청소년 미디어 이용 DB": "AI OFF 2026 뉴스 수집·동일사건 정제 데이터",
    }
    for old, new in replacements.items():
        page = page.replace(old, new)

    patch = r'''
<style>
.mode-label,.paper-head .mode-label,[data-mode-label]{display:none!important}
.aioff-news-preview{width:100%;height:230px;overflow:hidden;background:#e9edf2;position:relative}
.aioff-news-preview img{display:block;width:100%;height:100%;object-fit:cover}
.aioff-news-preview:after{content:"최신 뉴스";position:absolute;left:10px;bottom:9px;padding:4px 7px;border-radius:6px;background:rgba(0,0,0,.68);color:#fff;font-size:9px;font-weight:850}
.aioff-news-card{background:#fff}
.aioff-news-hero{height:clamp(320px,42vh,560px);background:#e9edf2;overflow:hidden}
.aioff-news-hero img{display:block;width:100%;height:100%;object-fit:cover}
.aioff-news-meta{padding:13px 16px;border-bottom:1px solid var(--line);font-size:10px;color:var(--muted)}
.aioff-news-reading{padding:18px 20px;background:#fff}
.aioff-news-reading h4{margin:0 0 11px;font-size:14px}.aioff-news-reading p{margin:0 0 12px;font-size:12px;line-height:1.75;color:var(--body)}
.aioff-news-related{padding:13px 20px;background:#f8f5ef;border-top:1px solid var(--line)}
.aioff-news-related small{display:block;font-size:9px;font-weight:850;color:var(--muted);margin-bottom:7px}.aioff-news-related div{font-size:10px;line-height:1.55;margin:4px 0}
@media(max-width:900px){.aioff-news-preview{height:170px}.aioff-news-hero{height:300px}}
</style>
<script>
(() => {
  function hideLooseOn(){
    document.querySelectorAll('body *').forEach(el=>{
      if(el.children.length===0 && ((el.textContent||'').trim()==='ON'||(el.textContent||'').trim()==='AI ON')) el.style.display='none';
    });
  }

  const previewBeforeRuntime=window.fixedPreview;
  if(typeof previewBeforeRuntime==='function'){
    window.fixedPreview=function(c){
      const id=String(c?.id||'');
      if(id.startsWith('news_')) return `<div class="aioff-news-preview"><img src="/api/aioff-news-thumb/${encodeURIComponent(id)}" alt="${esc(c.title||'뉴스')} 썸네일" loading="lazy"></div>`;
      return previewBeforeRuntime(c);
    };
  }

  function newsCard(c){
    const pack=c.news_pack||{};const reading=Array.isArray(pack.reading)?pack.reading:[];
    const alts=Array.isArray(c.news_alternates)?c.news_alternates:[];
    const related=alts.length?`<div class="aioff-news-related"><small>같은 사건을 다룬 다른 보도</small>${alts.slice(0,4).map(x=>`<div>${esc(x.publisher||'다른 언론')} · ${esc(x.title||'')}</div>`).join('')}</div>`:'';
    const readHtml=reading.length?reading.map(x=>`<p>${esc(x)}</p>`).join(''):`<p>기사 제목과 출처를 먼저 확인하고, 원문에서 근거와 맥락을 살펴보세요.</p>`;
    return `<div class="chat-case-media"><div class="kobaco-data-card aioff-news-card"><div class="aioff-news-hero"><img src="/api/aioff-news-thumb/${encodeURIComponent(c.id)}" alt="${esc(c.title||'뉴스')} 기사 이미지"></div><div class="aioff-news-meta">${esc(c.news_publisher||c.source_name||'')} · ${esc(String(c.news_published_at||'').slice(0,10))} · 동일 사건 ${esc(String(c.news_article_count||1))}건</div><div class="aioff-news-reading"><h4>읽어보기</h4>${readHtml}</div>${related}</div></div>`;
  }

  const caseMediaBeforeRuntime=window.caseMedia;
  if(typeof caseMediaBeforeRuntime==='function'){
    window.caseMedia=function(c){if(String(c?.id||'').startsWith('news_'))return newsCard(c);return caseMediaBeforeRuntime(c)};
  }

  hideLooseOn();
  new MutationObserver(hideLooseOn).observe(document.body,{childList:true,subtree:true,characterData:true});
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def aioff_runtime_index():
    return HTMLResponse(_render_runtime_index())
