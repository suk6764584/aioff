from __future__ import annotations

import html
import re
from urllib.parse import urljoin
from urllib.request import Request as URLRequest, urlopen

from fastapi import Request as FastAPIRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import literacy_kobaco_app_12 as previous

app = previous.app
base = previous.base
flow = previous.flow
v11 = previous.previous

_ASSET_CACHE: dict[str, dict[str, str]] = {}

# 검색결과에서 실제 공개 상세페이지 링크만 사용합니다.
_VIEW_PATTERN = re.compile(
    r'(?:https?://aisac\.kobaco\.co\.kr)?(/site/main/advideo/view\?advId=[0-9a-fA-F\-]{36})',
    re.I,
)
_MEDIA_PATTERNS = (
    # AiSAC 실제 상세페이지는 .mp4 확장자 없이 /advideo/video/... 엔드포인트를 사용합니다.
    re.compile(r'<source[^>]+src=["\']([^"\']*/site/main/advideo/video/[^"\']+)["\']', re.I),
    re.compile(r'<source[^>]+src=["\']([^"\']+\.(?:mp4|webm|ogg)(?:\?[^"\']*)?)["\']', re.I),
    re.compile(r'<video[^>]+src=["\']([^"\']+\.(?:mp4|webm|ogg)(?:\?[^"\']*)?)["\']', re.I),
)
_POSTER_PATTERN = re.compile(r'<video[^>]+poster=["\']([^"\']+)["\']', re.I)


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
        return []
    positions = [m.start() for m in re.finditer(re.escape(title), text, re.I)]
    return [text[max(0, pos - radius):pos + radius] for pos in positions[:8]]


def _detail_candidates(page: str, search_url: str, title: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for area in _title_areas(page, title):
        for match in _VIEW_PATTERN.finditer(area):
            url = _clean_url(match.group(1), search_url)
            if url and url not in seen:
                seen.add(url)
                out.append(url)
    return out


def _extract_media(page: str, base_url: str) -> str:
    text = html.unescape(page or "").replace("\\/", "/")
    for pattern in _MEDIA_PATTERNS:
        match = pattern.search(text)
        if match:
            url = _clean_url(match.group(1), base_url)
            if url and "xxx.mp4" not in url.lower():
                return url
    return ""


def _extract_poster(page: str, base_url: str) -> str:
    match = _POSTER_PATTERN.search(page or "")
    if not match:
        return ""
    url = _clean_url(match.group(1), base_url)
    if "bg_login" in url.lower():
        return ""
    return url


def _is_real_video(url: str, referer: str) -> bool:
    if not url or "xxx.mp4" in url.lower():
        return False
    headers = {
        "User-Agent": v11._USER_AGENT,
        "Accept": "video/*,*/*;q=0.8",
        "Range": "bytes=0-31",
        "Referer": referer,
    }
    try:
        with urlopen(URLRequest(url, headers=headers), timeout=10) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            first = response.read(32)
        if content_type.startswith("video/"):
            return True
        # MP4는 일반적으로 4바이트 길이 뒤에 ftyp 시그니처가 옵니다.
        return len(first) >= 8 and first[4:8] == b"ftyp"
    except Exception:
        return False


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

        for detail_url in candidates:
            try:
                detail_page = v11._fetch_html(detail_url, referer=search_url)
            except Exception:
                continue

            # 검색된 광고 제목이 실제 상세페이지에도 있어야 같은 사례로 인정합니다.
            if title and title.lower() not in detail_page.lower():
                continue

            video_url = _extract_media(detail_page, detail_url)
            if not video_url or not _is_real_video(video_url, detail_url):
                continue

            assets["detail"] = detail_url
            assets["video"] = video_url
            assets["thumb"] = _extract_poster(detail_page, detail_url)
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
        referer=assets["detail"],
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
    elif assets["detail"]:
        src = html.escape(assets["detail"], quote=True)
        body = f'''<a class="fallback" href="{src}" target="_blank" rel="noopener">
          <img src="{poster}" alt="{title} 미리보기"><span>원본 광고 열기</span>
        </a>'''
    else:
        body = f'<img class="poster" src="{poster}" alt="{title} 미리보기">'

    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#171513}}
video,.poster,.fallback{{width:100%;height:100%;display:block;border:0}}
video{{object-fit:contain;background:#171513}}
.poster{{object-fit:contain}}
.fallback{{position:relative;text-decoration:none;color:#fff}}
.fallback img{{width:100%;height:100%;object-fit:contain;display:block}}
.fallback span{{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);padding:7px 11px;border-radius:7px;background:rgba(0,0,0,.72);font:700 11px sans-serif}}
</style></head><body>{body}</body></html>''')


def _render_index_kobaco_v13():
    page = previous._render_index_kobaco_v12()
    patch = r'''
<style>
/* 실제 영상 플레이어는 현재 정상 동작을 유지하고, 화면 밀도만 정리합니다. */
.aisac-player-shell{width:100%;height:clamp(180px,32vh,250px);max-height:250px;background:#171513;overflow:hidden}
.aisac-player-frame{width:100%;height:100%;display:block;border:0;background:#171513}
.aisac-card-title{padding:8px 12px 3px;font-size:11px;font-weight:850;line-height:1.4}
.aisac-compact-actions{padding:0 12px 8px}.aisac-compact-actions .context-actions{margin-top:4px}
.aisac-info-column .fact-grid{padding:9px 12px;gap:6px}.aisac-info-column .aisac-result{padding:10px 12px}

/* AiSAC 사례 선택 카드에서는 실제 광고 MP4의 첫 프레임을 미리보기로 사용합니다. */
.aisac-picker-media{height:82px;margin:-10px -10px 9px;border-radius:7px;overflow:hidden;position:relative;background:#171513}
.aisac-picker-video{display:block;width:100%;height:100%;object-fit:cover;background:#171513;pointer-events:none}
.aisac-picker-media span{position:absolute;left:7px;bottom:6px;padding:3px 6px;border-radius:5px;background:rgba(0,0,0,.62);color:#fff;font-size:8px;font-weight:850;pointer-events:none}
@media(max-width:700px){
  .aisac-player-shell{height:clamp(160px,29vh,210px);max-height:210px}
}
</style>
<script>
/* 기존 public-ad/OTT 미리보기는 그대로 두고 AiSAC만 실제 영상 첫 프레임으로 교체합니다. */
const fixedPreviewBeforeV13=fixedPreview;
function fixedPreview(c){
  const id=String(c?.id||'');
  if(id.startsWith('kobaco_aisac_')){
    const cid=encodeURIComponent(c.id);
    return `<div class="aisac-picker-media"><video class="aisac-picker-video" muted playsinline preload="auto" src="/api/aisac-video/${cid}#t=0.1" onloadedmetadata="try{if(this.duration>0){this.currentTime=Math.min(.1,this.duration/2)}}catch(e){}"></video><span>AI가 읽은 광고</span></div>`;
  }
  return fixedPreviewBeforeV13(c);
}

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
