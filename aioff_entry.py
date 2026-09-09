from __future__ import annotations

from fastapi.responses import HTMLResponse

import news_learning as current

app = current.app
base = current.base

_RENDER_BEFORE_ENTRY = current.runtime._render_runtime_index


_INSTANT_SHELL = r'''
<div id="aioff-instant-shell" aria-hidden="true">
  <style>
    #aioff-instant-shell{
      position:fixed;
      inset:0;
      z-index:2147483647;
      overflow:hidden;
      background:#f5f0e7;
      color:#171411;
      font-family:Arial,"Noto Sans KR",sans-serif;
      pointer-events:none;
    }
    #aioff-instant-shell *{box-sizing:border-box}
    .aioff-instant-top{
      height:58px;
      display:flex;
      align-items:center;
      padding:0 28px;
      border-bottom:1px solid #ddd6cc;
      background:#fffdf9;
      font-size:17px;
      font-weight:900;
      letter-spacing:-.4px;
    }
    .aioff-instant-top b{color:#ef6a3a;margin-left:4px}
    .aioff-instant-wrap{
      width:min(1420px,calc(100% - 48px));
      margin:0 auto;
      padding:28px 0 36px;
    }
    .aioff-instant-status{
      display:flex;
      justify-content:space-between;
      gap:16px;
      padding:9px 12px;
      border:1px solid #ddd6cc;
      border-radius:8px;
      background:#fffaf3;
      color:#6c645b;
      font-size:11px;
    }
    .aioff-instant-status strong{color:#302b26}
    .aioff-instant-hero{
      display:grid;
      grid-template-columns:minmax(0,1.35fr) minmax(300px,.65fr);
      gap:44px;
      align-items:center;
      padding:28px 0 30px;
    }
    .aioff-instant-eyebrow{
      margin-bottom:10px;
      color:#ef6a3a;
      font-size:12px;
      font-weight:900;
      letter-spacing:.02em;
    }
    .aioff-instant-hero h1{
      margin:0;
      max-width:760px;
      font-size:clamp(34px,4vw,58px);
      line-height:1.08;
      letter-spacing:-2px;
    }
    .aioff-instant-hero p{
      margin:16px 0 0;
      max-width:780px;
      color:#665f57;
      font-size:14px;
      line-height:1.65;
    }
    .aioff-instant-note{
      border-top:2px solid #2f2a25;
      padding-top:15px;
      color:#5f5851;
      font-size:12px;
      line-height:1.6;
    }
    .aioff-instant-note strong{
      display:block;
      margin-bottom:6px;
      color:#292521;
      font-size:14px;
    }
    .aioff-instant-panel{
      padding:22px;
      border:1px solid #ddd6cc;
      border-radius:12px;
      background:#fffdf9;
    }
    .aioff-instant-panel h2{
      margin:0 0 5px;
      font-size:22px;
      letter-spacing:-.7px;
    }
    .aioff-instant-panel>p{
      margin:0 0 18px;
      color:#746c63;
      font-size:12px;
    }
    .aioff-instant-cards{
      display:grid;
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:12px;
    }
    .aioff-instant-card{
      min-height:118px;
      padding:17px 16px;
      border:1px solid #ddd6cc;
      border-radius:9px;
      background:#fff;
    }
    .aioff-instant-card:first-child{
      border:2px solid #2f6fe4;
      background:#edf3ff;
    }
    .aioff-instant-card strong{
      display:block;
      margin-bottom:9px;
      font-size:14px;
      line-height:1.35;
    }
    .aioff-instant-card span{
      display:block;
      color:#746c63;
      font-size:11px;
      line-height:1.45;
    }
    @media(max-width:780px){
      .aioff-instant-wrap{width:min(100% - 24px,1420px);padding-top:18px}
      .aioff-instant-hero{grid-template-columns:1fr;gap:18px;padding:20px 0}
      .aioff-instant-hero h1{font-size:36px}
      .aioff-instant-cards{grid-template-columns:1fr}
      .aioff-instant-card{min-height:0}
    }
  </style>
  <div class="aioff-instant-top">AI <b>OFF</b></div>
  <main class="aioff-instant-wrap">
    <div class="aioff-instant-status">
      <strong>KOBACO DB 연동 완료</strong>
      <span>AiSAC · 공식 교육자료 · 최신 뉴스 학습 데이터를 사용합니다.</span>
    </div>
    <section class="aioff-instant-hero">
      <div>
        <div class="aioff-instant-eyebrow">KOBACO DATA × AI OFF</div>
        <h1>미디어를 보고,<br>생각하고, 데이터로 확인해요.</h1>
        <p>실제 KOBACO 광고·공식 리터러시 교육자료·최신 뉴스 사례를 보고 자료에 나온 사실과 해석을 구분해봅니다.</p>
      </div>
      <div class="aioff-instant-note">
        <strong>마지막에는 혼자 풀어봐요</strong>
        AI와 학습한 대화를 분석하고 AI가 대신한 사고를 학생이 직접 다시 수행합니다.
      </div>
    </section>
    <section class="aioff-instant-panel">
      <h2>학습 주제를 선택하세요</h2>
      <p>주제를 고르면 실제 데이터와 공식 자료에서 구성한 사례를 살펴볼 수 있습니다.</p>
      <div class="aioff-instant-cards">
        <div class="aioff-instant-card">
          <strong>AI가 읽은 광고 vs 사람이 읽은 맥락</strong>
          <span>AiSAC이 실제 광고에서 인식한 사물·장소·키워드와 사람이 이해한 광고 메시지를 구분합니다.</span>
        </div>
        <div class="aioff-instant-card">
          <strong>리터러시 교육 안내서</strong>
          <span>수집된 디지털윤리 교육 안내서의 개념과 활동을 무작위 사례로 읽고 직접 적용합니다.</span>
        </div>
        <div class="aioff-instant-card">
          <strong>최신 뉴스에서 사실과 해석 구분하기</strong>
          <span>실제 최신 뉴스의 제목·출처·게시 시점과 동일 사건 보도를 비교해 사실과 해석을 구분합니다.</span>
        </div>
      </div>
    </section>
  </main>
</div>
<script>
(function(){
  const started = performance.now();
  function revealRealPage(){
    const shell = document.getElementById('aioff-instant-shell');
    if(!shell) return;
    const elapsed = performance.now() - started;
    const delay = Math.max(0, 320 - elapsed);
    window.setTimeout(function(){
      window.requestAnimationFrame(function(){
        window.requestAnimationFrame(function(){ shell.remove(); });
      });
    }, delay);
  }
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', revealRealPage, {once:true});
  }else{
    revealRealPage();
  }
})();
</script>
'''


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
    page = page.replace('<body>', '<body>' + _INSTANT_SHELL, 1)
    return page.replace('</body>', patch + '\n</body>')


# The landing page is deterministic for the lifetime of the process. Rendering it once
# removes repeated ~550 KB string assembly from preview/screenshot requests and makes
# the first response as cheap as possible without changing any API or learning state.
_ENTRY_PAGE = _render_entry_index()


base._remove_route('/', 'GET')


@app.get('/', response_class=HTMLResponse)
def aioff_entry_index():
    return HTMLResponse(
        _ENTRY_PAGE,
        headers={
            'Cache-Control': 'public, max-age=30, stale-while-revalidate=120',
        },
    )
