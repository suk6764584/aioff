from __future__ import annotations

import os

import requests
from fastapi import HTTPException
from fastapi.responses import HTMLResponse

import auth_proto as auth
import literacy_kobaco_app_17 as previous

app = previous.app
base = previous.base
flow = previous.flow


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
#aioff-school-search-btn{
  display:none!important;
}
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
#aioff-school-message{
  margin-top:6px!important;
  min-height:15px!important;
}

/* LOGIN ON일 때 큰 OFF 전용 박스는 없애고, 작은 로그아웃 링크만 남긴다. */
.aioff-auth-dock.is-on .aioff-auth-links{
  position:static!important;
  width:auto!important;height:auto!important;
  padding:2px 0 0!important;margin:0!important;
  display:flex!important;align-items:center!important;justify-content:flex-end!important;
  background:transparent!important;border:0!important;border-radius:0!important;
  box-shadow:none!important;gap:0!important;
}
.aioff-auth-dock.is-on .aioff-auth-links span{display:none!important}
.aioff-auth-dock.is-on .aioff-auth-links button,
.aioff-auth-dock.is-on .aioff-auth-links button:first-of-type{
  width:auto!important;height:auto!important;min-width:0!important;min-height:0!important;
  padding:0!important;margin:0!important;border:0!important;border-radius:0!important;
  background:transparent!important;color:#736d66!important;
  font-size:8px!important;line-height:1.2!important;font-weight:700!important;
  text-decoration:none!important;cursor:pointer!important;
}
.aioff-auth-dock.is-on .aioff-auth-links button:hover{text-decoration:underline!important}
</style>
<script>
(() => {
  const input=document.getElementById('aioff-school-name');
  const code=document.getElementById('aioff-school-code');
  const region=document.getElementById('aioff-school-region');
  const level=document.getElementById('aioff-school-level');
  const box=document.getElementById('aioff-school-results');
  const note=document.getElementById('aioff-school-message');
  if(!input||!code||!region||!level||!box) return;

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

/* 회원가입 API는 세션 쿠키를 즉시 발급한다. 성공 문구가 뜨면 UI도 즉시 LOGIN ON으로 동기화한다. */
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
      if(links && !links.querySelector('[data-auth-logout]')){
        links.innerHTML='<button type="button" data-auth-logout>로그아웃</button>';
      }
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
