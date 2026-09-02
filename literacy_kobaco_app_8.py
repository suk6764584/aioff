from __future__ import annotations

import re

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_7 as previous

# v7의 DB/영상 매칭은 유지하고, 학생 화면과 공익광고 튜터 문구를
# 초등 고학년~중학생 기준으로 짧고 쉽게 다시 정리합니다.
v6 = previous.previous
v5 = v6.previous
app = previous.app
base = previous.base
flow = v5.flow


# ---------------------------------------------------------------------------
# 1) 첫 질문: 한 번만, 짧고 구체적으로
# ---------------------------------------------------------------------------
for case in flow.CASE_LIBRARY.get("deepfake", []):
    title = str(case.get("archive_title") or case.get("title") or "공익광고").split(" · ", 1)[0].strip()
    questions = [
        f"'{title}' 광고를 보고 가장 먼저 떠오른 말을 한 문장으로 적어보세요. 기억에 남은 장면이나 문구도 하나 골라보세요.",
        f"'{title}' 광고에서 가장 기억에 남은 장면이나 문구는 무엇인가요? 그 장면이 어떤 말을 전한다고 느꼈는지도 적어보세요.",
        f"친구에게 '{title}' 광고를 짧게 설명한다면 뭐라고 말하겠어요? 그렇게 생각한 장면이나 문구를 하나 같이 적어보세요.",
    ]
    case["opening_questions"] = questions
    case["opening_question"] = questions[0]


# ---------------------------------------------------------------------------
# 2) 공익광고 대화: 교실 문장처럼 짧게, 한 번에 지표 하나씩
# ---------------------------------------------------------------------------
def _public_ad_prompt_v8(session_id: str, user_message: str, lesson_id: str, case):
    prior = base.core.messages(session_id, 40)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '학습도우미'}: {m['content']}"
        for m in prior
    )
    student_turns = sum(1 for m in prior if m["role"] == "user")
    rows = v5._case_rows(case)
    title = str(case.get("archive_title") or case.get("title") or "공익광고")
    survey = rows.get("조사", "-")
    trust = rows.get("신뢰성", "-")
    channel = rows.get("주요 인지경로", "-")
    impact = rows.get("임팩트 1위", "-")

    if student_turns == 0:
        focus = f"""학생의 첫 답변을 짧게 받아준 뒤 '가장 강한 인상을 준 요소' 조사값 하나만 연결한다.
- 조사값: {impact}
- 예시 말투: 학생이 '문구가 기억났다'고 하면 '조사에서도 나레이션·문구가 가장 강한 인상을 준 요소로 나타났어요.'처럼 비교한다.
- 마지막 질문은 '너에게도 그 부분이 가장 기억에 남았나요, 아니면 다른 장면이 더 기억났나요?'처럼 하나만 묻는다."""
    elif student_turns == 1:
        focus = f"""이번에는 '신뢰성' 하나만 다룬다.
- 조사값: {trust}
- '신뢰성'을 처음 쓸 때는 '광고의 신뢰성을 평가한 항목'이라고 바로 풀어 쓴다.
- 학생에게 이 값이 말해주는 사실을 짧게 표현하게 한다.
- 행동 변화, 실제 효과, 성공 여부로 확대하지 않는다."""
    elif student_turns == 2:
        focus = f"""이번에는 '광고를 접한 경로' 하나만 다룬다.
- 조사값: {channel}
- '인지경로'라는 어려운 말보다 '광고를 어디에서 접했는지 보는 항목'이라고 설명한다.
- 학생에게 이 수치로 바로 말할 수 있는 사실 한 문장을 만들어보게 한다."""
    else:
        focus = """이미 세 가지를 살펴봤다면 새 용어를 더 늘리지 않는다.
학생이 배운 내용을 2~3개의 짧은 문장으로 정리하고, '숫자는 무엇을 물어본 값인지 확인한 뒤 읽는다'는 기준을 남긴다.
같은 질문을 반복하지 않는다."""

    return f"""너는 공공기관의 초등 고학년~중학생 미디어 교육에서 쓰는 학습도우미다.
학생은 실제 KOBACO 공익광고와 효과평가 자료를 보고 있다.

[작품]
{title}

[자료 출처]
한국방송광고진흥공사(KOBACO) 공익광고 효과평가 · {survey}

[실제 조사값]
- 신뢰성: {trust}
- 광고를 접한 경로 중 가장 높은 값: {channel}
- 가장 강한 인상을 준 요소: {impact}

[이번 답변에서 다룰 내용]
{focus}

[문장 규칙]
1. 초등 고학년이 읽어도 바로 이해할 수 있는 단어를 쓴다.
2. 한 답변은 2~4문장, 문장 하나는 되도록 짧게 쓴다.
3. 한 번에 지표 하나만 설명한다. 세 수치를 한꺼번에 길게 나열하지 않는다.
4. '흥미로울 거야', '궁금해지네', '잘 짚어냈어', '강력한 메시지' 같은 인공지능식 칭찬·수식어를 쓰지 않는다.
5. 학생 답이 짧아도 과하게 칭찬하지 말고, 학생이 쓴 말을 그대로 받아 다음 비교로 이어간다.
6. '임팩트'라고만 말하지 말고 '가장 강한 인상을 준 요소'처럼 쉬운 말부터 쓴다.
7. '인지경로'라고만 말하지 말고 '광고를 어디에서 접했는지 보는 항목'처럼 쉬운 말부터 쓴다.
8. '신뢰성'은 공식 항목명으로 필요할 때만 쓰고, '광고의 신뢰성을 평가한 항목'이라고 함께 설명한다.
9. 표에 없는 광고 의도·행동 변화·인과효과를 만들어내지 않는다.
10. 출처가 필요한 설명에는 'KOBACO 효과평가'라고 짧게 밝혀도 좋다.
11. 마지막에는 질문을 하나만 한다.
12. AI OFF 문제는 지금 만들지 않는다.

[이전 대화]
{history or '(없음)'}

[학생의 새 답변]
{user_message}"""


