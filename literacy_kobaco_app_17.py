from __future__ import annotations

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_16 as previous

app = previous.app
base = previous.base
flow = previous.flow


def _render_index_kobaco_v17():
    page = previous._render_index_kobaco_v16()
    patch = r'''
<style>
/* v17: 학교 직접입력 + 공식 검색목록을 동시에 명확하게 제공 */
.aioff-school-manual-row{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  margin-top:7px;padding:8px 10px;border:1px dashed #d8d0c5;border-radius:8px;
  background:#fbf8f3;color:#6c655e;font-size:10px;line-height:1.35;
}
.aioff-school-manual-row button{
  flex:0 0 auto;border:1px solid #cfc7bc;border-radius:7px;background:#fff;
  padding:7px 10px;font-size:10px;font-weight:800;color:#3d3833;cursor:pointer;
}
.aioff-school-manual-row button:hover{background:#f2ede6}
#aioff-school-results.open{margin-top:7px}
#aioff-school-results.open:before{
  content:'학교 검색 결과';display:block;padding:8px 10px 6px;
  font-size:10px;font-weight:850;color:#5f5851;background:#f8f4ee;
  border-bottom:1px solid #e8e1d8;
}
</style>
<script>
(() => {
  const overlay=document.getElementById('aioff-auth-overlay');

  /* 입력값을 드래그해 선택하다 포인터가 바깥에서 끝나도 모달이 닫히지 않게 한다.
     모달 닫기는 X 버튼 / ESC만 사용한다. */
  if(overlay){
    overlay.addEventListener('click',e=>{
      if(e.target===overlay){
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    },true);
  }

  const schoolName=document.getElementById('aioff-school-name');
  const schoolCode=document.getElementById('aioff-school-code');
  const searchWrap=document.querySelector('.aioff-school-search');
  const note=document.getElementById('aioff-school-message');
  const results=document.getElementById('aioff-school-results');

  if(schoolName && schoolCode && searchWrap && !document.getElementById('aioff-school-manual-row')){
    const row=document.createElement('div');
    row.id='aioff-school-manual-row';
    row.className='aioff-school-manual-row';
    row.innerHTML='<span>목록에 없으면 입력한 학교명을 그대로 사용할 수 있습니다.</span><button type="button" id="aioff-school-manual-use">직접 입력 사용</button>';
    searchWrap.insertAdjacentElement('afterend',row);

    document.getElementById('aioff-school-manual-use').addEventListener('click',()=>{
      const value=schoolName.value.trim();
      if(!value){
        if(note) note.textContent='학교명을 먼저 입력해 주세요.';
        schoolName.focus();
        return;
      }
      schoolCode.value='';
      if(note) note.textContent=`'${value}'을(를) 직접 입력한 학교명으로 사용합니다. 검색 결과가 있으면 아래 목록에서 다시 선택할 수도 있습니다.`;
      schoolName.focus();
      schoolName.setSelectionRange?.(schoolName.value.length,schoolName.value.length);
    });
  }

  /* 검색 결과가 열려 있어도 직접 입력 필드는 그대로 유지한다. */
  if(results && schoolName){
    const observer=new MutationObserver(()=>{
      if(results.classList.contains('open')){
        schoolName.removeAttribute('readonly');
        schoolName.setAttribute('aria-describedby','aioff-school-message');
      }
    });
    observer.observe(results,{attributes:true,attributeFilter:['class'],childList:true,subtree:true});
  }
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v17():
    return HTMLResponse(_render_index_kobaco_v17())
