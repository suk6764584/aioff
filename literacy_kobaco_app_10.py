from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

import literacy_kobaco_app_9 as previous

# v9의 DB/공익광고 매칭/AI OFF 기능은 유지하고,
# v10에서는 학생이 먼저 이해할 수 있는 맥락을 보여준 뒤 데이터와 AI 해석을 비교합니다.
app = previous.app
base = previous.base
flow = previous.flow
v5 = previous.v5
v4 = previous.v4


# ---------------------------------------------------------------------------
# 1) OTT 주제는 실제 '청소년(13-19세)' 행만 사용
# ---------------------------------------------------------------------------
def _rebuild_youth_ott_cases() -> None:
    src = v4.v1
    db = src.get_kobaco_db()
    if db is None or not db.has_tables("ott_usage_by_demographic"):
        return

    rows = db.query(
        '''
        SELECT *
        FROM ott_usage_by_demographic
        WHERE "구분1"='연령별' AND "구분2"='13-19세'
        ORDER BY "연도" DESC
        LIMIT 9
        '''
    )
    service_columns = [
        "유튜브", "넷플릭스", "티빙", "웨이브", "SOOP(구 아프리카TV)", "카카오TV",
        "왓챠", "쿠팡플레이", "NAVER TV(구 NOW)", "디즈니플러스", "U플러스모바일TV", "애플TV플러스",
    ]
    cases: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, 1):
        ranked = []
        for col in service_columns:
            n = src._num(row.get(col))
            if n is not None:
                ranked.append((n, col))
        ranked.sort(reverse=True)
        top = ranked[:6]
        if not top:
            continue
        year = src._text(row.get("연도"))
        group = "13-19세"
        sample = src._int_text(row.get("사례수"))
        top_text = " · ".join(f"{name} {value:.1f}%" for value, name in top)
        cases.append(
            src._common_case(
                case_id=f"kobaco_ott_{idx:02d}",
                label="청소년 OTT 실제 통계",
                title=f"{year} · {group}",
                claim=(
                    f"{year}년 {group}의 플랫폼별 이용 비율을 읽고, "
                    "이용률을 선호도나 전체 청소년의 성향으로 확대하지 않는 법을 연습합니다."
                ),
                source_name="KOBACO 성별·연령별 OTT 이용비율",
                source_url="https://www.data.go.kr",
                source_excerpt=f"사례수 {sample}명 · {top_text} · OTT 비이용 {src._pct(row.get('OTT 비이용'))}",
                clues=[
                    f"연도: {year}",
                    f"조사 집단: {group}",
                    f"사례수: {sample}명",
                    f"플랫폼 이용비율: {top_text}",
                    f"OTT 비이용: {src._pct(row.get('OTT 비이용'))}",
                    "각 플랫폼 값은 이용 비율이며 선호도·만족도 값이 아니다.",
                ],
                resolution=(
                    f"이 표가 직접 보여주는 것은 {year}년 {group} 응답자의 플랫폼별 이용 비율입니다. "
                    "가장 높은 이용률을 '가장 좋아하는 서비스'라고 바꾸거나 다른 연령·전체 청소년에게 그대로 일반화할 수는 없습니다."
                ),
                opening_questions=[
                    f"먼저 {year}년 {group}의 조사 대상과 서비스별 이용 비율을 같이 보세요. 이 자료로 확실히 말할 수 있는 사실 하나와 말할 수 없는 해석 하나를 나눠보세요.",
                    "가장 높은 이용 비율을 곧바로 '가장 좋아하는 서비스'라고 말해도 될까요? 표의 항목 이름을 근거로 판단해보세요.",
                    "이 결과를 다른 연령이나 전체 청소년에게 그대로 확대해도 되는지 조사 조건을 보고 설명해보세요.",
                ],
                db_tables=["ott_usage_by_demographic"],
                data_rows=[
                    {"label": "연도·집단", "value": f"{year} · {group}"},
                    {"label": "사례수", "value": f"{sample}명"},
                    {"label": "이용비율 상위", "value": top_text},
                    {"label": "OTT 비이용", "value": src._pct(row.get("OTT 비이용"))},
                ],
                data_note="KOBACO 성별·연령별 OTT 이용비율 Parquet에서 13-19세 행만 직접 조회한 값입니다.",
            )
        )

    # 최소 3개 연도 확보 시에만 기존 풀을 교체합니다.
    if len(cases) >= 3:
        flow.CASE_LIBRARY["ai"] = cases
        flow.CASE_BY_ID.clear()
        flow.CASE_BY_ID.update({
            case["id"]: (lesson_id, case)
            for lesson_id, lesson_cases in flow.CASE_LIBRARY.items()
            for case in lesson_cases
        })


