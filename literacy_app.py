from fastapi import HTTPException
from fastapi.responses import HTMLResponse
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
    ("/api/analyze", "POST"),
    ("/api/off-test", "POST"),
]:
    _remove_route(_path, _method)


def _render_literacy_index():
    html = (core.BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    replacements = {
        "<title>AI OFF</title>": "<title>AI OFF | 디지털 리터러시 학습</title>",
        '<div class="hero-kicker">AI와 공부한 뒤</div>': '<div class="hero-kicker">AI와 공부하고, 직접 확인하기</div>',
        '<h1>AI에게 물어본 내용,<br>이번엔 내가 직접 해봅니다.</h1>': '<h1>AI에게 맡긴 생각과 판단,<br>이번엔 내가 직접 확인합니다.</h1>',
        '<p>공부할 내용을 AI와 이야기해 보세요. 대화를 마치면 방금 대화에서 AI 도움을 많이 받은 부분을 골라, 직접 풀어볼 문제 3개가 나옵니다.</p>': '<p>AI와 자유롭게 공부한 뒤 대화를 마치면, AI가 많이 대신한 사고와 직접 확인하지 않은 정보 판단을 찾아냅니다. 그 대화를 바탕으로 이해·출처·근거·교차검증을 직접 해보는 AI OFF 문제 3개가 나옵니다.</p>',
        '<div class="hero-note"><strong>문제는 언제 나오나요?</strong><span>공부를 마친 뒤 <b>‘대화 마치고 문제 만들기’</b>를 누르면 됩니다. 방금 나눈 대화를 바탕으로 문제 3개가 바로 나옵니다.</span></div>': '<div class="hero-note"><strong>무엇을 확인하나요?</strong><span>방금 나눈 대화에서 <b>AI에게 맡긴 사고</b>와 <b>직접 확인하지 않은 출처·근거·사실 판단</b>을 찾아, 학생이 다시 직접 수행할 문제를 만듭니다.</span></div>',
        '<div class="process-item" id="process2"><div class="process-dot">2</div><strong>대화 마치기</strong><span>공부한 내용을 정리합니다.</span></div>': '<div class="process-item" id="process2"><div class="process-dot">2</div><strong>대화 분석하기</strong><span>AI에 맡긴 사고와 판단을 찾습니다.</span></div>',
        '<div class="process-item off" id="process3"><div class="process-dot">3</div><strong>직접 풀어보기</strong><span>AI 없이 문제 3개를 풉니다.</span></div>': '<div class="process-item off" id="process3"><div class="process-dot">3</div><strong>직접 확인하기</strong><span>AI 없이 이해·출처·근거를 판단합니다.</span></div>',
        '<div class="process-item" id="process4"><div class="process-dot">4</div><strong>결과 확인하기</strong><span>AI 도움과 내 답변을 함께 봅니다.</span></div>': '<div class="process-item" id="process4"><div class="process-dot">4</div><strong>피드백 확인하기</strong><span>무엇을 직접 확인했는지 돌아봅니다.</span></div>',
        '<div class="guide-strip"><strong>지금은 AI와 함께 공부하는 단계입니다.</strong> 공부가 끝나면 아래 버튼을 눌러주세요. 그다음부터는 AI 없이 문제를 풀게 됩니다.</div>': '<div class="guide-strip"><strong>지금은 AI와 함께 공부하는 단계입니다.</strong> 설명을 듣는 데서 끝내지 말고 출처와 근거가 궁금한 부분도 질문해 보세요. 공부가 끝나면 AI OFF에서 내가 직접 확인하고 판단합니다. 이름·연락처 등 불필요한 개인정보는 입력하지 마세요.</div>',
        '<div class="finish-copy"><strong>충분히 공부했나요?</strong><span>버튼을 누르면 방금 대화에서 직접 확인해볼 문제 3개가 나옵니다.</span></div>': '<div class="finish-copy"><strong>이제 내가 직접 확인해볼까요?</strong><span>버튼을 누르면 AI가 많이 대신한 사고와 정보 판단을 분석한 뒤 문제 3개가 나옵니다.</span></div>',
        '<div class="side-help"><b>AI에 맡긴 정도</b>는 이 대화에서 해당 사고를 AI가 얼마나 대신했는지를 뜻합니다. <b>0</b>은 거의 직접 한 경우, <b>100</b>은 대부분 AI 도움을 받은 경우입니다.</div>': '<div class="side-help"><b>AI에 맡긴 정도</b>는 이 대화에서 생각하거나 정보의 신뢰성을 판단하는 일을 AI가 얼마나 대신했는지를 뜻합니다. 출처·근거·사실 판단도 학생이 직접 확인하지 않고 AI 판단에 맡겼다면 함께 표시합니다.</div>',
        '<div class="skills-title">AI 도움을 받은 부분</div>': '<div class="skills-title">AI에게 맡긴 사고·정보 판단</div>',
        '<div id="skills"><div class="empty-side">대화를 마치면 사고 기능별로 얼마나 AI 도움을 받았는지 여기에 표시됩니다.</div></div>': '<div id="skills"><div class="empty-side">대화를 마치면 자료 탐색·설명 같은 사고 기능과 출처·근거·교차검증 같은 정보 판단을 함께 분석해 여기에 표시합니다.</div></div>',
        '<div><div class="section-eyebrow">AI OFF</div><h2>이제 혼자 풀어볼 차례예요.</h2><p>방금 공부한 내용에서 문제 3개가 나왔습니다. AI 채팅은 잠시 꺼두고 직접 답해보세요.</p></div>': '<div><div class="section-eyebrow">AI OFF</div><h2>이제 직접 확인하고 판단해볼 차례예요.</h2><p>방금 공부한 내용에서 이해·출처·근거·교차검증이 필요한 문제 3개가 나왔습니다. AI 채팅은 잠시 꺼두고 직접 답해보세요.</p></div>',
        '<div class="off-notice"><b>완벽하게 쓰려고 하지 않아도 괜찮아요.</b> 내가 이해한 내용을 내 말로 설명해 보는 것이 중요합니다.</div>': '<div class="off-notice"><b>정답을 외우는 시험이 아닙니다.</b> 내가 이해한 내용을 설명하고, 어떤 정보와 근거를 믿을지 직접 판단해 보는 과정입니다.</div>',
        '<div><div class="section-eyebrow">이번 학습 결과</div><h2>AI 도움을 받은 부분과 직접 해낸 결과를 같이 봅니다.</h2><p>두 숫자는 뜻이 다릅니다. 아래 설명을 보고 이번 학습을 확인해 보세요.</p></div>': '<div><div class="section-eyebrow">이번 AI 활용 돌아보기</div><h2>AI에게 맡긴 사고·판단과 직접 확인한 결과를 같이 봅니다.</h2><p>무엇을 AI에게 맡겼고, AI OFF에서 무엇을 직접 설명·검증·판단했는지 함께 확인합니다.</p></div>',
        '<div class="guide-item"><strong>AI에 맡긴 정도</strong>AI와 대화할 때 해당 사고를 AI가 대신한 정도입니다. <b>0에 가까우면 직접 한 부분이 많고, 100에 가까우면 AI가 대신한 부분이 많습니다.</b></div>': '<div class="guide-item"><strong>AI에 맡긴 정도</strong>AI와 대화할 때 생각이나 정보 판단을 AI가 대신한 정도입니다. <b>출처·근거·사실 여부를 AI 판단에 그대로 맡긴 경우도 포함합니다.</b></div>',
        '<div class="guide-item green"><strong>혼자 수행한 결과</strong>AI 없이 문제에 답한 결과입니다. <b>100에 가까울수록 이번 문제에서 요구한 내용을 잘 해냈다는 뜻입니다.</b></div>': '<div class="guide-item green"><strong>직접 확인한 결과</strong>AI 없이 문제에 답하며 이해·근거·출처·교차검증을 직접 수행한 결과입니다. 수정 답변도 같은 문항 평가기준으로 다시 확인합니다.</div>',
        '이 결과는 이번 학습에서의 수행만 보여줍니다. 학생의 장기적인 능력이나 성향을 판단하는 점수가 아닙니다.': '이 결과는 이번 학습 대화와 AI OFF 답변만 보여줍니다. 학생의 장기적인 디지털 리터러시 능력이나 성향을 단정하는 점수가 아닙니다.',
        '답을 고쳐서 다시 채점하거나, 다른 주제로 새 학습을 시작할 수 있습니다.': '피드백을 보고 답을 고쳐 다시 확인하거나, 다른 주제로 새 학습을 시작할 수 있습니다.',
        '혼자 수행한 결과': '직접 확인한 결과',
    }
    for old, new in replacements.items():
        html = html.replace(old, new)
    return html


@app.get("/", response_class=HTMLResponse)
def literacy_index():
    return HTMLResponse(_render_literacy_index())


@app.post("/api/analyze")
def analyze_literacy(req: core.SessionRequest):
    tx = core.transcript(req.session_id)
    if not tx.strip():
        raise HTTPException(400, "분석할 학습 대화가 없습니다.")

    skill_list = ", ".join(ALL_SKILLS)
    prompt = f"""다음은 학생과 AI 튜터의 실제 학습 대화다.

{tx}

이 대화에서 학생이 AI에게 맡긴 사고와 정보 판단을 분석하라.
반드시 다음 10개 항목을 모두 평가한다.
{skill_list}

delegation은 0~100으로 기록한다.
- 자료 탐색, 개념 설명, 비교·분석, 주장 구성, 근거 판단: AI가 해당 사고를 대신 수행한 정도다.
- 출처 신뢰도 판단, 사실·의견 구분, 근거 충분성 판단, 교차검증, 불확실성 확인: 학생이 해당 판단을 직접 확인하지 않고 AI의 판단·설명에 맡긴 정도다.
- 대화에서 해당 판단이 필요하지 않았거나 근거가 없으면 0으로 둔다.
- 단순히 질문했다는 이유, AI를 사용했다는 이유만으로 높은 점수를 주지 않는다.
- 학생이 스스로 출처를 요구하거나 다른 근거를 비교·검증한 흔적이 있으면 해당 항목의 위임 정도를 낮게 본다.

evidence는 실제 대화에서 확인되는 짧은 근거를 최대 2개만 적는다.
top_skills에는 delegation이 0보다 큰 항목 중 최대 5개를 높은 순서대로 넣는다.
summary는 'AI가 많이 도와준 사고'와 '다시 확인해볼 정보 판단'을 구분해 2~4문장으로 작성한다.
학생의 장기 능력, 성향, 디지털 리터러시 수준을 단정하지 않는다.
대화에 없는 출처나 사실을 새로 만들어 평가 근거로 쓰지 않는다."""

    try:
        result, _ = core.generate_structured_with_fallback(
            prompt,
            core.AnalysisResult,
            max_output_tokens=1200,
        )
    except Exception as e:
        core.logger.exception("Conversation literacy analysis failed")
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
            "INSERT INTO analyses(session_id,result_json) VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET result_json=excluded.result_json, created_at=CURRENT_TIMESTAMP",
            (req.session_id, json.dumps(data, ensure_ascii=False)),
        )
    return data


