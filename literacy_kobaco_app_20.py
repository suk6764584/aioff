from __future__ import annotations

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_19 as previous

app = previous.app
base = previous.base
flow = previous.flow


def _render_index_kobaco_v20():
    page = previous._render_index_kobaco_v19()
    patch = r'''
<style>
/* v20 auth status: original AI ON/OFF-style dot only.
   OFF = gray, ON = blue. Logout stays on the same row with a small gap. */
.aioff-login-indicator{display:none!important}
.aioff-auth-state:before{
  content:""!important;
  display:inline-block!important;
  width:7px!important;height:7px!important;
  border-radius:50%!important;
  margin-right:6px!important;
  flex:0 0 7px!important;
  background:#aaa39a!important;
  vertical-align:1px!important;
}
.aioff-auth-dock.is-on .aioff-auth-state:before{background:#2f75e8!important}

.aioff-auth-dock.is-on{
  display:inline-flex!important;
  flex-direction:row!important;
  align-items:center!important;
  justify-content:flex-end!important;
  gap:10px!important;
}
.aioff-auth-dock.is-on .aioff-auth-state{
  display:inline-flex!important;
  align-items:center!important;
  margin:0!important;
  padding:0!important;
}
.aioff-auth-dock.is-on .aioff-auth-links{
  position:static!important;
  display:inline-flex!important;
  align-items:center!important;
  width:auto!important;height:auto!important;
  padding:0!important;margin:0!important;
  background:transparent!important;
  border:0!important;box-shadow:none!important;
}
.aioff-auth-dock.is-on .aioff-auth-links span{display:none!important}
.aioff-auth-dock.is-on .aioff-auth-links button,
.aioff-auth-dock.is-on .aioff-auth-links button:first-of-type{
  width:auto!important;
  min-width:72px!important;
  height:32px!important;
  min-height:32px!important;
  padding:0 12px!important;
  margin:0!important;
  border:1px solid #cfc7bc!important;
  border-radius:8px!important;
  background:#f7f3ed!important;
  color:#514b45!important;
  font-size:11px!important;
  font-weight:800!important;
}
</style>
<script>
(() => {
  /* v19가 넣었던 별도 span 점은 제거하고 :before 점 하나만 사용한다. */
  document.querySelectorAll('.aioff-login-indicator').forEach(el=>el.remove());

  /* 로그인/로그아웃으로 state textContent가 다시 그려져도 pseudo-element라 항상 유지된다. */
  const dock=document.querySelector('.aioff-auth-dock');
  if(!dock) return;
  const cleanExtraDot=()=>document.querySelectorAll('.aioff-login-indicator').forEach(el=>el.remove());
  new MutationObserver(cleanExtraDot).observe(dock,{childList:true,subtree:true});
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v20():
    return HTMLResponse(_render_index_kobaco_v20())
