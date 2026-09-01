from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import json

import literacy_app as base
from literacy_cases import CASE_LIBRARY

app = base.app

# 실제 사례는 별도 상단 패널이 아니라 기존 AI OFF 채팅창 안에서 제시한다.
# 주제별 사례 선택 → 사례 미디어/주장 표시 → AI 첫 질문 → 티키타카 → 기존 AI OFF 3문제 흐름.

with base.core.connect_db() as c:
    c.execute(
        "CREATE TABLE IF NOT EXISTS session_cases("
        "session_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )

CASE_BY_ID = {
    case["id"]: (lesson_id, case)
    for lesson_id, cases in CASE_LIBRARY.items()
    for case in cases
}


class CaseStartRequest(BaseModel):
    lesson_id: str
    case_id: str


def _save_case(session_id: str, case_id: str):
    with base.core.connect_db() as c:
        c.execute(
            "INSERT INTO session_cases(session_id,case_id) VALUES(?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET case_id=excluded.case_id",
            (session_id, case_id),
        )


def _get_case_id(session_id: str):
    with base.core.connect_db() as c:
        row = c.execute(
            "SELECT case_id FROM session_cases WHERE session_id=?",
            (session_id,),
        ).fetchone()
    return row["case_id"] if row and row["case_id"] in CASE_BY_ID else None


def _public_case(case):
    return {
        key: case[key]
        for key in (
            "id", "label", "title", "claim", "source_name", "source_url",
            "media_type", "media_url", "media_caption"
        )
    }


@app.post("/api/case-start")
def case_start(req: CaseStartRequest):
    found = CASE_BY_ID.get(req.case_id)
    if not found or found[0] != req.lesson_id or req.lesson_id not in base.LESSONS:
        raise HTTPException(400, "선택한 학습 사례를 찾을 수 없습니다.")

    _, case = found
    sid = str(base.core.uuid.uuid4())
    base._save_lesson(sid, req.lesson_id)
    _save_case(sid, req.case_id)

    # 첫 질문도 실제 학습 대화의 일부로 저장한다.
    with base.core.connect_db() as c:
        c.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)", (sid,))
        c.execute(
            "INSERT INTO messages(session_id, role, content) VALUES(?, 'assistant', ?)",
            (sid, case["opening_question"]),
        )

    return {
        "session_id": sid,
        "case": _public_case(case),
        "opening_question": case["opening_question"],
    }


