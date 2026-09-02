from __future__ import annotations

import html
import re
from urllib.parse import quote, unquote, urljoin

from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import literacy_kobaco_app_12 as previous

app = previous.app
base = previous.base
flow = previous.flow
v11 = previous.previous

_ASSET_CACHE: dict[str, dict[str, str]] = {}

_LINK_PATTERNS = (
    re.compile(r'(?:href|data-href|data-url)=["\']([^"\']+)["\']', re.I),
    re.compile(r'(?:location\.href|window\.location|location)\s*=\s*["\']([^"\']+)["\']', re.I),
)
_MEDIA_PATTERNS = (
    # AiSAC 실제 상세페이지는 .mp4 확장자 없이 /advideo/video/... 엔드포인트를 사용합니다.
    re.compile(r'<source[^>]+src=["\']([^"\']*/site/main/advideo/video/[^"\']+)["\']', re.I),
    re.compile(r'<source[^>]+src=["\']([^"\']+\.(?:mp4|webm|ogg)(?:\?[^"\']*)?)["\']', re.I),
    re.compile(r'<video[^>]+src=["\']([^"\']+\.(?:mp4|webm|ogg)(?:\?[^"\']*)?)["\']', re.I),
    re.compile(r'["\'](?:file|src|videoUrl|video_url|movieUrl|movie_url|fileUrl|file_url|vodUrl|vod_url)["\']\s*[:=]\s*["\']([^"\']+\.(?:mp4|webm|ogg)(?:\?[^"\']*)?)["\']', re.I),
    re.compile(r'(https?://[^"\'\s<>]+\.(?:mp4|webm|ogg)(?:\?[^"\'\s<>]*)?)', re.I),
    re.compile(r'["\']([^"\']+/[^"\']+\.(?:mp4|webm|ogg)(?:\?[^"\']*)?)["\']', re.I),
)
_IFRAME_PATTERN = re.compile(r'<iframe[^>]+src=["\']([^"\']+)["\']', re.I)
_POSTER_PATTERN = re.compile(r'<video[^>]+poster=["\']([^"\']+)["\']', re.I)
_ID_PATTERNS = (
    re.compile(r'advId(?:=|%3D|\s*[:=]\s*["\']?)([A-Za-z0-9_\-]{4,})', re.I),
    re.compile(r'(?:view|detail|goView|fnView|moveView)[^(]*\([^)]*["\']([A-Za-z0-9_\-]{4,})["\']', re.I),
)


def _clean_url(value: str, base_url: str) -> str:
    raw = html.unescape(str(value or "").strip()).replace("\\/", "/")
    if not raw or raw.startswith(("javascript:", "data:", "#")):
        return ""
    if raw.startswith("//"):
        return "https:" + raw
    return urljoin(base_url, raw)


def _title_areas(page: str, title: str, radius: int = 16000) -> list[str]:
    text = html.unescape(page or "")
    if not title:
        return [text]
    positions = [m.start() for m in re.finditer(re.escape(title), text, re.I)]
    areas = [text[max(0, pos - radius):pos + radius] for pos in positions[:8]]
    areas.append(text)
    return areas


