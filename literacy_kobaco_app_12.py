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

/* 공익광고 썸네일은 기존 v4 공식 아카이브 표현으로 복구합니다. */
.kobaco-thumb-stage{position:relative;height:225px;overflow:hidden;background:#27231f;border-bottom:1px solid #ddd5ca}
.kobaco-thumb-stage img{width:100%;height:100%;object-fit:cover;display:block}
.kobaco-thumb-stage:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(15,13,11,.08),rgba(15,13,11,.12) 42%,rgba(15,13,11,.86) 100%)}
.kobaco-thumb-copy{position:absolute;left:19px;right:19px;bottom:17px;z-index:2;color:white}
.kobaco-thumb-kicker{font-size:9px;font-weight:900;letter-spacing:.08em;color:#f4bf9d;margin-bottom:6px}
.kobaco-thumb-title{font-size:21px;line-height:1.25;font-weight:900;letter-spacing:-.5px;max-width:78%}
.kobaco-thumb-meta{font-size:9px;color:rgba(255,255,255,.68);margin-top:6px}
.kobaco-thumb-play{position:absolute;right:18px;bottom:18px;z-index:3;width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#f06a3c;color:white!important;text-decoration:none;font-size:17px;font-weight:900;box-shadow:0 8px 22px rgba(0,0,0,.25)}

@media(max-width:700px){
  .aisac-video-stage{height:clamp(160px,29vh,210px)!important;max-height:210px!important}
  .aisac-info-column .fact-grid{grid-template-columns:1fr 1fr!important}
  .kobaco-thumb-stage{height:190px}
  .kobaco-thumb-title{font-size:17px;max-width:75%}
}
</style>
<script>
/* 공익광고 선택 카드도 기존 공식 아카이브 썸네일로 복구합니다. */
const fixedPreviewBeforePublicAdRestore=window.fixedPreview;
window.fixedPreview=function(c){
  const id=String(c?.id||'');
  if(id.startsWith('kobaco_publicad_')){
    return `<div class="kobaco-picker-media"><img src="/api/kobaco-thumb/${encodeURIComponent(c.id)}" alt="${esc(c.archive_title||c.title||'공익광고')} 썸네일" loading="lazy"></div>`;
  }
  return fixedPreviewBeforePublicAdRestore(c);
};

/* 학습 흐름은 유지하고, 상단 썸네일 표현만 기존 v4 방식으로 되돌립니다. */
window.publicAdCard=function(c){
  const r=fixedRows(c);
  const metric=(label,value,meaning)=>`<div class="kobaco-readable-metric"><small>${esc(label)}</small><strong>${esc(value||'-')}</strong><p>${esc(meaning)}</p></div>`;
  const archive=c.archive_url?`<a href="${esc(c.archive_url)}" target="_blank" rel="noopener">공식 상세페이지 ↗</a>`:'';
  const video=c.video_url?`<a class="alt" href="${esc(c.video_url)}" target="_blank" rel="noopener">광고 영상 보기 ↗</a>`:'';
  const play=c.video_url||c.archive_url||'';
  const playButton=play?`<a class="kobaco-thumb-play" href="${esc(play)}" target="_blank" rel="noopener" title="공식 원문/영상 보기">▶</a>`:'';
  const meta=[c.archive_year,c.archive_category].filter(Boolean).join(' · ');
  return `<div class="chat-case-media"><div class="kobaco-data-card">
    <div class="kobaco-thumb-stage">
      <img src="/api/kobaco-thumb/${encodeURIComponent(c.id)}" alt="${esc(c.archive_title||c.title||'공익광고')} 공식 아카이브 썸네일" loading="eager">
      <div class="kobaco-thumb-copy"><div class="kobaco-thumb-kicker">KOBACO OFFICIAL ARCHIVE</div><div class="kobaco-thumb-title">${esc(c.archive_title||c.title||'KOBACO 공익광고')}</div><div class="kobaco-thumb-meta">${esc(meta)}</div></div>
      ${playButton}
    </div>
    <div class="context-card"><b>${esc(c.archive_title||c.title||'KOBACO 공익광고')}</b><div class="context-actions">${archive}${video}</div></div>
    <div class="kobaco-after-answer" data-kobaco-after-answer>
      <div class="kobaco-readable-metrics">${metric('광고의 신뢰성을 평가한 항목',r['신뢰성'],'행동 변화 비율을 뜻하지 않습니다.')}${metric('광고를 접한 경로 중 가장 높은 항목',r['주요 인지경로'],'광고의 좋고 나쁨을 평가한 점수가 아닙니다.')}${metric('가장 강한 인상을 준 요소',r['임팩트 1위'],'광고 전체 효과를 하나의 숫자로 나타낸 값이 아닙니다.')}</div>
      <details class="kobaco-evidence" open><summary>실제 조사 원자료 항목 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-table">${fixedRawRows(c)}</div></div></details>
    </div>
  </div></div>`;
};
</script>
'''
    return page.replace("</body>", override + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v12():
    return HTMLResponse(_render_index_kobaco_v12())
