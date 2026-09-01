from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response
import html as html_lib
import random
import re
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import literacy_media_app_8 as previous
from literacy_cases_8 import CASE_LIBRARY

# 기존 9개×3 랜덤 사례, 원문 발췌, AI OFF 흐름은 그대로 유지합니다.
# 이번 버전은 (1) 27개 전체의 미디어 미리보기 자동 보강,
# (2) 정답을 암시하지 않는 첫 질문/후속 질문 방식만 수정합니다.
flow = previous.flow
app = previous.app

flow.CASE_LIBRARY.clear()
flow.CASE_LIBRARY.update(CASE_LIBRARY)
flow.CASE_BY_ID.clear()
flow.CASE_BY_ID.update({
    case["id"]: (lesson_id, case)
    for lesson_id, cases in flow.CASE_LIBRARY.items()
    for case in cases
})


# ---------------------------------------------------------------------------
# 1) 실제 원문 기반 미디어 미리보기
# ---------------------------------------------------------------------------
# 명시적으로 연결된 이미지가 있으면 우선 사용하고,
# 없으면 해당 원문 페이지의 og:image / twitter:image / YouTube iframe 썸네일을 찾습니다.
# 그래도 없으면 '빈 검은 박스' 대신 출처·사례명이 적힌 문서형 SVG 미리보기를 반환합니다.
_THUMB_CACHE = {}
_META_PATTERNS = [
    re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image|twitter:image:src)["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image|twitter:image:src)["\']', re.I),
]
_YT_PATTERN = re.compile(r'(?:youtube\.com/embed/|youtu\.be/)([A-Za-z0-9_-]{6,})', re.I)


def _http_get(url: str, limit: int = 4_000_000):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        },
    )
    with urlopen(req, timeout=5) as r:
        data = r.read(limit + 1)
        if len(data) > limit:
            data = data[:limit]
        return data, r.headers.get("Content-Type", "")


def _source_preview_candidate(case):
    if case.get("media_type") == "image" and case.get("media_url"):
        return case["media_url"]

    source_url = case.get("source_url", "")
    if not source_url or source_url.lower().split("?", 1)[0].endswith(".pdf"):
        return ""

    try:
        raw, content_type = _http_get(source_url, 1_200_000)
    except Exception:
        return ""
    if "html" not in content_type.lower() and b"<html" not in raw[:5000].lower():
        return ""

    text = raw.decode("utf-8", errors="ignore")
    for pattern in _META_PATTERNS:
        m = pattern.search(text)
        if m:
            return urljoin(source_url, html_lib.unescape(m.group(1).strip()))

    yt = _YT_PATTERN.search(text)
    if yt:
        return f"https://img.youtube.com/vi/{yt.group(1)}/hqdefault.jpg"
    return ""


