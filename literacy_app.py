from fastapi import HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
import html as html_lib
import json

import app as core

app = core.app

GENERAL_SKILLS = [
    "자료 탐색",
    "주장 구성",
    "근거 판단",
    "반론 구성",
    "정보 검증",
]

LESSONS = {
    "news": {
        "title": "뉴스·허위정보 판단",
        "short": "제목만 믿지 않고 출처·원문·근거를 확인하고 다른 자료와 비교합니다.",
        "source_name": "한국언론진흥재단 2023년 미디어교육 운영학교 자료",
        "source_url": "https://www.meca.or.kr/api/common/upload/download?attachFilePath=%2Ffile%2Fpbanc%2FPBANC_230502110207120.pdf",
        "source_role": "학습 주제 참고",
        "source_note": "공식 교육자료에 ‘뉴스, 제목만 보니?’, ‘허위정보(가짜뉴스)가 우리를 혼란하게 해요’ 등의 뉴스·미디어 리터러시 수업 주제가 포함되어 있습니다.",
        "criteria": [
            "제목만으로 결론 내리지 않고 본문과 원문을 확인한다.",
            "작성 주체·게시 시점·출처가 무엇인지 확인한다.",
            "사실 주장과 의견·해석을 구분한다.",
            "독립된 다른 자료나 1차 자료와 교차검증한다.",
            "확인할 근거가 부족하면 판단을 유보한다.",
        ],
        "skills": ["출처 신뢰도 판단", "사실·의견 구분", "교차검증"],
        "starter": "[가상 사례] SNS 카드뉴스에 ‘다음 달부터 모든 중학생의 스마트폰 사용이 법으로 하루 2시간 제한된다’는 문구가 올라왔습니다. 이 내용을 바로 믿거나 공유하기 전에 무엇부터 확인해야 할까요?",
        "safety_note": "",
    },
    "deepfake": {
        "title": "딥페이크·합성콘텐츠",
        "short": "영상만 보고 단정하지 않고 게시 주체·원본 맥락·공식 자료를 확인합니다.",
        "source_name": "교육부 ‘딥페이크 등 디지털 성폭력 예방 교수학습자료(초중고용)’",
        "source_url": "https://www.moe.go.kr/boardCnts/viewRenew.do?boardID=316&boardSeq=101892&lev=0&m=0302&opType=N&page=1&s=moe",
        "source_role": "공식 교수학습자료",
        "source_note": "교육부가 학교 현장의 딥페이크 등 디지털 성폭력 예방교육에 활용하도록 공개한 초·중·고용 교수학습자료입니다.",
        "criteria": [
            "영상·이미지를 올린 계정과 최초 게시 출처를 확인한다.",
            "원본 영상·사진과 전체 맥락이 있는지 확인한다.",
            "공식 채널이나 독립된 신뢰할 만한 자료와 비교한다.",
            "시각적 어색함 하나만으로 진짜·가짜를 확정하지 않는다.",
            "확인 전에는 재공유·확산을 보류한다.",
        ],
        "skills": ["출처 신뢰도 판단", "교차검증", "불확실성 확인"],
        "starter": "[가상 사례] 학교 공식 계정과 이름이 비슷한 새 계정이 교장 선생님이 평소와 전혀 다른 발언을 하는 짧은 영상을 올렸습니다. 이 영상이 진짜인지 판단하려면 어떤 순서로 확인하는 것이 좋을까요?",
        "safety_note": "학습에서는 합성 여부와 출처 확인 같은 일반적인 판단 기준만 다룹니다. 성적·폭력적 이미지나 영상을 분석 대상으로 제시하지 않습니다.",
    },
    "ai": {
        "title": "AI 답변 검증",
        "short": "AI가 제시한 수치·출처·주장을 그대로 믿지 않고 원자료와 조건을 확인합니다.",
        "source_name": "NIA ‘2025 디지털정보격차 실태조사 보고서’",
        "source_url": "https://www.nia.or.kr/site/nia_kor/ex/bbs/View.do?bcIdx=29168&cbIdx=81623&parentSeq=29168",
        "source_role": "문제 배경 참고",
        "source_note": "NIA 공식 보고서는 디지털정보화 수준을 조사하고 부록에 인공지능(AI) 서비스 관련 항목을 별도로 수록하고 있습니다. 이 보고서의 특정 수치를 AI OFF 정답으로 사용하지는 않습니다.",
        "criteria": [
            "AI 답변에서 검증 가능한 사실 주장·수치·출처를 먼저 구분한다.",
            "AI가 제시한 출처가 실제 존재하고 해당 주장을 뒷받침하는지 확인한다.",
            "가능하면 기관 원문·연구 원문 등 1차 자료를 우선 확인한다.",
            "독립된 다른 자료와 비교해 같은 결론인지 살펴본다.",
            "조사 시점·표본·조건·불확실성을 확인한 뒤 판단한다.",
        ],
        "skills": ["출처 신뢰도 판단", "근거 충분성 판단", "불확실성 확인"],
        "starter": "[가상 AI 답변] ‘한국 청소년의 82%가 매일 생성형 AI를 이용합니다. 2025년 정부 조사 결과입니다.’라는 답을 받았습니다. 이 문장을 사실로 받아들이기 전에 어떤 내용을 확인해야 할까요?",
        "safety_note": "",
    },
}

