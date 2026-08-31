from fastapi import HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
import json

import app as core

app = core.app

GENERAL_SKILLS = [
    "자료 탐색",
    "개념 설명",
    "비교·분석",
    "주장 구성",
    "근거 판단",
]

LITERACY_SKILLS = [
    "출처 신뢰도 판단",
    "사실·의견 구분",
    "근거 충분성 판단",
    "교차검증",
    "불확실성 확인",
]

ALL_SKILLS = GENERAL_SKILLS + LITERACY_SKILLS

TOPICS = {
    "허위정보·가짜뉴스": {
        "description": "제목만 믿지 않고 출처·원문·다른 보도를 비교해 판단합니다.",
        "starter": "가짜뉴스나 허위정보를 볼 때 무엇부터 확인해야 하는지 사례로 연습하고 싶어요.",
        "skills": ["출처 신뢰도 판단", "사실·의견 구분", "교차검증"],
    },
    "딥페이크·AI 생성 콘텐츠": {
        "description": "영상·이미지의 원본, 맥락, 게시 주체와 검증 단서를 살펴봅니다.",
        "starter": "딥페이크나 AI 생성 콘텐츠를 의심해야 하는 상황을 사례로 연습하고 싶어요.",
        "skills": ["출처 신뢰도 판단", "교차검증", "불확실성 확인"],
    },
    "출처와 정보 신뢰성": {
        "description": "누가, 언제, 어떤 근거로 만든 정보인지 확인하는 기준을 익힙니다.",
        "starter": "인터넷 정보의 출처가 믿을 만한지 판단하는 기준을 사례로 배우고 싶어요.",
        "skills": ["출처 신뢰도 판단", "근거 충분성 판단", "교차검증"],
    },
    "통계·그래프 읽기": {
        "description": "표본·분모·기간·축·상관관계를 확인해 수치를 과하게 해석하지 않습니다.",
        "starter": "통계나 그래프를 보고 잘못 판단하기 쉬운 사례를 하나씩 연습하고 싶어요.",
        "skills": ["근거 충분성 판단", "불확실성 확인", "교차검증"],
    },
    "AI 답변 검증": {
        "description": "AI가 제시한 주장·수치·출처를 그대로 믿지 않고 확인하는 방법을 연습합니다.",
        "starter": "생성형 AI 답변에서 어떤 내용을 다시 확인해야 하는지 실제 대화처럼 연습하고 싶어요.",
        "skills": ["출처 신뢰도 판단", "근거 충분성 판단", "교차검증", "불확실성 확인"],
    },
}


with core.connect_db() as c:
    c.execute(
        "CREATE TABLE IF NOT EXISTS session_topics("
        "session_id TEXT PRIMARY KEY, topic TEXT NOT NULL, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )


def _remove_route(path: str, method: str | None = None):
    kept = []
    for route in app.router.routes:
        if getattr(route, "path", None) != path:
            kept.append(route)
            continue
        methods = getattr(route, "methods", None) or set()
        if method is not None and method.upper() not in methods:
            kept.append(route)
    app.router.routes = kept


for _path, _method in [
    ("/", "GET"),
    ("/api/chat-stream", "POST"),
    ("/api/analyze", "POST"),
    ("/api/off-test", "POST"),
]:
    _remove_route(_path, _method)


class LiteracyChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    learning_topic: str | None = None


def _save_topic(session_id: str, topic: str):
    if topic not in TOPICS:
        return
    with core.connect_db() as c:
        c.execute(
            "INSERT INTO session_topics(session_id,topic) VALUES(?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET topic=excluded.topic",
            (session_id, topic),
        )


def _get_topic(session_id: str):
    with core.connect_db() as c:
        row = c.execute(
            "SELECT topic FROM session_topics WHERE session_id=?",
            (session_id,),
        ).fetchone()
    if row and row["topic"] in TOPICS:
        return row["topic"]
    return None


def _literacy_chat_prompt(session_id: str, user_message: str, topic: str):
    prior = core.messages(session_id, 10)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '튜터'}: {m['content']}"
        for m in prior
    )
    topic_info = TOPICS[topic]
    return f"""너는 중·고등학생을 위한 디지털 리터러시 학습 튜터다.
이번 학습 주제는 '{topic}'이다.
학습 목표는 다음과 같다: {topic_info['description']}

수업 방식:
1. 개념을 길게 강의하기보다 짧은 사례나 상황을 제시하고 학생에게 먼저 판단을 묻는다.
2. 학생이 답하면 왜 그렇게 판단했는지 이유를 확인하고, 빠진 기준을 설명한다.
3. 출처, 작성 주체, 작성 시점, 원문, 근거, 교차검증, 맥락, 불확실성 중 이번 사례에 필요한 기준을 실제로 적용하게 한다.
4. 정답을 바로 외우게 하지 말고 '무엇을 확인해야 하는가'와 '왜 그런가'를 학생이 자신의 말로 설명하도록 돕는다.
5. 실제 뉴스·통계·사건처럼 보이는 사례를 임의로 사실이라고 만들지 않는다. 사실 확인이 되지 않은 사례는 반드시 '가상 사례'라고 표시한다.
6. 학생이 특정 실제 정보의 사실 여부를 물었는데 현재 대화만으로 검증할 수 없다면, 사실이라고 단정하지 말고 확인해야 할 자료와 절차를 안내한다.
7. 학생의 장기적인 리터러시 수준이나 성향을 평가하지 않는다.
8. 답변은 한국어로 자연스럽고 짧게 쓰고, 한 번에 너무 많은 기준을 나열하지 않는다.

[이전 학습 대화]
{history or '(없음)'}

[학생의 새 요청]
{user_message}"""


