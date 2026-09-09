from __future__ import annotations

import base64
from pathlib import Path

from fastapi.responses import HTMLResponse, Response

import news_learning as current

app = current.app
base = current.base

_RENDER_BEFORE_ENTRY = current.runtime._render_runtime_index
_ASSET_DIR = Path(__file__).resolve().parent / "assets"
_THUMBNAIL_JPEG = base64.b64decode(
    (_ASSET_DIR / "aioff-thumbnail.b64").read_text(encoding="ascii").strip(),
    validate=True,
)


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


@app.get('/aioff-thumbnail.jpg')
def aioff_thumbnail_jpg():
    return Response(
        content=_THUMBNAIL_JPEG,
        media_type='image/jpeg',
        headers={'Cache-Control': 'public, max-age=86400'},
    )


base._remove_route('/', 'GET')


@app.get('/', response_class=HTMLResponse)
def aioff_entry_index():
    return HTMLResponse(_render_entry_index())