def _detail_candidates(page: str, search_url: str, title: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        url = _clean_url(raw, search_url)
        if not url or url in seen:
            return
        low = url.lower()
        if "aisac.kobaco.co.kr" not in low or "/advideo/" not in low:
            return
        if "list_all_top" in low:
            return
        seen.add(url)
        out.append(url)

    for area in _title_areas(page, title):
        for pattern in _LINK_PATTERNS:
            for match in pattern.finditer(area):
                add(match.group(1))
        for pattern in _ID_PATTERNS:
            for match in pattern.finditer(area):
                adv_id = unquote(match.group(1)).strip()
                if not adv_id:
                    continue
                encoded = quote(adv_id, safe="-_~")
                for path in (
                    "/site/main/advideo/view_all_top?advId=",
                    "/site/main/advideo/view?advId=",
                    "/site/main/advideo/detail?advId=",
                    "/site/main/advideo/view_top?advId=",
                ):
                    add("https://aisac.kobaco.co.kr" + path + encoded)
    return out[:16]


def _extract_media(page: str, base_url: str) -> str:
    text = html.unescape(page or "").replace("\\/", "/")
    for pattern in _MEDIA_PATTERNS:
        for match in pattern.finditer(text):
            url = _clean_url(match.group(1), base_url)
            if url:
                return url
    return ""


def _extract_poster(page: str, base_url: str) -> str:
    match = _POSTER_PATTERN.search(page or "")
    if not match:
        return ""
    return _clean_url(match.group(1), base_url)


def _extract_iframe(page: str, base_url: str) -> str:
    candidates = []
    for match in _IFRAME_PATTERN.finditer(page or ""):
        url = _clean_url(match.group(1), base_url)
        if url:
            candidates.append(url)
    for url in candidates:
        low = url.lower()
        if any(word in low for word in ("player", "video", "media", "vod", "advideo")):
            return url
    return candidates[0] if candidates else ""


def _resolve_assets(case) -> dict[str, str]:
    case_id = str(case.get("id") or "")
    if case_id in _ASSET_CACHE:
        return _ASSET_CACHE[case_id]

    title = str(case.get("title") or "").strip()
    search_url = str(case.get("aisac_search_url") or v11._aisac_search_url(title))
    assets = {"detail": "", "video": "", "iframe": "", "thumb": ""}

    try:
        search_page = v11._fetch_html(search_url)
        candidates = _detail_candidates(search_page, search_url, title)

        # 기존 resolver에서 확인한 상세주소만 후보로 활용합니다. 임의 이미지/영상은 재사용하지 않습니다.
        legacy = v11._resolve_aisac_assets(case)
        if legacy.get("detail") and legacy["detail"] not in candidates:
            candidates.insert(0, legacy["detail"])

        for detail_url in candidates:
            try:
                detail_page = v11._fetch_html(detail_url, referer=search_url)
            except Exception:
                continue
            # 실제 광고 제목 또는 AiSAC 영상 태그가 있는 상세페이지를 채택합니다.
            low_page = detail_page.lower()
            if title and title.lower() not in low_page and "/site/main/advideo/video/" not in low_page:
                continue
            assets["detail"] = detail_url
            assets["video"] = _extract_media(detail_page, detail_url)
            assets["iframe"] = _extract_iframe(detail_page, detail_url)
            assets["thumb"] = _extract_poster(detail_page, detail_url)
            if assets["video"] or assets["iframe"]:
                break
    except Exception as exc:
        base.core.logger.warning("AiSAC v13 resolve failed for %s: %s", case_id, type(exc).__name__)

    _ASSET_CACHE[case_id] = assets
    return assets


def _case(case_id: str):
    return v11._aisac_case(case_id)


# 기존 v11 미디어 라우트는 새 resolver로 교체합니다.
for path in ("/api/aisac-open/{case_id}", "/api/aisac-thumb/{case_id}", "/api/aisac-video/{case_id}"):
    base._remove_route(path, "GET")


@app.get("/api/aisac-open/{case_id}")
def aisac_open_v13(case_id: str):
    case = _case(case_id)
    assets = _resolve_assets(case)
    if assets["detail"]:
        return RedirectResponse(assets["detail"], status_code=302)
    return RedirectResponse(str(case.get("aisac_search_url") or v11._aisac_search_url(case.get("title", ""))), status_code=302)


@app.get("/api/aisac-thumb/{case_id}")
def aisac_thumb_v13(case_id: str, request: FastAPIRequest):
    case = _case(case_id)
    assets = _resolve_assets(case)
    if assets["thumb"]:
        return v11._proxy_remote(
            assets["thumb"], request,
            referer=assets["detail"] or str(case.get("aisac_search_url") or ""),
            fallback_type="image/jpeg",
        )
    title = html.escape(str(case.get("title") or "KOBACO AiSAC 광고"))
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
    <rect width="1280" height="720" fill="#171513"/>
    <text x="70" y="94" fill="#f18a5b" font-family="Arial,sans-serif" font-size="24" font-weight="700">KOBACO AiSAC</text>
    <foreignObject x="70" y="190" width="1140" height="300"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:Arial,sans-serif;color:white;font-size:44px;font-weight:800;line-height:1.25">{title}</div></foreignObject>
    <text x="70" y="620" fill="#b8ada3" font-family="Arial,sans-serif" font-size="21">영상 재생 시 실제 광고 화면을 확인할 수 있습니다.</text>
    </svg>'''
    return Response(svg.encode("utf-8"), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=600"})


@app.get("/api/aisac-video/{case_id}")
def aisac_video_v13(case_id: str, request: FastAPIRequest):
    case = _case(case_id)
    assets = _resolve_assets(case)
    if not assets["video"]:
        return Response(status_code=404)
    return v11._proxy_remote(
        assets["video"], request,
        referer=assets["detail"] or str(case.get("aisac_search_url") or ""),
        fallback_type="video/mp4",
    )


@app.get("/api/aisac-player/{case_id}", response_class=HTMLResponse)
def aisac_player_v13(case_id: str):
    case = _case(case_id)
    assets = _resolve_assets(case)
    title = html.escape(str(case.get("title") or "AiSAC 광고"))
    poster = f"/api/aisac-thumb/{case_id}"

    if assets["video"]:
        body = f'''<video controls preload="metadata" poster="{poster}" playsinline>
          <source src="/api/aisac-video/{case_id}" type="video/mp4">
        </video>'''
    elif assets["iframe"]:
        src = html.escape(assets["iframe"], quote=True)
        body = f'<iframe src="{src}" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>'
    elif assets["detail"]:
        src = html.escape(assets["detail"], quote=True)
        body = f'''<a class="fallback" href="{src}" target="_blank" rel="noopener">
          <img src="{poster}" alt="{title} 미리보기"><span>원본 광고 열기</span>
        </a>'''
    else:
        body = f'<img class="poster" src="{poster}" alt="{title} 미리보기">'

    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#171513}}
video,iframe,.poster,.fallback{{width:100%;height:100%;display:block;border:0}}
video{{object-fit:contain;background:#171513}}
iframe{{background:#171513}}
.poster{{object-fit:contain}}
.fallback{{position:relative;text-decoration:none;color:#fff}}
.fallback img{{width:100%;height:100%;object-fit:contain;display:block}}
.fallback span{{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);padding:7px 11px;border-radius:7px;background:rgba(0,0,0,.72);font:700 11px sans-serif}}
</style></head><body>{body}</body></html>''')