_rebuild_youth_ott_cases()


# ---------------------------------------------------------------------------
# 2) AiSAC 사례에 '사람이 먼저 읽을 맥락' 추가
# ---------------------------------------------------------------------------
RELATED_CONTEXT = {
    "무주반딧불축제": {
        "url": "https://www.yonhapnewstv.co.kr/news/MYH20260815131118EZq",
        "label": "연합뉴스TV 관련 보도 보기",
        "summary": (
            "광고 제목상 무주군청의 '제30회 무주반딧불축제' 홍보편입니다. "
            "키워드만 보기 전에 관련 보도와 원본 광고에서 축제가 어떤 장면·문구·맥락으로 소개되는지 먼저 확인합니다."
        ),
    },
}


def _attach_aisac_context(case: dict[str, Any]) -> None:
    title = str(case.get("title") or "광고")
    matched = next((v for key, v in RELATED_CONTEXT.items() if key in title), None)
    if matched:
        case["context_url"] = matched["url"]
        case["context_label"] = matched["label"]
        case["context_summary"] = matched["summary"]
    else:
        if ":" in title:
            subject, piece = [x.strip() for x in title.split(":", 1)]
            summary = (
                f"광고 제목상 '{subject}'의 '{piece}' 소재입니다. "
                "제목과 AI 키워드만으로 전체 메시지를 정하지 말고 원본 영상·자막·앞뒤 장면을 먼저 확인합니다."
            )
        else:
            summary = (
                f"광고 소재명은 '{title}'입니다. "
                "AI 인식 키워드만으로 광고의 뜻을 정하지 말고 원본 영상·자막·장면 흐름을 함께 확인합니다."
            )
        case["context_url"] = ""
        case["context_label"] = "관련 정보 검색"
        case["context_summary"] = summary

    questions = [
        f"'{title}'의 원본 광고나 관련 맥락 자료를 먼저 확인해보세요. 사람이 이해한 내용 하나와 AiSAC이 찾은 요소 하나를 골라 둘이 같은지 다른지 말해보세요.",
        f"'{title}'에서 AI 키워드만으로는 알기 어려운 장면의 맥락이나 메시지를 하나 찾아보세요.",
        "원본 자료와 AI 인식 결과를 나란히 봤을 때, AI가 잡은 부분 하나와 사람이 직접 봐야 알 수 있는 부분 하나를 골라보세요.",
    ]
    case["opening_questions"] = questions
    case["opening_question"] = questions[0]


for _case in flow.CASE_LIBRARY.get("news", []):
    _attach_aisac_context(_case)


# case-start 응답에도 맥락 필드를 보존합니다.
_ORIGINAL_PUBLIC_CASE = flow._public_case


def _public_case_v10(case: dict[str, Any]) -> dict[str, Any]:
    data = dict(_ORIGINAL_PUBLIC_CASE(case))
    for key in (
        "context_url", "context_label", "context_summary",
        "archive_url", "archive_title", "archive_year", "archive_category",
    ):
        if key in case:
            data[key] = case.get(key, "")
    return data


flow._public_case = _public_case_v10


def _topic_payload() -> dict[str, list[dict[str, Any]]]:
    return {
        lesson_id: [flow._public_case(case) for case in flow.CASE_LIBRARY.get(lesson_id, [])]
        for lesson_id in ("news", "deepfake", "ai")
    }


