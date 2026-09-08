from __future__ import annotations

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_15 as previous

app = previous.app
base = previous.base
flow = previous.flow


def _render_index_kobaco_v16():
    page = previous._render_index_kobaco_v15()
    patch = r'''
<style>
/* v16 auth UI: LOGIN ON/OFF는 기존 AI ON/OFF 자리의 작은 상태표시로 유지.
   OFF일 때만 아래에 로그인/회원가입 2버튼 박스를 노출한다. */
.aioff-auth-dock{
  position:relative!important;
  top:auto!important;right:auto!important;
  width:auto!important;min-width:0!important;
  padding:0!important;margin:0!important;
  display:inline-flex!important;flex-direction:column!important;
  align-items:flex-end!important;gap:0!important;
  background:transparent!important;border:0!important;border-radius:0!important;
  box-shadow:none!important;white-space:nowrap!important;
  color:#59544f!important;z-index:70!important;
}
.aioff-auth-state{
  display:inline-flex!important;align-items:center!important;justify-content:flex-start!important;
  width:auto!important;min-width:0!important;
  padding:0!important;margin:0!important;border:0!important;background:transparent!important;
  font-size:9px!important;line-height:1.2!important;font-weight:800!important;
  color:#59544f!important;letter-spacing:.02em!important;
}
.aioff-auth-state:before{
  width:6px!important;height:6px!important;margin-right:5px!important;
  flex:0 0 auto!important;background:#aaa39a!important;
}
.aioff-auth-dock.is-on .aioff-auth-state{color:#1b61c8!important}
.aioff-auth-dock.is-on .aioff-auth-state:before{background:#2f75e8!important}

/* OFF 전용 버튼 박스: 기존 카드 크기 유지, 버튼 2개 동일 크기 */
.aioff-auth-links{
  position:absolute!important;top:22px!important;right:0!important;
  width:286px!important;height:74px!important;box-sizing:border-box!important;
  padding:14px!important;
  display:grid!important;grid-template-columns:1fr 1fr!important;gap:10px!important;
  align-items:stretch!important;
  background:#fffdf9!important;border:1px solid #d8d0c5!important;border-radius:12px!important;
  box-shadow:0 8px 24px rgba(35,29,23,.10)!important;
}
.aioff-auth-links button{
  width:100%!important;height:44px!important;min-width:0!important;min-height:44px!important;
  box-sizing:border-box!important;padding:0 12px!important;margin:0!important;
  display:flex!important;align-items:center!important;justify-content:center!important;
  border:1px solid #d2cbc2!important;border-radius:8px!important;
  background:#f4efe8!important;color:#3e3934!important;
  font-size:13px!important;font-weight:850!important;text-decoration:none!important;
}
.aioff-auth-links button:first-of-type{
  background:#22201d!important;border-color:#22201d!important;color:#fff!important;
}
.aioff-auth-dock.is-on .aioff-auth-links{display:none!important}

@media(max-width:700px){
  .aioff-auth-dock{position:relative!important;width:auto!important;margin:0!important}
  .aioff-auth-links{right:0!important;width:286px!important}
}
</style>
<script>
(() => {
  function syncAuthBox(){
    const dock=document.querySelector('.aioff-auth-dock');
    if(!dock) return;
    const links=dock.querySelector('.aioff-auth-links');
    if(!links) return;
    links.setAttribute('aria-hidden', dock.classList.contains('is-on') ? 'true' : 'false');
  }
  syncAuthBox();
  const observer=new MutationObserver(syncAuthBox);
  const dock=document.querySelector('.aioff-auth-dock');
  if(dock) observer.observe(dock,{attributes:true,attributeFilter:['class'],childList:true,subtree:true});
  setTimeout(syncAuthBox,250);
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v16():
    return HTMLResponse(_render_index_kobaco_v16())
