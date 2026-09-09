from __future__ import annotations

from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse

import news_learning as current

app = current.app
base = current.base

_RENDER_BEFORE_ENTRY = current.runtime._render_runtime_index
_THUMBNAIL_PATH = Path(__file__).resolve().parent / "assets" / "aioff-thumbnail.jpg"
if not _THUMBNAIL_PATH.is_file():
    raise RuntimeError(f"Missing AI OFF thumbnail asset: {_THUMBNAIL_PATH}")
with _THUMBNAIL_PATH.open("rb") as _thumbnail_file:
    if _thumbnail_file.read(2) != b"\xff\xd8":
        raise RuntimeError("Invalid AI OFF thumbnail JPEG asset")


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


def _thumbnail_response():
    return FileResponse(
        path=_THUMBNAIL_PATH,
        media_type='image/jpeg',
        headers={
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0',
        },
    )


@app.get('/aioff-thumbnail.jpg')
def aioff_thumbnail_jpg():
    return _thumbnail_response()


@app.get('/aioff-thumbnail-v2.jpg')
def aioff_thumbnail_v2_jpg():
    return _thumbnail_response()


base._remove_route('/', 'GET')


@app.get('/', response_class=HTMLResponse)
def aioff_entry_index():
    return HTMLResponse(_render_entry_index())
