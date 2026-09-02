from fastapi.responses import HTMLResponse

import literacy_kobaco_app_6 as previous

# v6의 YouTube 매칭 보강은 유지하고,
# 학생 화면에서는 반복 안내를 줄이고 글자 크기/정보 계층을 개선합니다.
v5 = previous.previous
app = previous.app
base = v5.base


def _render_index_kobaco_v7():
    page = v5._render_index_kobaco_v5()

    # 상단 안내도 학생용 문장으로 짧게 정리합니다.
    page = page.replace(
        "실제 KOBACO 데이터에서 바로 시작합니다.",
        "실제 KOBACO 자료로 연습합니다.",
    )
    page = page.replace(
        "주제를 고르면 KOBACO Parquet DB에서 구성한 실제 데이터 사례가 무작위로 나타납니다.",
        "사례를 고르고 AI 질문에 답하면 실제 데이터와 비교하며 판단 기준을 연습합니다.",
    )
    page = page.replace(
        "사례를 선택하면 사진·기사·문서와 DB 조회값, 판단할 주장을 보여주고 AI가 바로 첫 질문을 합니다.",
        "",
    )

    extra_css = r"""
/* 학생 화면 가독성 */
.paper-head h2{font-size:23px!important;letter-spacing:-.5px}
.paper-head p{font-size:13.5px!important;line-height:1.6!important;color:#6f675e!important}
.guide-strip{padding:14px 16px!important;font-size:13px!important;line-height:1.65!important}
.guide-strip strong{font-size:13.5px!important}
.chat{height:420px!important}
.msg{font-size:15px!important;line-height:1.72!important}
.speaker{font-size:11px!important;min-width:28px!important}
.composer textarea{font-size:14.5px!important;line-height:1.6!important;min-height:72px!important}
.send-btn{font-size:13px!important;padding:0 20px!important}

/* 사례 선택 */
.chat-case-picker{padding:16px!important}
.chat-case-picker-head strong{font-size:15px!important}
.chat-case-picker-head span{font-size:11.5px!important;line-height:1.5!important}
.chat-case-option{padding:11px!important}
.chat-case-option b{font-size:13px!important;line-height:1.45!important}
.chat-case-option small{font-size:10.5px!important;margin-top:5px!important}
.chat-case-shuffle{font-size:11.5px!important}

/* 사례 상단 정보 */
.chat-case-top{padding:14px 16px!important}
.chat-case-kicker{font-size:10.5px!important;margin-bottom:5px!important}
.chat-case-title{font-size:17px!important;line-height:1.4!important}
.chat-case-source{font-size:11.5px!important;line-height:1.45!important;margin-top:6px!important}
.chat-case-link{font-size:11.5px!important;padding:7px 10px!important}
.chat-case-summary,.chat-case-claim{font-size:13.5px!important;line-height:1.68!important;padding:14px 16px!important}
.chat-case-summary b,.chat-case-claim b{font-size:11px!important;margin-bottom:6px!important}
.chat-case-caption{font-size:10.5px!important;padding:9px 14px!important}

/* 공익광고 학습 카드 */
.kobaco-thumb-stage{height:250px!important}
.kobaco-thumb-title{font-size:23px!important;line-height:1.28!important}
.kobaco-thumb-kicker{font-size:10px!important}
.kobaco-thumb-meta{font-size:11px!important;line-height:1.45!important}
.kobaco-ad-actions{padding:12px 16px!important;gap:8px!important}
.kobaco-ad-action{font-size:11.5px!important;padding:8px 11px!important}
.kobaco-learn-step{padding:14px 17px!important}
.kobaco-learn-step b{font-size:14px!important;line-height:1.45!important;margin:0!important}
.kobaco-step-no{width:23px!important;height:23px!important;font-size:10px!important;margin-right:7px!important}
.kobaco-after-answer{border-top:1px solid #e2dbd1}
.kobaco-reveal-note{padding:11px 16px!important;font-size:11.5px!important;line-height:1.5!important}
.kobaco-thumb-metrics{gap:10px!important;padding:14px 16px!important}
.kobaco-thumb-metric{padding:11px 12px!important}
.kobaco-thumb-metric small{font-size:10.5px!important;margin-bottom:5px!important}
.kobaco-thumb-metric b{font-size:16px!important}
.kobaco-compare-callout{margin:0;padding:14px 16px;background:#fff;border-bottom:1px solid #e3dcd2}
.kobaco-compare-callout b{display:block;font-size:13.5px;color:#24211d;margin-bottom:5px}
.kobaco-compare-callout span{display:block;font-size:13px;line-height:1.62;color:#625b53}
.kobaco-evidence{background:#faf8f4;border-top:1px solid #e4ddd3}
.kobaco-evidence summary{cursor:pointer;list-style:none;padding:12px 16px;font-size:11.5px;font-weight:800;color:#6f675e}
.kobaco-evidence summary::-webkit-details-marker{display:none}
.kobaco-evidence summary:after{content:'＋';float:right;color:#8a8177}
.kobaco-evidence[open] summary:after{content:'－'}
.kobaco-evidence .kobaco-data-body{padding:0 16px 16px!important}
.kobaco-data-kicker{font-size:9.5px!important;line-height:1.5!important}
.kobaco-data-row b{font-size:11px!important}
.kobaco-data-row span{font-size:12.5px!important;line-height:1.55!important}
.kobaco-data-note{font-size:10.5px!important;line-height:1.5!important}

@media(max-width:650px){
  .paper-head h2{font-size:21px!important}
  .guide-strip{font-size:12.5px!important}
  .msg{font-size:14.5px!important}
  .kobaco-thumb-stage{height:210px!important}
  .kobaco-thumb-title{font-size:19px!important}
  .kobaco-thumb-metrics{grid-template-columns:1fr!important}
}
"""
    page = page.replace("</style>", extra_css + "\n</style>")

    # v5의 기능은 유지하되, 공익광고 카드의 중복 문구/기술정보 노출만 정리합니다.
    script = r'''
<script>
const caseCardBeforeReadable = window.caseCard;

window.kobacoPublicLearningCard = function(c){
  const rowsMap=kobacoRows(c);
  const trust=kobacoPct(rowsMap['신뢰성']);
  const channel=kobacoPct(rowsMap['주요 인지경로']);
  const impact=kobacoPct(rowsMap['임팩트 1위']);
  const metric=(label,val)=>`<div class="kobaco-thumb-metric"><small>${kobacoEsc(label)}</small><b>${val.toFixed(1)}%</b><div class="kobaco-thumb-meter"><i style="width:${val}%"></i></div></div>`;
  const tables=(c.db_tables||[]).map(x=>kobacoEsc(x)).join(' · ');
  const rawRows=(c.data_rows||[]).map(r=>`<div class="kobaco-data-row"><b>${kobacoEsc(r.label||'항목')}</b><span>${kobacoEsc(r.value||'-')}</span></div>`).join('');

  return `<div class="chat-case-media"><div class="kobaco-data-card">
    <div class="kobaco-thumb-stage"><img src="/api/kobaco-media-thumb/${encodeURIComponent(c.id)}" alt="${kobacoEsc(c.archive_title||c.title)} 광고 영상 썸네일" loading="eager"><div class="kobaco-thumb-copy"><div class="kobaco-thumb-kicker">KOBACO PUBLIC AD</div><div class="kobaco-thumb-title">${kobacoEsc(c.archive_title||String(c.title||'').split(' · ')[0])}</div><div class="kobaco-thumb-meta">${kobacoEsc([c.archive_year,c.archive_category].filter(Boolean).join(' · '))}</div></div></div>
    <div class="kobaco-ad-actions">${kobacoArchiveButton(c)}${kobacoVideoButton(c)}</div>
    <div class="kobaco-learn-step"><b><span class="kobaco-step-no">1</span>광고 살펴보기</b></div>
    <div class="kobaco-after-answer" data-kobaco-after-answer>
      <div class="kobaco-reveal-note">첫 답변 완료 · 실제 KOBACO 효과조사 결과</div>
      <div class="kobaco-thumb-metrics">${metric('신뢰성',trust)}${metric('주요 인지경로',channel)}${metric('임팩트 1위',impact)}</div>
      <div class="kobaco-compare-callout"><b>내 판단과 비교해보기</b><span>내가 꼽은 메시지·표현과 실제 조사 결과가 어디서 같고 다른지 살펴보세요. AI가 다음 질문에서 숫자의 의미를 함께 짚어줍니다.</span></div>
      <details class="kobaco-evidence"><summary>세부 DB 근거 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-kicker">PARQUET / DUCKDB · ${tables}</div><div class="kobaco-data-table">${rawRows}</div><div class="kobaco-data-note">${kobacoEsc(c.data_note||'KOBACO 실제 데이터 조회값')}</div></div></details>
    </div>
  </div></div>`;
};

window.caseCard = function(c){
  if(!c || !String(c.id||'').startsWith('kobaco_publicad_')) return caseCardBeforeReadable(c);
  return `<div class="chat-case-card kobaco-public-case"><div class="chat-case-top"><div><div class="chat-case-kicker">${kobacoEsc(c.label||'공익광고 효과조사')}</div><div class="chat-case-title">${kobacoEsc(c.title||'공익광고')}</div><div class="chat-case-source">KOBACO 공익광고 효과평가</div></div></div>${caseMedia(c)}</div>`;
};
</script>
'''
    page = page.replace("</body>", script + "\n</body>")
    return page


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v7():
    return HTMLResponse(_render_index_kobaco_v7())
