from __future__ import annotations

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_21 as previous

app = previous.app
base = previous.base
flow = previous.flow


def _render_index_aioff_ui():
    page = previous._render_index_kobaco_v21()
    patch = r'''
<style>
/* 화면 폭을 넓게 쓰되 현재 기능/자료 구조는 그대로 유지한다. */
main{
  width:calc(100% - 24px)!important;
  max-width:1800px!important;
  margin:0 auto!important;
  padding-left:0!important;
  padding-right:0!important;
  padding-top:28px!important;
  padding-bottom:42px!important;
}
.workspace{width:100%!important;max-width:none!important}
.study-paper{width:100%!important;max-width:none!important}

/* 리터러시 사례 학습 제목 옆 AI ON만 제거. 상단 전역 상태표시는 건드리지 않는다. */
.study-paper>.paper-head .mode-label{display:none!important}

/* 자료 영역 + 세로 입력 패널 */
.aioff-learning-columns{
  display:grid;
  grid-template-columns:minmax(0,1fr) clamp(320px,24vw,430px);
  min-height:calc(100vh - 150px);
  border-top:0;
}
.aioff-learning-columns>.chat-area{
  min-width:0;
  padding:18px 20px 18px 24px!important;
  border-right:1px solid var(--line);
}
.aioff-learning-columns .chat{
  height:calc(100vh - 205px)!important;
  min-height:760px!important;
  max-height:none!important;
  padding-bottom:18px!important;
}

.aioff-composer-side{
  min-width:0;
  display:flex;
  flex-direction:column;
  background:#fffdf9;
}
.aioff-composer-side-head{
  padding:18px 18px 14px;
  border-bottom:1px solid var(--line);
}
.aioff-composer-side-head strong{
  display:block;
  margin-bottom:4px;
  font-size:15px;
  color:var(--ink);
}
.aioff-composer-side-head span{
  display:block;
  font-size:11px;
  line-height:1.5;
  color:var(--muted);
}
.aioff-composer-side .composer-wrap{
  flex:1;
  min-height:0;
  display:flex;
  flex-direction:column;
  padding:16px 18px 18px!important;
}
.aioff-composer-side .composer{
  flex:1;
  min-height:0;
  display:flex!important;
  flex-direction:column!important;
  align-items:stretch!important;
  gap:12px!important;
  border-top:0!important;
  padding-top:0!important;
}
.aioff-composer-side .composer textarea{
  flex:1;
  width:100%!important;
  min-height:560px!important;
  max-height:none!important;
  resize:none!important;
  padding:16px!important;
  border-radius:12px!important;
  line-height:1.65!important;
  background:#fff!important;
}
.aioff-composer-side .send-btn{
  align-self:flex-end;
  min-width:96px;
  height:46px!important;
}
.aioff-composer-side .chat-status{
  margin-top:8px!important;
}

/* 큰 자료가 답답하지 않게 학습 카드 폭/높이를 확장한다. */
.education-study-v21{max-width:none!important;width:100%!important}
.education-study-v21-visual iframe{
  height:clamp(620px,72vh,920px)!important;
}
.education-study-v21-visual img{
  width:100%!important;
  max-height:900px!important;
  object-fit:contain!important;
}

@media(max-width:1180px){
  main{width:calc(100% - 20px)!important}
  .aioff-learning-columns{grid-template-columns:minmax(0,1fr) 320px}
  .aioff-composer-side .composer textarea{min-height:500px!important}
}
@media(max-width:900px){
  main{width:100%!important;padding-left:12px!important;padding-right:12px!important}
  .aioff-learning-columns{display:block;min-height:0}
  .aioff-learning-columns>.chat-area{border-right:0;padding:16px!important}
  .aioff-learning-columns .chat{height:680px!important;min-height:680px!important}
  .aioff-composer-side{border-top:1px solid var(--line)}
  .aioff-composer-side .composer textarea{min-height:220px!important}
  .education-study-v21-visual iframe{height:520px!important}
}
</style>
<script>
(() => {
  function installWideLearningLayout(){
    const paper=document.querySelector('.study-paper');
    if(!paper || paper.querySelector('.aioff-learning-columns')) return;

    /* 제목 옆의 AI ON만 제거 */
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
    side.innerHTML='<div class="aioff-composer-side-head"><strong>생각 적기</strong><span>자료를 보면서 판단한 내용이나 궁금한 점을 적어보세요.</span></div>';
    side.appendChild(composerWrap);
    columns.appendChild(side);

    const textarea=composerWrap.querySelector('textarea');
    if(textarea){
      textarea.placeholder='자료를 보면서 생각한 내용을 적어보세요.';
      textarea.setAttribute('aria-label','자료를 보면서 생각한 내용 입력');
    }
  }

  installWideLearningLayout();
  new MutationObserver(installWideLearningLayout).observe(document.body,{childList:true,subtree:true});
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def aioff_ui_index():
    return HTMLResponse(_render_index_aioff_ui())
