from __future__ import annotations

import json
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import aioff_runtime as runtime

app = runtime.app
base = runtime.base
current = runtime.current

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
}


def _decode_google_news_url(source_url: str) -> str:
    """Google News RSS 중간 주소를 실제 언론사 기사 주소로 해석한다."""
    try:
        parsed = urlparse(source_url)
        if not parsed.netloc.endswith("news.google.com"):
            return source_url
        parts = parsed.path.split("/")
        if len(parts) < 4 or parts[1] != "rss" or parts[2] != "articles":
            return source_url
        article_id = parts[-1]
        if not article_id:
            return source_url

        page = requests.get(
            f"https://news.google.com/articles/{article_id}",
            params={"hl": "ko", "gl": "KR", "ceid": "KR:ko"},
            headers={
                "User-Agent": "python-requests/2.32.3",
                "Accept-Encoding": "gzip, deflate",
                "Accept": "*/*",
                "Connection": "keep-alive",
            },
            timeout=10,
        )
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")
        data = soup.select_one("c-wiz > div[jscontroller]")
        if not data:
            return source_url
        signature = str(data.get("data-n-a-sg") or "")
        timestamp = str(data.get("data-n-a-ts") or "")
        if not signature or not timestamp:
            return source_url

        request_payload = [
            "Fbv4je",
            (
                "["
                '"garturlreq",'
                "["
                '["X","X",["X","X"],null,null,1,1,"KR:ko",null,1,null,null,null,null,null,0,1],'
                '"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
                f'"{article_id}",{timestamp},"{signature}"'
                "]"
            ),
        ]
        decoded = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data=f"f.req={quote(json.dumps([[request_payload]]))}",
            timeout=10,
        )
        decoded.raise_for_status()
        chunks = decoded.text.split("\n\n")
        if len(chunks) < 2:
            return source_url
        parsed_data = json.loads(chunks[1])[:-2]
        publisher_url = str(json.loads(parsed_data[0][2])[1] or "").strip()
        if publisher_url.startswith(("http://", "https://")):
            return publisher_url
    except Exception as exc:
        base.core.logger.info("Google News decode unavailable: %s", type(exc).__name__)
    return source_url


def _jsonld_article_body(soup: BeautifulSoup) -> str:
    bodies: list[str] = []

    def walk(value):
        if isinstance(value, dict):
            body = value.get("articleBody")
            if isinstance(body, str) and len(runtime._clean_text(body)) >= 120:
                bodies.append(runtime._clean_text(body))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            walk(json.loads(raw))
        except Exception:
            continue
    return max(bodies, key=len) if bodies else ""


def _extract_article_paragraphs(soup: BeautifulSoup) -> str:
    roots = []
    article = soup.find("article")
    if article:
        roots.append(article)
    for selector in (
        '[itemprop="articleBody"]', '#articleBody', '#article_body', '#news_body_area',
        '.article-body', '.article_body', '.article-view-content', '.article_view',
        '.view_con', '.view-content', '.news_body', '.news-body', '.article_txt',
        '.article-text', '.newsct_article', '.articleContent', '.article_content',
    ):
        node = soup.select_one(selector)
        if node and node not in roots:
            roots.append(node)

    candidates = []
    for root in roots:
        paragraphs = root.find_all("p")
        candidates.extend(paragraphs if paragraphs else [root])
    if not candidates:
        candidates = soup.find_all("p")

    out: list[str] = []
    total = 0
    boilerplate = (
        "무단전재", "재배포 금지", "저작권자", "기사제보", "구독", "로그인",
        "관련기사", "많이 본 뉴스", "Copyright", "All rights reserved",
    )
    for node in candidates:
        text = runtime._clean_text(node.get_text(" ", strip=True))
        if len(text) < 28 or text in out:
            continue
        if any(term.lower() in text.lower() for term in boilerplate) and len(text) < 160:
            continue
        out.append(text)
        total += len(text)
        if total >= 14000 or len(out) >= 42:
            break
    return "\n".join(out)[:14500]


