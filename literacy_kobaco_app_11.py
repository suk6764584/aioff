from __future__ import annotations

import html
import re
from datetime import date
from urllib.parse import quote, unquote, urljoin
from urllib.request import Request as URLRequest, urlopen

from fastapi import HTTPException, Request as FastAPIRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

import literacy_kobaco_app_10 as previous

# v10의 공익광고/OTT/AI 튜터는 그대로 유지하고,
# AiSAC 사례만 2020-01-01 이후로 고정하며 실제 썸네일/영상을 학생 화면에 표시합니다.
app = previous.app
base = previous.base
flow = previous.flow
src = previous.v4.v1

AISAC_START_DATE = "2020-01-01"
AISAC_END_DATE = date.today().isoformat()
AISAC_SEARCH_BASE = "https://aisac.kobaco.co.kr/site/main/advideo/list_all_top"
AISAC_DETAIL_BASE = "https://aisac.kobaco.co.kr/site/main/advideo/view?advId="
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36"


def _aisac_search_url(title: str) -> str:
    return (
        f"{AISAC_SEARCH_BASE}?kwdVal={quote(str(title or '').strip())}"
        f"&listType=list&pageSize=12&startDate={AISAC_START_DATE}&endDate={AISAC_END_DATE}"
        "&sortDirection=DESC&sortOrder=ADV_LIKE"
    )


def _rebuild_aisac_cases_2020() -> None:
    db = src.get_kobaco_db()
    required = ("aisac_ad_info", "aisac_ai_keywords")
    if db is None or not db.has_tables(*required):
        return

    rows = db.query(
        '''
        WITH joined AS (
          SELECT
            a."광고소재명",
            a."광고소재등록일",
            a."대업종 분류" AS "대업종",
            a."중업종 분류" AS "중업종",
            a."광고주명",
            k."얼굴인식 개수",
            k."사물인식 개수",
            k."장소인식 개수",
            k."키워드 개수",
            k."키워드",
            ROW_NUMBER() OVER (
              PARTITION BY a."광고소재명", a."광고소재등록일"
              ORDER BY a."광고소재명"
            ) AS duplicate_rn,
            ROW_NUMBER() OVER (
              PARTITION BY COALESCE(a."대업종 분류", '기타')
              ORDER BY a."광고소재등록일" DESC, a."광고소재명"
            ) AS category_rn
          FROM aisac_ad_info a
          JOIN aisac_ai_keywords k
            ON a."광고소재명" = k."광고소재명"
           AND a."광고소재등록일" = k."광고소재등록일"
          WHERE NULLIF(TRIM(CAST(k."키워드" AS VARCHAR)), '') IS NOT NULL
            AND COALESCE(k."키워드 개수", 0) >= 3
            AND TRY_CAST(SUBSTR(CAST(a."광고소재등록일" AS VARCHAR), 1, 4) AS INTEGER) >= 2020
        )
        SELECT * EXCLUDE (duplicate_rn, category_rn)
        FROM joined
        WHERE duplicate_rn = 1 AND category_rn <= 3
        ORDER BY "광고소재등록일" DESC, "대업종", "광고소재명"
        LIMIT 24
        '''
    )

    cases = []
    seen: set[str] = set()
    for row in rows:
        name = src._text(row.get("광고소재명"))
        if not name or name == "-" or name in seen:
            continue
        seen.add(name)
        registered = src._text(row.get("광고소재등록일"))
        keywords = src._compact_keywords(row.get("키워드"))
        category = " / ".join(
            x for x in [src._text(row.get("대업종"), ""), src._text(row.get("중업종"), "")] if x
        )
        idx = len(cases) + 1
        case = src._common_case(
            case_id=f"kobaco_aisac_{idx:02d}",
            label="AiSAC 실제 광고 · 2020년 이후",
            title=name,
            claim=f"'{name}' 원본 광고와 AiSAC 인식 결과를 함께 확인하는 사례입니다.",
            source_name="KOBACO AiSAC",
            source_url=_aisac_search_url(name),
            source_excerpt=f"{registered} · AI 인식 키워드: {keywords}",
            clues=[
                f"광고소재등록일: {registered}",
                f"업종: {category or '-'} / 광고주: {src._text(row.get('광고주명'))}",
                f"AiSAC 키워드 개수: {src._int_text(row.get('키워드 개수'))}",
                f"사물인식 개수: {src._int_text(row.get('사물인식 개수'))}, 장소인식 개수: {src._int_text(row.get('장소인식 개수'))}",
                f"DB 키워드 원문: {keywords}",
            ],
            resolution="원본 광고의 장면·문구와 AiSAC 인식 결과를 함께 보고 두 정보가 일치하는 부분과 다른 부분을 구분합니다.",
            opening_questions=[
                f"'{name}' 원본 광고를 먼저 보고 무엇을 홍보하는 광고인지 한 문장으로 적어보세요. 그 다음 AiSAC 키워드 중 실제 영상에서 확인되는 단어 하나를 골라보세요.",
                f"'{name}'에서 직접 본 장면이나 문구 하나와 AiSAC이 인식한 키워드 하나를 짝지어보세요.",
                "원본 광고에서 직접 확인한 사실 하나와 AiSAC이 인식한 항목 하나를 각각 적어보세요.",
            ],
            db_tables=list(required),
            data_rows=[
                {"label": "등록일", "value": registered},
                {"label": "광고주", "value": src._text(row.get("광고주명"))},
                {"label": "업종", "value": category or "-"},
                {"label": "키워드", "value": keywords},
                {"label": "인식 횟수", "value": f"사물 {src._int_text(row.get('사물인식 개수'))} · 장소 {src._int_text(row.get('장소인식 개수'))}"},
            ],
            data_note="AiSAC 광고소재 메타데이터와 AI 인식결과 중 2020-01-01 이후 등록 광고만 사용합니다.",
        )
        case["aisac_search_url"] = _aisac_search_url(name)
        case["aisac_start_date"] = AISAC_START_DATE
        case["aisac_end_date"] = AISAC_END_DATE
        case["registration_date"] = registered
        cases.append(case)

    if len(cases) >= 3:
        flow.CASE_LIBRARY["news"] = cases
        flow.CASE_BY_ID.clear()
        flow.CASE_BY_ID.update({
            case["id"]: (lesson_id, case)
            for lesson_id, lesson_cases in flow.CASE_LIBRARY.items()
            for case in lesson_cases
        })