@app.post("/api/chat-stream")
def literacy_chat_stream(req: LiteracyChatRequest):
    sid = req.session_id or str(core.uuid.uuid4())
    topic = req.learning_topic if req.learning_topic in TOPICS else _get_topic(sid)
    if topic not in TOPICS:
        raise HTTPException(400, "먼저 디지털 리터러시 학습 주제를 선택해 주세요.")

    _save_topic(sid, topic)
    prompt = _literacy_chat_prompt(sid, req.message, topic)

    def generate():
        reply_parts = []
        emitted = False
        gemini_error = None

        try:
            client = core.gemini_client()
            stream = client.models.generate_content_stream(
                model=core.gemini_model(),
                contents=prompt,
            )
            for chunk in stream:
                text = getattr(chunk, "text", None) or ""
                if text:
                    emitted = True
                    reply_parts.append(text)
                    yield text
            reply = "".join(reply_parts).strip()
            if not reply:
                raise ValueError("gemini_empty_response")
            core.save_chat_exchange(sid, req.message, reply)
            return
        except Exception as e:
            gemini_error = e
            if emitted:
                yield "\n\n응답 전송이 중단되었습니다. 같은 질문을 다시 보내주세요."
                return

        if core.groq_configured():
            try:
                client = core.groq_client()
                stream = client.chat.completions.create(
                    model=core.groq_model(),
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=700,
                    temperature=0.3,
                    stream=True,
                )
                reply_parts = []
                for chunk in stream:
                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    text = getattr(delta, "content", None) or ""
                    if text:
                        reply_parts.append(text)
                        yield text
                reply = "".join(reply_parts).strip()
                if not reply:
                    raise ValueError("groq_empty_response")
                core.save_chat_exchange(sid, req.message, reply)
                return
            except Exception as groq_error:
                core.logger.warning(
                    "Groq literacy stream fallback failed: %s",
                    type(groq_error).__name__,
                )
                yield f"Gemini 오류 후 Groq 보조 응답도 실패했습니다: {type(groq_error).__name__}"
                return

        code = core.error_code(gemini_error)
        suffix = f" ({code})" if code else ""
        yield f"Gemini 응답 오류: {type(gemini_error).__name__}{suffix}"

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Session-Id": sid,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _topic_cards_html():
    cards = []
    for name, info in TOPICS.items():
        cards.append(
            f'<button class="topic-card" type="button" data-topic="{name}" '
            f'data-starter="{info["starter"]}">'
            f'<strong>{name}</strong><span>{info["description"]}</span></button>'
        )
    return "".join(cards)