def _case_chat_prompt(session_id: str, user_message: str, lesson_id: str):
    case_id = _get_case_id(session_id)
    if not case_id or case_id not in CASE_BY_ID:
        return _ORIGINAL_LESSON_PROMPT(session_id, user_message, lesson_id)

    case_lesson_id, case = CASE_BY_ID[case_id]
    if case_lesson_id != lesson_id:
        return _ORIGINAL_LESSON_PROMPT(session_id, user_message, lesson_id)

    lesson = base.LESSONS[lesson_id]
    prior = base.core.messages(session_id, 14)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '튜터'}: {m['content']}"
        for m in prior
    )
    student_turns = sum(1 for m in prior if m["role"] == "user")
    criteria = "\n".join(f"- {x}" for x in lesson["criteria"])
    clues = "\n".join(f"- {x}" for x in case["clues"])

    if student_turns < 2:
        resolution = "아직 최종 검증 결과를 공개하지 않는다. 학생이 먼저 판단 근거와 확인 방법을 말하게 한다."
    else:
        resolution = case["resolution"]

    safety = lesson.get("safety_note") or ""
    return f"""너는 중·고등학생을 위한 디지털 리터러시 학습 튜터다.
현재 학생은 '{lesson['title']}' 주제에서 실제 사례 하나를 보고 있다.

[현재 실제 사례]
사례명: {case['title']}
당시 퍼진 주장·상황: {case['claim']}
출처: {case['source_name']}

[이번 학습의 판단 기준]
{criteria}

[검증에 사용할 수 있는 단서]
{clues}

[최종 검증 결과]
{resolution}

대화 규칙:
1. '안녕', '오늘은 ~를 배워보자' 같은 인사·수업 소개를 반복하지 않는다.
2. 학생의 방금 답변에 바로 반응하고, 짧은 피드백 뒤 다음 질문 하나만 한다.
3. 처음에는 진짜/가짜에 대한 학생의 판단과 이유를 묻고, 이후 왜 그렇게 생각했는지와 무엇을 확인할지 파고든다.
4. 학생이 단순히 '진짜/가짜'만 답하면 곧바로 정답을 말하지 말고 그 판단의 근거나 확인 방법을 묻는다.
5. 출처·원문·게시 시점·근거·교차검증·불확실성을 한 번에 나열하지 말고 대화에 맞춰 하나씩 적용한다.
6. 학생이 적절한 기준을 먼저 제시하면 인정하고, 아직 빠진 기준 하나를 다음 질문으로 이어간다.
7. 학생이 최소 두 번 자신의 판단 기준을 말하기 전에는 최종 검증 결과를 공개하지 않는다.
8. 최종 결과를 공개한 뒤에도 왜 그런 결론이 나왔는지 실제 단서와 검증 절차를 연결해 설명한다.
9. 사례에 없는 사실·수치·인물·출처를 새로 만들어내지 않는다.
10. 실시간 웹검색이나 RAG를 했다고 말하지 않는다. 제공된 실제 사례 정보와 정적 기준만 사용한다.
11. 대화 중 AI OFF 최종 3문제를 미리 출제하지 않는다. 학생이 학습 종료 버튼을 눌렀을 때 별도 생성된다.
12. 딥페이크 피해 사례에서는 성적·폭력적 합성물을 묘사하거나 재현하지 않는다.
13. 답변은 한국어로 자연스럽고 짧게 쓴다.
{('14. ' + safety) if safety else ''}

[이전 대화]
{history or '(없음)'}

[학생의 새 답변]
{user_message}"""


# literacy_app의 기존 스트리밍 라우트가 런타임에 이 함수를 사용하도록 교체한다.
_ORIGINAL_LESSON_PROMPT = base._lesson_chat_prompt
base._lesson_chat_prompt = _case_chat_prompt


def _case_payload():
    return {
        lesson_id: [_public_case(case) for case in cases]
        for lesson_id, cases in CASE_LIBRARY.items()
    }