def _render_index_kobaco_v13():
    page = previous._render_index_kobaco_v12()
    patch = r'''
<style>
.aisac-player-shell{width:100%;height:clamp(180px,32vh,250px);max-height:250px;background:#171513;overflow:hidden}
.aisac-player-frame{width:100%;height:100%;display:block;border:0;background:#171513}
@media(max-width:700px){.aisac-player-shell{height:clamp(160px,29vh,210px);max-height:210px}}
</style>
<script>
function aisacLearningCard(c){
  const r=fixedRows(c);
  const direct=`/api/aisac-open/${encodeURIComponent(c.id)}`;
  const search=aisacSearchUrl(c);
  const related=c.context_url?`<a class="alt" href="${esc(c.context_url)}" target="_blank" rel="noopener">${esc(c.context_label||'관련 자료 보기')} ↗</a>`:'';
  const verified=c.context_summary?`<div class="verified-context"><small>관련 자료에서 확인되는 내용</small><p>${esc(c.context_summary)}</p></div>`:'';
  return `<div class="chat-case-media"><div class="kobaco-data-card">
    <div class="aisac-player-shell"><iframe class="aisac-player-frame" src="/api/aisac-player/${encodeURIComponent(c.id)}" title="${esc(c.title||'AiSAC 광고')}" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe></div>
    <div class="aisac-card-title">${esc(c.title||'-')}</div>
    <div class="aisac-compact-actions"><div class="context-actions"><a href="${direct}" target="_blank" rel="noopener">원본 페이지 ↗</a><a class="alt" href="${esc(search)}" target="_blank" rel="noopener">검색 결과 ↗</a>${related}</div></div>
    <div class="aisac-info-column">
      <div class="fact-grid"><div><small>등록일</small><b>${esc(r['등록일']||c.registration_date||'-')}</b></div><div><small>광고주</small><b>${esc(r['광고주']||'-')}</b></div><div><small>업종</small><b>${esc(r['업종']||'-')}</b></div><div><small>검색 범위</small><b>2020-01-01 이후</b></div></div>
      ${verified}
      <div class="aisac-result"><small>AiSAC이 인식한 키워드</small><strong>${esc(r['키워드']||'-')}</strong><p>${esc(r['인식 횟수']||'-')}</p></div>
      <details class="kobaco-evidence"><summary>AiSAC 실제 데이터 항목 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-table">${fixedRawRows(c)}</div></div></details>
    </div>
  </div></div>`;
}
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v13():
    return HTMLResponse(_render_index_kobaco_v13())
