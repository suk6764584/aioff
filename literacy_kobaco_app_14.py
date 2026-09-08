from __future__ import annotations

import os

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

import auth_proto as auth
import literacy_kobaco_app_13 as previous

app = previous.app
base = previous.base
flow = previous.flow


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=100)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=100)
    name: str = Field(min_length=1, max_length=30)
    phone: str = Field(min_length=8, max_length=30)
    school_level: str
    school_region: str
    school_name: str = Field(min_length=1, max_length=120)
    school_code: str = Field(default="", max_length=30)
    grade: int


def _set_session_cookie(response: JSONResponse, token: str) -> None:
    secure = os.getenv("AUTH_COOKIE_SECURE", "1").strip().lower() not in {"0", "false", "no"}
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=token,
        max_age=auth.SESSION_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = auth.current_user(request.cookies.get(auth.COOKIE_NAME))
    return {"logged_in": bool(user), "user": user}


@app.post("/api/auth/login")
def auth_login(payload: LoginRequest):
    user = auth.authenticate(payload.email, payload.password)
    if not user:
        raise HTTPException(401, "이메일 또는 비밀번호를 확인해 주세요.")
    token = auth.create_session(int(user["id"]))
    response = JSONResponse({"ok": True, "user": user})
    _set_session_cookie(response, token)
    return response


