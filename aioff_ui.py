from __future__ import annotations

import html
import re
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
        plain_title = html.unescape(title)
        pos = text.find(plain_title)
        if pos < 0:
            compact = re.sub(r"\s+", "", plain_title)
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
    return Response(_aisac_fallback_svg(str(case.get("title") or "")), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=600"})


# ---------------------------------------------------------------------------
# Education case pool: 3 cards are a sample, not the entire archive.
# Filter by the logged-in school level, but keep shared middle/high and youth
# materials instead of collapsing the pool to only a few exact labels.
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
    adult = any(term in target for term in _ADULT_TARGET_TERMS)
    if adult:
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
        if grade and grade <= 3 and any(x in text for x in ("저학년", "1~3", "1-3", "1·2·3")):
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
# Education tutor: evaluate the current question first. Wrong/incomplete answers
# stay on the same question and get progressively stronger hints.
# Gemini is primary through generate_structured_with_fallback; Groq is fallback.
# ---------------------------------------------------------------------------
class AioffTutorChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    lesson_id: str | None = None
    current_question: str = Field(default="", max_length=1000)
    question_attempt: int = Field(default=1, ge=1, le=20)


class TutorDecision(BaseModel):
    verdict: Literal["pass", "retry"]
    response: str = Field(min_length=1, max_length=2200)


def _education_tutor_prompt(req: AioffTutorChatRequest, sid: str, case: dict, user: dict | None) -> str:
    source = previous._select_source(case)
    evidence = str(source.get("context") or source.get("text") or "")[:7500]
    question = str(req.current_question or case.get("opening_question") or "").strip()
    prior = base.core.messages(sid, 18)
    history = "\n".join(f"{'학생' if m['role']=='user' else '튜터'}: {m['content']}" for m in prior)
    profile = ""
    if user:
        level = str(user.get("school_level") or "")
        grade = int(user.get("grade") or 0)
        profile = f"{level} {grade}학년" if grade else level

    hint_rule = (
        "방향만 짚는 짧은 힌트 1개를 주고, 답을 다시 생각하게 하는 좁은 질문 1개를 한다."
        if req.question_attempt <= 1
        else "원문에서 확인해야 할 핵심 표현이나 위치를 더 구체적으로 짚어 주되 정답 문장을 그대로 말하지 않는다."
        if req.question_attempt == 2
        else "선택지나 문장 틀처럼 거의 답을 구성할 수 있는 발판을 준다. 그래도 학생이 마지막 판단은 직접 하게 한다."
    )

    return f'''너는 디지털 리터러시 수업에서 한 문항씩 지도하는 튜터다.
학생 답변을 먼저 판정하고, 틀렸거나 핵심이 부족하면 같은 문항을 유지한 채 힌트를 단계적으로 제공한다.

학생 수준: {profile or '학생'}
자료명: {case.get('title') or '-'}
현재 문항: {question or '(문항 정보 없음)'}
이번 문항 시도 횟수: {req.question_attempt}
학생의 이번 답변: {req.message}

[화면에 사용된 공식 원문 근거]
{evidence or '(원문 근거 없음)'}

[이전 대화]
{history or '(없음)'}

판정 원칙:
- verdict='pass': 현재 문항의 핵심에 직접 답했고 공식 원문과 모순되지 않으면 통과한다. 표현이 원문과 똑같을 필요는 없다.
- 의견·해석형 문항은 하나의 정답 문구를 강요하지 않는다. 근거가 있고 질문에 맞으면 통과할 수 있다.
- verdict='retry': 핵심을 빗나갔거나, 사실과 해석을 혼동했거나, 질문의 중요한 부분이 빠진 경우다.
- 단순히 짧다는 이유만으로 retry 하지 않는다.
- 원문에 없는 사실을 자료에 적혀 있다고 만들지 않는다.

retry일 때:
- 학생이 방금 한 말을 길게 되풀이하지 않는다.
- 무엇이 부족한지 한 가지만 짚는다.
- {hint_rule}
- 매번 같은 문장이나 같은 질문을 반복하지 않는다.

pass일 때:
- 왜 통과인지 핵심 근거를 2~4문장으로 짧게 설명한다.
- 다음 문항을 새로 만들어 묻지 않는다. 화면이 다음 문항으로 넘어간다.

response에는 학생에게 보여줄 말만 작성하고 'pass', 'retry', 판정 코드, 모델명은 쓰지 않는다.'''


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
        decision, provider = base.core.generate_structured_with_fallback(prompt, TutorDecision, max_output_tokens=700)
    except Exception as exc:
        base.core.logger.warning("Education tutor evaluation failed: %s", type(exc).__name__)
        raise HTTPException(502, "학습 답변 평가에 실패했습니다. 잠시 후 다시 시도해 주세요.")

    text = str(decision.response or "").strip()
    base.core.save_chat_exchange(sid, req.message, text)
    marker = "[[AIOFF_PASS]]" if decision.verdict == "pass" else "[[AIOFF_RETRY]]"
    base.core.logger.info("Education tutor provider=%s verdict=%s case=%s", provider, decision.verdict, case_id)
    return Response(
        text + marker,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Session-Id": sid,
            "X-AIOFF-Provider": provider,
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

@media(max-width:1180px){main{width:calc(100% - 20px)!important}.aioff-learning-columns{grid-template-columns:minmax(0,1fr) 320px}.aioff-composer-side .composer textarea{min-height:500px!important}.education-guide-preview-v19,.kobaco-picker-media,.topic-preview{height:205px!important;min-height:205px!important}}
@media(max-width:900px){main{width:100%!important;padding-left:12px!important;padding-right:12px!important}.aioff-learning-columns{display:block;min-height:0}.aioff-learning-columns>.chat-area{border-right:0;padding:16px!important}.aioff-learning-columns .chat{height:680px!important;min-height:680px!important}.aioff-composer-side{border-top:1px solid var(--line)}.aioff-composer-side .composer textarea{min-height:220px!important}.education-study-v21-visual iframe{height:520px!important}.education-guide-preview-v19,.kobaco-picker-media,.topic-preview{height:170px!important;min-height:170px!important}}
</style>
<script>
(() => {
  let activeEducationCard=null;
  let activeQuestions=[];
  let activeQuestionIndex=0;
  let questionAttempts=[];

  const nativeFetch=window.fetch.bind(window);

  function installWideLearningLayout(){
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

  function updateQuestionUI(retry=false){
    if(!activeEducationCard || !activeQuestions.length) return;
    const items=[...activeEducationCard.querySelectorAll('.education-study-v21-questions li')];
    items.forEach((li,i)=>li.classList.toggle('aioff-current-question',i===activeQuestionIndex));
    const heading=activeEducationCard.querySelector('.education-study-v21-questions h4');
    if(heading){
      let progress=heading.querySelector('.aioff-question-progress');
      if(!progress){progress=document.createElement('span');progress.className='aioff-question-progress';heading.appendChild(progress)}
      progress.textContent=`${activeQuestionIndex+1} / ${activeQuestions.length}${retry?' · 다시 생각해보기':''}`;
    }
    const side=document.querySelector('[data-aioff-side-question]');
    const sideProgress=document.querySelector('[data-aioff-side-progress]');
    const sideText=document.querySelector('[data-aioff-side-text]');
    if(side&&sideProgress&&sideText){side.style.display='block';sideProgress.textContent=`질문 ${activeQuestionIndex+1} / ${activeQuestions.length}${retry?' · 힌트를 보고 다시 답해보세요':''}`;sideText.textContent=activeQuestions[activeQuestionIndex]||''}
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
    activeEducationCard=card;activeQuestions=questions;activeQuestionIndex=0;questionAttempts=new Array(questions.length).fill(0);card.dataset.aioffSeq='1';updateQuestionUI(false);
  }

  window.fetch=async function(resource,init){
    const url=typeof resource==='string'?resource:String(resource?.url||'');
    if(url.includes('/api/chat-stream') && activeEducationCard && activeQuestions.length && init && typeof init.body==='string'){
      try{
        const body=JSON.parse(init.body);
        questionAttempts[activeQuestionIndex]=(questionAttempts[activeQuestionIndex]||0)+1;
        body.current_question=activeQuestions[activeQuestionIndex]||'';
        body.question_attempt=questionAttempts[activeQuestionIndex];
        init={...init,body:JSON.stringify(body)};
      }catch(e){}
    }
    return nativeFetch(resource,init);
  };

  function stripVerdict(el){
    const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);const nodes=[];let n;
    while((n=walker.nextNode())) nodes.push(n);
    nodes.forEach(node=>{node.nodeValue=(node.nodeValue||'').replaceAll('[[AIOFF_PASS]]','').replaceAll('[[AIOFF_RETRY]]','')});
  }

  function consumeTutorVerdict(){
    if(!activeEducationCard || !activeQuestions.length) return;
    const messages=[...document.querySelectorAll('#chat .msg.assistant')];
    for(const msg of messages){
      if(msg.dataset.aioffVerdict==='1') continue;
      const text=msg.textContent||'';
      let verdict='';
      if(text.includes('[[AIOFF_PASS]]')) verdict='pass';
      else if(text.includes('[[AIOFF_RETRY]]')) verdict='retry';
      if(!verdict) continue;
      msg.dataset.aioffVerdict='1';stripVerdict(msg);
      if(verdict==='pass'){
        if(activeQuestionIndex<activeQuestions.length-1){activeQuestionIndex+=1;updateQuestionUI(false)}
        else{
          const p=document.querySelector('[data-aioff-side-progress]');if(p)p.textContent=`질문 ${activeQuestions.length} / ${activeQuestions.length} · 답변 완료`;
          const t=document.querySelector('[data-aioff-side-text]');if(t)t.textContent='세 문항을 모두 마쳤습니다.';
        }
      }else updateQuestionUI(true);
    }
  }

  function scan(){installWideLearningLayout();installSequentialQuestions();consumeTutorVerdict()}
  installWideLearningLayout();scan();
  new MutationObserver(scan).observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['data-loaded']});
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def aioff_ui_index():
    return HTMLResponse(_render_index_aioff_ui())