def _svg_fallback(case):
    title = html_lib.escape(case.get("title", "실제 사례"))
    source = html_lib.escape(case.get("source_name", "원문 자료"))
    domain = html_lib.escape(urlparse(case.get("source_url", "")).netloc or "SOURCE")
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="620" viewBox="0 0 1200 620">
      <rect width="1200" height="620" fill="#eee9e1"/>
      <rect x="70" y="70" width="1060" height="480" rx="10" fill="#fff" stroke="#d8d0c5"/>
      <text x="115" y="145" font-family="Arial, sans-serif" font-size="24" fill="#756e65">SOURCE PREVIEW · {domain}</text>
      <line x1="115" y1="180" x2="1085" y2="180" stroke="#24211e" stroke-width="3"/>
      <foreignObject x="115" y="215" width="970" height="180">
        <div xmlns="http://www.w3.org/1999/xhtml" style="font-family:Arial,sans-serif;font-size:42px;font-weight:700;line-height:1.35;color:#24211e">{title}</div>
      </foreignObject>
      <foreignObject x="115" y="430" width="970" height="70">
        <div xmlns="http://www.w3.org/1999/xhtml" style="font-family:Arial,sans-serif;font-size:22px;line-height:1.4;color:#756e65">{source}</div>
      </foreignObject>
    </svg>'''
    return svg.encode("utf-8")


@app.get("/api/case-thumb/{case_id}")
def case_thumbnail(case_id: str):
    if case_id in _THUMB_CACHE:
        data, media_type = _THUMB_CACHE[case_id]
        return Response(content=data, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})

    found = flow.CASE_BY_ID.get(case_id)
    if not found:
        raise HTTPException(404, "사례를 찾을 수 없습니다.")
    case = found[1]

    candidate = _source_preview_candidate(case)
    if candidate:
        try:
            data, content_type = _http_get(candidate, 4_000_000)
            media_type = content_type.split(";", 1)[0].strip()
            if media_type.startswith("image/") and data:
                _THUMB_CACHE[case_id] = (data, media_type)
                return Response(content=data, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})
        except Exception:
            pass

    data = _svg_fallback(case)
    _THUMB_CACHE[case_id] = (data, "image/svg+xml")
    return Response(content=data, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


# ---------------------------------------------------------------------------
# 2) 첫 질문: 정답을 암시하지 않는 실제 행동/사용 결정형
# ---------------------------------------------------------------------------
flow.base._remove_route("/api/case-start", "POST")


@app.post("/api/case-start")
def case_start_v9(req: flow.CaseStartRequest):
    found = flow.CASE_BY_ID.get(req.case_id)
    if not found or found[0] != req.lesson_id or req.lesson_id not in flow.base.LESSONS:
        raise HTTPException(400, "선택한 학습 사례를 찾을 수 없습니다.")

    _, case = found
    sid = str(flow.base.core.uuid.uuid4())
    flow.base._save_lesson(sid, req.lesson_id)
    flow._save_case(sid, req.case_id)

    variants = case.get("opening_questions") or [case.get("opening_question", "이 사례에서 무엇을 먼저 확인하겠어?")]
    opening_question = random.choice(variants)

    with flow.base.core.connect_db() as c:
        c.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)", (sid,))
        c.execute(
            "INSERT INTO messages(session_id, role, content) VALUES(?, 'assistant', ?)",
            (sid, opening_question),
        )

    return {
        "session_id": sid,
        "case": flow._public_case(case),
        "opening_question": opening_question,
    }


# 후속 대화에서도 '믿어도 될까?'처럼 부정 답을 유도하지 않도록 기존 프롬프트 규칙을 교정합니다.
_ORIGINAL_CASE_PROMPT = flow._case_chat_prompt


def _case_chat_prompt_v9(session_id: str, user_message: str, lesson_id: str):
    prompt = _ORIGINAL_CASE_PROMPT(session_id, user_message, lesson_id)
    prompt = prompt.replace(
        "3. 처음에는 진짜/가짜에 대한 학생의 판단과 이유를 묻고, 이후 왜 그렇게 생각했는지와 무엇을 확인할지 파고든다.",
        "3. 학생이 선택한 행동·사용 결정의 이유를 먼저 듣고, 이후 그 판단을 만든 단서와 확인 절차를 하나씩 파고든다.",
    )
    prompt = prompt.replace(
        "4. 학생이 단순히 '진짜/가짜'만 답하면 곧바로 정답을 말하지 말고 그 판단의 근거나 확인 방법을 묻는다.",
        "4. 학생이 단순한 결론만 답하면 곧바로 정답을 말하지 말고, 그 결론을 만든 근거나 다음 확인 행동을 묻는다.",
    )
    prompt += """

추가 질문 작성 규칙:
- '믿어도 될까?', '바로 ~해도 될까?', '그렇다고 단정할 수 있을까?'처럼 정답이 '아니다'임을 쉽게 눈치챌 수 있는 문장을 피한다.
- 가능하면 '공유/보류/원문확인', '즉시 행동/별도 확인', '그대로 사용/원문 확인 후 사용'처럼 실제 상황에서 선택해야 하는 행동을 묻는다.
- 학생의 선택 자체보다 왜 그렇게 골랐는지, 어떤 단서를 봤는지, 다음에 무엇을 확인할지를 질문한다.
- 한 질문에 검증 기준을 여러 개 나열하지 않는다.
"""
    return prompt


flow._case_chat_prompt = _case_chat_prompt_v9
flow.base._lesson_chat_prompt = _case_chat_prompt_v9


# ---------------------------------------------------------------------------
# 3) 화면: 27개 모두 실제 원문 미리보기 또는 문서형 미리보기를 표시
# ---------------------------------------------------------------------------
def _render_index_v9():
    # app_8 -> app_7 -> app_6
    html = previous.previous.previous._render_index_v6()
    script = r'''
<script>
function caseMedia(c){
  return `<div class="chat-case-media"><img src="/api/case-thumb/${encodeURIComponent(c.id)}" alt="${esc(c.title)} 원문 미리보기" loading="eager"></div>`;
}
</script>
'''
    html = html.replace("</body>", script + "\n</body>")
    return html


flow.base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def inline_case_index_v9():
    return HTMLResponse(_render_index_v9())
