from __future__ import annotations

import base64
import os
import re
import secrets
import sqlite3
import time

import requests
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

import auth_proto as auth
import literacy_kobaco_app_17 as previous

app = previous.app
base = previous.base
flow = previous.flow


# v18 auth migration: 이메일은 연락정보로 유지하고, 로그인용 아이디를 별도 저장한다.
def _ensure_login_id_column() -> None:
    with auth._connect() as conn:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "login_id" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN login_id TEXT")
        conn.execute(
            "UPDATE users SET login_id=email WHERE login_id IS NULL OR TRIM(login_id)=''"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login_id ON users(login_id)"
        )
        conn.commit()


_ensure_login_id_column()


def _normalize_login_id(value: str) -> str:
    return (value or "").strip().lower()


class LoginRequestV18(BaseModel):
    login_id: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=1, max_length=100)


class RegisterRequestV18(BaseModel):
    login_id: str = Field(min_length=3, max_length=30)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=100)
    name: str = Field(min_length=1, max_length=30)
    phone: str = Field(min_length=8, max_length=30)
    school_level: str
    school_region: str
    school_name: str = Field(min_length=1, max_length=120)
    school_code: str = Field(default="", max_length=30)
    grade: int


def _set_session_cookie_v18(response: JSONResponse, token: str) -> None:
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


base._remove_route("/api/auth/login", "POST")
base._remove_route("/api/auth/register", "POST")


@app.post("/api/auth/login")
def auth_login_v18(payload: LoginRequestV18):
    login_id = _normalize_login_id(payload.login_id)
    with auth._connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(login_id)=? OR LOWER(email)=? LIMIT 1",
            (login_id, login_id),
        ).fetchone()
    if not row:
        raise HTTPException(401, "아이디 또는 비밀번호를 확인해 주세요.")

    try:
        salt = base64.b64decode(row["password_salt"])
        expected = base64.b64decode(row["password_hash"])
    except Exception:
        raise HTTPException(401, "아이디 또는 비밀번호를 확인해 주세요.")

    actual = auth._hash_password(payload.password, salt)
    if not auth.hmac.compare_digest(actual, expected):
        raise HTTPException(401, "아이디 또는 비밀번호를 확인해 주세요.")

    user = auth._public_user(row)
    token = auth.create_session(int(row["id"]))
    response = JSONResponse({"ok": True, "user": user})
    _set_session_cookie_v18(response, token)
    return response


