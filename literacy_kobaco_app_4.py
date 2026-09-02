from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from fastapi.responses import HTMLResponse, RedirectResponse, Response

import literacy_kobaco_app_3 as previous

# v3의 DB 기반 학습/차트 UI는 유지합니다.
# public_ad_master가 있으면 공익광고 효과조사 사례를 실제 KOBACO 작품과 연결해
# 공식 아카이브/유튜브 썸네일을 눈에 띄는 사례 카드와 선택 카드에 표시합니다.
v2 = previous.previous
v1 = v2.previous
app = v1.app
base = v1.base
flow = v1.flow


def _norm(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def _topic_candidates(topic: str) -> list[str]:
    raw = str(topic or "").strip()
    values = [raw]
    for sep in ("-", ":", "·", "/"):
        if sep in raw:
            values.extend(x.strip() for x in raw.split(sep) if x.strip())
    out = []
    for value in values:
        n = _norm(value)
        if len(n) >= 3 and n not in out:
            out.append(n)
    return out


def _match_score(topic: str, title: str) -> float:
    target = _norm(title)
    if not target:
        return 0.0
    best = 0.0
    for candidate in _topic_candidates(topic):
        if candidate == target:
            best = max(best, 120.0)
            continue
        shorter, longer = sorted((candidate, target), key=len)
        containment = len(shorter) >= 4 and shorter in longer
        if containment:
            ratio = len(shorter) / max(1, len(longer))
            best = max(best, 92.0 + ratio * 15.0)
        sim = SequenceMatcher(None, candidate, target).ratio()
        if sim >= 0.84:
            best = max(best, 78.0 + sim * 12.0)
    return best


def _youtube_id(url: str) -> str:
    text = str(url or "").strip()
    patterns = (
        r"youtu\.be/([A-Za-z0-9_-]{6,})",
        r"youtube\.com/watch\?[^#]*v=([A-Za-z0-9_-]{6,})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{6,})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})",
    )
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(1)
    return ""


def _enrich_public_ad_cases() -> None:
    db = v1.get_kobaco_db()
    if db is None or not db.has_tables("public_ad_master"):
        return

    masters = db.query(
        '''
        SELECT "제작연도", "고유번호", "공익광고작품명", "대분류", "소분류",
               "영상링크-코바코 홈페이지" AS "코바코링크",
               "영상링크-유튜브" AS "유튜브링크",
               "핵심 키워드(관리자 직접 지정)" AS "관리키워드",
               "썸네일 이미지 이름" AS "썸네일파일명"
        FROM public_ad_master
        WHERE NULLIF(TRIM(CAST("공익광고작품명" AS VARCHAR)), '') IS NOT NULL
        '''
    )

    for case in flow.CASE_LIBRARY.get("deepfake", []):
        topic = str(case.get("title") or "").split(" · ", 1)[0].strip()
        survey = str(case.get("title") or "")
        survey_year_match = re.search(r"(20\d{2})", survey)
        survey_year = int(survey_year_match.group(1)) if survey_year_match else None

        ranked = []
        for row in masters:
            score = _match_score(topic, str(row.get("공익광고작품명") or ""))
            if score <= 0:
                continue
            try:
                year = int(float(row.get("제작연도"))) if row.get("제작연도") is not None else None
            except (TypeError, ValueError):
                year = None
            if survey_year and year:
                if year == survey_year:
                    score += 8
                elif abs(year - survey_year) <= 1:
                    score += 3
            ranked.append((score, row))

        if not ranked:
            continue
        ranked.sort(key=lambda x: x[0], reverse=True)
        score, row = ranked[0]
        # 비슷한 제목을 억지로 연결하지 않습니다.
        if score < 90:
            continue

        archive_url = str(row.get("코바코링크") or "").strip()
        video_url = str(row.get("유튜브링크") or "").strip()
        yt_id = _youtube_id(video_url)
        if archive_url:
            case["source_url"] = archive_url
        case["archive_url"] = archive_url
        case["video_url"] = video_url
        case["youtube_id"] = yt_id
        case["thumbnail_url"] = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg" if yt_id else ""
        case["archive_title"] = str(row.get("공익광고작품명") or "").strip()
        case["archive_year"] = str(row.get("제작연도") or "").strip()
        case["archive_category"] = " / ".join(
            x for x in [str(row.get("대분류") or "").strip(), str(row.get("소분류") or "").strip()] if x
        )
        case["thumbnail_file"] = str(row.get("썸네일파일명") or "").strip()


_enrich_public_ad_cases()


# app1의 공개 payload를 확장하여 프론트엔드가 실제 아카이브 링크/썸네일 정보를 받게 합니다.
_OLD_PUBLIC_CASE = flow._public_case


def _public_case_v4(case):
    data = _OLD_PUBLIC_CASE(case)
    for key in (
        "archive_url", "video_url", "youtube_id", "thumbnail_url",
        "archive_title", "archive_year", "archive_category", "thumbnail_file",
    ):
        data[key] = case.get(key, "")
    return data


flow._public_case = _public_case_v4


_OG_PATTERNS = (
    re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image|twitter:image:src)["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image|twitter:image:src)["\']', re.I),
)
_THUMB_CACHE: dict[str, str] = {}