def _render_literacy_index():
    html = (core.BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

    replacements = {
        "<title>AI OFF</title>": "<title>AI OFF | 디지털 리터러시 학습</title>",
        '<div class="hero-kicker">AI와 공부한 뒤</div>': '<div class="hero-kicker">디지털 리터러시 × AI OFF</div>',
        '<h1>AI에게 물어본 내용,<br>이번엔 내가 직접 해봅니다.</h1>': '<h1>AI와 판단 기준을 배우고,<br>마지막에는 내가 직접 확인합니다.</h1>',
        '<p>공부할 내용을 AI와 이야기해 보세요. 대화를 마치면 방금 대화에서 AI 도움을 많이 받은 부분을 골라, 직접 풀어볼 문제 3개가 나옵니다.</p>': '<p>허위정보, 딥페이크, 출처, 통계, AI 답변 검증 중 하나를 골라 사례로 연습합니다. AI와 판단 기준을 익힌 뒤 AI OFF로 전환하면, 방금 배운 기준을 내가 직접 적용하는 문제 3개가 생성됩니다.</p>',
        '<div class="hero-note"><strong>문제는 언제 나오나요?</strong><span>공부를 마친 뒤 <b>‘대화 마치고 문제 만들기’</b>를 누르면 됩니다. 방금 나눈 대화를 바탕으로 문제 3개가 바로 나옵니다.</span></div>': '<div class="hero-note"><strong>AI OFF는 무엇을 하나요?</strong><span>정해진 퀴즈를 반복하지 않습니다. <b>방금 학생이 AI와 학습한 대화</b>에서 어떤 판단을 AI가 도왔는지 찾고, 같은 맥락에서 학생이 직접 출처·근거·불확실성을 판단하게 합니다.</span></div>',
        '<div class="process-item active" id="process1"><div class="process-dot">1</div><strong>AI와 공부하기</strong><span>질문하고 설명을 듣습니다.</span></div>': '<div class="process-item active" id="process1"><div class="process-dot">1</div><strong>주제 선택·사례 학습</strong><span>AI와 판단 기준을 연습합니다.</span></div>',
        '<div class="process-item" id="process2"><div class="process-dot">2</div><strong>대화 마치기</strong><span>공부한 내용을 정리합니다.</span></div>': '<div class="process-item" id="process2"><div class="process-dot">2</div><strong>대화 분석</strong><span>AI가 도운 사고와 판단을 찾습니다.</span></div>',
        '<div class="process-item off" id="process3"><div class="process-dot">3</div><strong>직접 풀어보기</strong><span>AI 없이 문제 3개를 풉니다.</span></div>': '<div class="process-item off" id="process3"><div class="process-dot">3</div><strong>AI OFF 직접 판단</strong><span>배운 기준을 스스로 적용합니다.</span></div>',
        '<div class="process-item" id="process4"><div class="process-dot">4</div><strong>결과 확인하기</strong><span>AI 도움과 내 답변을 함께 봅니다.</span></div>': '<div class="process-item" id="process4"><div class="process-dot">4</div><strong>피드백·재도전</strong><span>놓친 기준을 확인하고 다시 답합니다.</span></div>',
        '<div><h2>학습 대화</h2><p>궁금한 내용을 자유롭게 물어보세요. 공부가 끝나면 아래 버튼을 눌러 다음 단계로 넘어갑니다.</p></div>': '<div><h2>리터러시 사례 학습</h2><p id="topicLine">위에서 주제를 고르면 AI와 사례를 보며 판단 기준을 연습할 수 있습니다.</p></div>',
        '<div class="guide-strip"><strong>지금은 AI와 함께 공부하는 단계입니다.</strong> 공부가 끝나면 아래 버튼을 눌러주세요. 그다음부터는 AI 없이 문제를 풀게 됩니다.</div>': '<div class="guide-strip"><strong>정답부터 외우지 않습니다.</strong> 사례를 보고 먼저 판단한 뒤, 출처·근거·원문·다른 자료와의 비교처럼 필요한 확인 기준을 AI와 함께 익힙니다. 이름·연락처 등 불필요한 개인정보는 입력하지 마세요.</div>',
        '<textarea id="input" placeholder="예: 목성 안에서는 수소가 어떻게 변해?"></textarea>': '<textarea id="input" placeholder="먼저 위에서 학습 주제를 선택해 주세요."></textarea>',
        '<div class="finish-copy"><strong>충분히 공부했나요?</strong><span>버튼을 누르면 방금 대화에서 직접 확인해볼 문제 3개가 나옵니다.</span></div>': '<div class="finish-copy"><strong>판단 기준을 충분히 연습했나요?</strong><span>이제 AI OFF로 전환해 방금 배운 기준을 직접 적용해봅니다.</span></div>',
        '<div class="side-top"><div class="side-kicker" id="stageStep">1 / 4</div><div class="side-stage" id="stageText">AI와 공부 중</div></div>': '<div class="side-top"><div class="side-kicker" id="stageStep">1 / 4</div><div class="side-stage" id="stageText">학습 주제를 선택하세요</div></div>',
        '<div class="side-help"><b>AI에 맡긴 정도</b>는 이 대화에서 해당 사고를 AI가 얼마나 대신했는지를 뜻합니다. <b>0</b>은 거의 직접 한 경우, <b>100</b>은 대부분 AI 도움을 받은 경우입니다.</div>': '<div class="side-help"><b>대화 분석</b>은 이번 학습에서 AI가 설명·비교·근거 판단을 얼마나 도왔는지와, 출처·교차검증·불확실성 판단을 학생이 직접 했는지를 함께 살펴봅니다.</div>',
        '<div class="skills-title">AI 도움을 받은 부분</div>': '<div class="skills-title">이번 대화 분석 결과</div>',
        '<div id="skills"><div class="empty-side">대화를 마치면 사고 기능별로 얼마나 AI 도움을 받았는지 여기에 표시됩니다.</div></div>': '<div id="skills"><div class="empty-side">AI OFF로 전환하면 사고 위임과 디지털 리터러시 판단 항목이 나뉘어 표시됩니다.</div></div>',
        '<div><div class="section-eyebrow">AI OFF</div><h2>이제 혼자 풀어볼 차례예요.</h2><p>방금 공부한 내용에서 문제 3개가 나왔습니다. AI 채팅은 잠시 꺼두고 직접 답해보세요.</p></div>': '<div><div class="section-eyebrow">AI OFF</div><h2>이번에는 내가 직접 판단합니다.</h2><p>방금 AI와 연습한 사례와 판단 기준을 바탕으로 문제 3개가 나왔습니다. AI 채팅은 잠시 꺼두고 직접 답해보세요.</p></div>',
        '<div class="off-notice"><b>완벽하게 쓰려고 하지 않아도 괜찮아요.</b> 내가 이해한 내용을 내 말로 설명해 보는 것이 중요합니다.</div>': '<div class="off-notice"><b>진짜/가짜만 맞히는 시험이 아닙니다.</b> 무엇을 확인했고 왜 그렇게 판단했는지를 자신의 말로 설명하는 것이 중요합니다.</div>',
        '<div><div class="section-eyebrow">이번 학습 결과</div><h2>AI 도움을 받은 부분과 직접 해낸 결과를 같이 봅니다.</h2><p>두 숫자는 뜻이 다릅니다. 아래 설명을 보고 이번 학습을 확인해 보세요.</p></div>': '<div><div class="section-eyebrow">이번 리터러시 학습 돌아보기</div><h2>AI가 도운 판단과 내가 직접 적용한 결과를 같이 봅니다.</h2><p>이번 대화에서 어떤 기준을 AI에게 맡겼고, AI OFF에서 무엇을 직접 확인했는지 살펴봅니다.</p></div>',
        '<div class="guide-item"><strong>AI에 맡긴 정도</strong>AI와 대화할 때 해당 사고를 AI가 대신한 정도입니다. <b>0에 가까우면 직접 한 부분이 많고, 100에 가까우면 AI가 대신한 부분이 많습니다.</b></div>': '<div class="guide-item"><strong>AI가 도운 정도</strong>이번 학습 대화에서 설명·비교·정보 판단을 AI가 대신하거나 크게 도운 정도입니다. 이 값은 학생의 장기 능력을 뜻하지 않습니다.</div>',
        '<div class="guide-item green"><strong>혼자 수행한 결과</strong>AI 없이 문제에 답한 결과입니다. <b>100에 가까울수록 이번 문제에서 요구한 내용을 잘 해냈다는 뜻입니다.</b></div>': '<div class="guide-item green"><strong>직접 적용한 결과</strong>AI 없이 출처·근거·교차검증·불확실성 등의 기준을 직접 적용해 답한 결과입니다.</div>',
        '이 결과는 이번 학습에서의 수행만 보여줍니다. 학생의 장기적인 능력이나 성향을 판단하는 점수가 아닙니다.': '이 결과는 이번 학습 대화와 AI OFF 답변에서 확인된 수행만 보여줍니다. 학생의 장기적인 디지털 리터러시 능력이나 성향을 단정하는 점수가 아닙니다.',
        '답을 고쳐서 다시 채점하거나, 다른 주제로 새 학습을 시작할 수 있습니다.': '피드백을 보고 답을 고쳐 다시 확인하거나, 다른 리터러시 주제로 새 학습을 시작할 수 있습니다.',
        '혼자 수행한 결과': '직접 적용한 결과',
    }

    for old, new in replacements.items():
        html = html.replace(old, new)

    extra_css = """
.topic-panel{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:22px 24px;margin:0 0 28px}
.topic-panel-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;margin-bottom:15px}.topic-panel-head h2{margin:0;font-size:20px}.topic-panel-head p{margin:5px 0 0;color:var(--body);font-size:12px;line-height:1.55}.topic-hint{font-size:11px;color:var(--muted);white-space:nowrap}
.topic-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:9px}.topic-card{text-align:left;border:1px solid var(--line);background:#fff;border-radius:9px;padding:13px 12px;min-height:104px;color:var(--ink)}.topic-card:hover{border-color:#a9bce8}.topic-card.selected{border-color:var(--blue);background:var(--blue-soft);box-shadow:0 0 0 1px var(--blue) inset}.topic-card strong{display:block;font-size:13px;line-height:1.35;margin-bottom:6px}.topic-card span{display:block;font-size:11px;line-height:1.45;color:var(--body)}
.topic-choice{margin-top:12px;padding-top:11px;border-top:1px solid var(--line);font-size:12px;line-height:1.55;color:var(--body)}.topic-choice b{color:var(--blue)}
.scope-note{display:flex;gap:18px;flex-wrap:wrap;margin-top:11px;font-size:11px;color:var(--muted)}.scope-note strong{color:var(--body)}
.skill-group{margin-top:12px;padding-top:10px;border-top:1px solid var(--line)}.skill-group:first-child{margin-top:2px;padding-top:0;border-top:0}.skill-group-label{font-size:10px;font-weight:900;letter-spacing:.2px;color:var(--muted);margin-bottom:2px}.skill-group-label.literacy{color:var(--orange)}
.q-literacy{font-size:10px;font-weight:850;color:#a84a29;background:var(--orange-soft);border-radius:999px;padding:3px 7px}.q-direct{font-size:10px;font-weight:850;color:#2d5da9;background:var(--blue-soft);border-radius:999px;padding:3px 7px}
@media(max-width:1000px){.topic-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:650px){.topic-panel{padding:18px}.topic-panel-head{align-items:flex-start;flex-direction:column;gap:5px}.topic-grid{grid-template-columns:1fr}.topic-card{min-height:auto}.topic-hint{white-space:normal}}
"""
    html = html.replace("</style>", extra_css + "\n</style>")

    topic_panel = f"""
  <section id="literacyTopics" class="topic-panel">
    <div class="topic-panel-head">
      <div><h2>무엇을 연습할까요?</h2><p>한 가지 주제를 고르면 AI가 짧은 사례를 중심으로 판단 기준을 함께 연습합니다.</p></div>
      <div class="topic-hint">주제는 새 학습을 시작하면 다시 고를 수 있습니다.</div>
    </div>
    <div class="topic-grid">{_topic_cards_html()}</div>
    <div id="topicChoice" class="topic-choice">아직 선택한 주제가 없습니다.</div>
    <div class="scope-note"><span><strong>간단 개요</strong> · 사례 학습 → 대화 분석 → AI OFF 직접 판단 → 피드백</span><span><strong>사용 데이터</strong> · 현재 학습 대화, AI 응답, 학생 답변, 재채점 이력</span></div>
  </section>
"""
    html = html.replace(
        '  <section class="process" aria-label="이용 순서">',
        topic_panel + '\n  <section class="process" aria-label="이용 순서">',
    )

    html = html.replace(
        "let sessionId=null,questions=[],delegationMap={},aiOffStarted=false,requestInFlight=false,hasResult=false;",
        "let sessionId=null,questions=[],delegationMap={},aiOffStarted=false,requestInFlight=false,hasResult=false,literacyTopic=null;\n"
        "const literacySkillNames=['출처 신뢰도 판단','사실·의견 구분','근거 충분성 판단','교차검증','불확실성 확인'];",
    )

    hook = "const processItems=[1,2,3,4].map(i=>document.getElementById(`process${i}`));"
    hook_add = """
const processItems=[1,2,3,4].map(i=>document.getElementById(`process${i}`));
document.querySelectorAll('.topic-card').forEach(card=>card.addEventListener('click',()=>{
  if(sessionId){if(!confirm('이미 시작한 대화가 있습니다. 주제를 바꾸려면 새 학습으로 시작할까요?'))return;location.reload();return;}
  literacyTopic=card.dataset.topic;
  document.querySelectorAll('.topic-card').forEach(x=>x.classList.toggle('selected',x===card));
  document.getElementById('topicChoice').innerHTML=`선택한 주제 · <b>${esc(literacyTopic)}</b> — 아래 시작 문장을 그대로 보내거나, 궁금한 점을 직접 적어도 됩니다.`;
  document.getElementById('topicLine').textContent=`${literacyTopic} 사례를 보며 무엇을 확인해야 하는지 AI와 연습합니다.`;
  input.value=card.dataset.starter||'';
  input.placeholder='이 주제에서 궁금한 점을 적어보세요.';
  stageText.textContent='AI와 사례 학습 중';
  input.focus();
}));
"""
    html = html.replace(hook, hook_add)

    old_send = """send.onclick=async()=>{
  if(aiOffStarted||requestInFlight)return;const text=input.value.trim();if(!text)return;
  requestInFlight=true;const st=document.getElementById('chatStatus');clearError(st);addMsg('user',text);input.value='';send.disabled=true;finish.disabled=true;st.textContent='답변을 준비하고 있어요...';"""
    new_send = """send.onclick=async()=>{
  if(aiOffStarted||requestInFlight)return;const st=document.getElementById('chatStatus');clearError(st);if(!literacyTopic){setError(st,'먼저 위에서 디지털 리터러시 학습 주제를 선택해 주세요.');document.getElementById('literacyTopics').scrollIntoView({behavior:'smooth'});return;}const text=input.value.trim();if(!text)return;
  requestInFlight=true;addMsg('user',text);input.value='';send.disabled=true;finish.disabled=true;st.textContent='사례와 판단 기준을 준비하고 있어요...';"""
    html = html.replace(old_send, new_send)
    html = html.replace(
        "body:JSON.stringify({session_id:sessionId,message:text})",
        "body:JSON.stringify({session_id:sessionId,message:text,learning_topic:literacyTopic})",
    )

    old_render = """delegationMap=Object.fromEntries(a.scores.map(x=>[x.skill,x.delegation]));document.getElementById('skills').innerHTML=a.scores.map(x=>`<div class=\"skill\"><div class=\"skill-head\"><span>${esc(x.skill)}</span><strong>${x.delegation}</strong></div><div class=\"bar\"><div class=\"fill\" style=\"width:${x.delegation}%\"></div></div><div class=\"evidence\">${(x.evidence||[]).map(v=>'• '+esc(v)).join('<br>')}</div></div>`).join('');document.getElementById('analysisSummary').textContent=a.summary;"""
    new_render = """delegationMap=Object.fromEntries(a.scores.map(x=>[x.skill,x.delegation]));const thoughtScores=a.scores.filter(x=>!literacySkillNames.includes(x.skill));const literacyScores=a.scores.filter(x=>literacySkillNames.includes(x.skill));const skillHtml=x=>`<div class=\"skill\"><div class=\"skill-head\"><span>${esc(x.skill)}</span><strong>${x.delegation}</strong></div><div class=\"bar\"><div class=\"fill\" style=\"width:${x.delegation}%\"></div></div><div class=\"evidence\">${(x.evidence||[]).map(v=>'• '+esc(v)).join('<br>')}</div></div>`;document.getElementById('skills').innerHTML=`<div class=\"skill-group\"><div class=\"skill-group-label\">AI가 도운 사고</div>${thoughtScores.map(skillHtml).join('')}</div><div class=\"skill-group\"><div class=\"skill-group-label literacy\">디지털 리터러시 판단</div>${literacyScores.map(skillHtml).join('')}</div>`;document.getElementById('analysisSummary').textContent=a.summary;"""
    html = html.replace(old_render, new_render)

    old_question = """<div class=\"question\"><div class=\"q-top\"><span class=\"q-no\">문제 ${i+1}</span><span class=\"q-skill\">${esc(q.skill)}</span></div><p class=\"q-text\">${esc(q.question)}</p>"""
    new_question = """<div class=\"question\"><div class=\"q-top\"><span class=\"q-no\">문제 ${i+1}</span><span class=\"q-skill\">${esc(q.skill)}</span><span class=\"${literacySkillNames.includes(q.skill)?'q-literacy':'q-direct'}\">${literacySkillNames.includes(q.skill)?'리터러시 판단':'직접 수행'}</span></div><p class=\"q-text\">${esc(q.question)}</p>"""
    html = html.replace(old_question, new_question)

    return html


@app.get("/", response_class=HTMLResponse)
def literacy_index():
    return HTMLResponse(_render_literacy_index())


@app.post("/api/analyze")
def analyze_literacy(req: core.SessionRequest):
    tx = core.transcript(req.session_id)
    if not tx.strip():
        raise HTTPException(400, "분석할 학습 대화가 없습니다.")

    topic = _get_topic(req.session_id) or "디지털 리터러시"
    skill_list = ", ".join(ALL_SKILLS)
    prompt = f"""다음은 학생과 AI 튜터가 '{topic}' 주제로 진행한 실제 학습 대화다.

{tx}

이 대화에서 학생이 AI에게 맡긴 사고와 정보 판단을 분석하라.
반드시 다음 10개 항목을 모두 평가한다.
{skill_list}

delegation은 0~100으로 기록한다.
- 자료 탐색, 개념 설명, 비교·분석, 주장 구성, 근거 판단: AI가 해당 사고를 대신 수행한 정도다.
- 출처 신뢰도 판단, 사실·의견 구분, 근거 충분성 판단, 교차검증, 불확실성 확인: 학생이 해당 판단을 직접 수행하지 않고 AI의 판단이나 설명에 맡긴 정도다.
- 대화에서 해당 판단이 필요하지 않았거나 판단 근거가 없으면 0으로 둔다.
- 단순히 AI를 사용했다는 이유로 높은 점수를 주지 않는다.
- 학생이 스스로 출처를 요구하거나 원문·다른 근거를 비교·검증한 흔적이 있으면 관련 위임 정도를 낮게 본다.

evidence는 실제 대화에서 확인되는 짧은 근거를 최대 2개만 적는다.
top_skills에는 delegation이 0보다 큰 항목 중 최대 5개를 높은 순서대로 넣는다.
summary는 'AI가 도운 사고'와 '학생이 직접 다시 적용해볼 리터러시 기준'을 구분해 2~4문장으로 작성한다.
학생의 장기 능력, 성향, 전체 디지털 리터러시 수준을 단정하지 않는다.
대화에 없는 출처나 사실을 새로 만들어 평가 근거로 쓰지 않는다."""

    try:
        result, _ = core.generate_structured_with_fallback(
            prompt,
            core.AnalysisResult,
            max_output_tokens=1200,
        )
    except Exception as e:
        core.logger.exception("Literacy conversation analysis failed")
        raise HTTPException(502, f"대화 분석 오류: {type(e).__name__}")

    data = result.model_dump()
    by_name = {x["skill"]: x for x in data.get("scores", [])}
    normalized = []
    for skill in ALL_SKILLS:
        item = by_name.get(skill)
        if item is None:
            item = {
                "skill": skill,
                "delegation": 0,
                "evidence": [],
                "rationale": "대화에서 확인할 근거가 부족합니다.",
            }
        normalized.append(item)

    data["scores"] = normalized
    ranked = sorted(normalized, key=lambda x: x["delegation"], reverse=True)
    data["top_skills"] = [x["skill"] for x in ranked if x["delegation"] > 0][:5]

    with core.connect_db() as c:
        c.execute(
            "INSERT INTO analyses(session_id,result_json) VALUES(?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET result_json=excluded.result_json, created_at=CURRENT_TIMESTAMP",
            (req.session_id, json.dumps(data, ensure_ascii=False)),
        )
    return data


@app.post("/api/off-test")
def off_test_literacy(req: core.SessionRequest):
    tx = core.transcript(req.session_id)
    requests = core.student_requests(req.session_id)
    topic = _get_topic(req.session_id) or "AI 답변 검증"
    topic_info = TOPICS.get(topic, TOPICS["AI 답변 검증"])

    with core.connect_db() as c:
        row = c.execute(
            "SELECT result_json FROM analyses WHERE session_id=?",
            (req.session_id,),
        ).fetchone()

    analysis = json.loads(row["result_json"]) if row else analyze_literacy(req)
    ranked = sorted(analysis["scores"], key=lambda x: x["delegation"], reverse=True)
    meaningful_general = [x for x in ranked if x["skill"] in GENERAL_SKILLS and x["delegation"] > 0]
    relevant_literacy = topic_info["skills"]

    request_list = "\n".join(f"- {text}" for text in requests)
    general_text = ", ".join(x["skill"] for x in meaningful_general[:3]) or "개념 설명, 근거 판단"
    literacy_text = ", ".join(relevant_literacy)
    allowed_skills = list(dict.fromkeys([x["skill"] for x in meaningful_general[:3]] + relevant_literacy))

    prompt = f"""다음은 학생이 '{topic}' 주제로 진행한 디지털 리터러시 학습 세션이다.

[학생이 실제로 요청한 내용]
{request_list}

[전체 대화]
{tx}

[AI가 많이 도운 일반 사고]
{general_text}

[이번 주제에서 직접 적용할 리터러시 기준]
{literacy_text}

학생이 AI 없이 직접 판단해보는 AI OFF 문제를 정확히 3개 생성하라.

이번 서비스의 구조:
- AI와 사례를 보며 디지털 리터러시 판단 기준을 먼저 연습했다.
- AI OFF에서는 정답을 기억했는지가 아니라, 같은 기준을 학생이 새로운 질문이나 대화 맥락에 직접 적용할 수 있는지 확인한다.

문제 구성:
1. 1문제는 학생이 AI 도움 없이 핵심 개념·판단 이유를 자신의 말로 설명하거나 직접 수행하게 한다.
2. 2문제는 '{topic}'에서 중요한 디지털 리터러시 기준을 직접 적용하게 한다.
3. 리터러시 문제는 단순 '진짜/가짜' 선택으로 끝내지 말고, 무엇을 확인할지와 판단 이유를 함께 묻는다.
4. 학생이 대화에서 이미 잘 수행한 기준도 '학습한 기준을 다시 적용하는 확인 문제'로 출제할 수 있다. 이 경우 약점이라고 표현하지 않는다.
5. 실제 출처·기사·통계가 대화에 없으면 임의의 실제 사례를 사실처럼 만들지 않는다. 필요하면 '가상 사례'라고 분명히 표시한다.
6. 실제 외부 검색이 필요한 문제는 검색 결과 자체를 요구하기보다, 어떤 자료·원문·기준을 확인해야 하는지 판단하게 한다.

skill 규칙:
- skill은 다음 중 하나만 사용한다: {', '.join(allowed_skills)}
- 일반 사고 문제는 가능한 경우 위임 정도가 큰 기능을 사용한다.
- 리터러시 문제는 '{topic}'에 연결되는 기준을 우선한다.

작성 규칙:
- 방금 대화의 실제 학습 내용과 연결한다.
- 각 문제는 2~5분 안에 답할 수 있게 짧고 분명하게 쓴다.
- 정답이나 모범답안을 질문에 포함하지 않는다.
- evaluation_criteria는 핵심 판단 기준 2~4개를 적는다.
- why_this_question에는 'AI가 대신했다'고 근거 없이 단정하지 말고, 이번 학습에서 어떤 기준을 직접 적용해보는 문제인지 설명한다."""

    try:
        result, _ = core.generate_structured_with_fallback(
            prompt,
            core.OffTestResult,
            max_output_tokens=1500,
        )
        if len(result.questions) < 3:
            raise ValueError("off_test_question_count")
    except Exception as e:
        core.logger.exception("AI OFF literacy question generation failed")
        raise HTTPException(502, f"AI OFF 문제 생성 오류: {type(e).__name__}")

    out = []
    with core.connect_db() as c:
        c.execute("DELETE FROM off_questions WHERE session_id=?", (req.session_id,))
        c.execute("DELETE FROM off_results WHERE session_id=?", (req.session_id,))
        for q in result.questions[:3]:
            cur = c.execute(
                "INSERT INTO off_questions(session_id,skill,question,why_this_question,criteria_json) VALUES(?,?,?,?,?)",
                (
                    req.session_id,
                    q.skill,
                    q.question,
                    q.why_this_question,
                    json.dumps(q.evaluation_criteria, ensure_ascii=False),
                ),
            )
            out.append({"question_id": cur.lastrowid, **q.model_dump()})
    return {"questions": out}
