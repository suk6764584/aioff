from fastapi.responses import HTMLResponse

import literacy_media_app_5 as previous
from literacy_cases_5 import CASE_LIBRARY

# v5의 원문 발췌/채팅 내 사례/AI OFF 흐름은 유지합니다.
# 주제별 사례 풀만 9개로 확대하고, 주제를 누를 때마다 그중 3개를 무작위로 보여줍니다.
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


def _render_index_v6():
    html = previous._render_index_v5()

    html = html.replace(
        "3개 주제 · 주제별 실제 사례 3개",
        "3개 주제 · 주제별 실제 사례 9개 중 3개 랜덤",
    )
    html = html.replace(
        "주제를 고르면 이 채팅창 안에 실제 사례 3개가 나타납니다.",
        "주제를 고르면 9개의 실제 사례 풀에서 3개가 무작위로 나타납니다.",
    )
    html = html.replace(
        "주제를 고르면 아래 채팅창 안에서 실제 사례 3개를 선택할 수 있습니다.",
        "주제를 고르면 아래 채팅창에 9개 실제 사례 중 3개가 무작위로 표시됩니다.",
    )

    extra_css = r"""
.chat-case-shuffle{border:0;background:transparent;color:var(--blue);font-size:10px;font-weight:850;cursor:pointer;padding:2px 0}
.chat-case-shuffle:hover{text-decoration:underline}
"""
    html = html.replace("</style>", extra_css + "\n</style>")

    # literacy_media_app_2가 만든 pickerHtml/showCaseChooser를 마지막 스크립트에서 덮어씁니다.
    # CASE_BY_ID는 9개 전체를 유지하므로 실제 선택된 3개 모두 기존 /api/case-start를 그대로 사용합니다.
    script = r"""
<script>
let randomCaseSamples={};

function shuffleCases(items){
  const a=[...items];
  for(let i=a.length-1;i>0;i--){
    const j=Math.floor(Math.random()*(i+1));
    [a[i],a[j]]=[a[j],a[i]];
  }
  return a;
}
function sampleThreeCases(lessonId){
  const all=inlineCaseData[lessonId]||[];
  randomCaseSamples[lessonId]=shuffleCases(all).slice(0,Math.min(3,all.length));
  return randomCaseSamples[lessonId];
}
function currentCaseSample(lessonId){
  return randomCaseSamples[lessonId]||sampleThreeCases(lessonId);
}
function pickerHtml(lessonId,activeId=null){
  const cases=currentCaseSample(lessonId);
  const total=(inlineCaseData[lessonId]||[]).length;
  return `<div class="chat-case-picker"><div class="chat-case-picker-head"><div><strong>실제 사례를 골라보세요</strong><br><span>전체 ${total}개 중 3개가 무작위로 표시됩니다.</span></div><button type="button" class="chat-case-shuffle" data-shuffle-cases>↻ 다른 3개 보기</button></div><div class="chat-case-options">${cases.map((c,i)=>`<button type="button" class="chat-case-option ${c.id===activeId?'active':''}" data-case-id="${c.id}"><b>${i+1}. ${esc(compactTitle(c.title))}</b><small>${esc(c.label)}</small></button>`).join('')}</div></div>`;
}
function bindCaseButtons(lessonId){
  chat.querySelectorAll('[data-case-id]').forEach(btn=>btn.addEventListener('click',()=>startCase(lessonId,btn.dataset.caseId)));
  const shuffle=chat.querySelector('[data-shuffle-cases]');
  if(shuffle)shuffle.addEventListener('click',()=>reshuffleCaseCards(lessonId));
}
function reshuffleCaseCards(lessonId){
  if(sessionId&&inlineCaseId){
    if(!confirm('다른 사례를 보면 현재 대화가 새로 시작됩니다. 바꿀까요?'))return;
    sessionId=null;inlineCaseId=null;resetInlineState();
  }
  sampleThreeCases(lessonId);
  chat.innerHTML=pickerHtml(lessonId);
  bindCaseButtons(lessonId);
  input.disabled=true;send.disabled=true;finish.disabled=true;
  input.placeholder='위에서 실제 사례를 먼저 선택해 주세요.';
  stageText.textContent='실제 사례를 선택하세요';
  chat.scrollTop=0;
}
function showCaseChooser(lessonId){
  inlineLessonId=lessonId;inlineCaseId=null;sessionId=null;resetInlineState();
  sampleThreeCases(lessonId);
  chat.innerHTML=pickerHtml(lessonId);
  bindCaseButtons(lessonId);
  chat.scrollTop=0;
  input.placeholder='위에서 실제 사례를 먼저 선택해 주세요.';
  stageText.textContent='실제 사례를 선택하세요';
}
</script>
"""
    html = html.replace("</body>", script + "\n</body>")
    return html


# v5 루트만 제거하고 랜덤 사례 화면을 등록합니다.
flow.base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def inline_case_index_v6():
    return HTMLResponse(_render_index_v6())
