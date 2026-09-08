from __future__ import annotations

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_18 as previous

app = previous.app
base = previous.base
flow = previous.flow


def _render_index_kobaco_v19():
    page = previous._render_index_kobaco_v18()
    patch = r'''
<style>
/* v19: LOGIN 상태표시는 회색/파랑 점 하나만 사용 */
.aioff-auth-state:before{display:none!important}
.aioff-login-indicator{
  display:inline-block;width:7px;height:7px;border-radius:50%;
  flex:0 0 7px;background:#aaa39a;margin-right:6px;vertical-align:1px;
}
.aioff-auth-dock.is-on .aioff-login-indicator{background:#2f75e8}
.aioff-auth-state{display:inline-flex!important;align-items:center!important}

/* 학교 입력을 select와 같은 높이/정렬의 combobox로 보이게 한다. */
.aioff-school-search.aioff-school-combobox{
  position:relative!important;display:block!important;width:100%!important;
}
.aioff-school-search.aioff-school-combobox:after{
  content:"";position:absolute;right:16px;top:50%;width:7px;height:7px;
  border-right:1.5px solid #302c28;border-bottom:1.5px solid #302c28;
  transform:translateY(-68%) rotate(45deg);pointer-events:none;z-index:3;
  transition:transform .12s ease;
}
.aioff-school-search.aioff-school-combobox.is-open:after{
  transform:translateY(-28%) rotate(225deg);
}
#aioff-school-name{
  height:42px!important;min-height:42px!important;box-sizing:border-box!important;
  padding:0 42px 0 12px!important;margin:0!important;
  line-height:40px!important;border-radius:8px!important;
  background:#fff!important;
}
.aioff-school-search.aioff-school-combobox.is-open #aioff-school-name{
  border-bottom-left-radius:0!important;border-bottom-right-radius:0!important;
  border-color:#bdb4a9!important;
}
#aioff-school-results{
  left:0!important;right:0!important;top:calc(100% - 1px)!important;
  width:100%!important;box-sizing:border-box!important;margin:0!important;
  max-height:250px!important;padding:0!important;overflow-y:auto!important;
  border:1px solid #bdb4a9!important;border-top:0!important;
  border-radius:0 0 8px 8px!important;background:#fff!important;
  box-shadow:0 9px 22px rgba(35,29,23,.14)!important;
}
#aioff-school-results:not(.open){display:none!important}
#aioff-school-results.open{display:block!important}
#aioff-school-results.open:before{display:none!important}
#aioff-school-results .aioff-school-result{
  display:block!important;width:100%!important;min-height:48px!important;
  box-sizing:border-box!important;margin:0!important;padding:8px 12px!important;
  border:0!important;border-bottom:1px solid #ece5dc!important;border-radius:0!important;
  background:#fff!important;text-align:left!important;color:#2f2b27!important;
  line-height:1.25!important;white-space:normal!important;
}
#aioff-school-results .aioff-school-result:last-child{border-bottom:0!important}
#aioff-school-results .aioff-school-result:hover,
#aioff-school-results .aioff-school-result.is-active{background:#f2f5fa!important}
#aioff-school-results .aioff-school-result b{
  display:block!important;margin:0 0 3px!important;font-size:12px!important;line-height:1.25!important;
}
#aioff-school-results .aioff-school-result small{
  display:block!important;margin:0!important;font-size:10px!important;line-height:1.3!important;color:#756e67!important;
}
#aioff-school-message{margin-top:6px!important;line-height:1.35!important}
</style>
<script>
(() => {
  const dock=document.querySelector('.aioff-auth-dock');
  const state=dock?.querySelector('.aioff-auth-state');
  if(dock&&state){
    /* 예전 AI ON/OFF 자리에서 남아 있는 작은 빈 점이 있으면 숨기고, 우리가 관리하는 점 하나만 둔다. */
    const prev=dock.previousElementSibling;
    if(prev && !(prev.textContent||'').trim()){
      const r=prev.getBoundingClientRect();
      if(r.width<=16 && r.height<=16) prev.style.display='none';
    }
    if(!state.querySelector('.aioff-login-indicator')){
      const dot=document.createElement('span');
      dot.className='aioff-login-indicator';
      dot.setAttribute('aria-hidden','true');
      state.prepend(dot);
    }
  }

  const input=document.getElementById('aioff-school-name');
  const wrap=input?.closest('.aioff-school-search');
  const box=document.getElementById('aioff-school-results');
  if(!input||!wrap||!box) return;

  wrap.classList.add('aioff-school-combobox');
  input.setAttribute('autocomplete','off');
  input.setAttribute('role','combobox');
  input.setAttribute('aria-autocomplete','list');
  input.setAttribute('aria-controls','aioff-school-results');
  input.setAttribute('spellcheck','false');

  function syncOpen(){
    const open=box.classList.contains('open');
    wrap.classList.toggle('is-open',open);
    input.setAttribute('aria-expanded',open?'true':'false');
  }
  syncOpen();
  new MutationObserver(syncOpen).observe(box,{attributes:true,attributeFilter:['class']});
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v19():
    return HTMLResponse(_render_index_kobaco_v19())
