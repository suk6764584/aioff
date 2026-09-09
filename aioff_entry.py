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
</style>
'''
    return page.replace('</body>', patch + '\n</body>')


base._remove_route('/', 'GET')


@app.get('/', response_class=HTMLResponse)
def aioff_entry_index():
    return HTMLResponse(_render_entry_index())
