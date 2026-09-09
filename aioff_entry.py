from __future__ import annotations

from fastapi.responses import HTMLResponse

import news_learning as current

app = current.app
base = current.base

_RENDER_BEFORE_ENTRY = current.runtime._render_runtime_index


def _render_entry_index() -> str:
    page = _RENDER_BEFORE_ENTRY()
    patch = r'''
<style>
/* Final auth header override + full-width guard for the active learning layout. */
.workspace{
  display:block!important;
  grid-template-columns:none!important;
  gap:0!important;
  align-items:stretch!important;
}
.study-paper,
.aioff-learning-columns{
  width:100%!important;
  max-width:none!important;
}

.aioff-auth-dock.aioff-auth-global{
  position:fixed!important;
  top:18px!important;
  right:22px!important;
  z-index:10020!important;
  width:auto!important;
  height:auto!important;
  min-width:0!important;
  min-height:0!important;
  padding:0!important;
  margin:0!important;
  background:transparent!important;
  border:0!important;
  box-shadow:none!important;
  overflow:visible!important;
}

/* Auth-only pseudo cleanup. Never hide/remove learning UI classes globally. */
.aioff-auth-dock *,
.aioff-auth-dock *::before,
.aioff-auth-dock *::after{
  box-sizing:border-box!important;
}
.aioff-auth-dock *::before,
.aioff-auth-dock *::after{
  content:none!important;
  display:none!important;
}
.aioff-auth-dock .mode-dot,
.aioff-auth-dock .status-dot,
.aioff-auth-dock .login-dot,
.aioff-auth-dock .aioff-login-indicator,
.aioff-auth-dock .aioff-mode-dot,
.aioff-auth-dock [data-mode-label],
.aioff-auth-dock .mode-label{
  display:none!important;
}

/* Re-create exactly one state dot: gray OFF / blue ON. */
.aioff-auth-state::before{
  content:""!important;
  display:inline-block!important;
  width:6px!important;
  height:6px!important;
  min-width:6px!important;
  min-height:6px!important;
  margin-right:6px!important;
  border-radius:50%!important;
  background:#aaa39a!important;
  vertical-align:1px!important;
}
.aioff-auth-state::after{content:none!important;display:none!important}
.aioff-auth-dock.is-on .aioff-auth-state::before{background:#2f75e8!important}

/* Logged out: LOGIN OFF, then compact login/signup buttons. */
.aioff-auth-dock:not(.is-on){
  display:inline-flex!important;
  flex-direction:column!important;
  align-items:flex-end!important;
  justify-content:flex-start!important;
  gap:5px!important;
}
.aioff-auth-dock:not(.is-on) .aioff-auth-links{
  position:static!important;
  display:inline-flex!important;
  flex-direction:row!important;
  align-items:center!important;
  justify-content:flex-end!important;
  gap:6px!important;
  width:auto!important;
  height:auto!important;
  min-width:0!important;
  min-height:0!important;
  padding:0!important;
  margin:0!important;
  background:transparent!important;
  border:0!important;
  border-radius:0!important;
  box-shadow:none!important;
  overflow:visible!important;
}
.aioff-auth-dock:not(.is-on) .aioff-auth-links button{
  position:static!important;
  display:inline-flex!important;
  align-items:center!important;
  justify-content:center!important;
  width:auto!important;
  min-width:58px!important;
  height:28px!important;
  min-height:28px!important;
  padding:0 10px!important;
  margin:0!important;
  border:1px solid #d4ccc1!important;
  border-radius:7px!important;
  background:#fffaf3!important;
  color:#514b45!important;
  font-size:9px!important;
  font-weight:800!important;
  line-height:1!important;
  box-shadow:none!important;
}

/* Logged in: greeting + LOGIN ON + logout on one row. */
.aioff-auth-dock.is-on{
  display:inline-flex!important;
  flex-direction:row!important;
  align-items:center!important;
  justify-content:flex-end!important;
  gap:8px!important;
}
.aioff-auth-dock.is-on .aioff-auth-links{
  position:static!important;
  display:inline-flex!important;
  flex-direction:row!important;
  align-items:center!important;
  gap:6px!important;
  width:auto!important;
  height:auto!important;
  min-width:0!important;
  min-height:0!important;
  padding:0!important;
  margin:0!important;
  background:transparent!important;
  border:0!important;
  border-radius:0!important;
  box-shadow:none!important;
}
.aioff-auth-dock.is-on .aioff-auth-links>span{display:none!important}
.aioff-auth-dock.is-on .aioff-auth-links button{
  position:static!important;
  display:inline-flex!important;
  align-items:center!important;
  justify-content:center!important;
  width:auto!important;
  min-width:0!important;
  height:30px!important;
  min-height:30px!important;
  padding:0 11px!important;
  margin:0!important;
  border:1px solid #cfc7bc!important;
  border-radius:7px!important;
  background:#f7f3ed!important;
  color:#514b45!important;
  font-size:10px!important;
  font-weight:800!important;
  line-height:1!important;
  box-shadow:none!important;
}
.aioff-auth-greeting{
  font-size:10px!important;
  font-weight:750!important;
  color:#4c4742!important;
  white-space:nowrap!important;
}
</style>
<script>
(() => {
  function cleanAuthArtifacts(){
    const dock=document.querySelector('.aioff-auth-dock');
    if(!dock) return;

    /* Hide auth-only legacy indicators. Do not remove learning DOM nodes. */
    dock.querySelectorAll('.mode-dot,.status-dot,.login-dot,.aioff-login-indicator,.aioff-mode-dot,[data-mode-label],.mode-label').forEach(el=>{
      el.style.setProperty('display','none','important');
    });

    /* Standalone ON labels are hidden, not removed, so existing JS references stay valid. */
    document.querySelectorAll('body *').forEach(el=>{
      if(el.closest('.aioff-auth-state')) return;
      const text=(el.textContent||'').trim().replace(/\s+/g,' ');
      if(el.children.length===0 && (text==='ON'||text==='AI ON')){
        el.style.setProperty('display','none','important');
      }
    });

    /* Empty legacy auth indicators only; keep structural auth elements. */
    dock.querySelectorAll('*').forEach(el=>{
      if(el.matches('.aioff-auth-state,.aioff-auth-links,.aioff-auth-greeting,button')) return;
      if(el.children.length===0 && !(el.textContent||'').trim()) el.style.setProperty('display','none','important');
    });
  }

  cleanAuthArtifacts();
  new MutationObserver(cleanAuthArtifacts).observe(document.body,{childList:true,subtree:true,characterData:true});
})();
</script>
'''
    return page.replace('</body>', patch + '\n</body>')


base._remove_route('/', 'GET')


@app.get('/', response_class=HTMLResponse)
def aioff_entry_index():
    return HTMLResponse(_render_entry_index())