@app.post("/api/auth/register")
def auth_register(payload: RegisterRequest):
    try:
        user = auth.create_user(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    token = auth.create_session(int(user["id"]))
    response = JSONResponse({"ok": True, "user": user})
    _set_session_cookie(response, token)
    return response


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    token = request.cookies.get(auth.COOKIE_NAME)
    auth.delete_session(token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


@app.get("/api/auth/schools")
def auth_school_search(region: str, school_level: str, q: str):
    try:
        return auth.search_schools(region, school_level, q)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        base.core.logger.warning("school search failed: %s", type(exc).__name__)
        raise HTTPException(502, "학교 검색 중 오류가 발생했습니다. 학교명을 직접 입력해도 됩니다.")


def _render_index_kobaco_v14():
    page = previous._render_index_kobaco_v13()
    patch = r'''
<style>
/* v14 prototype member flow: current learning UI is unchanged. */
.aioff-auth-dock{display:inline-flex;flex-direction:column;align-items:flex-end;gap:2px;font-size:9px;line-height:1.2;color:#5b5650;white-space:nowrap;z-index:20}
.aioff-auth-state{border:0;background:transparent;padding:0;cursor:pointer;font:800 9px/1.2 inherit;color:#59544f;letter-spacing:.02em}
.aioff-auth-state:before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:5px;background:#aaa39a;vertical-align:1px}
.aioff-auth-dock.is-on .aioff-auth-state{color:#1b61c8}.aioff-auth-dock.is-on .aioff-auth-state:before{background:#2f75e8}
.aioff-auth-links{display:flex;gap:7px;align-items:center}.aioff-auth-links button{border:0;background:none;padding:0;color:#736d66;font-size:8px;cursor:pointer}.aioff-auth-links button:hover{text-decoration:underline}
.aioff-auth-fallback{position:fixed;top:19px;right:18px}

#aioff-auth-overlay{position:fixed;inset:0;z-index:10000;background:rgba(25,22,19,.28);display:none;align-items:center;justify-content:center;padding:20px}
#aioff-auth-overlay.open{display:flex}
.aioff-auth-modal{width:min(420px,calc(100vw - 30px));max-height:calc(100vh - 40px);overflow:auto;background:#f8f5ef;border:1px solid #d9d2c8;border-radius:10px;box-shadow:0 20px 55px rgba(30,25,20,.23)}
.aioff-auth-head{display:flex;align-items:flex-start;justify-content:space-between;padding:18px 20px 13px;border-bottom:1px solid #ded7cd}.aioff-auth-head h3{margin:0;font-size:17px}.aioff-auth-head p{margin:4px 0 0;color:#756f68;font-size:10px}.aioff-auth-close{border:0;background:none;font-size:18px;cursor:pointer;color:#716b65}
.aioff-auth-tabs{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid #ded7cd}.aioff-auth-tab{padding:11px;border:0;background:#eee9e1;color:#6e6760;font-weight:800;cursor:pointer}.aioff-auth-tab.active{background:#fff;color:#171513}
.aioff-auth-pane{display:none;padding:18px 20px 20px;background:#fff}.aioff-auth-pane.active{display:block}
.aioff-auth-form{display:grid;gap:10px}.aioff-auth-row{display:grid;grid-template-columns:1fr 1fr;gap:9px}.aioff-auth-field{display:grid;gap:5px}.aioff-auth-field label{font-size:9px;font-weight:800;color:#5e5852}.aioff-auth-field input,.aioff-auth-field select{width:100%;box-sizing:border-box;border:1px solid #cec7bd;border-radius:6px;background:#fff;padding:9px 10px;font-size:11px;color:#171513;outline:none}.aioff-auth-field input:focus,.aioff-auth-field select:focus{border-color:#2f75e8;box-shadow:0 0 0 2px rgba(47,117,232,.10)}
.aioff-phone-group{display:grid;grid-template-columns:58px 8px 1fr 8px 1fr;align-items:center;gap:4px}.aioff-phone-group span{text-align:center;color:#8a8279;font-size:10px}.aioff-phone-group input{text-align:center}.aioff-phone-prefix{background:#f2eee8!important;color:#5f5952!important;font-weight:800}
.aioff-auth-submit{border:0;border-radius:6px;background:#22201d;color:#fff;padding:10px 12px;font-weight:850;font-size:11px;cursor:pointer}.aioff-auth-submit:hover{background:#111}
.aioff-auth-note{font-size:9px;line-height:1.5;color:#777067}.aioff-auth-message{min-height:15px;font-size:9px;color:#bf4b2e}.aioff-auth-message.ok{color:#1a6d49}
.aioff-school-search{display:grid;grid-template-columns:1fr auto;gap:6px}.aioff-school-search button{border:1px solid #cfc7bc;background:#f6f1e9;border-radius:6px;padding:0 11px;font-size:9px;font-weight:800;cursor:pointer}.aioff-school-results{display:none;border:1px solid #d9d1c7;border-radius:6px;overflow:hidden;max-height:145px;overflow-y:auto}.aioff-school-results.open{display:block}.aioff-school-result{display:block;width:100%;border:0;border-bottom:1px solid #eee8e0;background:#fff;text-align:left;padding:8px 9px;cursor:pointer}.aioff-school-result:last-child{border-bottom:0}.aioff-school-result b{display:block;font-size:10px}.aioff-school-result small{display:block;color:#7e766e;font-size:8px;margin-top:2px}
#aioff-login-required{position:fixed;left:50%;top:82px;transform:translateX(-50%) translateY(-8px);z-index:9999;display:none;align-items:center;gap:12px;min-width:280px;max-width:calc(100vw - 30px);padding:11px 13px;border:1px solid #d8d0c5;background:#fffdf9;border-radius:8px;box-shadow:0 9px 30px rgba(35,29,23,.16);font-size:10px;color:#3f3a35}#aioff-login-required.show{display:flex;transform:translateX(-50%) translateY(0)}#aioff-login-required b{font-size:10px}#aioff-login-required button{margin-left:auto;border:0;border-radius:5px;background:#22201d;color:#fff;padding:7px 10px;font-size:9px;font-weight:800;cursor:pointer}
@media(max-width:600px){.aioff-auth-row{grid-template-columns:1fr}.aioff-auth-modal{width:min(390px,calc(100vw - 20px))}}
</style>

<div id="aioff-login-required"><span><b>로그인이 필요합니다.</b><br>학습 주제를 선택하려면 먼저 로그인해 주세요.</span><button type="button" data-auth-open="login">로그인</button></div>

<div id="aioff-auth-overlay" aria-hidden="true">
  <div class="aioff-auth-modal" role="dialog" aria-modal="true" aria-label="AI OFF 로그인 및 회원가입">
    <div class="aioff-auth-head"><div><h3>AI OFF</h3><p>학습 기록을 이어가기 위한 프로토타입 회원 기능입니다.</p></div><button type="button" class="aioff-auth-close" aria-label="닫기">×</button></div>
    <div class="aioff-auth-tabs"><button type="button" class="aioff-auth-tab active" data-auth-tab="login">로그인</button><button type="button" class="aioff-auth-tab" data-auth-tab="register">회원가입</button></div>
    <div class="aioff-auth-pane active" data-auth-pane="login">
      <form id="aioff-login-form" class="aioff-auth-form">
        <div class="aioff-auth-field"><label>이메일</label><input name="email" type="email" autocomplete="email" required pattern="[^@\s]+@[^@\s]+\.[^@\s]+" title="example@example.com 형식으로 입력해 주세요." placeholder="student@example.com"></div>
        <div class="aioff-auth-field"><label>비밀번호</label><input name="password" type="password" autocomplete="current-password" required placeholder="비밀번호"></div>
        <div id="aioff-login-message" class="aioff-auth-message"></div>
        <button class="aioff-auth-submit" type="submit">LOGIN</button>
      </form>
    </div>
    <div class="aioff-auth-pane" data-auth-pane="register">
      <form id="aioff-register-form" class="aioff-auth-form">
        <div class="aioff-auth-row">
          <div class="aioff-auth-field"><label>이름</label><input name="name" required maxlength="30"></div>
          <div class="aioff-auth-field"><label>전화번호</label><div class="aioff-phone-group"><input class="aioff-phone-prefix" id="aioff-phone-1" type="text" value="010" readonly aria-label="전화번호 앞자리"><span>-</span><input id="aioff-phone-2" type="text" inputmode="numeric" autocomplete="tel-local-prefix" required minlength="4" maxlength="4" pattern="[0-9]{4}" aria-label="전화번호 가운데 4자리"><span>-</span><input id="aioff-phone-3" type="text" inputmode="numeric" autocomplete="tel-local-suffix" required minlength="4" maxlength="4" pattern="[0-9]{4}" aria-label="전화번호 마지막 4자리"></div><input name="phone" id="aioff-phone-value" type="hidden"></div>
        </div>
        <div class="aioff-auth-field"><label>이메일</label><input name="email" type="email" autocomplete="email" required pattern="[^@\s]+@[^@\s]+\.[^@\s]+" title="example@example.com 형식으로 입력해 주세요." placeholder="student@example.com"></div>
        <div class="aioff-auth-field"><label>비밀번호</label><input name="password" type="password" autocomplete="new-password" minlength="6" required placeholder="6자 이상"></div>
        <div class="aioff-auth-row"><div class="aioff-auth-field"><label>지역</label><select name="school_region" id="aioff-school-region" required><option value="">지역 선택</option><option>서울</option><option>부산</option><option>대구</option><option>인천</option><option>광주</option><option>대전</option><option>울산</option><option>세종</option><option>경기</option><option>강원</option><option>충북</option><option>충남</option><option>전북</option><option>전남</option><option>경북</option><option>경남</option><option>제주</option></select></div><div class="aioff-auth-field"><label>학교급</label><select name="school_level" id="aioff-school-level" required><option value="">학교급 선택</option><option value="초">초등</option><option value="중">중등</option><option value="고">고등</option></select></div></div>
        <div class="aioff-auth-field"><label>학교</label><div class="aioff-school-search"><input name="school_name" id="aioff-school-name" required placeholder="학교명을 입력하고 검색"><button type="button" id="aioff-school-search-btn">학교 검색</button></div><input name="school_code" id="aioff-school-code" type="hidden"><div id="aioff-school-results" class="aioff-school-results"></div><div id="aioff-school-message" class="aioff-auth-note">지역과 학교급을 고른 뒤 학교명을 검색할 수 있습니다.</div></div>
        <div class="aioff-auth-field"><label>학년</label><select name="grade" id="aioff-grade" required><option value="">학교급을 먼저 선택해 주세요</option></select></div>
        <div class="aioff-auth-note">프로토타입이므로 이메일·전화번호 인증 절차는 생략합니다.</div>
        <div id="aioff-register-message" class="aioff-auth-message"></div>
        <button class="aioff-auth-submit" type="submit">회원가입</button>
      </form>
    </div>
  </div>
</div>

<script>
(() => {
  const TOPIC_TITLES=['AI가 읽은 광고 vs 사람이 읽은 맥락','공익광고 효과 수치 제대로 읽기','청소년·OTT 통계에서 사실과 해석 구분하기'];
  let authUser=null;
  let dock=null;
  const overlay=document.getElementById('aioff-auth-overlay');
  const requiredBox=document.getElementById('aioff-login-required');

  function escapeHtml(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  async function api(url,options={}){
    const response=await fetch(url,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
    let data={}; try{data=await response.json();}catch(e){}
    if(!response.ok) throw new Error(data.detail||data.message||`HTTP ${response.status}`);
    return data;
  }
  function openAuth(tab='login'){
    overlay.classList.add('open'); overlay.setAttribute('aria-hidden','false'); setTab(tab);
    setTimeout(()=>overlay.querySelector(`[data-auth-pane="${tab}"] input`)?.focus(),30);
  }
  function closeAuth(){overlay.classList.remove('open'); overlay.setAttribute('aria-hidden','true');}
  function setTab(tab){
    document.querySelectorAll('[data-auth-tab]').forEach(x=>x.classList.toggle('active',x.dataset.authTab===tab));
    document.querySelectorAll('[data-auth-pane]').forEach(x=>x.classList.toggle('active',x.dataset.authPane===tab));
  }
  function findOldStatus(){
    const nodes=[...document.body.querySelectorAll('*')];
    return nodes.find(el=>el.children.length===0 && el.textContent.trim()==='AI ON')||null;
  }
  function makeDock(){
    const el=document.createElement('span'); el.className='aioff-auth-dock';
    el.innerHTML='<button type="button" class="aioff-auth-state">LOGIN OFF</button><span class="aioff-auth-links"><button type="button" data-auth-open="login">로그인</button><button type="button" data-auth-open="register">회원가입</button></span>';
    el.querySelector('.aioff-auth-state').addEventListener('click',()=>{if(!authUser) openAuth('login');});
    return el;
  }
  function installDock(){
    if(dock?.isConnected) return true;
    const old=findOldStatus(); dock=makeDock();
    if(old){old.replaceWith(dock);}else{dock.classList.add('aioff-auth-fallback');document.body.appendChild(dock);}
    renderDock(); return !!old;
  }
  function renderDock(){
    if(!dock) return;
    dock.classList.toggle('is-on',!!authUser);
    dock.querySelector('.aioff-auth-state').textContent=authUser?'LOGIN ON':'LOGIN OFF';
    const links=dock.querySelector('.aioff-auth-links');
    if(authUser){links.innerHTML=`<span>${escapeHtml(authUser.name)} · ${escapeHtml(authUser.school_level)}${escapeHtml(authUser.grade)}학년</span><button type="button" data-auth-logout>로그아웃</button>`;}
    else{links.innerHTML='<button type="button" data-auth-open="login">로그인</button><button type="button" data-auth-open="register">회원가입</button>';}
  }
  async function refreshAuth(){
    try{const data=await api('/api/auth/me',{method:'GET',headers:{}});authUser=data.user||null;}catch(e){authUser=null;}
    installDock(); renderDock();
  }
  function showLoginRequired(){
    requiredBox.classList.add('show'); clearTimeout(showLoginRequired.t); showLoginRequired.t=setTimeout(()=>requiredBox.classList.remove('show'),3500);
  }
  function topicAncestor(target){
    let node=target;
    for(let i=0;i<8 && node && node!==document.body;i++,node=node.parentElement){
      const text=(node.textContent||'').replace(/\s+/g,' ').trim();
      if(TOPIC_TITLES.some(title=>text.includes(title))) return node;
    }
    return null;
  }

  document.addEventListener('click',async e=>{
    const open=e.target.closest?.('[data-auth-open]'); if(open){e.preventDefault();openAuth(open.dataset.authOpen||'login');return;}
    const logout=e.target.closest?.('[data-auth-logout]'); if(logout){e.preventDefault();try{await api('/api/auth/logout',{method:'POST',body:'{}'});}catch(err){}authUser=null;renderDock();return;}
    if(!authUser && topicAncestor(e.target)){e.preventDefault();e.stopImmediatePropagation();showLoginRequired();return;}
  },true);

  overlay.querySelector('.aioff-auth-close').addEventListener('click',closeAuth);
  overlay.addEventListener('click',e=>{if(e.target===overlay) closeAuth();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape') closeAuth();});
  document.querySelectorAll('[data-auth-tab]').forEach(btn=>btn.addEventListener('click',()=>setTab(btn.dataset.authTab)));

  document.getElementById('aioff-login-form').addEventListener('submit',async e=>{
    e.preventDefault(); const form=e.currentTarget; const msg=document.getElementById('aioff-login-message'); msg.textContent=''; msg.classList.remove('ok');
    const values=Object.fromEntries(new FormData(form));
    try{const data=await api('/api/auth/login',{method:'POST',body:JSON.stringify(values)});authUser=data.user;msg.textContent='로그인되었습니다.';msg.classList.add('ok');renderDock();setTimeout(closeAuth,250);}catch(err){msg.textContent=err.message;}
  });

  const phone2=document.getElementById('aioff-phone-2');
  const phone3=document.getElementById('aioff-phone-3');
  const phoneValue=document.getElementById('aioff-phone-value');
  function digitsOnly(input){input.value=input.value.replace(/\D/g,'').slice(0,4);}
  phone2.addEventListener('input',()=>{digitsOnly(phone2);if(phone2.value.length===4)phone3.focus();});
  phone3.addEventListener('input',()=>digitsOnly(phone3));
  phone3.addEventListener('keydown',e=>{if(e.key==='Backspace'&&!phone3.value){phone2.focus();}});

  const level=document.getElementById('aioff-school-level');
  const region=document.getElementById('aioff-school-region');
  const grade=document.getElementById('aioff-grade');
  const schoolName=document.getElementById('aioff-school-name');
  const schoolCode=document.getElementById('aioff-school-code');
  function rebuildGrades(){
    const count=level.value==='초'?6:(level.value==='중'||level.value==='고'?3:0); grade.innerHTML=count?'<option value="">학년 선택</option>'+Array.from({length:count},(_,i)=>`<option value="${i+1}">${i+1}학년</option>`).join(''):'<option value="">학교급을 먼저 선택해 주세요</option>'; schoolCode.value='';
  }
  level.addEventListener('change',rebuildGrades); region.addEventListener('change',()=>schoolCode.value=''); schoolName.addEventListener('input',()=>schoolCode.value='');

  document.getElementById('aioff-school-search-btn').addEventListener('click',async()=>{
    const box=document.getElementById('aioff-school-results'); const note=document.getElementById('aioff-school-message'); box.classList.remove('open'); box.innerHTML='';
    if(!region.value||!level.value){note.textContent='지역과 학교급을 먼저 선택해 주세요.';return;}
    if(schoolName.value.trim().length<2){note.textContent='학교명을 2글자 이상 입력해 주세요.';return;}
    note.textContent='학교를 검색하고 있습니다…';
    try{
      const data=await api(`/api/auth/schools?region=${encodeURIComponent(region.value)}&school_level=${encodeURIComponent(level.value)}&q=${encodeURIComponent(schoolName.value.trim())}`,{method:'GET',headers:{}});
      if(!data.configured){note.textContent=data.message||'학교 검색 API가 아직 연결되지 않았습니다. 학교명을 직접 입력해 주세요.';return;}
      if(!data.items?.length){note.textContent='검색 결과가 없습니다. 학교명을 다시 확인하거나 직접 입력해 주세요.';return;}
      box.innerHTML=data.items.map((x,i)=>`<button type="button" class="aioff-school-result" data-school-index="${i}"><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.address||'')}</small></button>`).join('');
      box.classList.add('open'); note.textContent=`${data.items.length}개 학교를 찾았습니다.`;
      box.querySelectorAll('[data-school-index]').forEach(btn=>btn.addEventListener('click',()=>{const item=data.items[Number(btn.dataset.schoolIndex)];schoolName.value=item.name;schoolCode.value=item.code||'';box.classList.remove('open');note.textContent=`${item.name} 선택됨`; }));
    }catch(err){note.textContent=err.message;}
  });

  document.getElementById('aioff-register-form').addEventListener('submit',async e=>{
    e.preventDefault(); const form=e.currentTarget; const msg=document.getElementById('aioff-register-message'); msg.textContent=''; msg.classList.remove('ok');
    digitsOnly(phone2); digitsOnly(phone3);
    if(phone2.value.length!==4||phone3.value.length!==4){msg.textContent='전화번호 가운데/마지막 번호를 숫자 4자리씩 입력해 주세요.';return;}
    phoneValue.value=`010${phone2.value}${phone3.value}`;
    const values=Object.fromEntries(new FormData(form)); values.grade=Number(values.grade||0);
    try{const data=await api('/api/auth/register',{method:'POST',body:JSON.stringify(values)});authUser=data.user;msg.textContent='회원가입이 완료되었습니다.';msg.classList.add('ok');renderDock();setTimeout(closeAuth,350);}catch(err){msg.textContent=err.message;}
  });

  refreshAuth();
  let tries=0; const timer=setInterval(()=>{tries++;const exact=installDock();if(exact||tries>12)clearInterval(timer);},180);
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v14():
    return HTMLResponse(_render_index_kobaco_v14())