# app5의 라우팅 함수는 런타임에 module global _public_ad_prompt를 찾습니다.
v5._public_ad_prompt = _public_ad_prompt_v8


# ---------------------------------------------------------------------------
# 3) 학생 화면: 큰 제목 + 큰 수치 + 쉬운 뜻 + 출처
# ---------------------------------------------------------------------------
def _render_index_kobaco_v8():
    page = previous._render_index_kobaco_v7()

    # 기존 설명 중 공모전/개발자 관점 문구는 학생용으로 교체합니다.
    replacements = {
        "실제 미디어 데이터를 읽고,<br>AI와 해석 기준을 연습합니다.": "미디어를 보고,<br>생각하고, 데이터로 확인해요.",
        "AI와 해석 기준을 연습합니다.": "미디어를 보고, 생각하고, 데이터로 확인해요.",
        "공식 교육·조사자료를 바탕으로 정리한 뉴스·딥페이크·AI 답변 검증 기준을 사례로 연습합니다. 학습을 마치면 AI OFF가 방금 대화를 분석해, 같은 판단 기준을 혼자 적용해보는 문제 3개를 만듭니다.": "실제 KOBACO 광고·공익광고·미디어 이용 자료를 보고, 내가 본 내용과 조사 결과를 비교하며 미디어를 읽는 방법을 연습합니다.",
        "실제 KOBACO 자료로 연습합니다.": "실제 KOBACO 자료로 배워요.",
        "사례를 고르고 AI 질문에 답하면 실제 데이터와 비교하며 판단 기준을 연습합니다.": "자료를 보고 내 생각을 적은 뒤, 실제 조사 결과와 비교해봅니다.",
        "기존 AI OFF는 그대로": "마지막에는 혼자 풀어봐요",
        "AI와 학습한 대화를 분석하고 AI가 대신한 사고를 학생이 직접 다시 수행하는 기존 구조를 유지합니다. 이번에는 학습 주제를 디지털 리터러시로 구체화했습니다.": "학습이 끝나면 같은 기준을 새 문제에 직접 적용해봅니다. 답을 고친 뒤 다시 확인할 수도 있습니다.",
        "KOBACO PUBLIC AD · STEP 1": "KOBACO 공익광고",
        "아직 조사 수치를 보지 않습니다. 썸네일 또는 광고 영상을 보고 핵심 메시지와 기억에 남는 장면·문구·표현을 먼저 내 말로 설명해보세요.": "",
        "실제 조사 결과는 첫 답변을 보낸 뒤 열립니다. 먼저 광고 자체를 읽어야 내 판단과 조사 결과를 비교할 수 있습니다.": "",
        "광고를 먼저 보고 내 판단 만들기": "광고 보기",
        "DB 조회값": "조사 자료",
        "판단할 해석·상황": "생각해 볼 점",
    }
    for old, new in replacements.items():
        page = page.replace(old, new)

    extra_css = r"""
/* 전체 가독성: 학생 화면에서 본문을 작게 만들지 않습니다. */
body{font-size:15px!important}
.paper-head h2{font-size:26px!important;line-height:1.25!important;font-weight:900!important}
.paper-head p{font-size:15px!important;line-height:1.65!important;max-width:680px!important}
.guide-strip{font-size:14px!important;line-height:1.65!important;padding:14px 17px!important}
.chat{height:455px!important}
.msg{font-size:16px!important;line-height:1.72!important;color:#292521!important}
.speaker{font-size:11px!important;font-weight:900!important;min-width:54px!important;color:#765f45!important}
.composer textarea{font-size:16px!important;min-height:78px!important;padding:14px!important}
.send-btn{font-size:14px!important;font-weight:900!important;padding:0 22px!important}

/* 공익광고 카드 */
.kid-ad-card{width:100%;background:#fff}
.kid-sourcebar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:12px 16px;background:#fff7ef;border-bottom:1px solid #eed9c7;font-size:12px;color:#6b5b4e}
.kid-sourcebar strong{font-size:12.5px;color:#352d27}
.kid-sourcebar .tag{display:inline-flex;padding:4px 7px;border-radius:999px;background:#ef6b42;color:#fff;font-size:10px;font-weight:900}
.kobaco-thumb-stage{height:285px!important}
.kobaco-thumb-title{font-size:26px!important;font-weight:950!important;line-height:1.23!important;max-width:82%!important;text-shadow:0 1px 8px rgba(0,0,0,.28)}
.kobaco-thumb-meta{font-size:12px!important;font-weight:700!important}
.kobaco-ad-actions{padding:13px 16px!important}
.kobaco-ad-action{font-size:12.5px!important;font-weight:900!important;padding:9px 12px!important}

/* 첫 답변 뒤 공개되는 조사 결과 */
.kid-result-wrap{background:#fff}
.kid-result-head{padding:18px 18px 10px}
.kid-result-head span{display:block;font-size:11px;font-weight:900;color:#ef6b42;letter-spacing:.04em;margin-bottom:5px}
.kid-result-head h3{font-size:21px;line-height:1.35;margin:0;color:#24201c;letter-spacing:-.35px}
.kid-stat-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:10px 16px 16px}
.kid-stat{border:1px solid #ddd4c8;border-radius:12px;padding:14px;background:#fff;min-height:185px;box-shadow:0 4px 14px rgba(50,40,30,.035)}
.kid-stat .eyebrow{font-size:11px;font-weight:900;color:#7b6e62;margin-bottom:7px}
.kid-stat .value{display:block;font-size:30px;line-height:1;font-weight:950;color:#ef6338;letter-spacing:-1px;margin-bottom:10px}
.kid-stat .name{display:block;font-size:15px;line-height:1.35;font-weight:900;color:#25211d;margin-bottom:7px}
.kid-stat p{margin:0;font-size:13px;line-height:1.58;color:#5e564e}
.kid-stat p b{color:#2f2a25;font-weight:900}
.kid-stat .meter{height:6px;background:#eee8df;border-radius:999px;overflow:hidden;margin:10px 0 9px}.kid-stat .meter i{display:block;height:100%;background:#ef6b42;border-radius:999px}
.kid-source-note{margin:0 16px 14px;padding:11px 13px;border-radius:9px;background:#f6f3ee;font-size:12px;line-height:1.55;color:#665e56}
.kid-source-note strong{color:#2e2924}
.kid-compare{margin:0 16px 16px;padding:15px 16px;border-left:4px solid #ef6b42;background:#fff8f2;border-radius:0 10px 10px 0}
.kid-compare b{display:block;font-size:15px;margin-bottom:5px;color:#25211d}
.kid-compare span{display:block;font-size:14px;line-height:1.62;color:#5b534b}
.kobaco-evidence{margin:0 16px 16px;border:1px solid #e1d9cf;border-radius:9px;overflow:hidden;background:#faf8f4!important}
.kobaco-evidence summary{font-size:11.5px!important}

/* 사례 헤더도 한눈에 읽히게 */
.chat-case-title{font-size:19px!important;font-weight:950!important;line-height:1.35!important}
.chat-case-kicker{font-size:11px!important;font-weight:900!important}
.chat-case-source{font-size:12px!important}
.chat-case-option b{font-size:14px!important;font-weight:900!important}
.chat-case-option small{font-size:11px!important}

@media(max-width:760px){
  .kid-stat-grid{grid-template-columns:1fr}
  .kid-stat{min-height:0}
  .kobaco-thumb-stage{height:230px!important}
  .kobaco-thumb-title{font-size:21px!important;max-width:76%!important}
  .paper-head h2{font-size:23px!important}
  .msg{font-size:15px!important}
}
"""
    page = page.replace("</style>", extra_css + "\n</style>")

    script = r'''
<script>
const caseMediaKidBase = caseMedia;
const caseCardKidBase = caseCard;
const addMsgKidBase = addMsg;

function kidMetricParts(value){
  const text=String(value||'').trim();
  const m=text.match(/^(.*?)(?:\s*·\s*)?(-?\d+(?:\.\d+)?)%\s*$/);
  if(!m)return {name:text||'-',value:null};
  return {name:(m[1]||'').trim().replace(/[·\s]+$/,''),value:Number(m[2])};
}
function kidPct(value){
  const m=String(value||'').match(/-?\d+(?:\.\d+)?/);
  return m?Number(m[0]):null;
}
function kidStatCard(eyebrow,value,name,description){
  const n=value===null?0:Math.max(0,Math.min(100,value));
  const shown=value===null?'-':`${value.toFixed(1)}%`;
  return `<div class="kid-stat"><div class="eyebrow">${kobacoEsc(eyebrow)}</div><strong class="value">${shown}</strong><span class="name">${kobacoEsc(name)}</span><div class="meter"><i style="width:${n}%"></i></div><p>${description}</p></div>`;
}
function kobacoPublicLearningCard(c){
  const rows=kobacoRows(c);
  const survey=rows['조사']||String(c.title||'').split(' · ').slice(-1)[0]||'';
  const trust=kidPct(rows['신뢰성']);
  const channel=kidMetricParts(rows['주요 인지경로']);
  const impact=kidMetricParts(rows['임팩트 1위']);
  const tables=(c.db_tables||[]).map(x=>kobacoEsc(x)).join(' · ');
  const rawRows=(c.data_rows||[]).map(r=>`<div class="kobaco-data-row"><b>${kobacoEsc(r.label||'항목')}</b><span>${kobacoEsc(r.value||'-')}</span></div>`).join('');
  const title=c.archive_title||String(c.title||'').split(' · ')[0]||'공익광고';
  const source=`한국방송광고진흥공사(KOBACO) 공익광고 효과평가${survey?` · ${kobacoEsc(survey)}`:''}`;

  return `<div class="chat-case-media"><div class="kid-ad-card">
    <div class="kid-sourcebar"><span class="tag">공식 자료</span><strong>${source}</strong></div>
    <div class="kobaco-thumb-stage"><img src="/api/kobaco-media-thumb/${encodeURIComponent(c.id)}" alt="${kobacoEsc(title)} 광고 영상 썸네일" loading="eager"><div class="kobaco-thumb-copy"><div class="kobaco-thumb-kicker">KOBACO 공익광고</div><div class="kobaco-thumb-title">${kobacoEsc(title)}</div><div class="kobaco-thumb-meta">${kobacoEsc([c.archive_year,c.archive_category].filter(Boolean).join(' · '))}</div></div></div>
    <div class="kobaco-ad-actions">${kobacoArchiveButton(c)}${kobacoVideoButton(c)}</div>
    <div class="kobaco-after-answer kid-result-wrap" data-kobaco-after-answer>
      <div class="kid-result-head"><span>실제 조사 결과</span><h3>이 광고를 본 사람들의 응답을 확인해요</h3></div>
      <div class="kid-stat-grid">
        ${kidStatCard('신뢰성',trust,'광고의 신뢰성',`<b>신뢰성</b>은 광고의 신뢰성을 평가한 항목이에요. 이 값만으로 행동 변화까지 알 수는 없어요.`)}
        ${kidStatCard('광고를 접한 경로',channel.value,channel.name||'가장 높은 매체',`사람들이 이 광고를 <b>어떤 매체에서 접했는지</b> 보여주는 비중이에요. 광고의 좋고 나쁨을 뜻하는 점수는 아니에요.`)}
        ${kidStatCard('가장 강한 인상',impact.value,impact.name||'가장 높은 요소',`광고를 볼 때 <b>가장 강한 인상을 준 요소</b>를 조사한 값이에요. 광고 전체의 효과를 하나의 점수로 나타낸 값은 아니에요.`)}
      </div>
      <div class="kid-source-note"><strong>자료 출처</strong> · ${source}<br>작품별 공식 상세페이지와 KOBACO 효과평가 데이터를 함께 사용합니다.</div>
      <div class="kid-compare"><b>내 생각과 비교해보기</b><span>내가 기억한 장면·문구와 조사에서 가장 강한 인상을 준 요소가 같은지 비교해보세요. 숫자는 ‘무엇을 물어본 값인지’ 확인한 뒤 읽는 것이 중요해요.</span></div>
      <details class="kobaco-evidence"><summary>선생님·검토용 세부 데이터 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-kicker">PARQUET / DUCKDB · ${tables}</div><div class="kobaco-data-table">${rawRows}</div><div class="kobaco-data-note">${kobacoEsc(c.data_note||'KOBACO 실제 데이터 조회값')}</div></div></details>
    </div>
  </div></div>`;
}

caseMedia = function(c){
  if(c && String(c.id||'').startsWith('kobaco_publicad_')) return kobacoPublicLearningCard(c);
  return caseMediaKidBase(c);
};

caseCard = function(c){
  if(!c || !String(c.id||'').startsWith('kobaco_publicad_')) return caseCardKidBase(c);
  return `<div class="chat-case-card kobaco-public-case"><div class="chat-case-top"><div><div class="chat-case-kicker">공익광고 효과조사</div><div class="chat-case-title">${kobacoEsc(c.archive_title||String(c.title||'').split(' · ')[0])}</div><div class="chat-case-source">KOBACO 공익광고 효과평가</div></div></div>${caseMedia(c)}</div>`;
};

addMsg = function(role,text){
  addMsgKidBase(role,text);
  if(role==='assistant'){
    const messages=chat.querySelectorAll('.msg');
    const last=messages[messages.length-1];
    const speaker=last&&last.querySelector('.speaker');
    if(speaker)speaker.textContent='도우미';
  }
};

revealKobacoSurvey = function(){
  document.querySelectorAll('[data-kobaco-after-answer]').forEach(el=>el.classList.add('revealed'));
  const first=document.querySelector('[data-kobaco-after-answer].revealed');
  if(first)window.setTimeout(()=>first.scrollIntoView({behavior:'smooth',block:'nearest'}),180);
};
</script>
'''
    page = page.replace("</body>", script + "\n</body>")
    return page


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v8():
    return HTMLResponse(_render_index_kobaco_v8())