def _page_image(url: str) -> str:
    if not url:
        return ""
    if url in _THUMB_CACHE:
        return _THUMB_CACHE[url]
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
            },
        )
        with urlopen(req, timeout=5) as response:
            raw = response.read(1_500_000)
        text = raw.decode("utf-8", errors="ignore")
        for pattern in _OG_PATTERNS:
            match = pattern.search(text)
            if match:
                result = urljoin(url, html.unescape(match.group(1).strip()))
                _THUMB_CACHE[url] = result
                return result
    except Exception:
        pass
    _THUMB_CACHE[url] = ""
    return ""


def _fallback_svg(case) -> bytes:
    title = html.escape(str(case.get("archive_title") or case.get("title") or "KOBACO 공익광고"))
    year = html.escape(str(case.get("archive_year") or "KOBACO ARCHIVE"))
    category = html.escape(str(case.get("archive_category") or "공익광고 아카이브"))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
    <defs><linearGradient id="g" x1="0" x2="1"><stop stop-color="#23201c"/><stop offset="1" stop-color="#514338"/></linearGradient></defs>
    <rect width="1280" height="720" fill="url(#g)"/><circle cx="1080" cy="80" r="260" fill="#fff" opacity=".055"/>
    <text x="86" y="100" font-family="Arial,sans-serif" font-size="24" font-weight="700" fill="#efb38a">KOBACO PUBLIC AD</text>
    <text x="86" y="170" font-family="Arial,sans-serif" font-size="25" fill="#d7cdc3">{year} · {category}</text>
    <foreignObject x="86" y="230" width="1050" height="270"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:Arial,sans-serif;color:white;font-size:58px;font-weight:800;line-height:1.22">{title}</div></foreignObject>
    <circle cx="104" cy="610" r="31" fill="#ef7d42"/><polygon points="96,592 96,628 124,610" fill="white"/>
    <text x="154" y="619" font-family="Arial,sans-serif" font-size="24" fill="#fff">공식 아카이브에서 원문 보기</text>
    </svg>'''
    return svg.encode("utf-8")


@app.get("/api/kobaco-thumb/{case_id}")
def kobaco_thumbnail(case_id: str):
    found = flow.CASE_BY_ID.get(case_id)
    if not found:
        return Response(status_code=404)
    case = found[1]
    direct = str(case.get("thumbnail_url") or "").strip()
    if direct:
        return RedirectResponse(direct, status_code=302)
    archive = str(case.get("archive_url") or "").strip()
    page_image = _page_image(archive)
    if page_image:
        return RedirectResponse(page_image, status_code=302)
    return Response(_fallback_svg(case), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


def _render_index_kobaco_v4():
    page = previous._render_index_kobaco_v3()

    extra_css = r"""
.kobaco-picker-media{height:86px;margin:-10px -10px 9px;overflow:hidden;border-radius:7px 7px 4px 4px;background:#29251f;position:relative}
.kobaco-picker-media img{width:100%;height:100%;object-fit:cover;display:block}.kobaco-picker-media:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 35%,rgba(20,17,14,.45))}
.kobaco-picker-placeholder{height:86px;margin:-10px -10px 9px;border-radius:7px 7px 4px 4px;background:linear-gradient(135deg,#29251f,#4c4036);display:flex;align-items:flex-end;padding:10px;color:#fff;font-size:9px;font-weight:900;letter-spacing:.06em}
.kobaco-thumb-stage{position:relative;height:225px;overflow:hidden;background:#27231f;border-bottom:1px solid #ddd5ca}.kobaco-thumb-stage img{width:100%;height:100%;object-fit:cover;display:block}.kobaco-thumb-stage:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(15,13,11,.08),rgba(15,13,11,.12) 42%,rgba(15,13,11,.86) 100%)}
.kobaco-thumb-copy{position:absolute;left:19px;right:19px;bottom:17px;z-index:2;color:white}.kobaco-thumb-kicker{font-size:9px;font-weight:900;letter-spacing:.08em;color:#f4bf9d;margin-bottom:6px}.kobaco-thumb-title{font-size:21px;line-height:1.25;font-weight:900;letter-spacing:-.5px;max-width:78%}.kobaco-thumb-meta{font-size:9px;color:rgba(255,255,255,.68);margin-top:6px}.kobaco-thumb-play{position:absolute;right:18px;bottom:18px;z-index:3;width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#f06a3c;color:white;text-decoration:none;font-size:17px;font-weight:900;box-shadow:0 8px 22px rgba(0,0,0,.25)}
.kobaco-thumb-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:12px 14px;background:#f7f3ec;border-bottom:1px solid #ddd5ca}.kobaco-thumb-metric{background:#fff;border:1px solid #dfd7cc;border-radius:8px;padding:9px 10px}.kobaco-thumb-metric small{display:block;color:#8a8177;font-size:8px;margin-bottom:4px}.kobaco-thumb-metric b{font-size:13px;color:#2d2925}.kobaco-thumb-meter{height:4px;border-radius:999px;background:#eee7dd;overflow:hidden;margin-top:6px}.kobaco-thumb-meter i{display:block;height:100%;background:#ef7d42}
@media(max-width:650px){.kobaco-thumb-stage{height:190px}.kobaco-thumb-title{font-size:17px;max-width:75%}.kobaco-thumb-metrics{grid-template-columns:1fr}.kobaco-picker-media{height:72px}}
"""
    page = page.replace("</style>", extra_css + "\n</style>")

    script = r'''