@app.post("/api/off-test")
def off_test_literacy(req: core.SessionRequest):
    tx = core.transcript(req.session_id)
    requests = core.student_requests(req.session_id)

    with core.connect_db() as c:
        row = c.execute(
            "SELECT result_json FROM analyses WHERE session_id=?",
            (req.session_id,),
        ).fetchone()

    analysis = json.loads(row["result_json"]) if row else analyze_literacy(req)
    ranked = sorted(analysis["scores"], key=lambda x: x["delegation"], reverse=True)
    meaningful_general = [x for x in ranked if x["skill"] in GENERAL_SKILLS and x["delegation"] > 0]
    meaningful_literacy = [x for x in ranked if x["skill"] in LITERACY_SKILLS and x["delegation"] > 0]
    meaningful = meaningful_general + meaningful_literacy

    if not meaningful:
        raise HTTPException(
            400,
            "이번 세션에서는 AI에 의미 있게 맡긴 사고나 정보 판단이 확인되지 않아 AI OFF 문제를 만들지 않았습니다.",
        )

    selected_skills = []
    if meaningful_general:
        selected_skills.extend(x["skill"] for x in meaningful_general[:3])
    if meaningful_literacy:
        selected_skills.extend(x["skill"] for x in meaningful_literacy[:3])
    selected_skills = list(dict.fromkeys(selected_skills))[:6]

    request_list = "\n".join(f"- {text}" for text in requests)
    general_text = ", ".join(x["skill"] for x in meaningful_general[:3]) or "없음"
    literacy_text = ", ".join(x["skill"] for x in meaningful_literacy[:3]) or "없음"

    prompt = f"""다음은 학생의 전체 학습 세션이다.

[학생이 실제로 요청한 내용]
{request_list}

[전체 대화]
{tx}

[AI가 많이 대신한 사고]
{general_text}

[학생이 직접 다시 확인할 정보 판단]
{literacy_text}

학생이 AI 없이 직접 수행할 수 있는지 확인하는 AI OFF 문제를 정확히 3개 생성하라.

핵심 목적:
- 단순 암기시험이 아니라 'AI에게 맡긴 사고를 다시 직접 하기'와 'AI가 준 정보를 스스로 확인하고 판단하기'를 함께 훈련한다.
- 디지털 리터러시 문제는 출처 신뢰도, 사실과 의견, 근거 충분성, 교차검증, 불확실성을 학생이 직접 판단하도록 만든다.
- 학생에게 검색 결과나 정답을 대신 제공하지 않는다. 필요한 경우 '어떤 출처를 우선 확인할지와 그 이유'처럼 판단 기준을 묻는다.

문제 구성 규칙:
- 의미 있는 일반 사고 기능이 있으면 최소 1문제는 그 기능을 학생이 직접 수행하게 한다.
- 의미 있는 리터러시 기능이 있으면 최소 1문제는 해당 정보 판단을 직접 수행하게 한다.
- 세 번째 문제는 이번 대화에서 위임 정도가 큰 기능을 우선한다.
- 리터러시 기능 점수가 모두 0이면 출처·가짜뉴스 문제를 억지로 만들지 않는다.
- 서로 다른 학습 주제가 2개 이상이면 가능한 범위에서 여러 주제를 고르게 반영한다.

skill 규칙:
- skill은 다음 의미 있는 기능 중 하나만 사용한다: {', '.join(selected_skills)}
- 위임 정도가 0인 기능을 억지로 검증하지 않는다.

문제 작성 규칙:
- 방금 대화의 실제 주제와 내용을 활용한다.
- 2~5분 안에 답할 수 있게 짧고 분명하게 작성한다.
- 정답이나 모범답안을 질문에 포함하지 않는다.
- 출처 신뢰도를 묻는 경우 특정 출처 이름을 임의로 사실처럼 만들어내지 않는다.
- evaluation_criteria는 문항별 핵심 기준 2~4개를 적는다.
- why_this_question에는 이번 대화에서 왜 이 판단을 다시 해봐야 하는지 학생이 이해할 수 있게 설명한다."""

    try:
        result, _ = core.generate_structured_with_fallback(
            prompt,
            core.OffTestResult,
            max_output_tokens=1400,
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