@app.post("/api/auth/register")
def auth_register_v18(payload: RegisterRequestV18):
    login_id = _normalize_login_id(payload.login_id)
    if not re.fullmatch(r"[^\s@]{3,30}", login_id):
        raise HTTPException(400, "아이디는 공백 없이 3~30자로 입력해 주세요.")

    try:
        clean = auth.validate_registration(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    salt = secrets.token_bytes(16)
    digest = auth._hash_password(clean.pop("password"), salt)
    now = int(time.time())

    try:
        with auth._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM users WHERE LOWER(login_id)=? LIMIT 1", (login_id,)
            ).fetchone()
            if existing:
                raise HTTPException(400, "이미 사용 중인 아이디입니다.")

            cur = conn.execute(
                """
                INSERT INTO users(
                    login_id,email,password_hash,password_salt,name,phone,
                    school_level,school_region,school_name,school_code,grade,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    login_id,
                    clean["email"],
                    base64.b64encode(digest).decode("ascii"),
                    base64.b64encode(salt).decode("ascii"),
                    clean["name"],
                    clean["phone"],
                    clean["school_level"],
                    clean["school_region"],
                    clean["school_name"],
                    clean["school_code"],
                    clean["grade"],
                    now,
                ),
            )
            user_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            conn.commit()
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(400, "이미 가입된 이메일이거나 사용 중인 아이디입니다.")

    user = auth._public_user(row)
    token = auth.create_session(user_id)
    response = JSONResponse({"ok": True, "user": user})
    _set_session_cookie_v18(response, token)
    return response


# v18: 학교 검색은 한 줄짜리 autocomplete UI로 동작한다.
# - 빈 입력에서도 지역/학교급 기준 목록을 보여준다.
# - 입력 중에는 관련 학교만 다시 검색한다.
# - 목록을 선택하지 않아도 직접 입력한 학교명을 그대로 제출할 수 있다.
base._remove_route("/api/auth/schools", "GET")


@app.get("/api/auth/schools")
def auth_school_search_v18(region: str, school_level: str, q: str = ""):
    region = (region or "").strip()
    school_level = (school_level or "").strip()
    query = (q or "").strip()

    if region not in auth.REGION_CODES:
        raise HTTPException(400, "지역을 선택해 주세요.")
    if school_level not in auth.SCHOOL_LEVEL_NAMES:
        raise HTTPException(400, "학교급을 선택해 주세요.")

    key = os.getenv("NEIS_API_KEY", "").strip()
    sample_mode = not bool(key)

    params = {
        "Type": "json",
        "pIndex": 1,
        "pSize": 5 if sample_mode else 100,
        "ATPT_OFCDC_SC_CODE": auth.REGION_CODES[region],
        "SCHUL_KND_SC_NM": auth.SCHOOL_LEVEL_NAMES[school_level],
    }
    if query:
        params["SCHUL_NM"] = query
    if key:
        params["KEY"] = key

    try:
        response = requests.get("https://open.neis.go.kr/hub/schoolInfo", params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        base.core.logger.warning("NEIS school autocomplete failed: %s", type(exc).__name__)
        raise HTTPException(502, "학교 검색 서버 연결에 실패했습니다. 학교명은 직접 입력할 수 있습니다.")

    rows = []
    for block in payload.get("schoolInfo") or []:
        if isinstance(block, dict) and isinstance(block.get("row"), list):
            rows.extend(block["row"])

    items = []
    seen = set()
    for row in rows:
        code = str(row.get("SD_SCHUL_CODE") or "").strip()
        name = str(row.get("SCHUL_NM") or "").strip()
        address = str(row.get("ORG_RDNMA") or row.get("ORG_RDNDA") or "").strip()
        if not name:
            continue
        marker = code or f"{name}|{address}"
        if marker in seen:
            continue
        seen.add(marker)
        items.append({"code": code, "name": name, "address": address})

    return {
        "configured": True,
        "sample_mode": sample_mode,
        "items": items[: (5 if sample_mode else 100)],
        "message": (
            "NEIS 샘플 모드에서는 최대 5개가 표시됩니다. 학교명은 직접 입력할 수 있습니다."
            if sample_mode else ""
        ),
    }


def _render_index_kobaco_v18():
    page = previous._render_index_kobaco_v17()
    patch = r'''
<style>
/* v18 school autocomplete: 입력창 하나 + 바로 아래 드롭다운 */
.aioff-school-search{
  position:relative!important;
  display:block!important;
}
#aioff-school-name{
  width:100%!important;
  padding-right:38px!important;
}
#aioff-school-search-btn,
#aioff-school-manual-row{
  display:none!important;
}
#aioff-school-results{
  position:absolute!important;
  left:0!important;right:0!important;top:calc(100% + 4px)!important;
  z-index:120!important;
  margin:0!important;
  max-height:220px!important;
  overflow-y:auto!important;
  border:1px solid #d6cec3!important;
  border-radius:8px!important;
  background:#fff!important;
  box-shadow:0 10px 24px rgba(35,29,23,.15)!important;
}
#aioff-school-results.open:before{display:none!important}
.aioff-school-result{
  padding:10px 12px!important;
  background:#fff!important;
  border-bottom:1px solid #eee8df!important;
}
.aioff-school-result:hover,
.aioff-school-result.is-active{
  background:#f3f6fb!important;
}
.aioff-school-result b{font-size:12px!important}
.aioff-school-result small{font-size:10px!important;margin-top:2px!important}
#aioff-school-message{margin-top:6px!important;min-height:15px!important}

/* LOGIN ON: 중복된 오른쪽 점은 제거하고 로그아웃은 버튼 크기로 키운다. */
.aioff-auth-state:before{display:none!important}
.aioff-auth-dock.is-on .aioff-auth-links{
  position:static!important;
  width:auto!important;height:auto!important;
  padding:5px 0 0!important;margin:0!important;
  display:flex!important;align-items:center!important;justify-content:flex-end!important;
  background:transparent!important;border:0!important;border-radius:0!important;
  box-shadow:none!important;gap:0!important;
}
.aioff-auth-dock.is-on .aioff-auth-links span{display:none!important}
.aioff-auth-dock.is-on .aioff-auth-links button,
.aioff-auth-dock.is-on .aioff-auth-links button:first-of-type{
  width:auto!important;height:30px!important;min-width:72px!important;min-height:30px!important;
  padding:0 12px!important;margin:0!important;
  border:1px solid #cfc7bc!important;border-radius:7px!important;
  background:#f7f3ed!important;color:#514b45!important;
  font-size:11px!important;line-height:1!important;font-weight:800!important;
  text-decoration:none!important;cursor:pointer!important;
}
.aioff-auth-dock.is-on .aioff-auth-links button:hover{background:#eee8df!important}
</style>
<script>
(() => {
  /* 로그인 입력을 이메일이 아닌 별도 아이디로 전환 */
  const loginPane=document.querySelector('[data-auth-pane="login"]');
  const loginInput=loginPane?.querySelector('input[name="email"]');
  if(loginInput){
    loginInput.name='login_id';
    loginInput.type='text';
    loginInput.removeAttribute('pattern');
    loginInput.removeAttribute('title');
    loginInput.placeholder='아이디';
    loginInput.autocomplete='username';
    const label=loginInput.closest('.aioff-auth-field')?.querySelector('label');
    if(label) label.textContent='아이디';
  }

  /* 회원가입: 이메일은 연락정보로 두고 로그인용 아이디 행을 별도 추가 */
  const registerPane=document.querySelector('[data-auth-pane="register"]');
  const registerEmail=registerPane?.querySelector('input[name="email"]');
  if(registerEmail && !registerPane.querySelector('input[name="login_id"]')){
    const emailField=registerEmail.closest('.aioff-auth-field');
    const idField=document.createElement('div');
    idField.className='aioff-auth-field';
    idField.innerHTML='<label>아이디</label><input name="login_id" type="text" autocomplete="username" minlength="3" maxlength="30" required placeholder="로그인에 사용할 아이디">';
    emailField?.insertAdjacentElement('afterend',idField);
  }

  const input=document.getElementById('aioff-school-name');
  const code=document.getElementById('aioff-school-code');
  const region=document.getElementById('aioff-school-region');
  const level=document.getElementById('aioff-school-level');
  const box=document.getElementById('aioff-school-results');
  const note=document.getElementById('aioff-school-message');
  const searchWrap=input?.closest('.aioff-school-search');
  if(!input||!code||!region||!level||!box||!searchWrap) return;

  /* 결과 박스를 입력창 래퍼 안으로 옮겨 실제 자동완성 드롭다운처럼 붙인다. */
  if(box.parentElement!==searchWrap) searchWrap.appendChild(box);

  const esc18=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let timer=null;
  let seq=0;
  let activeIndex=-1;
  let currentItems=[];

  function closeList(){box.classList.remove('open');activeIndex=-1;}
  function setNote(text){if(note) note.textContent=text||'';}
  function choose(item){
    input.value=item.name||'';
    code.value=item.code||'';
    closeList();
    setNote(item.address ? `${item.name} · ${item.address}` : `${item.name} 선택됨`);
  }
  function render(items,message){
    currentItems=Array.isArray(items)?items:[];
    activeIndex=-1;
    if(!currentItems.length){
      box.innerHTML='';
      closeList();
      setNote(message||'검색 결과가 없습니다. 입력한 학교명을 그대로 사용할 수 있습니다.');
      return;
    }
    box.innerHTML=currentItems.map((x,i)=>`<button type="button" class="aioff-school-result" data-i="${i}"><b>${esc18(x.name||'')}</b><small>${esc18(x.address||'')}</small></button>`).join('');
    box.classList.add('open');
    setNote(message||`${currentItems.length}개 학교`);
    box.querySelectorAll('[data-i]').forEach(btn=>btn.addEventListener('mousedown',e=>{
      e.preventDefault();
      choose(currentItems[Number(btn.dataset.i)]);
    }));
  }
  function markActive(){
    box.querySelectorAll('[data-i]').forEach((el,i)=>el.classList.toggle('is-active',i===activeIndex));
    if(activeIndex>=0) box.querySelector(`[data-i="${activeIndex}"]`)?.scrollIntoView({block:'nearest'});
  }
  async function loadSchools(query=''){
    if(!region.value||!level.value){
      closeList();
      setNote('지역과 학교급을 먼저 선택해 주세요.');
      return;
    }
    const my=++seq;
    setNote(query ? '관련 학교를 찾는 중…' : '학교 목록을 불러오는 중…');
    try{
      const r=await fetch(`/api/auth/schools?region=${encodeURIComponent(region.value)}&school_level=${encodeURIComponent(level.value)}&q=${encodeURIComponent(query)}`,{credentials:'same-origin'});
      let data={}; try{data=await r.json();}catch(e){}
      if(my!==seq) return;
      if(!r.ok) throw new Error(data.detail||data.message||`HTTP ${r.status}`);
      const msg=data.sample_mode
        ? ((data.message||'') + (query ? '' : ' 입력하면 관련 학교만 다시 보여줍니다.')).trim()
        : (query ? `${(data.items||[]).length}개 관련 학교` : `${(data.items||[]).length}개 학교 · 입력하면 바로 필터링됩니다.`);
      render(data.items||[],msg);
    }catch(err){
      if(my!==seq) return;
      closeList();
      setNote(`${err.message} 학교명은 직접 입력할 수 있습니다.`);
    }
  }
  function schedule(){
    code.value='';
    clearTimeout(timer);
    timer=setTimeout(()=>loadSchools(input.value.trim()),220);
  }

  input.addEventListener('focus',()=>loadSchools(input.value.trim()));
  input.addEventListener('click',()=>{if(!box.classList.contains('open')) loadSchools(input.value.trim());});
  input.addEventListener('input',schedule);
  input.addEventListener('keydown',e=>{
    if(!box.classList.contains('open')||!currentItems.length) return;
    if(e.key==='ArrowDown'){
      e.preventDefault(); activeIndex=Math.min(activeIndex+1,currentItems.length-1); markActive();
    }else if(e.key==='ArrowUp'){
      e.preventDefault(); activeIndex=Math.max(activeIndex-1,0); markActive();
    }else if(e.key==='Enter'&&activeIndex>=0){
      e.preventDefault(); choose(currentItems[activeIndex]);
    }else if(e.key==='Escape'){
      e.preventDefault(); closeList();
    }
  });

  region.addEventListener('change',()=>{code.value='';input.value='';closeList();});
  level.addEventListener('change',()=>{code.value='';input.value='';closeList();});

  document.addEventListener('mousedown',e=>{
    if(!e.target.closest?.('.aioff-school-search')) closeList();
  },true);
})();

/* 회원가입 성공 직후 발급된 세션을 읽어 LOGIN ON 상태로 즉시 동기화 */
(() => {
  const message=document.getElementById('aioff-register-message');
  if(!message) return;

  async function syncRegisteredLogin(){
    if(!message.classList.contains('ok')) return;
    try{
      const r=await fetch('/api/auth/me',{credentials:'same-origin'});
      if(!r.ok) return;
      const data=await r.json();
      if(!data.logged_in) return;
      const dock=document.querySelector('.aioff-auth-dock');
      if(!dock) return;
      dock.classList.add('is-on');
      const state=dock.querySelector('.aioff-auth-state');
      if(state) state.textContent='LOGIN ON';
      const links=dock.querySelector('.aioff-auth-links');
      if(links) links.innerHTML='<button type="button" data-auth-logout>로그아웃</button>';
    }catch(e){}
  }

  const observer=new MutationObserver(syncRegisteredLogin);
  observer.observe(message,{childList:true,characterData:true,subtree:true,attributes:true,attributeFilter:['class']});
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v18():
    return HTMLResponse(_render_index_kobaco_v18())