with core.connect_db() as c:
    c.execute(
        "CREATE TABLE IF NOT EXISTS session_lessons("
        "session_id TEXT PRIMARY KEY, lesson_id TEXT NOT NULL, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )


class LiteracyChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    lesson_id: str | None = None


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
    ("/api/off-submit", "POST"),
]:
    _remove_route(_path, _method)


def _save_lesson(session_id: str, lesson_id: str):
    if lesson_id not in LESSONS:
        return
    with core.connect_db() as c:
        c.execute(
            "INSERT INTO session_lessons(session_id,lesson_id) VALUES(?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET lesson_id=excluded.lesson_id",
            (session_id, lesson_id),
        )


def _get_lesson_id(session_id: str):
    with core.connect_db() as c:
        row = c.execute(
            "SELECT lesson_id FROM session_lessons WHERE session_id=?",
            (session_id,),
        ).fetchone()
    if row and row["lesson_id"] in LESSONS:
        return row["lesson_id"]
    return None


def _lesson_chat_prompt(session_id: str, user_message: str, lesson_id: str):
    lesson = LESSONS[lesson_id]
    prior = core.messages(session_id, 10)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '튜터'}: {m['content']}"
        for m in prior
    )
    criteria = "\n".join(f"- {x}" for x in lesson["criteria"])
    safety = f"\n추가 안전 기준:\n- {lesson['safety_note']}" if lesson["safety_note"] else ""

    return f"""너는 중·고등학생을 위한 디지털 리터러시 학습 튜터다.
이번 학습 주제는 '{lesson['title']}'이다.

[공식 자료 참고]
자료명: {lesson['source_name']}
자료 역할: {lesson['source_role']}
확인한 내용: {lesson['source_note']}

[이번 수업에서 사용할 큐레이션 판단 기준]
{criteria}

수업 원칙:
1. 위 판단 기준은 예선 프로토타입에서 팀이 공식 원문을 확인해 정리한 정적 학습 기준이다.
2. 실시간 외부 검색이나 RAG를 한 것처럼 말하지 않는다.
3. 짧은 사례를 하나씩 다루고 학생에게 먼저 '무엇을 확인할지'와 '왜 그런지' 묻는다.
4. 학생이 답하면 잘 적용한 기준과 빠진 기준을 구분해 설명한다.
5. 진짜/가짜를 찍게 하는 데서 끝내지 않고 출처·원문·근거·교차검증·불확실성을 실제로 적용하게 한다.
6. 실제 기사·통계·사건처럼 보이는 내용을 임의로 사실이라고 만들지 않는다. 새 사례를 만들면 반드시 '[가상 사례]'라고 표시한다.
7. 특정 실제 정보의 사실 여부가 제공된 자료만으로 확인되지 않으면 맞다/틀리다 단정하지 말고 확인 절차를 안내한다.
8. 학생의 장기적인 디지털 리터러시 수준이나 성향을 평가하지 않는다.
9. 답변은 한국어로 자연스럽고 간결하게 작성한다.{safety}

[이전 학습 대화]
{history or '(없음)'}

[학생의 새 요청]
{user_message}"""


@app.post("/api/chat-stream")
def literacy_chat_stream(req: LiteracyChatRequest):
    sid = req.session_id or str(core.uuid.uuid4())
    lesson_id = req.lesson_id if req.lesson_id in LESSONS else _get_lesson_id(sid)
    if lesson_id not in LESSONS:
        raise HTTPException(400, "먼저 학습 자료를 선택해 주세요.")

    _save_lesson(sid, lesson_id)
    prompt = _lesson_chat_prompt(sid, req.message, lesson_id)

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
                    "Groq literacy fallback failed: %s",
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