def _article_meta_from_url(url: str) -> dict:
    result = {"resolved_url": url, "description": "", "body": "", "image": ""}
    if not url.startswith(("http://", "https://")):
        return result
    try:
        response = requests.get(url, headers=_HEADERS, timeout=12, allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text[:4_000_000], "html.parser")
        result["resolved_url"] = response.url

        for attrs in (
            {"property": "og:image"}, {"name": "twitter:image"}, {"property": "twitter:image"},
        ):
            node = soup.find("meta", attrs=attrs)
            image = str(node.get("content") or "").strip() if node else ""
            if image:
                result["image"] = urljoin(response.url, image)
                break

        for attrs in (
            {"property": "og:description"}, {"name": "description"}, {"name": "twitter:description"},
        ):
            node = soup.find("meta", attrs=attrs)
            desc = runtime._clean_text(node.get("content") if node else "")
            if desc and "Google 뉴스" not in desc:
                result["description"] = desc[:1800]
                break

        jsonld = _jsonld_article_body(soup)
        paragraphs = _extract_article_paragraphs(soup)
        result["body"] = jsonld if len(jsonld) > len(paragraphs) else paragraphs
    except Exception as exc:
        base.core.logger.info("publisher article fetch unavailable: %s", type(exc).__name__)
    return result


def _fetch_news_meta(case: dict) -> dict:
    case_id = str(case.get("id") or "")
    if case_id in runtime._NEWS_META_CACHE:
        return dict(runtime._NEWS_META_CACHE[case_id])

    source_url = str(case.get("source_url") or "").strip()
    resolved = _decode_google_news_url(source_url)
    result = _article_meta_from_url(resolved)
    result["url"] = source_url

    if len(runtime._clean_text(result.get("body") or "")) < 350:
        for alt in list(case.get("news_alternates") or [])[:3]:
            alt_url = str(alt.get("url") or "").strip()
            if not alt_url:
                continue
            alt_resolved = _decode_google_news_url(alt_url)
            alt_meta = _article_meta_from_url(alt_resolved)
            if len(runtime._clean_text(alt_meta.get("body") or "")) <= len(runtime._clean_text(result.get("body") or "")):
                continue
            if not result.get("image") and alt_meta.get("image"):
                result["image"] = alt_meta["image"]
            result["body"] = alt_meta.get("body") or result.get("body")
            result["description"] = alt_meta.get("description") or result.get("description")
            result["content_source_url"] = alt_meta.get("resolved_url") or alt_resolved
            result["content_source_publisher"] = str(alt.get("publisher") or "다른 언론사")
            if len(runtime._clean_text(result.get("body") or "")) >= 900:
                break

    runtime._NEWS_META_CACHE[case_id] = dict(result)
    return dict(result)


def _news_reading_limits(user: dict | None) -> tuple[int, int, str]:
    level = str((user or {}).get("school_level") or "")
    grade = int((user or {}).get("grade") or 0)
    if level == "초" and grade <= 3:
        return 4, 5, "짧은 문장과 쉬운 말로 설명하되 사건의 핵심 인물·기관·숫자는 빼지 않는다."
    if level == "초":
        return 5, 6, "어려운 용어는 쉬운 말로 풀되 중요한 고유명사·수치·핵심 용어는 그대로 남긴다."
    if level == "중":
        return 5, 7, "사건의 경과, 근거, 쟁점, 대응, 아직 확인할 부분을 나누어 충분히 설명한다."
    if level == "고":
        return 6, 8, "사실관계와 쟁점, 법·정책·기술 용어, 이해관계자의 주장과 불확실성을 충분히 보존한다."
    return 5, 7, "원문을 따로 열지 않아도 사건의 핵심 사실과 쟁점을 이해할 정도로 충분히 설명한다."