_rebuild_aisac_cases_2020()


# v10 공개 payload에 AiSAC 직접열기용 필드를 추가합니다.
_OLD_PUBLIC_CASE = flow._public_case


def _public_case_v11(case):
    data = dict(_OLD_PUBLIC_CASE(case))
    for key in (
        "aisac_search_url", "aisac_start_date", "aisac_end_date", "registration_date",
    ):
        data[key] = case.get(key, "")
    return data


flow._public_case = _public_case_v11


# AiSAC advId가 반드시 UUID라는 가정을 두지 않습니다.
_DETAIL_PATTERNS = (
    re.compile(r'/site/main/advideo/view\?advId=([^"\'&<>\s]+)', re.I),
    re.compile(r'advId(?:=|%3D|\s*[:=]\s*["\']?)([A-Za-z0-9_\-]{4,})', re.I),
    re.compile(r'(?:view|detail|goView|fnView|moveView)[^(]*\([^)]*["\']([A-Za-z0-9_\-]{4,})["\']', re.I),
)
_IMG_PATTERNS = (
    re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image|twitter:image:src)["\'][^>]+content=["\']([^"\']+)', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image|twitter:image:src)["\']', re.I),
    re.compile(r'<video[^>]+poster=["\']([^"\']+)', re.I),
    re.compile(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)', re.I),
)
_VIDEO_PATTERNS = (
    re.compile(r'<source[^>]+src=["\']([^"\']+\.(?:mp4|webm)(?:\?[^"\']*)?)["\']', re.I),
    re.compile(r'<video[^>]+src=["\']([^"\']+\.(?:mp4|webm)(?:\?[^"\']*)?)["\']', re.I),
    re.compile(r'["\'](?:file|src|videoUrl|video_url|movieUrl|movie_url|fileUrl|file_url|vodUrl|vod_url)["\']\s*[:=]\s*["\']([^"\']+\.(?:mp4|webm)(?:\?[^"\']*)?)["\']', re.I),
    re.compile(r'(https?://[^"\'\s<>]+\.(?:mp4|webm)(?:\?[^"\'\s<>]*)?)', re.I),
    re.compile(r'["\']([^"\']+/[^"\']+\.(?:mp4|webm)(?:\?[^"\']*)?)["\']', re.I),
)
_AISAC_ASSET_CACHE: dict[str, dict[str, str]] = {}