def _lesson_cards():
    cards = []
    for lesson_id, lesson in LESSONS.items():
        title = html_lib.escape(lesson["title"])
        short = html_lib.escape(lesson["short"])
        source = html_lib.escape(lesson["source_name"])
        starter = html_lib.escape(lesson["starter"], quote=True)
        cards.append(
            f'<button type="button" class="lesson-card" data-lesson="{lesson_id}" '
            f'data-starter="{starter}">'
            f'<strong>{title}</strong><span>{short}</span>'
            f'<small>사용 자료 · {source}</small></button>'
        )
    return "".join(cards)


def _lesson_payload():
    return {
        lesson_id: {
            "title": x["title"],
            "source_name": x["source_name"],
            "source_url": x["source_url"],
            "source_role": x["source_role"],
            "source_note": x["source_note"],
            "criteria": x["criteria"],
            "safety_note": x["safety_note"],
        }
        for lesson_id, x in LESSONS.items()
    }


def _render_index():
    html = (core.BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

    replacements = {
        "<title>AI OFF</title>": "<title>AI OFF | 디지털 리터러시 학습</title>",
        '<div class="hero-kicker">AI와 공부한 뒤</div>':
            '<div class="hero-kicker">디지털 리터러시 × AI OFF</div>',
        '<h1>AI에게 물어본 내용,<br>이번엔 내가 직접 해봅니다.</h1>':
            '<h1>AI와 판단 기준을 배우고,<br>마지막에는 내가 직접 확인합니다.</h1>',
        '<p>공부할 내용을 AI와 이야기해 보세요. 대화를 마치면 방금 대화에서 AI 도움을 많이 받은 부분을 골라, 직접 풀어볼 문제 3개가 나옵니다.</p>':
            '<p>공식 교육·조사자료를 바탕으로 정리한 뉴스·딥페이크·AI 답변 검증 기준을 사례로 연습합니다. 학습을 마치면 AI OFF가 방금 대화를 분석해, 같은 판단 기준을 혼자 적용해보는 문제 3개를 만듭니다.</p>',
        '<div class="hero-note"><strong>문제는 언제 나오나요?</strong><span>공부를 마친 뒤 <b>‘대화 마치고 문제 만들기’</b>를 누르면 됩니다. 방금 나눈 대화를 바탕으로 문제 3개가 바로 나옵니다.</span></div>':
            '<div class="hero-note"><strong>기존 AI OFF는 그대로</strong><span>AI와 학습한 대화를 분석하고 <b>AI가 대신한 사고를 학생이 직접 다시 수행</b>하는 기존 구조를 유지합니다. 이번에는 학습 주제를 디지털 리터러시로 구체화했습니다.</span></div>',
        '<div class="process-item active" id="process1"><div class="process-dot">1</div><strong>AI와 공부하기</strong><span>질문하고 설명을 듣습니다.</span></div>':
            '<div class="process-item active" id="process1"><div class="process-dot">1</div><strong>자료 선택·사례 학습</strong><span>판단 기준을 AI와 연습합니다.</span></div>',
        '<div class="process-item" id="process2"><div class="process-dot">2</div><strong>대화 마치기</strong><span>공부한 내용을 정리합니다.</span></div>':
            '<div class="process-item" id="process2"><div class="process-dot">2</div><strong>대화 분석</strong><span>AI가 도운 사고를 확인합니다.</span></div>',
        '<div class="process-item off" id="process3"><div class="process-dot">3</div><strong>직접 풀어보기</strong><span>AI 없이 문제 3개를 풉니다.</span></div>':
            '<div class="process-item off" id="process3"><div class="process-dot">3</div><strong>AI OFF</strong><span>판단 기준을 혼자 적용합니다.</span></div>',
        '<div class="process-item" id="process4"><div class="process-dot">4</div><strong>결과 확인하기</strong><span>AI 도움과 내 답변을 함께 봅니다.</span></div>':
            '<div class="process-item" id="process4"><div class="process-dot">4</div><strong>피드백·재도전</strong><span>답을 고쳐 다시 확인합니다.</span></div>',
        '<div><h2>학습 대화</h2><p>궁금한 내용을 자유롭게 물어보세요. 공부가 끝나면 아래 버튼을 눌러 다음 단계로 넘어갑니다.</p></div>':
            '<div><h2>리터러시 사례 학습</h2><p id="lessonLine">위에서 학습 자료를 고른 뒤 사례를 보며 판단 기준을 연습합니다.</p></div>',
        '<div class="guide-strip"><strong>지금은 AI와 함께 공부하는 단계입니다.</strong> 공부가 끝나면 아래 버튼을 눌러주세요. 그다음부터는 AI 없이 문제를 풀게 됩니다.</div>':
            '<div class="guide-strip"><strong>정답을 먼저 외우는 퀴즈가 아닙니다.</strong> 사례에서 무엇을 확인해야 하는지 먼저 판단해보고, AI와 함께 빠진 기준을 확인합니다. 새 사례는 실제 뉴스처럼 꾸미지 않고 ‘가상 사례’로 구분합니다.</div>',
        '<textarea id="input" placeholder="예: 목성 안에서는 수소가 어떻게 변해?"></textarea>':
            '<textarea id="input" placeholder="먼저 위에서 학습 자료를 선택해 주세요."></textarea>',
        '<div class="finish-copy"><strong>충분히 공부했나요?</strong><span>버튼을 누르면 방금 대화에서 직접 확인해볼 문제 3개가 나옵니다.</span></div>':
            '<div class="finish-copy"><strong>판단 기준을 충분히 연습했나요?</strong><span>AI OFF로 전환하면 방금 대화를 바탕으로 직접 적용할 문제 3개가 나옵니다.</span></div>',
        '<div class="side-top"><div class="side-kicker" id="stageStep">1 / 4</div><div class="side-stage" id="stageText">AI와 공부 중</div></div>':
            '<div class="side-top"><div class="side-kicker" id="stageStep">1 / 4</div><div class="side-stage" id="stageText">학습 자료를 선택하세요</div></div>',
        '<div class="side-help"><b>AI에 맡긴 정도</b>는 이 대화에서 해당 사고를 AI가 얼마나 대신했는지를 뜻합니다. <b>0</b>은 거의 직접 한 경우, <b>100</b>은 대부분 AI 도움을 받은 경우입니다.</div>':
            '<div class="side-help"><b>AI에 맡긴 정도</b>는 이번 대화에서 설명·탐색·근거 판단과 리터러시 판단을 AI가 얼마나 대신하거나 크게 도왔는지를 뜻합니다. 이번 학습 대화만 분석하며 장기 능력을 뜻하지 않습니다.</div>',
        '<div class="skills-title">AI 도움을 받은 부분</div>':
            '<div class="skills-title">이번 대화에서 AI가 도운 부분</div>',
        '<div id="skills"><div class="empty-side">대화를 마치면 사고 기능별로 얼마나 AI 도움을 받았는지 여기에 표시됩니다.</div></div>':
            '<div id="skills"><div class="empty-side">AI OFF로 전환하면 기존 사고 기능과 이번 학습의 리터러시 판단 항목을 함께 보여줍니다.</div></div>',
        '<div><div class="section-eyebrow">AI OFF</div><h2>이제 혼자 풀어볼 차례예요.</h2><p>방금 공부한 내용에서 문제 3개가 나왔습니다. AI 채팅은 잠시 꺼두고 직접 답해보세요.</p></div>':
            '<div><div class="section-eyebrow">AI OFF</div><h2>이번에는 내가 직접 판단합니다.</h2><p>방금 학습한 공식 자료의 판단 기준과 실제 대화를 바탕으로 문제 3개를 만들었습니다. AI 채팅은 잠시 꺼두고 직접 답해보세요.</p></div>',
        '<div class="off-notice"><b>완벽하게 쓰려고 하지 않아도 괜찮아요.</b> 내가 이해한 내용을 내 말로 설명해 보는 것이 중요합니다.</div>':
            '<div class="off-notice"><b>진짜/가짜만 맞히는 시험이 아닙니다.</b> 무엇을 확인할지, 어떤 근거로 판단할지를 자신의 말로 설명하는 것이 중요합니다.</div>',
        '<div><div class="section-eyebrow">이번 학습 결과</div><h2>AI 도움을 받은 부분과 직접 해낸 결과를 같이 봅니다.</h2><p>두 숫자는 뜻이 다릅니다. 아래 설명을 보고 이번 학습을 확인해 보세요.</p></div>':
            '<div><div class="section-eyebrow">이번 리터러시 학습 결과</div><h2>AI가 도운 부분과 내가 직접 적용한 결과를 같이 봅니다.</h2><p>채점은 이번 학습에서 사용한 정적 판단 기준과 각 문항의 평가기준을 함께 사용합니다.</p></div>',
        '<div class="guide-item green"><strong>혼자 수행한 결과</strong>AI 없이 문제에 답한 결과입니다. <b>100에 가까울수록 이번 문제에서 요구한 내용을 잘 해냈다는 뜻입니다.</b></div>':
            '<div class="guide-item green"><strong>직접 적용한 결과</strong>AI 없이 이번 학습의 판단 기준을 문제에 적용한 결과입니다. 실제 사실 여부를 모델 상식만으로 맞다·틀리다 판정하지 않습니다.</div>',
        '이 결과는 이번 학습에서의 수행만 보여줍니다. 학생의 장기적인 능력이나 성향을 판단하는 점수가 아닙니다.':
            '이 결과는 이번 학습 대화와 AI OFF 답변만 보여줍니다. 학생의 장기적인 디지털 리터러시 능력이나 성향을 판단하는 점수가 아닙니다.',
        '혼자 수행한 결과': '직접 적용한 결과',
    }
    for old, new in replacements.items():
        html = html.replace(old, new)

    lesson_json = json.dumps(_lesson_payload(), ensure_ascii=False).replace("</", "<\\/")
    extra_css = """
.lesson-panel{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:22px 24px;margin:0 0 28px}
.lesson-head{display:flex;justify-content:space-between;gap:20px;align-items:flex-end;margin-bottom:15px}.lesson-head h2{margin:0;font-size:20px}.lesson-head p{margin:5px 0 0;color:var(--body);font-size:12px;line-height:1.55}.lesson-tag{font-size:11px;color:var(--muted)}
.lesson-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.lesson-card{text-align:left;border:1px solid var(--line);background:#fff;border-radius:9px;padding:15px;min-height:132px;color:var(--ink)}.lesson-card:hover{border-color:#9eb4e9}.lesson-card.selected{border-color:var(--blue);background:var(--blue-soft);box-shadow:0 0 0 1px var(--blue) inset}.lesson-card strong{display:block;font-size:14px;margin-bottom:7px}.lesson-card span{display:block;font-size:11px;line-height:1.48;color:var(--body)}.lesson-card small{display:block;margin-top:10px;padding-top:9px;border-top:1px solid var(--line);font-size:10px;line-height:1.35;color:var(--muted)}
.lesson-detail{display:none;margin-top:14px;border-top:1px solid var(--line);padding-top:14px;grid-template-columns:1fr 1fr;gap:22px}.lesson-detail.show{display:grid}.lesson-detail h3{font-size:12px;margin:0 0 7px}.lesson-detail ul{margin:0;padding-left:18px}.lesson-detail li,.lesson-detail p{font-size:11px;line-height:1.55;color:var(--body);margin:4px 0}.lesson-detail a{color:var(--blue);text-decoration:none}.lesson-detail a:hover{text-decoration:underline}.lesson-safety{margin-top:8px;padding:8px 10px;background:var(--orange-soft);font-size:11px;line-height:1.5;color:#765e50}
@media(max-width:800px){.lesson-grid{grid-template-columns:1fr}.lesson-detail.show{grid-template-columns:1fr}.lesson-card{min-height:auto}.lesson-head{align-items:flex-start;flex-direction:column;gap:5px}}
"""
    html = html.replace("</style>", extra_css + "\n</style>")

    panel = f"""
  <section id="lessonPanel" class="lesson-panel">
    <div class="lesson-head">
      <div><h2>학습 자료를 선택하세요</h2><p>예선에서는 공식 원문을 확인해 정리한 기준을 사용합니다. 실시간 RAG로 외부 자료를 임의로 끌어오지 않습니다.</p></div>
      <div class="lesson-tag">현재 3개 학습 모듈</div>
    </div>
    <div class="lesson-grid">{_lesson_cards()}</div>
    <div id="lessonDetail" class="lesson-detail">
      <div><h3>이번 학습의 판단 기준</h3><ul id="criteriaList"></ul></div>
      <div><h3>사용 자료</h3><p id="sourceInfo"></p><p><a id="sourceLink" href="#" target="_blank" rel="noopener">공식 원문 열기 →</a></p><div id="safetyNote" class="lesson-safety hidden"></div></div>
    </div>
  </section>
"""
    html = html.replace(
        '  <section class="process" aria-label="이용 순서">',
        panel + '\n  <section class="process" aria-label="이용 순서">',
    )

    html = html.replace(
        "let sessionId=null,questions=[],delegationMap={},aiOffStarted=false,requestInFlight=false,hasResult=false;",
        "let sessionId=null,questions=[],delegationMap={},aiOffStarted=false,requestInFlight=false,hasResult=false,selectedLesson=null;\n"
        f"const lessonData={lesson_json};",
    )

    hook = "const processItems=[1,2,3,4].map(i=>document.getElementById(`process${i}`));"
    hook_add = """const processItems=[1,2,3,4].map(i=>document.getElementById(`process${i}`));
document.querySelectorAll('.lesson-card').forEach(card=>card.addEventListener('click',()=>{
  if(sessionId){if(confirm('이미 시작한 학습이 있습니다. 다른 자료를 선택하려면 새 학습으로 시작할까요?'))location.reload();return;}
  selectedLesson=card.dataset.lesson;
  const d=lessonData[selectedLesson];
  document.querySelectorAll('.lesson-card').forEach(x=>x.classList.toggle('selected',x===card));
  document.getElementById('lessonDetail').classList.add('show');
  document.getElementById('criteriaList').innerHTML=d.criteria.map(x=>`<li>${esc(x)}</li>`).join('');
  document.getElementById('sourceInfo').textContent=`${d.source_role} · ${d.source_name}\n${d.source_note}`;
  const link=document.getElementById('sourceLink');link.href=d.source_url;
  const safety=document.getElementById('safetyNote');if(d.safety_note){safety.textContent=d.safety_note;safety.classList.remove('hidden');}else{safety.textContent='';safety.classList.add('hidden');}
  document.getElementById('lessonLine').textContent=`${d.title} 사례를 보며 판단 기준을 연습합니다.`;
  input.value=card.dataset.starter||'';
  input.placeholder='이 사례에서 무엇을 확인해야 할지 적어보세요.';
  stageText.textContent='AI와 사례 학습 중';
  input.focus();
}));"""
    html = html.replace(hook, hook_add)

    html = html.replace(
        "if(aiOffStarted||requestInFlight)return;const text=input.value.trim();if(!text)return;",
        "if(aiOffStarted||requestInFlight)return;if(!selectedLesson){const preStatus=document.getElementById('chatStatus');clearError(preStatus);setError(preStatus,'먼저 위에서 학습 자료를 선택해 주세요.');document.getElementById('lessonPanel').scrollIntoView({behavior:'smooth'});return;}const text=input.value.trim();if(!text)return;",
    )
    html = html.replace(
        "body:JSON.stringify({session_id:sessionId,message:text})",
        "body:JSON.stringify({session_id:sessionId,message:text,lesson_id:selectedLesson})",
    )
    return html


@app.get("/", response_class=HTMLResponse)
def literacy_index():
    return HTMLResponse(_render_index())


@app.post("/api/analyze")
def analyze_literacy(req: core.SessionRequest):
    tx = core.transcript(req.session_id)
    if not tx.strip():
        raise HTTPException(400, "분석할 학습 대화가 없습니다.")

    lesson_id = _get_lesson_id(req.session_id)
    if lesson_id not in LESSONS:
        raise HTTPException(400, "학습 자료 선택 정보가 없습니다.")
    lesson = LESSONS[lesson_id]

    skills = list(dict.fromkeys(GENERAL_SKILLS + lesson["skills"]))
    criteria = "\n".join(f"- {x}" for x in lesson["criteria"])
    prompt = f"""다음은 학생과 AI 튜터가 '{lesson['title']}'을 학습한 실제 대화다.

{tx}

이번 학습에서 AI가 어떤 사고와 판단을 얼마나 대신하거나 크게 도왔는지 분석하라.
반드시 다음 기능을 모두 평가한다:
{', '.join(skills)}

[이번 학습의 정적 판단 기준]
{criteria}

delegation은 0~100이다.
- 일반 사고 기능은 AI가 설명·탐색·근거 판단 등을 실제로 대신한 정도를 본다.
- 리터러시 기능은 학생이 판단 기준을 스스로 적용하기보다 AI가 결론이나 확인 절차를 대신 제시한 정도를 본다.
- 단순히 AI에게 질문했다는 이유만으로 높은 값을 주지 않는다.
- 학생이 스스로 확인 기준이나 이유를 먼저 제시했다면 해당 위임 정도를 낮게 본다.
- 대화에서 해당 기능을 판단할 근거가 없으면 0으로 둔다.
- evidence는 실제 대화에서 확인되는 짧은 근거만 최대 2개 적는다.
- summary는 이번 대화에서 AI가 크게 도운 부분과 학생이 직접 시도한 부분을 2~4문장으로 설명한다.
- 학생의 장기 능력이나 성향을 단정하지 않는다."""

    try:
        result, _ = core.generate_structured_with_fallback(
            prompt,
            core.AnalysisResult,
            max_output_tokens=1200,
        )
    except Exception as e:
        core.logger.exception("Literacy analysis failed")
        raise HTTPException(502, f"대화 분석 오류: {type(e).__name__}")

    data = result.model_dump()
    by_name = {x["skill"]: x for x in data.get("scores", [])}
    normalized = []
    for skill in skills:
        normalized.append(
            by_name.get(skill) or {
                "skill": skill,
                "delegation": 0,
                "evidence": [],
                "rationale": "대화에서 확인할 근거가 부족합니다.",
            }
        )
    data["scores"] = normalized
    ranked = sorted(normalized, key=lambda x: x["delegation"], reverse=True)
    data["top_skills"] = [x["skill"] for x in ranked if x["delegation"] > 0][:5]

    with core.connect_db() as c:
        c.execute(
            "INSERT INTO analyses(session_id,result_json) VALUES(?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "result_json=excluded.result_json, created_at=CURRENT_TIMESTAMP",
            (req.session_id, json.dumps(data, ensure_ascii=False)),
        )
    return data


@app.post("/api/off-test")
def off_test_literacy(req: core.SessionRequest):
    tx = core.transcript(req.session_id)
    lesson_id = _get_lesson_id(req.session_id)
    if lesson_id not in LESSONS:
        raise HTTPException(400, "학습 자료 선택 정보가 없습니다.")
    lesson = LESSONS[lesson_id]

    with core.connect_db() as c:
        row = c.execute(
            "SELECT result_json FROM analyses WHERE session_id=?",
            (req.session_id,),
        ).fetchone()

    analysis = json.loads(row["result_json"]) if row else analyze_literacy(req)
    ranked = sorted(analysis["scores"], key=lambda x: x["delegation"], reverse=True)
    general_top = [x["skill"] for x in ranked if x["skill"] in GENERAL_SKILLS and x["delegation"] > 0]
    direct_skill = general_top[0] if general_top else "근거 판단"
    allowed = list(dict.fromkeys([direct_skill] + lesson["skills"]))
    criteria = "\n".join(f"- {x}" for x in lesson["criteria"])

    prompt = f"""다음은 학생이 '{lesson['title']}'을 학습한 실제 대화다.

[전체 대화]
{tx}

[공식 자료]
{lesson['source_name']}
자료 활용 범위: {lesson['source_note']}

[예선 프로토타입에서 사용하는 정적 판단 기준]
{criteria}

AI OFF 문제를 정확히 3개 생성하라.

목적:
- 기존 AI OFF의 핵심인 'AI가 도운 사고를 학생이 다시 직접 수행'하는 구조를 유지한다.
- 동시에 디지털 리터러시 판단 기준을 새로운 상황에 학생이 직접 적용하게 한다.

문제 구성:
1. 1문제는 '{direct_skill}'을 학생이 AI 도움 없이 직접 수행하도록 한다.
2. 나머지 2문제는 다음 리터러시 기능을 중심으로 판단 기준을 적용하게 한다: {', '.join(lesson['skills'])}
3. 리터러시 문제는 진짜/가짜 선택만 시키지 말고 '무엇을 확인할지 + 왜 그런지'를 함께 묻는다.
4. 필요하면 새로운 사례를 만들 수 있지만 반드시 '[가상 사례]'라고 표시한다.
5. 실제 뉴스·수치·인물·기관의 사실관계를 임의로 만들어내지 않는다.
6. 실제 외부 검색 결과를 요구하지 않는다. 어떤 원문·출처·기준을 확인해야 하는지 판단하게 한다.
7. 각 문제는 2~5분 안에 답할 수 있는 분량으로 만든다.

skill은 반드시 다음 중 하나만 사용한다:
{', '.join(allowed)}

evaluation_criteria는 반드시 위 정적 판단 기준에서 관련된 항목을 중심으로 2~4개 작성한다.
why_this_question에는 이번 학습에서 어떤 판단 기준을 직접 적용해보는지 설명한다."""

    try:
        result, _ = core.generate_structured_with_fallback(
            prompt,
            core.OffTestResult,
            max_output_tokens=1500,
        )
        if len(result.questions) < 3:
            raise ValueError("off_test_question_count")
    except Exception as e:
        core.logger.exception("Literacy AI OFF question generation failed")
        raise HTTPException(502, f"AI OFF 문제 생성 오류: {type(e).__name__}")

    out = []
    with core.connect_db() as c:
        c.execute("DELETE FROM off_questions WHERE session_id=?", (req.session_id,))
        c.execute("DELETE FROM off_results WHERE session_id=?", (req.session_id,))
        for q in result.questions[:3]:
            cur = c.execute(
                "INSERT INTO off_questions(session_id,skill,question,why_this_question,criteria_json) "
                "VALUES(?,?,?,?,?)",
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


@app.post("/api/off-submit")
def off_submit_grounded(req: core.SubmitOffRequest):
    if not req.answers:
        raise HTTPException(400, "제출된 답변이 없습니다.")

    lesson_id = _get_lesson_id(req.session_id)
    if lesson_id not in LESSONS:
        raise HTTPException(400, "학습 자료 선택 정보가 없습니다.")
    lesson = LESSONS[lesson_id]

    ids = [a.question_id for a in req.answers]
    marks = ",".join("?" for _ in ids)
    with core.connect_db() as c:
        rows = c.execute(
            f"SELECT id,skill,question,criteria_json FROM off_questions "
            f"WHERE session_id=? AND id IN ({marks})",
            [req.session_id] + ids,
        ).fetchall()

    qmap = {r["id"]: r for r in rows}
    answer_map = {a.question_id: a.answer for a in req.answers}
    if len(qmap) != len(req.answers):
        raise HTTPException(400, "현재 세션의 AI OFF 문항과 제출 답변이 일치하지 않습니다.")

    lesson_criteria = "\n".join(f"- {x}" for x in lesson["criteria"])
    blocks = []
    for i, answer in enumerate(req.answers, 1):
        q = qmap[answer.question_id]
        qcriteria = "\n".join(f"- {x}" for x in json.loads(q["criteria_json"]))
        blocks.append(
            f"""[문항 {i}]
question_id: {answer.question_id}
기능: {q['skill']}
질문: {q['question']}
학생 답변: {answer.answer}
문항 평가기준:
{qcriteria}"""
        )

    prompt = f"""다음은 '{lesson['title']}' 학습 후 학생이 AI OFF에서 직접 작성한 답변이다.

[이번 학습의 공식 자료]
{lesson['source_name']}
자료 활용 범위: {lesson['source_note']}

[이번 학습에서 사용하는 정적 판단 기준]
{lesson_criteria}

{chr(10).join(blocks)}

평가 원칙:
- 각 문항의 저장된 평가기준과 위 정적 판단 기준을 우선하여 평가한다.
- 학생이 '무엇을 확인할지', '왜 확인할지', '언제 판단을 유보할지'를 적절히 설명했는지 본다.
- 가상 사례의 실제 진위 여부를 모델 상식으로 추측해 채점하지 않는다.
- 실제 사실 확인이 필요한 내용을 학생이 단정해도 모델 상식만으로 맞다/틀리다 확정하지 않는다. 확인 절차와 근거 판단의 타당성을 평가한다.
- 문장 표현보다 판단 과정과 기준 적용을 우선한다.
- score는 0~100 숫자로 작성한다.
- feedback은 잘 적용한 기준과 빠진 기준을 2~3문장으로 구분해 쓴다.
- 학생의 지능·성향·장기 리터러시 능력을 평가하지 않는다.
- 모든 question_id를 정확히 한 번씩 포함한다.

반환 형식:
{{
  "results": [
    {{"question_id": 1, "score": 80, "feedback": "..."}}
  ],
  "overall_summary": "이번 AI OFF 수행에 대한 1~2문장 요약"
}}"""

    try:
        draft, _ = core.generate_structured_with_fallback(
            prompt,
            core.EvaluationDraft,
            max_output_tokens=1000,
        )
        parsed_results, overall_summary = core.validate_evaluation(draft, set(ids))
    except Exception as e:
        core.logger.exception("Grounded literacy evaluation failed")
        raise HTTPException(502, f"AI OFF 답변 평가 오류: {type(e).__name__}")

    results = []
    with core.connect_db() as c:
        c.execute("DELETE FROM off_results WHERE session_id=?", (req.session_id,))
        for x in parsed_results:
            q = qmap[x["question_id"]]
            item = {
                "question_id": x["question_id"],
                "skill": q["skill"],
                "score": x["score"],
                "level": x["level"],
                "feedback": x["feedback"],
            }
            results.append(item)
            c.execute(
                "INSERT INTO off_results(question_id,session_id,skill,answer,score,level,feedback) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    x["question_id"],
                    req.session_id,
                    q["skill"],
                    answer_map.get(x["question_id"], ""),
                    x["score"],
                    x["level"],
                    x["feedback"],
                ),
            )

    return {"results": results, "overall_summary": overall_summary}
