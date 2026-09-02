from fastapi.responses import HTMLResponse

import literacy_kobaco_app_11 as previous

app = previous.app
base = previous.base
flow = previous.flow


def _render_index_kobaco_v12():
    page = previous._render_index_kobaco_v11()
    override = r'''
<style>
/* AiSAC 영상은 학습창 안에서 원본 프레임 전체가 한 번에 보이도록 표시합니다. */
.aisac-learning-grid{display:block!important}
.aisac-media-column{border-right:0!important;background:#fff!important}
.aisac-info-column{display:block!important}
.aisac-video-stage{
  height:clamp(180px,32vh,250px)!important;
  max-height:250px!important;
  width:100%!important;
  display:flex!important;
  align-items:center!important;
  justify-content:center!important;
  background:#171513!important;
  overflow:hidden!important;
}
.aisac-video-stage video,
.aisac-video-stage .aisac-video-poster{
  width:100%!important;
  height:100%!important;
  object-fit:contain!important;
  object-position:center center!important;
}
.aisac-video-stage .aisac-video-poster{background:#171513!important}
.aisac-info-column .fact-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important}
@media(max-width:700px){
  .aisac-video-stage{height:clamp(160px,29vh,210px)!important;max-height:210px!important}
  .aisac-info-column .fact-grid{grid-template-columns:1fr 1fr!important}
}
</style>
'''
    return page.replace("</body>", override + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v12():
    return HTMLResponse(_render_index_kobaco_v12())