def _rows(case: dict[str, Any]) -> dict[str, str]:
    return {
        str(row.get("label") or "").strip(): str(row.get("value") or "").strip()
        for row in (case.get("data_rows") or [])
    }


def _student_turns(session_id: str) -> int:
    return sum(1 for m in base.core.messages(session_id, 30) if m["role"] == "user")


def _case_kind(case_id: str) -> str:
    if case_id.startswith("kobaco_aisac_"):
        return "aisac"
    if case_id.startswith("kobaco_publicad_"):
        return "publicad"
    if case_id.startswith("kobaco_ott_"):
        return "ott"
    return "unknown"


# ---------------------------------------------------------------------------
# 3) 학생 답변을 실제로 읽는 AI 튜터
# ---------------------------------------------------------------------------
def _learning_prompt(session_id: str, user_message: str, lesson_id: str, case_id: str, case: dict[str, Any]) -> str:
    lesson = base.LESSONS[lesson_id]
    prior = base.core.messages(session_id, 24)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '학습도우미'}: {m['content']}" for m in prior
    )
    db_values = "\n".join(f"- {k}: {v}" for k, v in _rows(case).items()) or "- 표시 값 없음"
    criteria = "\n".join(f"- {x}" for x in lesson.get("criteria", []))
    turn = _student_turns(session_id)
    kind = _case_kind(case_id)

    if kind == "publicad":
        stage = f'''
학생은 실제 공익광고를 보고 자신의 해석과 KOBACO 효과평가를 비교한다.
현재 학생 답변 횟수: {turn}
- 첫 답변부터 퍼센트 숫자를 정답처럼 던지지 않는다.
- 학생이 무엇을 느꼈는지와 그 근거 장면·문구를 먼저 다룬다.
- 신뢰성, 광고를 접한 경로, 가장 강한 인상을 준 요소는 서로 다른 질문의 값이라고 설명한다.
- 숫자는 항목의 쉬운 뜻과 함께 제시하고 행동 변화·인과효과로 확대하지 않는다.
'''
    elif kind == "aisac":
        stage = f'''
학생은 광고의 원본/관련 맥락 자료를 먼저 보고 AiSAC 인식값과 비교한다.
현재 학생 답변 횟수: {turn}
- 키워드만 보고 광고 의미를 추측하게 하지 않는다.
- 학생이 실제 자료에서 본 장면·문구·맥락과 AI가 찾은 키워드를 구분한다.
- AI 인식값은 관찰값이며 광고의 의도·감정·메시지 자체가 아니라고 설명한다.
- 원본을 아직 안 봤다면 먼저 화면의 원본/관련 정보 버튼을 보도록 안내한다.
'''
    elif kind == "ott":
        stage = f'''
학생은 13-19세 청소년 OTT 이용비율을 읽는다.
현재 학생 답변 횟수: {turn}
- 연도·연령집단·사례수를 먼저 확인한다.
- 이용률과 선호도·만족도를 구분한다.
- 다른 연령이나 전체 청소년에게 과잉 일반화하지 않도록 설명한다.
- 표에서 직접 말할 수 있는 사실과 추가 근거가 필요한 해석을 나누게 한다.
'''
    else:
        stage = "제공된 자료가 직접 말하는 사실과 추가 해석을 구분한다."

    return f'''너는 초등 고학년~중학생을 위한 미디어 리터러시 학습도우미다.
학생이 화면의 자료를 이해한 뒤 스스로 판단하는 법을 배우게 한다.

[현재 사례]
사례명: {case.get('title', '-')}
출처: {case.get('source_name', '-')}
설명: {case.get('claim', '-')}
맥락: {case.get('context_summary', '-')}

[실제 데이터]
{db_values}

[판단 기준]
{criteria}

[이번 사례 진행]
{stage}

응답 규칙:
1. 학생의 방금 답에 직접 반응한다. 정해진 문장을 순서대로 재생하지 않는다.
2. 3~6문장 정도로 설명과 피드백을 함께 준다.
3. 학생이 틀리거나 자료보다 넓게 단정하면 이유를 설명하며 바로 교정한다.
4. 학생이 모르겠다고 하면 질문을 반복하지 말고 읽는 방법을 먼저 알려준다.
5. 숫자만 단독으로 던지지 않고 무엇을 측정한 값인지 함께 말한다.
6. 제공된 자료에 없는 사실·의도·인과효과를 만들지 않는다.
7. 같은 질문을 표현만 바꿔 반복하지 않는다.
8. AI OFF 최종 문제는 지금 미리 출제하지 않는다.

[이전 대화]
{history or '(없음)'}

[학생의 새 답변]
{user_message}
'''