def _news_study_pack(case: dict, user: dict | None) -> dict:
    level = str((user or {}).get("school_level") or "")
    grade = int((user or {}).get("grade") or 0)
    key = (str(case.get("id") or ""), level, grade)
    if key in runtime._NEWS_PACK_CACHE:
        return dict(runtime._NEWS_PACK_CACHE[key])

    profile, rules, _ = runtime._news_profile(user)
    min_paragraphs, max_paragraphs, paragraph_rule = _news_reading_limits(user)
    meta = _fetch_news_meta(case)
    description = runtime._clean_text(meta.get("description") or "")
    body = runtime._clean_text(meta.get("body") or "")
    summary = runtime._clean_text(case.get("news_summary") or "")
    if summary == runtime._clean_text(f"{case.get('title','')} {case.get('source_name','')}"):
        summary = ""

    source_parts = []
    if description:
        source_parts.append("[기사 설명] " + description)
    if body and body not in description:
        source_parts.append("[기사 본문] " + body)
    if not source_parts and summary:
        source_parts.append("[수집 요약] " + summary)
    source_text = "\n\n".join(source_parts)

    alternates = list(case.get("news_alternates") or [])
    alt_text = "\n".join(
        f"- {x.get('publisher','')} | {x.get('title','')}" for x in alternates[:4]
    ) or "- 동일 사건 다른 기사 메타데이터 없음"

    if len(source_text) >= 240:
        prompt = f'''다음 실제 뉴스 기사를 {profile} 학생이 읽는 미디어 리터러시 학습자료로 재구성하라.
수준 규칙: {rules}

기사 제목: {case.get('title','')}
언론사: {case.get('source_name','')}
게시일: {str(case.get('news_published_at') or '')[:10]}

[확인된 기사 내용]
{source_text[:12500]}

[동일 사건 다른 보도 제목]
{alt_text}

작성 규칙:
1. 단순한 3문장 요약이나 일반론으로 끝내지 않는다. 학생이 이 화면만 읽어도 실제 사건의 중요한 내용을 파악할 수 있게 기사 내용을 충분히 살린다.
2. reading은 {min_paragraphs}~{max_paragraphs}개 문단으로 작성한다. {paragraph_rule}
3. 기사에 나온 사람·기관·기업·지역·날짜·수치·법령/정책명·기술명·핵심 쟁점 용어는 중요 정보이면 삭제하거나 모호한 일반어로 바꾸지 않는다. 어려운 용어는 원래 용어를 남긴 뒤 쉬운 말로 설명한다.
4. 가능한 범위에서 '무슨 일이 있었는지 → 구체적으로 확인된 내용 → 왜 문제가 되는지 → 관계기관/당사자의 대응 → 아직 확인되지 않았거나 논쟁 중인 부분' 순서로 이해할 수 있게 구성한다.
5. 원문이 '검토', '의혹', '정황', '가능성', '주장'처럼 확정되지 않은 표현을 썼다면 그 불확실성을 그대로 보존한다.
6. 기사에 서로 다른 주체의 주장이나 인용이 있으면 누가 한 말인지 보존한다. 기자의 평가와 사실 진술을 섞지 않는다.
7. 원문 문장을 길게 그대로 복사하지 말고 학생용 문장으로 재구성한다. 중요한 사실을 줄이기 위해 핵심 단어와 수치를 버리지 않는다.
8. 동일 사건 다른 보도 제목은 비교 관점을 잡는 데만 사용하고 그 제목만으로 새로운 사실을 만들지 않는다.
9. questions는 정확히 3개. 모든 질문은 화면에 표시될 reading만 읽어도 답할 수 있어야 한다.
10. 질문은 단순 암기보다 사실/해석 구분, 근거 판단, 표현의 불확실성, 기사 비교 중 학생 수준에 맞는 사고를 한 가지씩 묻는다. 한 질문에 여러 요구를 몰아넣지 않는다.
11. 기사 원문에만 있고 reading에서 빠진 세부 정보를 학생이 알아야 풀 수 있는 질문은 금지한다.

JSON 스키마에 맞춰 반환하라.'''
        try:
            draft, _ = base.core.generate_structured_with_fallback(
                prompt,
                runtime.NewsStudyDraft,
                max_output_tokens=2600,
            )
            reading = [runtime._clean_text(x) for x in draft.reading if runtime._clean_text(x)][:max_paragraphs]
            questions = [runtime._clean_text(x) for x in draft.questions if runtime._clean_text(x)][:3]
            if len(reading) >= min_paragraphs and len(questions) == 3:
                pack = {
                    "reading": reading,
                    "questions": questions,
                    "resolved_url": meta.get("resolved_url") or case.get("source_url"),
                    "content_source_url": meta.get("content_source_url") or meta.get("resolved_url") or case.get("source_url"),
                    "content_source_publisher": meta.get("content_source_publisher") or case.get("source_name") or "",
                }
                runtime._NEWS_PACK_CACHE[key] = dict(pack)
                return pack
        except Exception as exc:
            base.core.logger.warning("expanded news study generation failed: %s", type(exc).__name__)

    count = int(case.get("news_article_count") or 1)
    reading = [
        f"이 사례의 대표 보도는 {case.get('source_name') or '언론사'}가 {str(case.get('news_published_at') or '')[:10] or '게시일 미확인'}에 낸 ‘{case.get('title') or ''}’ 기사입니다.",
        "현재 서버가 기사 본문을 충분히 불러오지 못해 제목과 출처를 넘어선 세부 사실을 임의로 채우지 않았습니다. 이 경우에는 원문 보기에서 기사 내용을 확인한 뒤 학습하는 것이 정확합니다.",
        f"수집 데이터에서는 같은 사건 기사 {count}건이 한 묶음으로 정리되어 있습니다. 제목에 들어간 표현 중 사실로 직접 확인되는 부분과 원문 확인이 필요한 판단·평가 표현을 구분해보세요.",
    ]
    questions = [
        "현재 화면에서 확실히 확인되는 사실은 무엇인가요?",
        "기사 원문에서 가장 먼저 확인해야 할 세부 정보는 무엇인가요?",
        "제목에 사실 표현과 해석·평가 표현이 함께 있다면 어떻게 구분할 수 있을까요?",
    ]
    pack = {
        "reading": reading,
        "questions": questions,
        "resolved_url": meta.get("resolved_url") or case.get("source_url"),
    }
    runtime._NEWS_PACK_CACHE[key] = dict(pack)
    return pack


