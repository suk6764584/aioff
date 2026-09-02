from fastapi.responses import HTMLResponse

import literacy_kobaco_app_2 as previous

# v2의 KOBACO DB 조회/사례 생성/대화 흐름은 그대로 유지하고,
# 사례 카드의 시각 표현만 데이터 유형별로 풍부하게 보강합니다.
v1 = previous.previous
app = v1.app
base = v1.base


def _render_index_kobaco_v3():
    html = v1._render_index_kobaco()

    extra_css = r"""
.kobaco-data-card{padding:0!important;background:#f8f5ef!important}
.kobaco-visual{position:relative;min-height:178px;padding:18px 18px 16px;overflow:hidden;border-bottom:1px solid #ddd5ca;background:linear-gradient(135deg,#28241f 0%,#3a332b 100%);color:#fff}
.kobaco-visual:after{content:"";position:absolute;width:210px;height:210px;border-radius:50%;right:-72px;top:-82px;background:rgba(255,255,255,.055);pointer-events:none}
.kobaco-visual-head{display:flex;align-items:center;justify-content:space-between;gap:12px;position:relative;z-index:1;margin-bottom:15px}
.kobaco-visual-type{font-size:9px;font-weight:900;letter-spacing:.08em;color:#f2c6a7;text-transform:uppercase}
.kobaco-visual-source{font-size:9px;color:rgba(255,255,255,.62);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:58%}
.kobaco-visual-title{position:relative;z-index:1;font-size:17px;font-weight:850;line-height:1.35;letter-spacing:-.4px;margin-bottom:13px;max-width:85%}
.kobaco-keywords{position:relative;z-index:1;display:flex;flex-wrap:wrap;gap:6px}
.kobaco-chip{display:inline-flex;align-items:center;min-height:25px;padding:5px 9px;border:1px solid rgba(255,255,255,.14);border-radius:999px;background:rgba(255,255,255,.08);font-size:9px;line-height:1.25;color:#fff}
.kobaco-counts{position:relative;z-index:1;display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
.kobaco-count{min-width:82px;padding:8px 10px;border-radius:8px;background:rgba(255,255,255,.075);border:1px solid rgba(255,255,255,.09)}
.kobaco-count b{display:block;font-size:15px;line-height:1.1;margin-bottom:3px}.kobaco-count span{font-size:8px;color:rgba(255,255,255,.58)}
.kobaco-metrics{position:relative;z-index:1;display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:8px}
.kobaco-metric{padding:10px 11px;border-radius:9px;background:rgba(255,255,255,.075);border:1px solid rgba(255,255,255,.10);min-width:0}
.kobaco-metric-label{font-size:8px;color:rgba(255,255,255,.6);margin-bottom:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kobaco-metric-value{font-size:16px;font-weight:900;line-height:1.15;margin-bottom:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.kobaco-meter{height:5px;background:rgba(255,255,255,.12);border-radius:999px;overflow:hidden}.kobaco-meter i{display:block;height:100%;border-radius:999px;background:#f5a873}
.kobaco-bars{position:relative;z-index:1;display:grid;gap:9px;margin-top:7px}
.kobaco-bar-row{display:grid;grid-template-columns:92px 1fr 45px;gap:9px;align-items:center;font-size:9px}.kobaco-bar-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:rgba(255,255,255,.82)}.kobaco-bar-track{height:8px;background:rgba(255,255,255,.12);border-radius:999px;overflow:hidden}.kobaco-bar-track i{display:block;height:100%;border-radius:999px;background:#7fa8ff}.kobaco-bar-value{text-align:right;font-weight:850;color:#fff;font-variant-numeric:tabular-nums}
.kobaco-visual-foot{position:relative;z-index:1;margin-top:12px;font-size:8px;color:rgba(255,255,255,.48);line-height:1.4}
.kobaco-data-body{padding:14px 16px 15px}
.kobaco-data-kicker{margin-bottom:9px!important}.kobaco-data-note{margin-top:9px!important}
.kobaco-data-table{box-shadow:0 3px 12px rgba(40,31,22,.035)}
.kobaco-data-row b{display:flex;align-items:center}.kobaco-data-row span{font-weight:650}
.kobaco-db-banner{box-shadow:0 4px 14px rgba(55,45,35,.035)}
.chat-case-card{box-shadow:0 7px 24px rgba(50,40,28,.055)}
@media(max-width:650px){.kobaco-metrics{grid-template-columns:1fr}.kobaco-bar-row{grid-template-columns:76px 1fr 40px}.kobaco-visual{min-height:160px;padding:15px}.kobaco-visual-title{font-size:15px;max-width:100%}.kobaco-visual-source{max-width:50%}}
"""
    html = html.replace("</style>", extra_css + "\n</style>")

    script = r'''
<script>
function kobacoEsc(v){return esc(String(v??''));}
function kobacoRows(c){
  const out={};
  (c.data_rows||[]).forEach(r=>{out[String(r.label||'').trim()]=String(r.value||'').trim();});
  return out;
}
function kobacoNumber(v){
  const m=String(v||'').replace(/,/g,'').match(/-?\d+(?:\.\d+)?/);
  return m?Number(m[0]):null;
}
function kobacoPct(v){const n=kobacoNumber(v);return n===null?0:Math.max(0,Math.min(100,n));}
function kobacoKeywords(v){
  let parts=String(v||'').split(/[,·|/;]+/).map(x=>x.trim()).filter(Boolean);
  if(parts.length<3) parts=String(v||'').split(/\s+/).map(x=>x.trim()).filter(x=>x.length>1);
  return [...new Set(parts)].slice(0,9);
}
function kobacoPairs(v){
  const text=String(v||'');
  const chunks=text.split('·').map(x=>x.trim()).filter(Boolean);
  const result=[];
  for(const chunk of chunks){
    const m=chunk.match(/^(.*?)\s+(-?\d+(?:\.\d+)?)%\s*$/);
    if(m) result.push({name:m[1].trim(),value:Number(m[2])});
  }
  return result.slice(0,4);
}
function kobacoBaseHead(kind,c){
  const tables=(c.db_tables||[]).join(' · ');
  return `<div class="kobaco-visual-head"><span class="kobaco-visual-type">${kobacoEsc(kind)}</span><span class="kobaco-visual-source">${kobacoEsc(tables)}</span></div>`;
}
function kobacoAisacVisual(c,rows){
  const keywords=kobacoKeywords(rows['키워드']);
  const counts=String(rows['인식 횟수']||'').match(/사물\s*([\d,.-]+).*장소\s*([\d,.-]+)/);
  const objectCount=counts?counts[1]:'-';
  const placeCount=counts?counts[2]:'-';
  return `<div class="kobaco-visual kobaco-aisac">${kobacoBaseHead('AI VISION / KEYWORDS',c)}<div class="kobaco-visual-title">${kobacoEsc(c.title||'AiSAC 광고 인식')}</div><div class="kobaco-keywords">${keywords.map(x=>`<span class="kobaco-chip">${kobacoEsc(x)}</span>`).join('')||'<span class="kobaco-chip">AI 인식 키워드</span>'}</div><div class="kobaco-counts"><div class="kobaco-count"><b>${kobacoEsc(objectCount)}</b><span>사물 인식</span></div><div class="kobaco-count"><b>${kobacoEsc(placeCount)}</b><span>장소 인식</span></div><div class="kobaco-count"><b>${kobacoEsc(rows['광고주']||'-')}</b><span>광고주</span></div></div><div class="kobaco-visual-foot">AI가 감지한 요소와 사람이 이해한 광고의 의미를 구분해 봅니다.</div></div>`;
}
function kobacoPublicAdVisual(c,rows){
  const trust=kobacoPct(rows['신뢰성']);
  const channel=kobacoPct(rows['주요 인지경로']);
  const impact=kobacoPct(rows['임팩트 1위']);
  const channelName=String(rows['주요 인지경로']||'').split('·')[0].trim()||'인지경로';
  const impactName=String(rows['임팩트 1위']||'').split('·')[0].trim()||'임팩트';
  const metric=(label,value,name)=>`<div class="kobaco-metric"><div class="kobaco-metric-label">${kobacoEsc(label)}</div><div class="kobaco-metric-value">${value.toFixed(1)}%</div><div class="kobaco-meter"><i style="width:${value}%"></i></div>${name?`<div class="kobaco-visual-foot">${kobacoEsc(name)}</div>`:''}</div>`;
  return `<div class="kobaco-visual kobaco-publicad">${kobacoBaseHead('PUBLIC AD EFFECT',c)}<div class="kobaco-visual-title">${kobacoEsc(c.title||'공익광고 효과조사')}</div><div class="kobaco-metrics">${metric('신뢰성',trust,'')}${metric('주요 인지경로',channel,channelName)}${metric('임팩트 1위',impact,impactName)}</div><div class="kobaco-visual-foot">서로 다른 지표를 하나의 ‘효과’ 숫자로 합치지 않고 각각의 의미를 읽습니다.</div></div>`;
}
function kobacoOttVisual(c,rows){
  const pairs=kobacoPairs(rows['이용비율 상위']);
  const bars=pairs.map(p=>`<div class="kobaco-bar-row"><span class="kobaco-bar-name">${kobacoEsc(p.name)}</span><span class="kobaco-bar-track"><i style="width:${Math.max(0,Math.min(100,p.value))}%"></i></span><span class="kobaco-bar-value">${p.value.toFixed(1)}%</span></div>`).join('');
  return `<div class="kobaco-visual kobaco-ott">${kobacoBaseHead('OTT USAGE / DEMOGRAPHIC',c)}<div class="kobaco-visual-title">${kobacoEsc(rows['연도·집단']||c.title||'연령별 OTT 이용')}</div><div class="kobaco-bars">${bars||'<div class="kobaco-visual-foot">이용비율 데이터를 불러오는 중입니다.</div>'}</div><div class="kobaco-visual-foot">사례수 ${kobacoEsc(rows['사례수']||'-')} · 이용률과 선호도는 같은 지표가 아닙니다.</div></div>`;
}
function kobacoVisual(c){
  const rows=kobacoRows(c);
  const id=String(c.id||'');
  if(id.startsWith('kobaco_aisac_')) return kobacoAisacVisual(c,rows);
  if(id.startsWith('kobaco_publicad_')) return kobacoPublicAdVisual(c,rows);
  if(id.startsWith('kobaco_ott_')) return kobacoOttVisual(c,rows);
  return '';
}
function caseMedia(c){
  if(!c || !Array.isArray(c.data_rows) || !c.data_rows.length){
    return `<div class="chat-case-media"><img src="/api/case-thumb/${encodeURIComponent(c.id)}" alt="${kobacoEsc(c.title)} 미리보기" loading="eager"></div>`;
  }
  const tables=(c.db_tables||[]).map(x=>kobacoEsc(x)).join(' · ');
  const rows=c.data_rows.map(r=>`<div class="kobaco-data-row"><b>${kobacoEsc(r.label||'항목')}</b><span>${kobacoEsc(r.value||'-')}</span></div>`).join('');
  return `<div class="chat-case-media"><div class="kobaco-data-card">${kobacoVisual(c)}<div class="kobaco-data-body"><div class="kobaco-data-kicker">PARQUET / DUCKDB · ${tables}</div><div class="kobaco-data-table">${rows}</div><div class="kobaco-data-note">${kobacoEsc(c.data_note||'KOBACO 실제 데이터 조회값')}</div></div></div></div>`;
}
</script>
'''
    html = html.replace("</body>", script + "\n</body>")
    return html


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v3():
    return HTMLResponse(_render_index_kobaco_v3())