def _stream_model_reply(prompt: str, sid: str, user_message: str):
    emitted = False
    parts: list[str] = []
    gemini_error: Exception | None = None
    try:
        client = base.core.gemini_client()
        stream = client.models.generate_content_stream(model=base.core.gemini_model(), contents=prompt)
        for chunk in stream:
            text = getattr(chunk, "text", None) or ""
            if text:
                emitted = True
                parts.append(text)
                yield text
        reply = "".join(parts).strip()
        if not reply:
            raise ValueError("gemini_empty_response")
        base.core.save_chat_exchange(sid, user_message, reply)
        return
    except Exception as exc:
        gemini_error = exc
        if emitted:
            yield "\n\nAI 응답 전송이 중단되었습니다. 같은 답변을 다시 보내주세요."
            return

    if base.core.groq_configured():
        try:
            client = base.core.groq_client()
            stream = client.chat.completions.create(
                model=base.core.groq_model(),
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=700,
                temperature=0.25,
                stream=True,
            )
            parts = []
            for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                text = getattr(getattr(choices[0], "delta", None), "content", None) or ""
                if text:
                    parts.append(text)
                    yield text
            reply = "".join(parts).strip()
            if not reply:
                raise ValueError("groq_empty_response")
            base.core.save_chat_exchange(sid, user_message, reply)
            return
        except Exception as exc:
            base.core.logger.warning("Groq KOBACO learning fallback failed: %s", type(exc).__name__)

    base.core.logger.warning(
        "Gemini KOBACO learning failed: %s",
        type(gemini_error).__name__ if gemini_error else "UnknownError",
    )
    yield "AI 학습도우미 연결에 실패했습니다. 잠시 후 같은 답변을 다시 보내주세요."


base._remove_route("/api/chat-stream", "POST")