def _clean_asset_url(value: str, base_url: str) -> str:
    raw = html.unescape(str(value or "").strip()).replace("\\/", "/")
    if not raw or raw.startswith("data:") or raw.startswith("javascript:"):
        return ""
    if raw.startswith("//"):
        return "https:" + raw
    return urljoin(base_url, raw)


def _fetch_html(url: str, limit: int = 3_500_000, referer: str = "") -> str:
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    }
    if referer:
        headers["Referer"] = referer
    request = URLRequest(url, headers=headers)
    with urlopen(request, timeout=10) as response:
        raw = response.read(limit)
    return raw.decode("utf-8", errors="ignore")


def _title_areas(page: str, title: str, radius: int = 12000) -> list[str]:
    text = html.unescape(page or "")
    positions = [m.start() for m in re.finditer(re.escape(title), text, re.I)] if title else []
    areas = [text[max(0, pos - radius): pos + radius] for pos in positions[:8]]
    areas.append(text)
    return areas


def _extract_adv_id(page: str, title: str) -> str:
    for area in _title_areas(page, title):
        for pattern in _DETAIL_PATTERNS:
            match = pattern.search(area)
            if match:
                return unquote(match.group(1)).strip()
    return ""


def _extract_image(page: str, base_url: str, title: str = "") -> str:
    for area in _title_areas(page, title) if title else [page]:
        for pattern in _IMG_PATTERNS:
            for match in pattern.finditer(area):
                candidate = _clean_asset_url(match.group(1), base_url)
                low = candidate.lower()
                if candidate and not any(x in low for x in ("logo", "icon", "favicon", "spinner", "loading", "common/")):
                    return candidate
    return ""


def _extract_video(page: str, base_url: str) -> str:
    text = html.unescape(page or "").replace("\\/", "/")
    for pattern in _VIDEO_PATTERNS:
        for match in pattern.finditer(text):
            candidate = _clean_asset_url(match.group(1), base_url)
            if candidate:
                return candidate
    return ""


def _resolve_aisac_assets(case) -> dict[str, str]:
    case_id = str(case.get("id") or "")
    if case_id in _AISAC_ASSET_CACHE:
        return _AISAC_ASSET_CACHE[case_id]

    title = str(case.get("title") or "").strip()
    search_url = str(case.get("aisac_search_url") or _aisac_search_url(title))
    assets = {"detail": "", "thumb": "", "video": ""}
    try:
        search_page = _fetch_html(search_url)
        assets["thumb"] = _extract_image(search_page, search_url, title)
        adv_id = _extract_adv_id(search_page, title)
        if adv_id:
            detail_url = AISAC_DETAIL_BASE + quote(adv_id, safe="-_~")
            assets["detail"] = detail_url
            detail_page = _fetch_html(detail_url, referer=search_url)
            assets["video"] = _extract_video(detail_page, detail_url)
            detail_thumb = _extract_image(detail_page, detail_url, title)
            if detail_thumb:
                assets["thumb"] = detail_thumb
    except Exception as exc:
        base.core.logger.warning("AiSAC asset resolve failed for %s: %s", case_id, type(exc).__name__)

    _AISAC_ASSET_CACHE[case_id] = assets
    return assets


def _aisac_case(case_id: str):
    found = flow.CASE_BY_ID.get(case_id)
    if not found or found[0] != "news" or not case_id.startswith("kobaco_aisac_"):
        raise HTTPException(404, "AiSAC 사례를 찾을 수 없습니다.")
    return found[1]


