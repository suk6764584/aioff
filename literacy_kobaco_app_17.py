from __future__ import annotations

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_16 as previous

app = previous.app
base = previous.base
flow = previous.flow


def _render_index_kobaco_v17():
    page = previous._render_index_kobaco_v16()
    patch = r'''
<script>
(() => {
  const overlay=document.getElementById('aioff-auth-overlay');
  if(!overlay) return;

  /* 입력값을 드래그해 선택하다 포인터가 바깥에서 끝나도 모달이 닫히지 않게 한다.
     모달 닫기는 X 버튼 / ESC만 사용한다. */
  overlay.addEventListener('click',e=>{
    if(e.target===overlay){
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  },true);
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v17():
    return HTMLResponse(_render_index_kobaco_v17())
