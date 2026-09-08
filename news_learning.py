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