def _proxy_remote(url: str, request: FastAPIRequest, referer: str = "", fallback_type: str = "application/octet-stream"):
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": request.headers.get("accept", "*/*"),
    }
    if referer:
        headers["Referer"] = referer
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    try:
        upstream = urlopen(URLRequest(url, headers=headers), timeout=20)
    except Exception as exc:
        base.core.logger.warning("AiSAC media proxy failed: %s", type(exc).__name__)
        return Response(status_code=502)

    status = getattr(upstream, "status", 200) or 200
    content_type = upstream.headers.get("Content-Type") or fallback_type
    response_headers = {"Cache-Control": "public, max-age=1800"}
    for key in ("Content-Length", "Content-Range", "Accept-Ranges"):
        value = upstream.headers.get(key)
        if value:
            response_headers[key] = value

    def iterator():
        try:
            while True:
                chunk = upstream.read(256 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    return StreamingResponse(iterator(), status_code=status, media_type=content_type, headers=response_headers)


@app.get("/api/aisac-open/{case_id}")
def aisac_open(case_id: str):
    case = _aisac_case(case_id)
    assets = _resolve_aisac_assets(case)
    if assets["detail"]:
        return RedirectResponse(assets["detail"], status_code=302)
    return RedirectResponse(str(case.get("aisac_search_url") or _aisac_search_url(case.get("title", ""))), status_code=302)


@app.get("/api/aisac-thumb/{case_id}")
def aisac_thumbnail(case_id: str, request: FastAPIRequest):
    case = _aisac_case(case_id)
    assets = _resolve_aisac_assets(case)
    if assets["thumb"]:
        return _proxy_remote(
            assets["thumb"],
            request,
            referer=assets["detail"] or str(case.get("aisac_search_url") or ""),
            fallback_type="image/jpeg",
        )
    title = html.escape(str(case.get("title") or "KOBACO AiSAC 광고"))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
    <rect width="1280" height="720" fill="#e9e4dc"/>
    <text x="72" y="92" fill="#df6635" font-family="Arial,sans-serif" font-size="24" font-weight="700">KOBACO AiSAC</text>
    <foreignObject x="72" y="185" width="1120" height="280"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:Arial,sans-serif;color:#2a2521;font-size:48px;font-weight:800;line-height:1.25">{title}</div></foreignObject>
    <text x="72" y="600" fill="#766b61" font-family="Arial,sans-serif" font-size="22">원본 페이지에서 미리보기를 불러오는 중입니다.</text>
    </svg>'''
    return Response(svg.encode("utf-8"), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=600"})


@app.get("/api/aisac-video/{case_id}")
def aisac_video(case_id: str, request: FastAPIRequest):
    case = _aisac_case(case_id)
    assets = _resolve_aisac_assets(case)
    if not assets["video"]:
        return Response(status_code=404)
    return _proxy_remote(
        assets["video"],
        request,
        referer=assets["detail"] or str(case.get("aisac_search_url") or ""),
        fallback_type="video/mp4",
    )


def _render_index_kobaco_v11():
    page = previous._render_index_kobaco_v10()
    patch = r'''
<style>
.aisac-learning-grid{display:grid;grid-template-columns:minmax(270px,.92fr) minmax(0,1.08fr);background:#fff;border-bottom:1px solid #ded5ca}
.aisac-media-column{min-width:0;border-right:1px solid #e1d9cf;background:#f7f4ef}.aisac-info-column{min-width:0;background:#fff}
.aisac-video-stage{position:relative;height:228px;background:#171513;overflow:hidden}.aisac-video-stage video{position:relative;z-index:2;width:100%;height:100%;display:block;object-fit:contain;background:transparent}.aisac-video-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:1}.aisac-video-stage.video-failed video{display:none}.aisac-video-fallback{display:none;position:absolute;inset:0;z-index:3;align-items:center;justify-content:center;text-align:center;padding:20px;background:rgba(24,21,18,.72);color:#fff;font-size:11px;line-height:1.55}.aisac-video-stage.video-failed .aisac-video-fallback{display:flex}
.aisac-card-title{padding:9px 12px;background:#fff;border-top:1px solid #e2dbd1;font-size:11px;font-weight:900;line-height:1.35}.aisac-compact-actions{padding:8px 10px;background:#fff}.aisac-compact-actions .context-actions{margin:0;gap:6px}.aisac-compact-actions .context-actions a{padding:6px 8px;font-size:9px}
.aisac-info-column .fact-grid{grid-template-columns:1fr 1fr;padding:9px;gap:6px}.aisac-info-column .fact-grid div{padding:8px}.aisac-info-column .fact-grid small{font-size:8px}.aisac-info-column .fact-grid b{font-size:10px;line-height:1.3}.aisac-info-column .verified-context{padding:9px 11px}.aisac-info-column .verified-context p{font-size:10px;line-height:1.45}.aisac-info-column .aisac-result{padding:10px 11px}.aisac-info-column .aisac-result small{font-size:8px}.aisac-info-column .aisac-result strong{font-size:11px;line-height:1.45;max-height:66px;overflow:auto}.aisac-info-column .aisac-result p{font-size:9px;margin-top:4px}.aisac-info-column details{margin:0}.aisac-info-column details summary{font-size:9px}
.aisac-picker-media{height:86px;margin:-10px -10px 9px;overflow:hidden;border-radius:7px 7px 4px 4px;background:#eee8df}.aisac-picker-media img{width:100%;height:100%;object-fit:cover;display:block}
@media(max-width:700px){.aisac-learning-grid{grid-template-columns:1fr}.aisac-media-column{border-right:0}.aisac-video-stage{height:185px}.aisac-info-column .fact-grid{grid-template-columns:1fr 1fr}.aisac-picker-media{height:72px}}
</style>
<script>
function fixedPreview(c){
  const id=String(c.id||'');
  if(id.startsWith('kobaco_publicad_')) return `<div class="kobaco-picker-media"><img src="/api/kobaco-media-thumb/${encodeURIComponent(c.id)}" alt="공익광고 썸네일" loading="lazy"></div>`;
  if(id.startsWith('kobaco_aisac_')) return `<div class="aisac-picker-media"><img src="/api/aisac-thumb/${encodeURIComponent(c.id)}" alt="${esc(c.title||'AiSAC 광고')} 썸네일" loading="lazy"></div>`;
  if(id.startsWith('kobaco_ott_')) return `<div class="topic-preview ott"><b>청소년·OTT 통계</b><span>13-19세 조사 조건과 이용률</span></div>`;
  return '';
}
function aisacSearchUrl(c){
  return c.aisac_search_url || `https://aisac.kobaco.co.kr/site/main/advideo/list_all_top?kwdVal=${encodeURIComponent(c.title||'')}&listType=list&pageSize=12&startDate=2020-01-01&endDate=${new Date().toISOString().slice(0,10)}&sortDirection=DESC&sortOrder=ADV_LIKE`;
}
function aisacVideoFailed(el){
  const stage=el.closest('.aisac-video-stage');
  if(stage)stage.classList.add('video-failed');
}
function aisacLearningCard(c){
  const r=fixedRows(c);
  const direct=`/api/aisac-open/${encodeURIComponent(c.id)}`;
  const video=`/api/aisac-video/${encodeURIComponent(c.id)}`;
  const thumb=`/api/aisac-thumb/${encodeURIComponent(c.id)}`;
  const search=aisacSearchUrl(c);
  const related=c.context_url?`<a class="alt" href="${esc(c.context_url)}" target="_blank" rel="noopener">${esc(c.context_label||'관련 자료 보기')} ↗</a>`:'';
  const verified=c.context_summary?`<div class="verified-context"><small>관련 자료에서 확인되는 내용</small><p>${esc(c.context_summary)}</p></div>`:'';
  return `<div class="chat-case-media"><div class="kobaco-data-card"><div class="aisac-learning-grid">
    <div class="aisac-media-column">
      <div class="aisac-video-stage"><img class="aisac-video-poster" src="${thumb}" alt="${esc(c.title||'AiSAC 광고')} 썸네일"><video controls preload="metadata" poster="${thumb}" onerror="aisacVideoFailed(this)"><source src="${video}" type="video/mp4"></video><div class="aisac-video-fallback">이 사례는 브라우저에서 직접 재생할 영상 주소를 확인하지 못했습니다.<br>아래 원본 페이지에서 바로 볼 수 있습니다.</div></div>
      <div class="aisac-card-title">${esc(c.title||'-')}</div>
      <div class="aisac-compact-actions"><div class="context-actions"><a href="${direct}" target="_blank" rel="noopener">원본 페이지 ↗</a><a class="alt" href="${esc(search)}" target="_blank" rel="noopener">검색 결과 ↗</a>${related}</div></div>
    </div>
    <div class="aisac-info-column">
      <div class="fact-grid"><div><small>등록일</small><b>${esc(r['등록일']||c.registration_date||'-')}</b></div><div><small>광고주</small><b>${esc(r['광고주']||'-')}</b></div><div><small>업종</small><b>${esc(r['업종']||'-')}</b></div><div><small>검색 범위</small><b>2020-01-01 이후</b></div></div>
      ${verified}
      <div class="aisac-result"><small>AiSAC이 인식한 키워드</small><strong>${esc(r['키워드']||'-')}</strong><p>${esc(r['인식 횟수']||'-')}</p></div>
      <details class="kobaco-evidence"><summary>AiSAC 실제 데이터 항목 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-table">${fixedRawRows(c)}</div></div></details>
    </div>
  </div></div></div>`;
}
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v11():
    return HTMLResponse(_render_index_kobaco_v11())