def _render_index():
    html = base._render_index()
    cases_json = json.dumps(_case_payload(), ensure_ascii=False).replace("</", "<\\/")

    # 상단은 '주제 선택'까지만 두고, 실제 사례/미디어는 채팅 안에서만 보여준다.
    html = html.replace("학습 자료를 선택하세요", "학습 주제를 선택하세요")
    html = html.replace("현재 3개 학습 모듈", "3개 주제 · 주제별 실제 사례 3개")
    html = html.replace(
        "예선에서는 공식 원문을 확인해 정리한 기준을 사용합니다. 실시간 RAG로 외부 자료를 임의로 끌어오지 않습니다.",
        "주제를 고르면 아래 채팅창 안에서 실제 사례 3개를 선택할 수 있습니다.",
    )
    html = html.replace(
        '<div class="guide-strip"><strong>정답을 먼저 외우는 퀴즈가 아닙니다.</strong> 사례에서 무엇을 확인해야 하는지 먼저 판단해보고, AI와 함께 빠진 기준을 확인합니다. 새 사례는 실제 뉴스처럼 꾸미지 않고 ‘가상 사례’로 구분합니다.</div>',
        '<div class="guide-strip"><strong>실제 사례에서 바로 시작합니다.</strong> 주제를 고르면 이 채팅창 안에 실제 사례 3개가 나타납니다. 사례를 선택하면 사진·기사·문서와 당시 주장을 보여주고 AI가 바로 첫 질문을 합니다.</div>',
    )
    html = html.replace(
        '<div><h2>리터러시 사례 학습</h2><p id="lessonLine">위에서 학습 자료를 고른 뒤 사례를 보며 판단 기준을 연습합니다.</p></div>',
        '<div><h2>리터러시 사례 학습</h2><p id="lessonLine">주제를 고른 뒤 이 채팅창에서 실제 사례를 선택하고 AI와 판단을 이어갑니다.</p></div>',
    )

    extra_css = r"""
.lesson-detail{display:none!important}
.chat-case-picker{margin:8px 0 18px;border:1px solid var(--line);background:#fff;border-radius:10px;padding:14px}
.chat-case-picker-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:10px}
.chat-case-picker-head strong{font-size:13px}.chat-case-picker-head span{font-size:10px;color:var(--muted)}
.chat-case-options{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}
.chat-case-option{border:1px solid var(--line);background:var(--paper);border-radius:8px;padding:10px;text-align:left;color:var(--ink)}
.chat-case-option:hover{border-color:#9db2e7}.chat-case-option.active{border-color:var(--blue);background:var(--blue-soft)}
.chat-case-option b{display:block;font-size:11px;line-height:1.35;margin-bottom:4px}.chat-case-option small{display:block;font-size:9px;color:var(--muted)}
.chat-case-card{border:1px solid var(--line);border-radius:10px;background:#fff;overflow:hidden;margin:12px 0 18px}
.chat-case-top{padding:11px 13px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.chat-case-kicker{font-size:9px;font-weight:900;color:var(--orange);margin-bottom:3px}.chat-case-title{font-size:14px;font-weight:850;line-height:1.35}.chat-case-source{font-size:9px;color:var(--muted);margin-top:4px}
.chat-case-link{font-size:10px;font-weight:800;color:var(--body);text-decoration:none;border:1px solid var(--line);padding:6px 8px;border-radius:7px;white-space:nowrap}
.chat-case-media{background:#eee9e1;min-height:160px;display:flex;align-items:center;justify-content:center;overflow:hidden}.chat-case-media img{width:100%;max-height:250px;object-fit:cover;display:block}
.chat-case-article{width:100%;padding:25px 20px;background:#282624;color:#fff}.chat-case-article small{display:block;font-size:9px;opacity:.65;margin-bottom:8px}.chat-case-article strong{display:block;font-size:17px;line-height:1.4}
.chat-case-doc{width:88%;margin:20px;background:#fff;border:1px solid #d7d0c5;padding:20px;color:var(--ink);box-shadow:0 8px 22px rgba(30,25,20,.06)}.chat-case-doc small{font-size:9px;color:var(--muted)}.chat-case-doc .rule{height:2px;background:var(--ink);margin:10px 0 14px}.chat-case-doc strong{font-size:16px;line-height:1.4}
.chat-case-claim{padding:12px 14px;font-size:12px;line-height:1.58;color:var(--body);border-top:1px solid var(--line)}.chat-case-claim b{display:block;color:var(--ink);font-size:10px;margin-bottom:4px}.chat-case-caption{padding:7px 14px;border-top:1px solid var(--line);font-size:9px;line-height:1.45;color:var(--muted)}
@media(max-width:650px){.chat-case-options{grid-template-columns:1fr}.chat-case-top{flex-direction:column}.chat-case-link{white-space:normal}}
"""
    html = html.replace("</style>", extra_css + "\n</style>")

    script = f"""
<script>
const inlineCaseData={cases_json};
let inlineLessonId=null,inlineCaseId=null;

function resetInlineState(){{
  questions=[];delegationMap={{}};aiOffStarted=false;hasResult=false;requestInFlight=false;
  document.getElementById('offSection')?.classList.add('hidden');
  document.getElementById('resultSection')?.classList.add('hidden');
  input.value='';input.disabled=true;send.disabled=true;finish.disabled=true;
  badge.querySelector('span:last-child').textContent='AI ON';
  badge.querySelector('.mode-dot').style.background='var(--blue)';
}}
function compactTitle(t){{return t.length>25?t.slice(0,25)+'…':t;}}
function pickerHtml(lessonId,activeId=null){{
  const cases=inlineCaseData[lessonId]||[];
  return `<div class="chat-case-picker"><div class="chat-case-picker-head"><div><strong>실제 사례를 골라보세요</strong><br><span>이 주제에 ${{cases.length}}개 사례가 준비되어 있습니다.</span></div><span>선택하면 AI가 바로 질문합니다.</span></div><div class="chat-case-options">${{cases.map((c,i)=>`<button type="button" class="chat-case-option ${{c.id===activeId?'active':''}}" data-case-id="${{c.id}}"><b>${{i+1}}. ${{esc(compactTitle(c.title))}}</b><small>${{esc(c.label)}}</small></button>`).join('')}}</div></div>`;
}}
function bindCaseButtons(lessonId){{chat.querySelectorAll('[data-case-id]').forEach(btn=>btn.addEventListener('click',()=>startCase(lessonId,btn.dataset.caseId)));}}
function caseMedia(c){{
  if(c.media_type==='image'&&c.media_url)return `<div class="chat-case-media"><img src="${{esc(c.media_url)}}" alt="${{esc(c.title)}} 관련 사례 이미지" loading="lazy"></div>`;
  if(c.media_type==='document')return `<div class="chat-case-media"><div class="chat-case-doc"><small>ACTUAL DOCUMENT / CASE</small><div class="rule"></div><strong>${{esc(c.title)}}</strong></div></div>`;
  return `<div class="chat-case-media"><div class="chat-case-article"><small>ACTUAL NEWS / FACT-CHECK</small><strong>${{esc(c.title)}}</strong></div></div>`;
}}
function caseCard(c){{
  return `<div class="chat-case-card"><div class="chat-case-top"><div><div class="chat-case-kicker">${{esc(c.label)}}</div><div class="chat-case-title">${{esc(c.title)}}</div><div class="chat-case-source">사례 출처 · ${{esc(c.source_name)}}</div></div><a class="chat-case-link" href="${{esc(c.source_url)}}" target="_blank" rel="noopener">원문 보기 ↗</a></div>${{caseMedia(c)}}<div class="chat-case-claim"><b>당시 퍼진 주장·상황</b>${{esc(c.claim)}}</div><div class="chat-case-caption">${{esc(c.media_caption)}}</div></div>`;
}}
function showCaseChooser(lessonId){{
  inlineLessonId=lessonId;inlineCaseId=null;sessionId=null;resetInlineState();
  chat.innerHTML=pickerHtml(lessonId);bindCaseButtons(lessonId);chat.scrollTop=0;
  input.placeholder='위에서 실제 사례를 먼저 선택해 주세요.';stageText.textContent='실제 사례를 선택하세요';
}}
async function startCase(lessonId,caseId){{
  if(sessionId&&inlineCaseId&&inlineCaseId!==caseId&&!confirm('다른 사례를 선택하면 현재 대화가 새로 시작됩니다. 바꿀까요?'))return;
  const st=document.getElementById('chatStatus');clearError(st);st.textContent='실제 사례를 불러오고 있어요...';
  try{{
    const r=await fetch('/api/case-start',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{lesson_id:lessonId,case_id:caseId}})}});
    const d=await r.json().catch(()=>({{}}));if(!r.ok)throw new Error(d.detail||'사례를 시작하지 못했습니다.');
    questions=[];delegationMap={{}};aiOffStarted=false;hasResult=false;sessionId=d.session_id;selectedLesson=lessonId;inlineLessonId=lessonId;inlineCaseId=caseId;
    chat.innerHTML=pickerHtml(lessonId,caseId)+caseCard(d.case);bindCaseButtons(lessonId);addMsg('assistant',d.opening_question);
    input.disabled=false;send.disabled=false;finish.disabled=false;input.value='';input.placeholder='내 판단과 이유를 적어보세요.';
    stageText.textContent='AI와 실제 사례 학습 중';st.textContent='';chat.scrollTop=chat.scrollHeight;input.focus();
  }}catch(e){{setError(st,e.message);}}
}}

// literacy_app의 주제 카드 동작 직후, 가상 starter 대신 채팅 안 실제 사례 선택 화면을 연다.
document.querySelectorAll('.lesson-card').forEach(card=>card.addEventListener('click',()=>setTimeout(()=>showCaseChooser(card.dataset.lesson),0)));
input.disabled=true;send.disabled=true;finish.disabled=true;
</script>
"""
    html = html.replace("</body>", script + "\n</body>")
    return html


# literacy_app의 루트 화면만 교체한다. 채팅/분석/AI OFF/재채점 API는 그대로 재사용한다.
base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def inline_case_index():
    return HTMLResponse(_render_index())