# 런타임의 기존 뉴스 라우트가 이 강화된 함수들을 사용하게 한다.
runtime._fetch_news_meta = _fetch_news_meta
runtime._news_study_pack = _news_study_pack


# 기존 .chat-case-media img의 max-height:250px가 뉴스 큰 이미지에도 상속돼
# 이미지 아래에 큰 빈 영역이 생기던 문제를 최종 렌더 단계에서만 교정한다.
_RENDER_BEFORE_NEWS_LAYOUT = runtime._render_runtime_index


def _render_news_layout() -> str:
    page = _RENDER_BEFORE_NEWS_LAYOUT()
    css = r'''
<style>
.aioff-news-hero{
  height:clamp(260px,28vw,420px)!important;
  min-height:0!important;
  overflow:hidden!important;
  background:#e9edf2!important;
}
.chat-case-media .aioff-news-hero img,
.aioff-news-hero img{
  display:block!important;
  width:100%!important;
  height:100%!important;
  max-height:none!important;
  object-fit:cover!important;
  object-position:center center!important;
}
@media(max-width:900px){
  .aioff-news-hero{height:260px!important}
}
</style>
'''
    return page.replace("</body>", css + "\n</body>")


runtime._render_runtime_index = _render_news_layout


# ---------------------------------------------------------------------------
# 뉴스 튜터 설명 강화: 답을 다시 묻기 전에 왜 맞거나 부족한지 자료에 근거해 설명한다.
# ---------------------------------------------------------------------------
from fastapi import HTTPException as _HTTPException, Request as _Request
from fastapi.responses import Response as _Response

