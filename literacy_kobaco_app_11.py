from __future__ import annotations

import html
import re
from datetime import date
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

import literacy_kobaco_app_10 as previous

# v10의 공익광고/OTT/AI 튜터는 그대로 유지하고,
# AiSAC 사례만 2020-01-01 이후로 고정하며 원본 광고 상세페이지까지 바로 엽니다.
app = previous.app
base = previous.base
flow = previous.flow
src = previous.v4.v1

AISAC_START_DATE = "2020-01-01"
AISAC_END_DATE = date.today().isoformat()
AISAC_SEARCH_BASE = "https://aisac.kobaco.co.kr/site/main/advideo/list_all_top"
AISAC_DETAIL_BASE = "https://aisac.kobaco.co.kr/site/main/advideo/view?advId="


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


_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
_DETAIL_PATTERNS = (
    re.compile(rf"/site/main/advideo/view\?advId=({_UUID})", re.I),
    re.compile(rf"advId(?:=|%3D|\s*[:=]\s*[\"']?)({_UUID})", re.I),
    re.compile(rf"(?:view|detail|goView|fnView|moveView)[^(]*\([^)]*[\"']({_UUID})[\"']", re.I),
)
_AISAC_DETAIL_CACHE: dict[str, str] = {}


def _extract_adv_id(page: str, title: str) -> str:
    text = html.unescape(page or "")
    positions = [m.start() for m in re.finditer(re.escape(title), text, re.I)] if title else []
    areas = []
    for pos in positions[:5]:
        areas.append(text[max(0, pos - 4500): pos + 4500])
    areas.append(text)
    for area in areas:
        for pattern in _DETAIL_PATTERNS:
            match = pattern.search(area)
            if match:
                return match.group(1)
    return ""


def _resolve_aisac_detail(case) -> str:
    case_id = str(case.get("id") or "")
    if case_id in _AISAC_DETAIL_CACHE:
        return _AISAC_DETAIL_CACHE[case_id]

    title = str(case.get("title") or "").strip()
    search_url = str(case.get("aisac_search_url") or _aisac_search_url(title))
    try:
        request = Request(
            search_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
            },
        )
        with urlopen(request, timeout=8) as response:
            raw = response.read(2_500_000)
        page = raw.decode("utf-8", errors="ignore")
        adv_id = _extract_adv_id(page, title)
        if adv_id:
            detail = AISAC_DETAIL_BASE + adv_id
            _AISAC_DETAIL_CACHE[case_id] = detail
            return detail
    except Exception as exc:
        base.core.logger.warning("AiSAC detail resolve failed for %s: %s", case_id, type(exc).__name__)

    _AISAC_DETAIL_CACHE[case_id] = ""
    return ""


@app.get("/api/aisac-open/{case_id}")
def aisac_open(case_id: str):
    found = flow.CASE_BY_ID.get(case_id)
    if not found or found[0] != "news" or not case_id.startswith("kobaco_aisac_"):
        raise HTTPException(404, "AiSAC 사례를 찾을 수 없습니다.")
    case = found[1]
    detail = _resolve_aisac_detail(case)
    if detail:
        return RedirectResponse(detail, status_code=302)
    # AiSAC 페이지 구조가 바뀌어 상세 ID를 추출하지 못한 경우에만 고정 기간 검색으로 이동합니다.
    return RedirectResponse(str(case.get("aisac_search_url") or _aisac_search_url(case.get("title", ""))), status_code=302)


def _render_index_kobaco_v11():
    page = previous._render_index_kobaco_v10()
    patch = r'''
<style>
.fact-grid{grid-template-columns:1.45fr .8fr 1fr .85fr}
@media(max-width:650px){.fact-grid{grid-template-columns:1fr}}
</style>
<script>
function aisacSearchUrl(c){
  return c.aisac_search_url || `https://aisac.kobaco.co.kr/site/main/advideo/list_all_top?kwdVal=${encodeURIComponent(c.title||'')}&listType=list&pageSize=12&startDate=2020-01-01&endDate=${new Date().toISOString().slice(0,10)}&sortDirection=DESC&sortOrder=ADV_LIKE`;
}
function aisacLearningCard(c){
  const r=fixedRows(c);
  const direct=`/api/aisac-open/${encodeURIComponent(c.id)}`;
  const search=aisacSearchUrl(c);
  const related=c.context_url?`<a class="alt" href="${esc(c.context_url)}" target="_blank" rel="noopener">${esc(c.context_label||'관련 자료 보기')} ↗</a>`:'';
  const verified=c.context_summary?`<div class="verified-context"><small>관련 자료에서 확인되는 내용</small><p>${esc(c.context_summary)}</p></div>`:'';
  return `<div class="chat-case-media"><div class="kobaco-data-card">
    <div class="context-card"><b>AiSAC 광고 원본</b><p>검색 기간 ${esc(c.aisac_start_date||'2020-01-01')} ~ ${esc(c.aisac_end_date||'')} · 사례도 같은 기간의 광고만 사용합니다.</p><div class="context-actions"><a href="${direct}" target="_blank" rel="noopener">원본 광고 바로 보기 ↗</a><a class="alt" href="${esc(search)}" target="_blank" rel="noopener">검색 결과 확인 ↗</a>${related}</div></div>
    <div class="fact-grid"><div><small>광고명</small><b>${esc(c.title||'-')}</b></div><div><small>등록일</small><b>${esc(r['등록일']||c.registration_date||'-')}</b></div><div><small>광고주</small><b>${esc(r['광고주']||'-')}</b></div><div><small>업종</small><b>${esc(r['업종']||'-')}</b></div></div>
    ${verified}
    <div class="aisac-result"><small>AiSAC이 인식한 키워드</small><strong>${esc(r['키워드']||'-')}</strong><p>${esc(r['인식 횟수']||'-')}</p></div>
    <details class="kobaco-evidence"><summary>AiSAC 실제 데이터 항목 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-table">${fixedRawRows(c)}</div></div></details>
  </div></div>`;
}
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v11():
    return HTMLResponse(_render_index_kobaco_v11())
