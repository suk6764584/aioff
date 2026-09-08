from __future__ import annotations

import re

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_20 as previous

app = previous.app
base = previous.base
flow = previous.flow


def _render_index_kobaco_v21():
    page = previous._render_index_kobaco_v20()

    # 상단 1~4 단계 표시 영역은 화면에서 완전히 제거한다.
    page = re.sub(
        r'\s*<section class="process" aria-label="이용 순서">.*?</section>\s*',
        '\n',
        page,
        count=1,
        flags=re.S,
    )

    # 오른쪽 설명/분석 사이드바도 제거한다.
    # 기존 JS가 참조하는 상태용 id는 보이지 않는 holder에만 남겨 기능을 유지한다.
    hidden_state = '''
    <div id="aioff-hidden-state" hidden aria-hidden="true">
      <div id="process1"></div><div id="process2"></div><div id="process3"></div><div id="process4"></div>
      <span id="stageStep">1 / 4</span><span id="stageText"></span>
      <div id="skills"></div><div id="analysisSummary"></div>
    </div>
    '''
    page = re.sub(
        r'\s*<aside class="study-side">.*?</aside>\s*',
        '\n' + hidden_state + '\n',
        page,
        count=1,
        flags=re.S,
    )

    # 사례 학습 영역이 오른쪽 빈 칸 없이 전체 폭을 사용하도록 확장한다.
    patch = r'''
<style>
.workspace{
  grid-template-columns:minmax(0,1fr)!important;
  gap:0!important;
}
.study-paper{
  width:100%!important;
  max-width:none!important;
}
</style>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v21():
    return HTMLResponse(_render_index_kobaco_v21())