_PREVIOUS_NEWS_CHAT_STREAM = runtime.runtime_chat_stream
base._remove_route("/api/chat-stream", "POST")


def _feedback_length_rule(user: dict | None) -> str:
    level = str((user or {}).get("school_level") or "")
    grade = int((user or {}).get("grade") or 0)
    if level == "초" and grade <= 3:
        return "3~4문장. 쉬운 말로 판단 이유를 한 가지씩 설명한다."
    if level == "초":
        return "4~5문장. 학생 답을 해석하고 기사 근거와 연결해 설명한다."
    if level == "중":
        return "5~7문장. 학생 답의 의미, 기사 근거, 사실과 해석의 차이를 충분히 설명한다."
    if level == "고":
        return "6~8문장. 근거의 범위, 불확실성, 다른 해석 가능성까지 필요하면 설명한다."
    return "4~6문장. 판단 근거와 미디어 리터러시 포인트를 충분히 설명한다."


@app.post("/api/chat-stream")
def detailed_news_chat_stream(req: current.AioffTutorChatRequest, request: _Request):
    sid = req.session_id or str(base.core.uuid.uuid4())
    lesson_id = req.lesson_id if req.lesson_id in base.LESSONS else base._get_lesson_id(sid)
    case_id = runtime.flow._get_case_id(sid) if sid else None
    found = runtime.flow.CASE_BY_ID.get(case_id) if case_id else None
    if not found or not str(case_id).startswith("news_"):
        return _PREVIOUS_NEWS_CHAT_STREAM(req, request)

    case = found[1]
    user = runtime.auth.current_user(request.cookies.get(runtime.auth.COOKIE_NAME))
    pack = runtime._news_study_pack(case, user)
    profile, _, _ = runtime._news_profile(user)
    reading_items = [str(x).strip() for x in pack.get("reading", []) if str(x).strip()]
    questions = [str(x).strip() for x in pack.get("questions", []) if str(x).strip()]
    reading = "\n".join(f"- {x}" for x in reading_items)
    prior = base.core.messages(sid, 24)
    history = "\n".join(f"{'학생' if m['role']=='user' else '튜터'}: {m['content']}" for m in prior)
    current_question = str(req.current_question or "").strip()
    if not current_question:
        for message in reversed(prior):
            if message.get("role") == "assistant" and str(message.get("content") or "").strip():
                current_question = str(message.get("content") or "").strip()
                break
    if not current_question and questions:
        current_question = questions[0]

    length_rule = _feedback_length_rule(user)
    prompt = f'''너는 실제 뉴스를 이용한 디지털 리터러시 튜터다.
학생 수준: {profile}
설명 분량: {length_rule}

[기사]
제목: {case.get('title','')}
언론사: {case.get('source_name','')}
게시일: {str(case.get('news_published_at') or '')[:10]}

[학생 화면에 실제 표시된 읽어보기]
{reading or '(읽어보기 없음)'}

[현재 질문]
{current_question or '(질문 정보 없음)'}

[준비된 후속 질문]
{chr(10).join(f'- {x}' for x in questions) or '- 없음'}

[이전 대화]
{history or '(없음)'}

[학생의 새 답변]
{req.message}

반드시 학생 답을 먼저 '설명'한 뒤 다음 질문을 한다.
1. 학생이 쓴 말의 의도와 의미를 문맥에서 먼저 해석한다. 키워드가 빠졌다는 이유로 오답 처리하지 않는다.
2. 첫 문장에서는 학생의 답이 어떤 점에서 맞는지, 부족한지, 또는 애매한지를 분명히 말한다.
3. 그 다음 2~5문장에서는 반드시 읽어보기에 실제로 나온 구체적 사실과 연결해 왜 그런 판단인지 설명한다. 학생이 방금 말한 내용과 기사 사실 사이의 관계를 풀어준다.
4. 특히 '확인하지 못했다', '검토 중이다', '정황이 있다', '가능성이 있다', '주장했다' 같은 표현은 '확정됐다'와 무엇이 다른지 설명한다.
5. 사실, 해석, 추정, 추가 확인이 필요한 부분을 구분해야 하는 이유도 현재 사례와 연결해서 알려준다. 일반적인 훈계 문장만 쓰지 않는다.
6. 학생 답이 충분하면 같은 내용을 다시 말하게 하지 않는다. 이해한 부분을 인정하고 준비된 다음 질문 중 아직 다루지 않은 하나로 넘어간다.
7. 학생 답이 부분적으로 맞으면, 맞는 부분을 먼저 설명한 뒤 부족한 한 부분만 짚는다. '좀 더 명확히 말해볼래?'만 단독으로 쓰지 않는다.
8. 학생 답이 틀렸어도 정답을 한 단어씩 유도하는 도돌이표를 만들지 않는다. 읽어보기의 어느 사실 때문에 판단이 달라지는지 설명한 뒤 한 번만 다시 생각하게 한다.
9. 화면에 표시되지 않은 기사 원문 내용이나 모델의 배경지식을 근거로 채점하지 않는다.
10. 기사에 없는 사실을 새로 만들지 않는다.
11. response는 설명이 중심이고 마지막에만 질문 하나를 둔다. 질문만 던지는 답변은 금지한다.

예시 형식(문구를 그대로 복사하지 말 것):
'맞아. 이 기사에서는 회사가 피해 대상을 특정했다고 하지 않고, 거래내역을 갖고 있지 않아 구체적인 피해 대상을 특정하지 못했다고 설명해. 그래서 "피해가 없다"와 "피해 규모를 아직 정확히 모른다"는 서로 다른 뜻이야. 기사에서 확인 가능한 사실은 후자이고, 전자는 근거가 더 필요해. 이런 차이를 구분하는 게 뉴스에서 사실과 추정을 나누는 핵심이야. 다음으로 ...은 어떻게 봐야 할까?'

verdict는 pass, clarify, retry 중 하나로 판단한다.
- pass: 학생 답의 의미가 현재 질문의 핵심을 충족한다.
- clarify: 방향은 맞지만 학생 표현의 뜻이 실제로 두 가지 이상으로 해석될 수 있다.
- retry: 읽어보기와 명확히 모순되거나 질문을 잘못 이해했다.
response에는 학생에게 보여줄 자연스러운 설명만 작성하고 verdict나 모델명은 쓰지 않는다.'''

    try:
        decision, provider = base.core.generate_structured_with_fallback(
            prompt,
            current.TutorDecision,
            max_output_tokens=1200,
        )
    except Exception as exc:
        base.core.logger.warning("Detailed news tutor failed: %s", type(exc).__name__)
        raise _HTTPException(502, "뉴스 학습 답변 평가에 실패했습니다. 잠시 후 다시 시도해 주세요.")

    text = str(decision.response or "").strip()
    base.core.save_chat_exchange(sid, req.message, text)
    base.core.logger.info(
        "Detailed news tutor provider=%s verdict=%s case=%s",
        provider,
        decision.verdict,
        case_id,
    )
    return _Response(
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
# 로그인 영역 아래에 남던 구형 'ON' 라벨 제거.
# ---------------------------------------------------------------------------
_RENDER_BEFORE_FINAL_FIX = runtime._render_runtime_index


def _render_final_fix() -> str:
    page = _RENDER_BEFORE_FINAL_FIX()
    patch = r'''
<style>
.aioff-auth-dock .mode-label{display:none!important}
</style>
<script>
(() => {
  function removeStandaloneOn(){
    document.querySelectorAll('body *').forEach(el=>{
      if(el.children.length===0 && (el.textContent||'').trim()==='ON' && !el.classList.contains('aioff-auth-state')){
        el.remove();
      }
    });
  }
  removeStandaloneOn();
  new MutationObserver(removeStandaloneOn).observe(document.body,{childList:true,subtree:true,characterData:true});
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


runtime._render_runtime_index = _render_final_fix