@app.post("/api/chat-stream")
def kobaco_ai_chat_stream(req: base.LiteracyChatRequest):
    sid = req.session_id or str(base.core.uuid.uuid4())
    lesson_id = req.lesson_id if req.lesson_id in base.LESSONS else base._get_lesson_id(sid)
    if lesson_id not in base.LESSONS:
        raise HTTPException(400, "먼저 학습 주제를 선택해 주세요.")
    base._save_lesson(sid, lesson_id)
    case_id = flow._get_case_id(sid)
    found = flow.CASE_BY_ID.get(case_id) if case_id else None
    if not found or found[0] != lesson_id:
        raise HTTPException(400, "선택한 사례를 다시 확인해 주세요.")
    prompt = _learning_prompt(sid, req.message, lesson_id, case_id, found[1])
    return StreamingResponse(
        _stream_model_reply(prompt, sid, req.message),
        media_type="text/plain; charset=utf-8",
        headers={"X-Session-Id": sid, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 4) 학생 화면
# ---------------------------------------------------------------------------
def _render_index_kobaco_v10():
    page = v5._render_index_kobaco_v5()
    topic_json = json.dumps(_topic_payload(), ensure_ascii=False).replace("</", "<\\/")

    replacements = {
        "실제 미디어 데이터를 읽고,<br>AI와 해석 기준을 연습합니다.": "미디어를 보고,<br>생각하고, 데이터로 확인해요.",
        "AI와 해석 기준을 연습합니다.": "미디어를 보고, 생각하고, 데이터로 확인해요.",
        "공식 교육·조사자료를 바탕으로 정리한 뉴스·딥페이크·AI 답변 검증 기준을 사례로 연습합니다. 학습을 마치면 AI OFF가 방금 대화를 분석해, 같은 판단 기준을 혼자 적용해보는 문제 3개를 만듭니다.": "실제 KOBACO 광고·공익광고·청소년 미디어 이용 자료를 먼저 이해하고, 내가 본 내용과 데이터가 말하는 범위를 비교하며 연습합니다.",
        "기존 AI OFF는 그대로": "마지막에는 혼자 풀어봐요",
        "AI와 학습한 대화를 분석하고 AI가 대신한 사고를 학생이 직접 다시 수행하는 기존 구조를 유지합니다. 이번에는 학습 주제를 디지털 리터러시로 구체화했습니다.": "학습이 끝나면 같은 기준을 새 문제에 직접 적용해봅니다. 답을 고친 뒤 다시 확인할 수도 있습니다.",
        "실제 KOBACO 데이터에서 바로 시작합니다.": "실제 KOBACO 자료로 배워요.",
        "주제를 고르면 KOBACO Parquet DB에서 구성한 실제 데이터 사례가 무작위로 나타납니다.": "주제를 고르면 실제 자료 사례 3개가 나타납니다.",
        "사례를 선택하면 사진·기사·문서와 DB 조회값, 판단할 주장을 보여주고 AI가 바로 첫 질문을 합니다.": "사례를 선택하면 먼저 이해할 자료와 배경을 보여주고, 그 다음 AI가 함께 비교해줍니다.",
        "광고를 먼저 보고 내 판단 만들기": "광고를 보고 내 해석 만들기",
        "DB 조회값": "실제 조사·인식 데이터",
        "판단할 해석·상황": "생각해 볼 점",
    }
    for old, new in replacements.items():
        page = page.replace(old, new)

    css = r'''
.context-card{padding:14px 16px;background:#fff7ef;border-bottom:1px solid #eadbcb}.context-card b{display:block;font-size:13px;margin-bottom:6px}.context-card p{margin:0;font-size:11px;line-height:1.65;color:#62584f}
.context-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.context-actions a{display:inline-flex;text-decoration:none;padding:8px 11px;border-radius:7px;background:#2d2925;color:#fff!important;font-size:10px;font-weight:850}.context-actions a.alt{background:#fff;color:#2d2925!important;border:1px solid #cfc6ba}
.compare-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:14px;background:#f7f4ef;border-bottom:1px solid #e2dbd1}.compare-box{background:#fff;border:1px solid #ddd5ca;border-radius:9px;padding:12px}.compare-box small{display:block;font-size:9px;font-weight:900;color:#7e7369;margin-bottom:6px}.compare-box strong{display:block;font-size:12px;line-height:1.5;margin-bottom:5px}.compare-box p{font-size:10px;line-height:1.55;color:#6b625a;margin:0}
.ott-summary{padding:14px 16px;background:#fff7ef;border-bottom:1px solid #eadbcb;font-size:11px;line-height:1.65}.ott-summary b{color:#28231f}.ott-context{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:12px 16px;background:#f7f4ef}.ott-context div{background:#fff;border:1px solid #ddd5ca;border-radius:8px;padding:10px}.ott-context small{display:block;font-size:9px;color:#7b7168;margin-bottom:4px}.ott-context b{font-size:12px}.ott-bars{padding:14px 16px;background:#fff}.ott-bar{display:grid;grid-template-columns:110px 1fr 48px;gap:9px;align-items:center;margin:8px 0;font-size:10px}.ott-bar-track{height:9px;border-radius:999px;background:#eee8df;overflow:hidden}.ott-bar-track i{display:block;height:100%;background:#4e6680;border-radius:999px}.ott-bar-value{text-align:right;font-weight:850}
.kobaco-readable-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;padding:14px;background:#f8f5ef}.kobaco-readable-metric{background:#fff;border:1px solid #ddd5ca;border-radius:9px;padding:12px}.kobaco-readable-metric small{display:block;font-size:9px;font-weight:850;color:#776d63;margin-bottom:6px}.kobaco-readable-metric strong{display:block;font-size:14px;line-height:1.4;margin-bottom:7px}.kobaco-readable-metric p{margin:0;font-size:10px;line-height:1.55;color:#70675f}
.topic-preview{height:82px;margin:-10px -10px 9px;border-radius:7px;padding:10px;display:flex;flex-direction:column;justify-content:flex-end;background:#33465b;color:#fff}.topic-preview.ott{background:#5a493d}.topic-preview b{font-size:10px!important;color:#fff!important;margin:0 0 3px!important}.topic-preview span{font-size:8px;color:#eee}
@media(max-width:650px){.compare-grid,.ott-context,.kobaco-readable-metrics{grid-template-columns:1fr}.ott-bar{grid-template-columns:85px 1fr 44px}}
'''
    page = page.replace("</style>", css + "\n</style>")

    script = f'''
<script>
const fixedTopicCases={topic_json};
const fixedSamples={{}};
function fixedShuffle(items){{const a=[...items];for(let i=a.length-1;i>0;i--){{const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]];}}return a;}}
function fixedSample(lessonId){{fixedSamples[lessonId]=fixedShuffle(fixedTopicCases[lessonId]||[]).slice(0,3);return fixedSamples[lessonId];}}
function fixedPreview(c){{const id=String(c.id||'');if(id.startsWith('kobaco_publicad_'))return `<div class="kobaco-picker-media"><img src="/api/kobaco-media-thumb/${{encodeURIComponent(c.id)}}" alt="공익광고 썸네일" loading="lazy"></div>`;if(id.startsWith('kobaco_aisac_'))return `<div class="topic-preview"><b>AI가 읽은 광고</b><span>원본·관련 맥락을 먼저 보고 AI 인식값과 비교합니다.</span></div>`;if(id.startsWith('kobaco_ott_'))return `<div class="topic-preview ott"><b>청소년·OTT 통계</b><span>13-19세 조사 조건과 이용률을 함께 읽습니다.</span></div>`;return '';}}
function fixedPickerHtml(lessonId,activeId=null){{const cases=fixedSamples[lessonId]||fixedSample(lessonId);const total=(fixedTopicCases[lessonId]||[]).length;return `<div class="chat-case-picker"><div class="chat-case-picker-head"><div><strong>사례를 골라보세요</strong><br><span>전체 ${{total}}개 중 3개를 보여줍니다.</span></div><button type="button" class="chat-case-shuffle" data-shuffle-cases>다른 사례 보기</button></div><div class="chat-case-options">${{cases.map((c,i)=>`<button type="button" class="chat-case-option ${{c.id===activeId?'active':''}}" data-case-id="${{c.id}}">${{fixedPreview(c)}}<b>${{i+1}}. ${{esc(compactTitle(c.title))}}</b><small>${{esc(c.label||'')}}</small></button>`).join('')}}</div></div>`;}}
function pickerHtml(lessonId,activeId=null){{return fixedPickerHtml(lessonId,activeId);}}
function bindCaseButtons(lessonId){{chat.querySelectorAll('[data-case-id]').forEach(btn=>btn.addEventListener('click',()=>startCase(lessonId,btn.dataset.caseId)));const shuffle=chat.querySelector('[data-shuffle-cases]');if(shuffle)shuffle.addEventListener('click',()=>{{if(sessionId&&inlineCaseId&&!confirm('다른 사례를 보면 현재 대화가 새로 시작됩니다. 바꿀까요?'))return;sessionId=null;inlineCaseId=null;resetInlineState();fixedSample(lessonId);chat.innerHTML=fixedPickerHtml(lessonId);bindCaseButtons(lessonId);input.disabled=true;send.disabled=true;finish.disabled=true;}});}}
function showCaseChooser(lessonId){{selectedLesson=lessonId;inlineLessonId=lessonId;inlineCaseId=null;sessionId=null;resetInlineState();fixedSample(lessonId);chat.innerHTML=fixedPickerHtml(lessonId);bindCaseButtons(lessonId);input.placeholder='위에서 사례를 먼저 선택해 주세요.';stageText.textContent='사례를 선택하세요';chat.scrollTop=0;}}
function fixedRows(c){{const out={{}};(c.data_rows||[]).forEach(r=>out[String(r.label||'').trim()]=String(r.value||'').trim());return out;}}
function fixedRawRows(c){{return (c.data_rows||[]).map(r=>`<div class="kobaco-data-row"><b>${{esc(r.label||'항목')}}</b><span>${{esc(r.value||'-')}}</span></div>`).join('');}}
function fixedDataMedia(c,kind,title,intro){{return `<div class="chat-case-media"><div class="kobaco-data-card"><div class="context-card"><b>${{esc(kind)}} · ${{esc(title)}}</b><p>${{esc(intro)}}</p></div><div class="kobaco-data-body"><div class="kobaco-data-table">${{fixedRawRows(c)}}</div></div></div></div>`;}}
function aisacSearchUrl(c){{return `https://aisac.kobaco.co.kr/site/main/advideo/list_all_top?kwdVal=${{encodeURIComponent(c.title||'')}}&listType=list&pageSize=12`;}}
function relatedSearchUrl(c){{return `https://search.naver.com/search.naver?where=nexearch&query=${{encodeURIComponent((c.title||'')+' 광고')}}`;}}
function aisacLearningCard(c){{const r=fixedRows(c);const related=c.context_url||relatedSearchUrl(c);const label=c.context_url?(c.context_label||'관련 보도 보기'):'관련 정보 검색';return `<div class="chat-case-media"><div class="kobaco-data-card"><div class="context-card"><b>먼저, 이 광고가 무엇인지 파악합니다.</b><p>${{esc(c.context_summary||c.title||'광고 맥락을 먼저 확인합니다.')}}</p><div class="context-actions"><a href="${{aisacSearchUrl(c)}}" target="_blank" rel="noopener">AiSAC 원본 광고 찾기 ↗</a><a class="alt" href="${{esc(related)}}" target="_blank" rel="noopener">${{esc(label)}} ↗</a></div></div><div class="compare-grid"><div class="compare-box"><small>사람이 먼저 확인할 내용</small><strong>장면·자막·내레이션·앞뒤 맥락</strong><p>관련 자료나 원본을 본 뒤 이 광고가 무엇을 보여주는지 내 말로 정리합니다.</p></div><div class="compare-box"><small>AiSAC이 인식한 내용</small><strong>${{esc(r['키워드']||'-')}}</strong><p>${{esc(r['인식 횟수']||'-')}} · AI가 화면에서 찾은 요소이며 광고의 전체 뜻은 아닙니다.</p></div></div><div class="kobaco-why"><b>비교할 때 참고</b>광고주 ${{esc(r['광고주']||'-')}} · 업종 ${{esc(r['업종']||'-')}}. 원본 맥락과 AI 인식값이 어디까지 겹치는지 확인합니다.</div><details class="kobaco-evidence"><summary>AiSAC 실제 데이터 항목 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-table">${{fixedRawRows(c)}}</div></div></details></div></div>`;}}
function ottPairs(v){{return String(v||'').split('·').map(x=>x.trim()).map(x=>{{const m=x.match(/^(.*?)\s+([0-9]+(?:\.[0-9]+)?)%$/);return m?{{name:m[1].trim(),value:Number(m[2])}}:null;}}).filter(Boolean);}}
function ottLearningCard(c){{const r=fixedRows(c);const group=r['연도·집단']||c.title||'-';const sample=r['사례수']||'-';const nonuse=r['OTT 비이용']||'-';const pairs=ottPairs(r['이용비율 상위']);const bars=pairs.map(p=>`<div class="ott-bar"><span>${{esc(p.name)}}</span><span class="ott-bar-track"><i style="width:${{Math.max(0,Math.min(100,p.value))}}%"></i></span><span class="ott-bar-value">${{p.value.toFixed(1)}}%</span></div>`).join('');return `<div class="chat-case-media"><div class="kobaco-data-card"><div class="ott-summary"><b>이 자료는 무엇인가요?</b><br>${{esc(group)}} 응답자의 OTT 서비스 이용 여부를 비교한 실제 KOBACO 통계입니다. '이용 비율'은 해당 서비스를 이용한 비율이지 가장 좋아하는 순위를 뜻하지 않습니다.</div><div class="ott-context"><div><small>조사 대상</small><b>${{esc(group)}}</b></div><div><small>사례수</small><b>${{esc(sample)}}</b></div><div><small>OTT 비이용</small><b>${{esc(nonuse)}}</b></div></div><div class="ott-bars"><b>서비스별 이용 비율 상위</b>${{bars}}</div><div class="ott-summary"><b>여기까지 말할 수 있어요:</b> 이 연도 13-19세 집단의 서비스별 이용 비율.<br><b>이 표만으로는 말할 수 없어요:</b> 선호도·만족도·다른 연령이나 전체 청소년의 성향.</div><details class="kobaco-evidence"><summary>실제 조사 데이터 항목 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-table">${{fixedRawRows(c)}}</div></div></details></div></div>`;}}
function publicAdCard(c){{const r=fixedRows(c);const metric=(label,value,meaning)=>`<div class="kobaco-readable-metric"><small>${{esc(label)}}</small><strong>${{esc(value||'-')}}</strong><p>${{esc(meaning)}}</p></div>`;return `<div class="chat-case-media"><div class="kobaco-data-card"><div class="kobaco-thumb-stage"><img src="/api/kobaco-media-thumb/${{encodeURIComponent(c.id)}}" alt="공익광고 썸네일" loading="eager"></div><div class="context-card"><b>광고를 먼저 보고 내 해석을 적어보세요.</b><p>첫 답변 뒤 실제 KOBACO 효과평가를 열어 내 해석과 조사 결과를 비교합니다.</p></div><div class="kobaco-after-answer" data-kobaco-after-answer><div class="kobaco-readable-metrics">${{metric('광고의 신뢰성을 평가한 항목',r['신뢰성'],'행동 변화 비율을 뜻하지 않습니다.')}}${{metric('광고를 접한 경로 중 가장 높은 항목',r['주요 인지경로'],'광고의 좋고 나쁨을 평가한 점수가 아닙니다.')}}${{metric('가장 강한 인상을 준 요소',r['임팩트 1위'],'광고 전체 효과를 하나의 숫자로 나타낸 값이 아닙니다.')}}</div><details class="kobaco-evidence" open><summary>실제 조사 원자료 항목 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-table">${{fixedRawRows(c)}}</div></div></details></div></div></div>`;}}
// 세 데이터 유형을 여기서 직접 렌더링해 재귀 호출을 완전히 끊습니다.
function caseMedia(c){{const id=String(c?.id||'');if(id.startsWith('kobaco_publicad_'))return publicAdCard(c);if(id.startsWith('kobaco_aisac_'))return aisacLearningCard(c);if(id.startsWith('kobaco_ott_'))return ottLearningCard(c);return fixedDataMedia(c,'KOBACO 실제 자료',c.title||'자료','자료가 직접 말하는 범위와 추가 해석을 구분합니다.');}}
const oldCards=[...document.querySelectorAll('.lesson-card')];oldCards.forEach(old=>{{const card=old.cloneNode(true);old.replaceWith(card);card.addEventListener('click',()=>{{selectedLesson=card.dataset.lesson;document.querySelectorAll('.lesson-card').forEach(x=>x.classList.toggle('selected',x===card));showCaseChooser(selectedLesson);}});}});
</script>
'''
    page = page.replace("</body>", script + "\n</body>")
    return page


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v10():
    return HTMLResponse(_render_index_kobaco_v10())