<script>
function kobacoPickerPreview(c){
  const id=String(c.id||'');
  if(id.startsWith('kobaco_publicad_')) return `<div class="kobaco-picker-media"><img src="/api/kobaco-thumb/${encodeURIComponent(c.id)}" alt="${kobacoEsc(c.title)} 썸네일" loading="lazy"></div>`;
  if(id.startsWith('kobaco_aisac_')) return `<div class="kobaco-picker-placeholder">AI VISION · KEYWORDS</div>`;
  if(id.startsWith('kobaco_ott_')) return `<div class="kobaco-picker-placeholder">OTT DATA · DEMOGRAPHIC</div>`;
  return '';
}
function pickerHtml(lessonId,activeId=null){
  const cases=currentCaseSample(lessonId);
  const total=(inlineCaseData[lessonId]||[]).length;
  return `<div class="chat-case-picker"><div class="chat-case-picker-head"><div><strong>실제 데이터 사례를 골라보세요</strong><br><span>전체 ${total}개 중 3개가 무작위로 표시됩니다.</span></div><button type="button" class="chat-case-shuffle" data-shuffle-cases>↻ 다른 3개 보기</button></div><div class="chat-case-options">${cases.map((c,i)=>`<button type="button" class="chat-case-option ${c.id===activeId?'active':''}" data-case-id="${c.id}">${kobacoPickerPreview(c)}<b>${i+1}. ${esc(compactTitle(c.title))}</b><small>${esc(c.label)}</small></button>`).join('')}</div></div>`;
}
function kobacoPublicThumb(c,rows){
  const trust=kobacoPct(rows['신뢰성']);
  const channel=kobacoPct(rows['주요 인지경로']);
  const impact=kobacoPct(rows['임팩트 1위']);
  const link=c.video_url||c.archive_url||c.source_url||'#';
  const metric=(label,val)=>`<div class="kobaco-thumb-metric"><small>${kobacoEsc(label)}</small><b>${val.toFixed(1)}%</b><div class="kobaco-thumb-meter"><i style="width:${val}%"></i></div></div>`;
  return `<div class="kobaco-thumb-stage"><img src="/api/kobaco-thumb/${encodeURIComponent(c.id)}" alt="${kobacoEsc(c.archive_title||c.title)} 공식 아카이브 썸네일" loading="eager"><div class="kobaco-thumb-copy"><div class="kobaco-thumb-kicker">KOBACO OFFICIAL ARCHIVE</div><div class="kobaco-thumb-title">${kobacoEsc(c.archive_title||c.title)}</div><div class="kobaco-thumb-meta">${kobacoEsc([c.archive_year,c.archive_category].filter(Boolean).join(' · '))}</div></div><a class="kobaco-thumb-play" href="${kobacoEsc(link)}" target="_blank" rel="noopener" title="공식 원문/영상 보기">▶</a></div><div class="kobaco-thumb-metrics">${metric('신뢰성',trust)}${metric('주요 인지경로',channel)}${metric('임팩트 1위',impact)}</div>`;
}
function caseMedia(c){
  if(!c || !Array.isArray(c.data_rows) || !c.data_rows.length){
    return `<div class="chat-case-media"><img src="/api/case-thumb/${encodeURIComponent(c.id)}" alt="${kobacoEsc(c.title)} 미리보기" loading="eager"></div>`;
  }
  const tables=(c.db_tables||[]).map(x=>kobacoEsc(x)).join(' · ');
  const rowsMap=kobacoRows(c);
  const id=String(c.id||'');
  const visual=id.startsWith('kobaco_publicad_')?kobacoPublicThumb(c,rowsMap):kobacoVisual(c);
  const rows=c.data_rows.map(r=>`<div class="kobaco-data-row"><b>${kobacoEsc(r.label||'항목')}</b><span>${kobacoEsc(r.value||'-')}</span></div>`).join('');
  return `<div class="chat-case-media"><div class="kobaco-data-card">${visual}<div class="kobaco-data-body"><div class="kobaco-data-kicker">PARQUET / DUCKDB · ${tables}</div><div class="kobaco-data-table">${rows}</div><div class="kobaco-data-note">${kobacoEsc(c.data_note||'KOBACO 실제 데이터 조회값')}</div></div></div></div>`;
}
</script>
'''
    page = page.replace("</body>", script + "\n</body>")
    return page


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v4():
    return HTMLResponse(_render_index_kobaco_v4())
