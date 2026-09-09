from __future__ import annotations

import html
import json
import mimetypes
import posixpath
import random
import re
import sqlite3
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from urllib.parse import quote, urljoin
from urllib.request import Request as URLRequest, urlopen
from xml.etree import ElementTree as ET

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter

import literacy_app as base
from kobaco_db import get_kobaco_db, kobaco_status

app = base.app
ROOT = Path(__file__).resolve().parent
EDU_DB = ROOT / "data" / "education" / "education.db"
EDU_FILES = (ROOT / "data" / "education" / "files").resolve()
ARCHIVE_URL = "https://xn--2z1b40gs9nlqcf0n.kr/front/archive/archiveMainList.do"

base.LESSONS.clear()
base.LESSONS.update({
    "news": {
        "title": "AI가 읽은 광고 vs 사람이 읽은 맥락",
        "short": "AiSAC이 실제 광고에서 인식한 사물·장소·키워드와 사람이 이해한 광고 메시지를 구분합니다.",
        "source_name": "KOBACO AiSAC 광고소재 AI 인식결과·키워드 DB",
        "source_url": "https://aisac.kobaco.co.kr",
        "source_role": "실제 KOBACO DB 학습 데이터",
        "source_note": "AiSAC 광고소재 메타데이터와 AI 인식 사물·장소·키워드를 서버의 Parquet DB에서 직접 조회해 사례를 구성합니다.",
        "criteria": [
            "DB가 직접 기록한 광고소재·업종·광고주·AI 인식값과 내가 붙인 해석을 구분한다.",
            "AI가 인식한 사물·장소·키워드를 광고의 의도나 핵심 메시지와 같은 뜻으로 단정하지 않는다.",
            "광고의 의미를 설명하려면 원본 영상·문구와 광고주·제품 맥락을 추가로 확인한다.",
            "AI 인식 결과에는 누락·오인식 가능성이 있으므로 중요한 판단은 원본과 비교한다.",
            "보고서에 사용할 때는 어떤 DB 필드와 등록 시점에서 나온 값인지 출처를 함께 밝힌다.",
        ],
        "skills": ["관측값·해석 구분", "AI 인식 한계 판단", "원본 맥락 확인"],
        "starter": "AiSAC 실제 광고 데이터를 선택해 AI 인식값과 광고 메시지를 구분해봅니다.",
        "safety_note": "",
    },
    "deepfake": {
        "title": "리터러시 교육 안내서",
        "short": "수집된 디지털윤리 교육 안내서의 개념과 활동을 무작위 사례로 읽고 직접 적용합니다.",
        "source_name": "디지털윤리 교육자료실",
        "source_url": ARCHIVE_URL,
        "source_role": "공식 디지털윤리 교육자료",
        "source_note": "수집된 디지털윤리 교육 안내서와 활동 자료 전체를 학습 자료로 사용합니다.",
        "criteria": [
            "자료에 적힌 개념과 활동 지시를 먼저 확인한다.",
            "사실·해석·의견을 구분해 자신의 말로 설명한다.",
            "정보의 출처와 근거를 확인하고 필요한 경우 교차검증한다.",
            "디지털 환경에서 안전하고 책임 있는 행동으로 연결한다.",
            "AI가 대신 결론 내리게 하기보다 학생이 직접 판단하고 답한다.",
        ],
        "skills": ["정보판별", "디지털 안전", "AI 윤리", "디지털 소통"],
        "starter": "공식 리터러시 교육자료를 골라 읽고 직접 생각해봅니다.",
        "safety_note": "",
    },
    "ai": {
        "title": "최신 뉴스에서 사실과 해석 구분하기",
        "short": "실제 최신 뉴스의 제목·출처·게시 시점과 동일 사건 보도를 비교해 사실과 해석을 구분합니다.",
        "source_name": "AI OFF 2026 뉴스 수집·동일사건 정제 데이터",
        "source_url": "",
        "source_role": "실제 뉴스 사례 학습 데이터",
        "source_note": "수집 뉴스를 동일 사건 단위로 정제한 대표기사를 사용합니다.",
        "criteria": [
            "제목만으로 사건 전체를 확정하지 않고 원문을 확인한다.",
            "언론사·게시 시점·인용 주체와 근거 출처를 확인한다.",
            "기사에서 직접 확인되는 사실과 기자·제목의 해석 또는 평가를 구분한다.",
            "같은 사건을 다룬 독립된 다른 보도와 표현·근거를 비교한다.",
            "근거가 부족하면 결론을 서두르지 않고 판단을 유보한다.",
        ],
        "skills": ["사실·해석 구분", "출처 확인", "교차검증"],
        "starter": "최신 뉴스 사례를 골라 사실과 해석을 구분해봅니다.",
        "safety_note": "",
    },
})

CASE_LIBRARY: dict[str, list[dict[str, Any]]] = {"news": [], "deepfake": [], "ai": []}
CASE_BY_ID: dict[str, tuple[str, dict[str, Any]]] = {}
with base.core.connect_db() as _conn:
    _conn.execute("CREATE TABLE IF NOT EXISTS session_cases(session_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")

class CaseStartRequest(BaseModel):
    lesson_id: str
    case_id: str

def _save_case(session_id: str, case_id: str) -> None:
    with base.core.connect_db() as conn:
        conn.execute("INSERT INTO session_cases(session_id,case_id) VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET case_id=excluded.case_id", (session_id, case_id))

def _get_case_id(session_id: str) -> str | None:
    with base.core.connect_db() as conn:
        row = conn.execute("SELECT case_id FROM session_cases WHERE session_id=?", (session_id,)).fetchone()
    return str(row["case_id"]) if row and str(row["case_id"]) in CASE_BY_ID else None

def _public_case(case: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "label", "title", "claim", "source_name", "source_url", "source_excerpt", "media_type", "media_url", "media_caption",
        "opening_question", "opening_questions", "clues", "resolution", "db_tables", "data_rows", "data_note",
        "context_url", "context_label", "context_summary", "aisac_search_url", "aisac_start_date", "aisac_end_date", "registration_date",
        "education_material_id", "education_target", "education_year", "education_material_type", "education_topics", "education_chunk_count",
        "education_embedded_chunk_count", "education_focus_page", "education_focus_text", "education_source_questions",
        "news_publisher", "news_published_at", "news_summary", "news_topics", "news_article_count", "news_alternates", "news_pack",
    )
    return {key: case.get(key, "") for key in keys if key in case or key in {"id", "label", "title", "claim", "source_name", "source_url"}}

def _reindex_cases() -> None:
    CASE_BY_ID.clear()
    CASE_BY_ID.update({str(case["id"]): (lesson_id, case) for lesson_id, cases in CASE_LIBRARY.items() for case in cases if case.get("id")})

AISAC_START_DATE = "2020-01-01"
AISAC_END_DATE = date.today().isoformat()
AISAC_SEARCH_BASE = "https://aisac.kobaco.co.kr/site/main/advideo/list_all_top"
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36"

def _text(value: Any, fallback: str = "-") -> str:
    if value is None: return fallback
    text = str(value).strip()
    return text if text else fallback

def _num(value: Any) -> float | None:
    try: return float(value)
    except (TypeError, ValueError): return None

def _int_text(value: Any) -> str:
    num = _num(value)
    return "-" if num is None else f"{int(round(num)):,}"

def _compact_keywords(value: Any, limit: int = 180) -> str:
    text = " ".join(_text(value, "").replace("\r", " ").replace("\n", " ").replace("'", "").split())
    return text if len(text) <= limit else text[:limit-1] + "…"

def _common_case(**kwargs: Any) -> dict[str, Any]:
    data = dict(kwargs)
    data.setdefault("media_type", "data"); data.setdefault("media_url", ""); data.setdefault("media_caption", "KOBACO 실제 데이터")
    questions = list(data.get("opening_questions") or []); data["opening_questions"] = questions
    data["opening_question"] = questions[0] if questions else str(data.get("opening_question") or "")
    return data

def _aisac_search_url(title: str) -> str:
    return f"{AISAC_SEARCH_BASE}?kwdVal={quote(str(title or '').strip())}&listType=list&pageSize=12&startDate={AISAC_START_DATE}&endDate={AISAC_END_DATE}&sortDirection=DESC&sortOrder=ADV_LIKE"

def _build_aisac_cases() -> list[dict[str, Any]]:
    db = get_kobaco_db(); required = ("aisac_ad_info", "aisac_ai_keywords")
    if db is None or not db.has_tables(*required): return []
    rows = db.query('''
        WITH joined AS (
          SELECT a."광고소재명",a."광고소재등록일",a."대업종 분류" AS "대업종",a."중업종 분류" AS "중업종",a."광고주명",
                 k."얼굴인식 개수",k."사물인식 개수",k."장소인식 개수",k."키워드 개수",k."키워드",
                 ROW_NUMBER() OVER (PARTITION BY a."광고소재명",a."광고소재등록일" ORDER BY a."광고소재명") AS duplicate_rn,
                 ROW_NUMBER() OVER (PARTITION BY COALESCE(a."대업종 분류",'기타') ORDER BY a."광고소재등록일" DESC,a."광고소재명") AS category_rn
          FROM aisac_ad_info a JOIN aisac_ai_keywords k ON a."광고소재명"=k."광고소재명" AND a."광고소재등록일"=k."광고소재등록일"
          WHERE NULLIF(TRIM(CAST(k."키워드" AS VARCHAR)), '') IS NOT NULL AND COALESCE(k."키워드 개수",0)>=3
            AND TRY_CAST(SUBSTR(CAST(a."광고소재등록일" AS VARCHAR),1,4) AS INTEGER)>=2020
        )
        SELECT * EXCLUDE (duplicate_rn,category_rn) FROM joined WHERE duplicate_rn=1 AND category_rn<=3
        ORDER BY "광고소재등록일" DESC,"대업종","광고소재명" LIMIT 24
    ''')
    cases=[]; seen=set()
    for row in rows:
        name=_text(row.get("광고소재명"),"")
        if not name or name in seen: continue
        seen.add(name); registered=_text(row.get("광고소재등록일")); keywords=_compact_keywords(row.get("키워드"))
        category=" / ".join(x for x in (_text(row.get("대업종"),""),_text(row.get("중업종"),"")) if x); idx=len(cases)+1
        case=_common_case(
            id=f"kobaco_aisac_{idx:02d}",label="AiSAC 실제 광고 · 2020년 이후",title=name,
            claim=f"'{name}' 원본 광고와 AiSAC 인식 결과를 함께 확인하는 사례입니다.",source_name="KOBACO AiSAC",source_url=_aisac_search_url(name),
            source_excerpt=f"{registered} · AI 인식 키워드: {keywords}",
            clues=[f"광고소재등록일: {registered}",f"업종: {category or '-'} / 광고주: {_text(row.get('광고주명'))}",f"AiSAC 키워드 개수: {_int_text(row.get('키워드 개수'))}",f"사물인식 개수: {_int_text(row.get('사물인식 개수'))}, 장소인식 개수: {_int_text(row.get('장소인식 개수'))}",f"DB 키워드 원문: {keywords}"],
            resolution="원본 광고의 장면·문구와 AiSAC 인식 결과를 함께 보고 두 정보가 일치하는 부분과 다른 부분을 구분합니다.",
            opening_questions=[f"'{name}' 원본 광고를 먼저 보고 무엇을 홍보하는 광고인지 한 문장으로 적어보세요. 그 다음 AiSAC 키워드 중 실제 영상에서 확인되는 단어 하나를 골라보세요.",f"'{name}'에서 직접 본 장면이나 문구 하나와 AiSAC이 인식한 키워드 하나를 짝지어보세요.","원본 광고에서 직접 확인한 사실 하나와 AiSAC이 인식한 항목 하나를 각각 적어보세요."],
            db_tables=list(required),data_rows=[{"label":"등록일","value":registered},{"label":"광고주","value":_text(row.get("광고주명"))},{"label":"업종","value":category or "-"},{"label":"키워드","value":keywords},{"label":"인식 횟수","value":f"사물 {_int_text(row.get('사물인식 개수'))} · 장소 {_int_text(row.get('장소인식 개수'))}"}],
            data_note="AiSAC 광고소재 메타데이터와 AI 인식결과 중 2020-01-01 이후 등록 광고만 사용합니다.",media_caption="KOBACO AiSAC 실제 광고")
        case.update(aisac_search_url=_aisac_search_url(name),aisac_start_date=AISAC_START_DATE,aisac_end_date=AISAC_END_DATE,registration_date=registered,context_url="",context_label="",context_summary="")
        cases.append(case)
    return cases

_VIEW_PATTERN=re.compile(r'(?:https?://aisac\.kobaco\.co\.kr)?(/site/main/advideo/view\?advId=[0-9a-fA-F\-]{36})',re.I)
_MEDIA_PATTERNS=(re.compile(r'<source[^>]+src=["\']([^"\']*/site/main/advideo/video/[^"\']+)["\']',re.I),re.compile(r'<source[^>]+src=["\']([^"\']+\.(?:mp4|webm|ogg)(?:\?[^"\']*)?)["\']',re.I),re.compile(r'<video[^>]+src=["\']([^"\']+\.(?:mp4|webm|ogg)(?:\?[^"\']*)?)["\']',re.I))
_POSTER_PATTERN=re.compile(r'<video[^>]+poster=["\']([^"\']+)["\']',re.I); _AISAC_ASSET_CACHE={}

def _fetch_html(url: str, referer: str="") -> str:
    headers={"User-Agent":_USER_AGENT,"Accept-Language":"ko-KR,ko;q=0.9,en;q=0.5"}
    if referer: headers["Referer"]=referer
    with urlopen(URLRequest(url,headers=headers),timeout=10) as response: return response.read(3_500_000).decode("utf-8",errors="ignore")

def _clean_url(value: str, base_url: str) -> str:
    raw=html.unescape(str(value or "").strip()).replace("\\/","/")
    if not raw or raw.startswith(("javascript:","data:","#")): return ""
    if raw.startswith("//"): return "https:"+raw
    return urljoin(base_url,raw)

def _detail_candidates(page: str, search_url: str, title: str) -> list[str]:
    text=html.unescape(page or ""); positions=[m.start() for m in re.finditer(re.escape(title),text,re.I)] if title else []
    areas=[text[max(0,p-16000):p+16000] for p in positions[:8]] or [text]; out=[]
    for area in areas:
        for match in _VIEW_PATTERN.finditer(area):
            url=_clean_url(match.group(1),search_url)
            if url and url not in out: out.append(url)
    return out

def _extract_media(page: str, base_url: str) -> str:
    text=html.unescape(page or "").replace("\\/","/")
    for pattern in _MEDIA_PATTERNS:
        match=pattern.search(text)
        if match:
            url=_clean_url(match.group(1),base_url)
            if url and "xxx.mp4" not in url.lower(): return url
    return ""

def _extract_poster(page: str, base_url: str) -> str:
    match=_POSTER_PATTERN.search(page or "")
    if not match: return ""
    url=_clean_url(match.group(1),base_url)
    return "" if "bg_login" in url.lower() else url

def _is_real_video(url: str, referer: str) -> bool:
    if not url: return False
    try:
        with urlopen(URLRequest(url,headers={"User-Agent":_USER_AGENT,"Range":"bytes=0-31","Referer":referer}),timeout=10) as response:
            content_type=str(response.headers.get("Content-Type") or "").lower(); first=response.read(32)
        return content_type.startswith("video/") or (len(first)>=8 and first[4:8]==b"ftyp")
    except Exception: return False

def _aisac_case(case_id: str) -> dict[str,Any]:
    found=CASE_BY_ID.get(case_id)
    if not found or found[0]!="news" or not str(case_id).startswith("kobaco_aisac_"): raise HTTPException(404,"AiSAC 사례를 찾을 수 없습니다.")
    return found[1]

def _resolve_aisac_assets(case: dict[str,Any]) -> dict[str,str]:
    case_id=str(case.get("id") or "")
    if case_id in _AISAC_ASSET_CACHE: return dict(_AISAC_ASSET_CACHE[case_id])
    title=str(case.get("title") or "").strip(); search_url=str(case.get("aisac_search_url") or _aisac_search_url(title)); assets={"detail":"","video":"","thumb":""}
    try:
        search_page=_fetch_html(search_url)
        for detail_url in _detail_candidates(search_page,search_url,title):
            try: detail_page=_fetch_html(detail_url,referer=search_url)
            except Exception: continue
            if title and title.lower() not in detail_page.lower(): continue
            video=_extract_media(detail_page,detail_url)
            if video and _is_real_video(video,detail_url): assets.update(detail=detail_url,video=video,thumb=_extract_poster(detail_page,detail_url)); break
    except Exception as exc: base.core.logger.warning("AiSAC resolve failed for %s: %s",case_id,type(exc).__name__)
    _AISAC_ASSET_CACHE[case_id]=dict(assets); return assets

def _proxy_remote(url: str, request: Request, referer: str="", fallback_type: str="application/octet-stream"):
    headers={"User-Agent":_USER_AGENT,"Accept":request.headers.get("accept","*/*")}
    if referer: headers["Referer"]=referer
    if request.headers.get("range"): headers["Range"]=request.headers["range"]
    try: upstream=urlopen(URLRequest(url,headers=headers),timeout=20)
    except Exception as exc: base.core.logger.warning("AiSAC proxy failed: %s",type(exc).__name__); return Response(status_code=502)
    status=getattr(upstream,"status",200) or 200; response_headers={"Cache-Control":"public, max-age=1800"}
    for key in ("Content-Length","Content-Range","Accept-Ranges"):
        value=upstream.headers.get(key)
        if value: response_headers[key]=value
    def iterator():
        try:
            while True:
                chunk=upstream.read(256*1024)
                if not chunk: break
                yield chunk
        finally: upstream.close()
    return StreamingResponse(iterator(),status_code=status,media_type=upstream.headers.get("Content-Type") or fallback_type,headers=response_headers)

@app.get("/api/aisac-open/{case_id}")
def aisac_open(case_id: str):
    case=_aisac_case(case_id); assets=_resolve_aisac_assets(case)
    return RedirectResponse(assets["detail"] or str(case.get("aisac_search_url") or _aisac_search_url(case.get("title",""))),status_code=302)

@app.get("/api/aisac-thumb/{case_id}")
def aisac_thumb(case_id: str, request: Request):
    case=_aisac_case(case_id); assets=_resolve_aisac_assets(case)
    if assets["thumb"]: return _proxy_remote(assets["thumb"],request,referer=assets["detail"] or str(case.get("aisac_search_url") or ""),fallback_type="image/jpeg")
    title=html.escape(str(case.get("title") or "KOBACO AiSAC 광고")); svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><rect width="1280" height="720" fill="#ece8e1"/><text x="70" y="95" font-family="sans-serif" font-size="28" font-weight="800" fill="#356fe8">KOBACO AiSAC</text><foreignObject x="70" y="190" width="1140" height="320"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:sans-serif;font-size:46px;font-weight:850;line-height:1.25;color:#292521">{title}</div></foreignObject></svg>'''
    return Response(svg.encode("utf-8"),media_type="image/svg+xml",headers={"Cache-Control":"public, max-age=600"})

@app.get("/api/aioff-aisac-thumb/{case_id}")
def aioff_aisac_thumb(case_id: str, request: Request): return aisac_thumb(case_id,request)

@app.get("/api/aisac-video/{case_id}")
def aisac_video(case_id: str, request: Request):
    case=_aisac_case(case_id); assets=_resolve_aisac_assets(case)
    if not assets["video"]: return Response(status_code=404)
    return _proxy_remote(assets["video"],request,referer=assets["detail"],fallback_type="video/mp4")

@app.get("/api/aisac-player/{case_id}",response_class=HTMLResponse)
def aisac_player(case_id: str):
    case=_aisac_case(case_id); assets=_resolve_aisac_assets(case); title=html.escape(str(case.get("title") or "AiSAC 광고")); poster=f"/api/aisac-thumb/{case_id}"
    if assets["video"]: body=f'<video controls preload="metadata" poster="{poster}" playsinline><source src="/api/aisac-video/{case_id}" type="video/mp4"></video>'
    elif assets["detail"]: body=f'<a class="fallback" href="{html.escape(assets["detail"],quote=True)}" target="_blank" rel="noopener"><img src="{poster}" alt="{title}"><span>원본 광고 열기</span></a>'
    else: body=f'<img class="poster" src="{poster}" alt="{title}">'
    return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#171513}}video,.poster,.fallback{{width:100%;height:100%;display:block;border:0}}video{{object-fit:contain}}.poster,.fallback img{{object-fit:contain;width:100%;height:100%}}.fallback{{position:relative}}.fallback span{{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);padding:7px 11px;background:rgba(0,0,0,.7);color:#fff;border-radius:7px;font:700 11px sans-serif}}</style></head><body>{body}</body></html>''')

def _education_cases() -> list[dict[str,Any]]:
    if not EDU_DB.exists(): return []
    conn=sqlite3.connect(EDU_DB); conn.row_factory=sqlite3.Row
    try:
        rows=conn.execute('''SELECT m.id,m.title,m.target,m.year,m.material_type,m.topics_json,m.source_url,COUNT(c.id) AS chunk_count,SUM(CASE WHEN c.embedding IS NOT NULL THEN 1 ELSE 0 END) AS embedded_chunk_count FROM materials m JOIN chunks c ON c.material_id=m.id GROUP BY m.id ORDER BY CASE WHEN m.title LIKE '%교육 안내서%' THEN 0 WHEN m.title LIKE '%안내서%' THEN 1 WHEN m.title LIKE '%가이드%' THEN 2 ELSE 3 END,m.year DESC,m.title''').fetchall(); cases=[]
        for row in rows:
            snippets=conn.execute("SELECT text FROM chunks WHERE material_id=? ORDER BY CASE WHEN embedding IS NOT NULL THEN 0 ELSE 1 END,id LIMIT 3",(row["id"],)).fetchall(); clues=[" ".join(str(x["text"] or "").split())[:420] for x in snippets if str(x["text"] or "").strip()]
            if not clues: continue
            try: topics=[str(x) for x in json.loads(row["topics_json"] or "[]") if str(x).strip()]
            except Exception: topics=[]
            title=str(row["title"] or "").strip(); target=str(row["target"] or "").strip(); year=str(row["year"] or "").strip(); material_type=str(row["material_type"] or "").strip(); source_url=str(row["source_url"] or "").strip() or ARCHIVE_URL
            opening=f"'{title}' 자료에서 가장 중요하다고 생각한 내용을 하나 골라 자료에 적힌 내용을 근거로 자신의 생각을 설명해보세요."
            cases.append(_common_case(id=f"education_{int(row['id']):04d}",label="리터러시 교육 안내서",title=title,claim="공식 디지털윤리 교육자료의 개념과 활동을 읽고 직접 적용하는 학습 자료입니다.",source_name="디지털윤리 교육자료실",source_url=source_url,source_excerpt=" · ".join(x for x in (target,year,material_type) if x),clues=clues,resolution="이 자료의 원문과 활동 문항을 근거로 개념을 이해하고 자신의 판단과 행동으로 직접 적용합니다.",opening_questions=[opening],db_tables=["education.materials","education.chunks"],data_rows=[{"label":"대상","value":target or "-"},{"label":"연도","value":year or "-"},{"label":"자료유형","value":material_type or "-"},{"label":"주제","value":" · ".join(topics) if topics else "-"},{"label":"임베딩","value":f"{int(row['embedded_chunk_count'] or 0)}/{int(row['chunk_count'])}"}],data_note="디지털윤리 교육자료실에서 수집·추출한 공식 교육자료를 사용합니다.",education_material_id=int(row["id"]),education_target=target,education_year=year,education_material_type=material_type,education_topics=topics,education_chunk_count=int(row["chunk_count"]),education_embedded_chunk_count=int(row["embedded_chunk_count"] or 0),media_type="document",media_caption="공식 디지털윤리 교육자료"))
        return cases
    finally: conn.close()

def _education_case(case_id: str) -> dict[str,Any]:
    found=CASE_BY_ID.get(case_id)
    if not found or not str(case_id).startswith("education_"): raise HTTPException(404,"교육자료를 찾을 수 없습니다.")
    return found[1]

def _safe_local_path(raw: str) -> Path|None:
    if not raw: return None
    path=Path(raw)
    if not path.is_absolute(): path=ROOT/path
    try: resolved=path.resolve()
    except Exception: return None
    if not resolved.exists() or not resolved.is_file(): return None
    if EDU_FILES!=resolved and EDU_FILES not in resolved.parents: return None
    return resolved

def _material_attachments(material_id: int) -> list[dict[str,Any]]:
    if not EDU_DB.exists(): return []
    conn=sqlite3.connect(EDU_DB); conn.row_factory=sqlite3.Row
    try: return [dict(x) for x in conn.execute("SELECT id,filename,local_path,mime_type FROM attachments WHERE material_id=? AND local_path<>'' ORDER BY CASE WHEN LOWER(filename) LIKE '%.pdf' THEN 0 WHEN LOWER(filename) LIKE '%.zip' THEN 1 ELSE 2 END,id",(int(material_id),)).fetchall()]
    finally: conn.close()

def _attachment(attachment_id: int|None) -> dict[str,Any]|None:
    if not attachment_id or not EDU_DB.exists(): return None
    conn=sqlite3.connect(EDU_DB); conn.row_factory=sqlite3.Row
    try:
        row=conn.execute("SELECT id,material_id,filename,local_path,mime_type FROM attachments WHERE id=?",(int(attachment_id),)).fetchone(); return dict(row) if row else None
    finally: conn.close()

def _pdf_document(material_id: int) -> Path|None:
    attachments=_material_attachments(material_id)
    for item in attachments:
        path=_safe_local_path(str(item.get("local_path") or ""))
        if path and path.suffix.lower()==".pdf": return path
    cache_dir=ROOT/"data"/"education"/"preview_cache"/f"{material_id:04d}"; cached=cache_dir/"document.pdf"
    if cached.exists() and cached.stat().st_size>0: return cached
    for item in attachments:
        path=_safe_local_path(str(item.get("local_path") or ""))
        if not path or path.suffix.lower()!=".zip": continue
        try:
            with zipfile.ZipFile(path) as zf:
                pdfs=[x for x in zf.infolist() if not x.is_dir() and x.filename.lower().endswith(".pdf") and "__macosx/" not in x.filename.lower()]
                if not pdfs: continue
                pdfs.sort(key=lambda x:(x.filename.count("/"),len(x.filename),x.filename)); data=zf.read(pdfs[0])
                if data.startswith(b"%PDF"): cache_dir.mkdir(parents=True,exist_ok=True); cached.write_bytes(data); return cached
        except Exception: continue
    return None

@app.get("/api/education-file/{case_id}")
def education_file(case_id: str):
    case=_education_case(case_id); path=_pdf_document(int(case.get("education_material_id") or 0))
    if not path: raise HTTPException(404,"브라우저에서 바로 볼 수 있는 PDF 원문이 없습니다.")
    return FileResponse(path,media_type="application/pdf",headers={"Content-Disposition":"inline"})

_STUDENT_FILE_TERMS=("학생용","학습지","활동지","워크북","교재","학습자료","활동자료","실습")
_TEACHER_FILE_TERMS=("교사용","지도서","교수학습","수업지도","지도안","강사용","매뉴얼")
_ACTIVITY_TERMS=("생각 열기","생각열기","생각 펼치기","생각펼치기","생각 키우기","생각키우기","함께 생각","다음 상황","활동","실천","찾아보","골라보","선택해","비교해","이야기해","말해보","적어보","써보","확인해","판단해","해볼까요","해봅시다")
_TEACHER_TEXT_TERMS=("수업 전개 흐름","수업전개흐름","학습 목표","학습목표","교수·학습","교수학습","수업 개요","수업개요","지도상의 유의","교사용","지도서","성취기준","교육과정","관련 교과","교과 연계","교과연계","차시","핵심역량","평가기준")
_META_TERMS=("목차","차례","발간사","머리말","참고문헌","집필진","연구진","발행처","ISBN","CIP")
_PROMPT_TERMS=("왜","무엇","어떻게","어떤","찾아보","골라보","선택해","비교해","이야기해","말해보","적어보","써보","생각해","확인해","판단해","해볼까요","해봅시다")
_VISUAL_DEPENDENT_TERMS=("아래 표","아래의 표","위의 표","그림","사진","이미지","장면","화면","말풍선","가로","세로","대각선","연결해","선을 그","빈칸","위에서 찾","다음 상황을 보고")
_TABLE_CODE_RE=re.compile(r"\[[0-9]{1,2}[가-힣A-Za-z]+[0-9\-~.]+\]"); _TOKEN_RE=re.compile(r"[가-힣A-Za-z0-9]{2,}")
_SOURCE_CACHE={}; _VISUAL_CACHE={}; _ADAPTIVE_PACK_CACHE={}; _EDUCATION_CONTEXT_CACHE={}

class EducationReadingDraft(BaseModel): activity_title: str=""; reading: list[str]=[]
class EducationQuestionDraft(BaseModel): questions: list[str]=[]

def _clean_text(value: str) -> str:
    value=str(value or "").replace("\u00a0"," ").replace("？","?"); value=re.sub(r"[ \t]+"," ",value); value=re.sub(r"\n{3,}","\n\n",value); return value.strip()

def _clean_lines(value: str) -> list[str]:
    out=[]
    for raw in _clean_text(value).splitlines():
        line=re.sub(r"\s+"," ",raw).strip(" \t-•·")
        if len(line)<5 or re.fullmatch(r"\d{1,3}",line): continue
        if line not in out: out.append(line)
    return out

def _is_prompt(line: str) -> bool: return "?" in line or (any(term in line for term in _PROMPT_TERMS) and 8<=len(line)<=220)

def _source_prompts(text: str) -> list[str]:
    out=[]
    for line in _clean_lines(text):
        lower=line.lower()
        if any(term.lower() in lower for term in _TEACHER_TEXT_TERMS+_META_TERMS) or not _is_prompt(line): continue
        line=re.sub(r"^\s*\d+\s*[.)]\s*","",line).strip()
        if line and line not in out: out.append(line)
        if len(out)>=5: break
    return out

def _section_role_score(section: str) -> int:
    text=str(section or "").lower(); return sum(80 for x in _STUDENT_FILE_TERMS if x.lower() in text)-sum(105 for x in _TEACHER_FILE_TERMS if x.lower() in text)

def _chunk_score(row: sqlite3.Row) -> tuple[int,list[str]]:
    text=_clean_text(row["text"] or ""); lower=text.lower(); prompts=_source_prompts(text); score=_section_role_score(str(row["section"] or ""))+len(prompts)*45
    score+=sum(13 for term in _ACTIVITY_TERMS if term in text); score-=sum(60 for term in _TEACHER_TEXT_TERMS if term.lower() in lower); score-=sum(70 for term in _META_TERMS if term.lower() in lower); score-=min(8,len(_TABLE_CODE_RE.findall(text)))*18
    if 180<=len(text)<=5000: score+=18
    if not prompts and not any(term in text for term in _ACTIVITY_TERMS): score-=35
    return score,prompts

def _select_source(case: dict[str,Any]) -> dict[str,Any]:
    material_id=int(case.get("education_material_id") or 0)
    if material_id in _SOURCE_CACHE: return dict(_SOURCE_CACHE[material_id])
    empty={"material_id":material_id,"row_id":0,"attachment_id":0,"section":"","page_start":None,"page_end":None,"text":"","prompts":[],"context":"","source_name":""}
    if not material_id or not EDU_DB.exists(): _SOURCE_CACHE[material_id]=empty; return dict(empty)
    conn=sqlite3.connect(EDU_DB); conn.row_factory=sqlite3.Row
    try: rows=conn.execute("SELECT id,attachment_id,page_start,page_end,section,text FROM chunks WHERE material_id=? AND TRIM(text)<>'' ORDER BY id",(material_id,)).fetchall()
    finally: conn.close()
    if not rows: _SOURCE_CACHE[material_id]=empty; return dict(empty)
    ranked=[(*_chunk_score(row),row) for row in rows]; ranked.sort(key=lambda x:x[0],reverse=True); usable=[x for x in ranked if x[1] or any(term in str(x[2]["text"] or "") for term in _ACTIVITY_TERMS)]; _,prompts,best=(usable or ranked)[0]
    same=[row for row in rows if int(row["attachment_id"] or 0)==int(best["attachment_id"] or 0) and abs(int(row["id"])-int(best["id"]))<=2]; parts=[]
    for row in same:
        text=_clean_text(row["text"] or "")
        if text and text not in parts: parts.append(text)
    section=str(best["section"] or ""); result={"material_id":material_id,"row_id":int(best["id"]),"attachment_id":int(best["attachment_id"] or 0),"section":section,"page_start":best["page_start"],"page_end":best["page_end"],"text":_clean_text(best["text"] or ""),"prompts":prompts,"context":"\n\n".join(parts)[:9000] or _clean_text(best["text"] or ""),"source_name":Path(section.split(" :: ")[-1]).name if section else ""}; _SOURCE_CACHE[material_id]=result; return dict(result)

def _visual_required(source: dict[str,Any]) -> bool:
    text=" ".join([str(source.get("text") or ""),*[str(x) for x in source.get("prompts",[])]]); return any(term in text for term in _VISUAL_DEPENDENT_TERMS)

def _tokens(text: str) -> set[str]:
    stop={"그리고","합니다","하세요","있습니다","에서는","것입니다","여러분","아래의","위에서"}; return {x for x in _TOKEN_RE.findall(_clean_text(text)) if x not in stop}

def _text_overlap_score(seed: str,candidate: str) -> int: return sum(min(8,len(x)) for x in (_tokens(seed)&_tokens(candidate)))

def _expanded_education_context(source: dict[str,Any]) -> str:
    material_id=int(source.get("material_id") or 0)
    if material_id in _EDUCATION_CONTEXT_CACHE: return _EDUCATION_CONTEXT_CACHE[material_id]
    fallback=str(source.get("context") or source.get("text") or "").strip()
    if not material_id or not EDU_DB.exists(): return fallback
    conn=sqlite3.connect(EDU_DB); conn.row_factory=sqlite3.Row
    try: rows=conn.execute("SELECT id,attachment_id,page_start,page_end,section,text FROM chunks WHERE material_id=? AND TRIM(text)<>'' ORDER BY id",(material_id,)).fetchall()
    except Exception as exc: base.core.logger.warning("Expanded education context failed: %s",type(exc).__name__); return fallback
    finally: conn.close()
    selected_id=int(source.get("row_id") or 0); selected_attachment=int(source.get("attachment_id") or 0); candidates=[r for r in rows if not selected_attachment or int(r["attachment_id"] or 0)==selected_attachment] or rows; seed=str(source.get("text") or ""); ranked=[]
    for row in candidates:
        text=str(row["text"] or "").strip()
        if not text: continue
        distance=abs(int(row["id"])-selected_id) if selected_id else 0; score=max(0,90-distance*8)+(220 if int(row["id"])==selected_id else 0)
        try: score+=max(-90,min(180,int(_chunk_score(row)[0])))
        except Exception: pass
        score+=min(140,_text_overlap_score(seed,text)*3); ranked.append((score,row))
    ranked.sort(key=lambda x:x[0],reverse=True); chosen={}
    if selected_id:
        for row in candidates:
            if abs(int(row["id"])-selected_id)<=4: chosen[int(row["id"])]=row
    for _,row in ranked:
        chosen[int(row["id"])]=row
        if len(chosen)>=16: break
    parts=[]; total=0
    for row_id in sorted(chosen):
        row=chosen[row_id]; text=re.sub(r"\s+"," ",str(row["text"] or "")).strip()
        if not text or text in parts: continue
        piece=(f"[원문 {row['page_start']}쪽] " if row["page_start"] else "[원문] ")+text
        if total+len(piece)>22000 and parts: break
        parts.append(piece); total+=len(piece)
    context="\n\n".join(parts).strip() or fallback; _EDUCATION_CONTEXT_CACHE[material_id]=context; return context

def _simple_visual(source: dict[str,Any]) -> dict[str,Any]|None:
    path=_pdf_document(int(source.get("material_id") or 0))
    if not path: return None
    return {"kind":"pdf","page":int(source.get("page_start") or 1),"path":path}

@app.get("/api/education-visual/{case_id}")
def education_visual(case_id: str):
    source=_select_source(_education_case(case_id)); visual=_simple_visual(source)
    if not visual: raise HTTPException(404,"표시할 시각 학습자료가 없습니다.")
    return FileResponse(visual["path"],media_type="application/pdf",headers={"Content-Disposition":"inline"})

def _learning_level_rules() -> tuple[str,int]:
    return "학생이 이해할 수 있는 자연스러운 표현을 사용하고 자료의 사실·근거·판단 기준을 자신의 말로 설명하게 한다.",3

def _reading_plan() -> tuple[int,int,str]:
    return 4,6,"학생이 원문을 따로 열지 않아도 학습할 수 있을 만큼 충분히 설명한다."

def _fallback_questions(count: int,reading: list[str]) -> list[str]:
    bank=["읽어보기에서 가장 중요하다고 생각한 내용을 하나 골라 자신의 말로 설명해보세요.","읽어보기에서 그 판단을 뒷받침하는 근거를 하나 찾아 설명해보세요.","읽어보기의 내용을 실제 디지털 생활에 적용한다면 무엇을 조심하거나 확인해야 할지 적어보세요."]
    return bank[:max(1,count)] if reading else ["읽어보기에서 확인한 내용을 자신의 말로 한 문장으로 정리해보세요."]

def _make_adaptive_study_pack(case: dict[str,Any],source: dict[str,Any],visual: dict[str,Any]|None) -> dict[str,Any]:
    material_id=int(source.get("material_id") or 0); key=material_id
    if key in _ADAPTIVE_PACK_CACHE: return dict(_ADAPTIVE_PACK_CACHE[key])
    level_rules,question_count=_learning_level_rules(); min_p,max_p,paragraph_rule=_reading_plan(); profile="학생"; expanded=_expanded_education_context(source); original_questions="\n".join(f"- {q}" for q in source.get("prompts",[])) or "- 없음"
    reading_prompt=f'''다음 공식 디지털 리터러시 교육자료를 학생이 실제로 읽을 학습 내용으로 재구성하라.
대상: {profile}
표현 규칙: {level_rules}
자료명: {case.get('title','')}
원문 파일: {source.get('source_name','')}

[관련 원문 묶음]
{expanded[:22000]}

[원문 활동문 - 학습 목적 참고]
{original_questions}

규칙:
1. 원문이 뒷받침하는 사실·개념·사례만 사용하고 새로 만들지 않는다.
2. 학생이 원문 PDF를 따로 열지 않아도 읽어보기만으로 뒤 질문을 풀 수 있을 만큼 필요한 배경과 개념을 충분히 제공한다.
3. 과도하게 요약하지 말고 배경·특징·원인·영향·위험·주의점·사례·판단 기준 중 관련 내용을 보존한다.
4. reading은 {min_p}~{max_p}개 문단. {paragraph_rule}
5. 원문을 순서대로 복사하지 말고 이해하기 쉽게 구조화한다.
6. 페이지·차시·파일명·목차·교사용 지시·성취기준은 제외한다.
7. 화면에 없는 그림·표를 본 것처럼 설명하지 않는다.
8. activity_title은 실제 학습 주제를 쓴다.
9. 이 단계에서는 질문을 만들지 않는다.
JSON 스키마에 맞춰 반환하라.'''
    try:
        draft,_=base.core.generate_structured_with_fallback(reading_prompt,EducationReadingDraft,max_output_tokens=1700); reading=[str(x).strip() for x in draft.reading if str(x).strip()][:max_p]; title=str(draft.activity_title or "").strip()
        if len(reading)<min_p: raise ValueError("education_reading_too_short")
    except Exception as exc:
        base.core.logger.warning("Education reading generation failed: %s",type(exc).__name__); raw=re.sub(r"\s+"," ",expanded).strip(); reading=[raw[:1800]] if raw else ["이 자료에서 확인할 수 있는 내용을 살펴보세요."]; title=str(case.get("title") or "").strip()
    visible="\n\n".join(f"{i+1}. {x}" for i,x in enumerate(reading)); question_prompt=f'''다음은 학생 화면에 실제로 표시될 읽어보기 내용이다. 이 내용만 읽은 학생이 답할 수 있는 질문을 만들어라.
대상: {profile}
표현 규칙: {level_rules}
학습 주제: {title or case.get('title','')}

[학생 화면 읽어보기]
{visible}

규칙:
1. questions는 정확히 {question_count}개.
2. 답에 필요한 정보는 반드시 읽어보기 안에 있어야 한다. 숨겨진 PDF 지식을 요구하지 않는다.
3. 한 질문에는 한 가지 핵심 사고만 요구한다.
4. 단순 복사보다 이해·비교·근거 찾기·적용을 요구한다.
5. 질문끼리 반복하지 않는다.
JSON 스키마에 맞춰 반환하라.'''
    try:
        qdraft,_=base.core.generate_structured_with_fallback(question_prompt,EducationQuestionDraft,max_output_tokens=700); questions=[str(x).strip() for x in qdraft.questions if str(x).strip()][:question_count]
        if len(questions)<question_count: raise ValueError("education_questions_incomplete")
    except Exception as exc: base.core.logger.warning("Education question generation failed: %s",type(exc).__name__); questions=_fallback_questions(question_count,reading)
    pack={"activity_title":title or str(case.get("title") or "").strip(),"reading":reading,"questions":questions,"visual_kind":"pdf" if visual else "","visual_available":bool(visual),"visual_required":_visual_required(source),"source_name":source.get("source_name",""),"page":(visual or {}).get("page") or source.get("page_start") or "","student_level":profile}; _ADAPTIVE_PACK_CACHE[key]=dict(pack); return pack

CASE_LIBRARY["news"]=_build_aisac_cases(); CASE_LIBRARY["deepfake"]=_education_cases(); _reindex_cases()
KOBACO_STATUS=kobaco_status()
if isinstance(KOBACO_STATUS,dict): KOBACO_STATUS["case_counts"]={"news":len(CASE_LIBRARY["news"]),"deepfake":len(CASE_LIBRARY["deepfake"])}

flow=SimpleNamespace(CASE_LIBRARY=CASE_LIBRARY,CASE_BY_ID=CASE_BY_ID,CaseStartRequest=CaseStartRequest,_save_case=_save_case,_get_case_id=_get_case_id,_public_case=_public_case)

@app.get("/api/kobaco-status")
def api_kobaco_status(): return KOBACO_STATUS

@app.get("/api/aioff-education-cases")
def aioff_education_cases():
    items=[flow._public_case(case) for case in CASE_LIBRARY.get("deepfake",[]) if str(case.get("id") or "").startswith("education_")]
    random.shuffle(items)
    return {"count":len(items),"items":items}

@app.get("/api/education-learning/{case_id}")
def aioff_education_learning(case_id: str):
    case=_education_case(case_id); source=_select_source(case); visual=_simple_visual(source); return {"ok":True,"pack":_make_adaptive_study_pack(case,source,visual)}

@app.post("/api/case-start")
def case_start(req: CaseStartRequest):
    found=CASE_BY_ID.get(req.case_id)
    if not found or found[0]!=req.lesson_id or req.lesson_id not in base.LESSONS: raise HTTPException(400,"선택한 학습 사례를 찾을 수 없습니다.")
    _,case=found; sid=str(base.core.uuid.uuid4()); base._save_lesson(sid,req.lesson_id); _save_case(sid,req.case_id); opening=str(case.get("opening_question") or "자료를 보고 생각한 내용을 적어보세요.")
    with base.core.connect_db() as conn: conn.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)",(sid,)); conn.execute("INSERT INTO messages(session_id,role,content) VALUES(?, 'assistant', ?)",(sid,opening))
    return {"session_id":sid,"case":flow._public_case(case),"opening_question":opening}
flow.case_start=case_start

class AioffTutorChatRequest(BaseModel): session_id: str|None=None; message: str=Field(min_length=1,max_length=4000); lesson_id: str|None=None; current_question: str=Field(default="",max_length=1000); question_attempt: int=Field(default=1,ge=1,le=20)
class TutorDecision(BaseModel): verdict: Literal["pass","clarify","retry"]; response: str=Field(min_length=1,max_length=2200)

def _tutor_level_rules() -> str:
    return "학생의 답을 2~5문장으로 자연스럽게 해석하고, 자료의 사실·근거·판단 기준과 연결해 설명한다."

def _rows(case: dict[str,Any]) -> dict[str,str]: return {str(x.get("label") or "").strip():str(x.get("value") or "").strip() for x in case.get("data_rows",[])}

def _kobaco_learning_prompt(sid: str,message: str,lesson_id: str,case: dict[str,Any]) -> str:
    prior=base.core.messages(sid,24); history="\n".join(f"{'학생' if m['role']=='user' else '학습도우미'}: {m['content']}" for m in prior); db_values="\n".join(f"- {k}: {v}" for k,v in _rows(case).items()) or "- 표시 값 없음"; criteria="\n".join(f"- {x}" for x in base.LESSONS[lesson_id].get("criteria",[]))
    return f'''너는 학생을 위한 미디어 리터러시 학습도우미다.
학생은 원본 광고와 AiSAC 인식값을 비교하고 있다.
사례명: {case.get('title','-')}
출처: {case.get('source_name','-')}
[실제 데이터]
{db_values}
[판단 기준]
{criteria}
규칙: 학생의 답에 직접 반응하고, 원본에서 확인한 내용과 AI 키워드를 구분한다. 화면에 없는 사실을 만들지 않는다. 같은 질문을 반복하지 않는다. 3~6문장으로 설명한다.
[이전 대화]
{history or '(없음)'}
[학생의 새 답변]
{message}'''

def _stream_model_reply(prompt: str,sid: str,message: str):
    emitted=False; parts=[]; gemini_error=None
    try:
        stream=base.core.gemini_client().models.generate_content_stream(model=base.core.gemini_model(),contents=prompt)
        for chunk in stream:
            text=getattr(chunk,"text",None) or ""
            if text: emitted=True; parts.append(text); yield text
        reply="".join(parts).strip()
        if not reply: raise ValueError("gemini_empty_response")
        base.core.save_chat_exchange(sid,message,reply); return
    except Exception as exc:
        gemini_error=exc
        if emitted: yield "\n\nAI 응답 전송이 중단되었습니다. 같은 답변을 다시 보내주세요."; return
    if base.core.groq_configured():
        try:
            stream=base.core.groq_client().chat.completions.create(model=base.core.groq_model(),messages=[{"role":"user","content":prompt}],max_completion_tokens=700,temperature=0.25,stream=True); parts=[]
            for chunk in stream:
                choices=getattr(chunk,"choices",None) or []; text=getattr(getattr(choices[0],"delta",None),"content",None) if choices else ""
                if text: parts.append(text); yield text
            reply="".join(parts).strip()
            if not reply: raise ValueError("groq_empty_response")
            base.core.save_chat_exchange(sid,message,reply); return
        except Exception as exc: base.core.logger.warning("Groq tutor fallback failed: %s",type(exc).__name__)
    base.core.logger.warning("Gemini tutor failed: %s",type(gemini_error).__name__ if gemini_error else "UnknownError"); yield "AI 학습도우미 연결에 실패했습니다. 잠시 후 같은 답변을 다시 보내주세요."

def kobaco_ai_chat_stream(req: AioffTutorChatRequest):
    sid=req.session_id or str(base.core.uuid.uuid4()); lesson_id=req.lesson_id if req.lesson_id in base.LESSONS else base._get_lesson_id(sid)
    if lesson_id not in base.LESSONS: raise HTTPException(400,"먼저 학습 주제를 선택해 주세요.")
    base._save_lesson(sid,lesson_id); case_id=_get_case_id(sid); found=CASE_BY_ID.get(case_id) if case_id else None
    if not found or found[0]!=lesson_id: raise HTTPException(400,"선택한 사례를 다시 확인해 주세요.")
    return StreamingResponse(_stream_model_reply(_kobaco_learning_prompt(sid,req.message,lesson_id,found[1]),sid,req.message),media_type="text/plain; charset=utf-8",headers={"X-Session-Id":sid,"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

def _education_tutor_prompt(req: AioffTutorChatRequest,sid: str,case: dict[str,Any]) -> str:
    source=_select_source(case); visual=_simple_visual(source); pack=_make_adaptive_study_pack(case,source,visual); evidence="\n\n".join(str(x) for x in pack.get("reading",[]) if str(x).strip())[:10000]; question=str(req.current_question or case.get("opening_question") or "").strip(); prior=base.core.messages(sid,18); history="\n".join(f"{'학생' if m['role']=='user' else '튜터'}: {m['content']}" for m in prior); profile="학생"; process_hint="오답이면 정답 내용을 말하지 말고 학생이 질문에서 놓친 요구사항 하나만 확인하게 한다." if req.question_attempt<=1 else "오답이 반복되면 정답 키워드 대신 질문을 나눠 읽기, 읽어보기에서 근거 찾기 같은 사고 절차만 제안한다."
    return f'''너는 디지털 리터러시 수업의 대화형 튜터다. 학생이 실제로 무슨 뜻으로 답했는지 이해하는 것이 우선이다.
대상: {profile}
피드백 규칙: {_tutor_level_rules()}
현재 문항: {question}
학생 답변: {req.message}
[학생 화면 읽어보기]
{evidence}
[이전 대화]
{history or '(없음)'}
판정은 키워드 일치가 아니라 의미로 한다. 화면에 없는 PDF 지식은 요구하지 않는다. 의견형 문항에 하나의 정답 문구를 강요하지 않는다.
pass=핵심에 맞고 읽어보기와 모순되지 않음, clarify=맞는 방향이나 너무 짧거나 모호함, retry=합리적으로 해석해도 질문과 무관하거나 명확히 모순됨.
clarify는 학생 표현의 뜻을 조금 더 풀어 달라고 묻고 새 정답 키워드를 주지 않는다. retry는 {process_hint} pass는 왜 맞는지 읽어보기 기준으로 설명한다.
response에는 학생에게 보여줄 말만 쓴다.'''

base._remove_route("/api/chat-stream","POST")
@app.post("/api/chat-stream")
def aioff_chat_stream(req: AioffTutorChatRequest,request: Request):
    sid=req.session_id or str(base.core.uuid.uuid4()); lesson_id=req.lesson_id if req.lesson_id in base.LESSONS else base._get_lesson_id(sid)
    if lesson_id not in base.LESSONS: raise HTTPException(400,"먼저 학습 주제를 선택해 주세요.")
    base._save_lesson(sid,lesson_id); case_id=_get_case_id(sid); found=CASE_BY_ID.get(case_id) if case_id else None
    if not found or found[0]!=lesson_id: raise HTTPException(400,"선택한 사례를 다시 확인해 주세요.")
    if not str(case_id).startswith("education_"): return kobaco_ai_chat_stream(req)
    prompt=_education_tutor_prompt(req,sid,found[1])
    try: decision,provider=base.core.generate_structured_with_fallback(prompt,TutorDecision,max_output_tokens=700)
    except Exception as exc: base.core.logger.warning("Education tutor evaluation failed: %s",type(exc).__name__); raise HTTPException(502,"학습 답변 평가에 실패했습니다. 잠시 후 다시 시도해 주세요.")
    text=str(decision.response or "").strip(); base.core.save_chat_exchange(sid,req.message,text); return Response(text,media_type="text/plain; charset=utf-8",headers={"X-Session-Id":sid,"X-AIOFF-Provider":provider,"X-AIOFF-Verdict":decision.verdict,"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# Renderer: self-contained picker + wide study layout

def _render_index_aioff_ui() -> str:
    page=base._render_index(); page=re.sub(r'\s*<section class="process" aria-label="이용 순서">.*?</section>\s*',"\n",page,count=1,flags=re.S)
    hidden='<div id="aioff-hidden-state" hidden aria-hidden="true"><div id="process1"></div><div id="process2"></div><div id="process3"></div><div id="process4"></div><span id="stageStep">1 / 4</span><span id="stageText"></span><div id="skills"></div><div id="analysisSummary"></div></div>'
    page=re.sub(r'\s*<aside class="study-side">.*?</aside>\s*',"\n"+hidden+"\n",page,count=1,flags=re.S)
    replacements={"디지털 리터러시 × AI OFF":"KOBACO DATA × AI OFF","AI와 판단 기준을 배우고,<br>마지막에는 내가 직접 확인합니다.":"미디어를 보고,<br>생각하고, 데이터로 확인해요.","공식 교육·조사자료를 바탕으로 정리한 뉴스·딥페이크·AI 답변 검증 기준을 사례로 연습합니다. 학습을 마치면 AI OFF가 방금 대화를 분석해, 같은 판단 기준을 혼자 적용해보는 문제 3개를 만듭니다.":"실제 KOBACO 광고·공식 리터러시 교육자료·최신 뉴스 사례를 보고 자료에 나온 사실과 해석을 구분해봅니다.","기존 AI OFF는 그대로":"마지막에는 혼자 풀어봐요","AI와 학습한 대화를 분석하고 AI가 대신한 사고를 학생이 직접 다시 수행하는 기존 구조를 유지합니다. 이번에는 학습 주제를 디지털 리터러시로 구체화했습니다.":"AI와 학습한 대화를 분석하고 AI가 대신한 사고를 마지막에 학생이 직접 다시 수행합니다.","학습 자료를 선택하세요":"학습 주제를 선택하세요","예선에서는 공식 원문을 확인해 정리한 기준을 사용합니다. 실시간 RAG로 외부 자료를 임의로 끌어오지 않습니다.":"주제를 고르면 실제 데이터와 공식 자료에서 구성한 사례 3개가 나타납니다.","위에서 학습 자료를 고른 뒤 사례를 보며 판단 기준을 연습합니다.":"자료를 살펴보고 질문에 답하며 판단 기준을 연습합니다."}
    for old,new in replacements.items(): page=page.replace(old,new)
    page=re.sub(r'<div class="guide-strip">.*?</div>','<div class="guide-strip"><strong>사례를 하나 선택하세요.</strong> 자료를 확인하고 질문에 답해보세요.</div>',page,count=1,flags=re.S)
    status="KOBACO DB 연동 완료" if CASE_LIBRARY.get("news") else "KOBACO DB 대기 중"; page=page.replace("<main>",f'<main><div class="kobaco-db-banner"><strong>{status}</strong><span>AiSAC · 공식 교육자료 · 최신 뉴스 학습 데이터를 사용합니다.</span></div>',1)
    topic_json=json.dumps({lesson_id:[flow._public_case(c) for c in CASE_LIBRARY.get(lesson_id,[])] for lesson_id in ("news","deepfake","ai")},ensure_ascii=False).replace("</","<\\/")
    css=r'''<style>
main{width:calc(100% - 24px)!important;max-width:1800px!important;margin:0 auto!important;padding:28px 0 42px!important}.workspace,.study-paper{width:100%!important;max-width:none!important}.study-paper>.paper-head .mode-label{display:none!important}.lesson-detail{display:none!important}.kobaco-db-banner{display:flex;justify-content:space-between;gap:18px;align-items:center;margin:0 0 16px;padding:10px 14px;border:1px solid #d9d2c8;border-radius:9px;background:#f8f5ef;color:#3a352f;font-size:10px}.kobaco-db-banner strong{font-size:11px}.kobaco-db-banner span{color:#71695f}.chat-case-picker{margin:8px 0 18px;border:1px solid var(--line);background:#fff;border-radius:10px;padding:18px}.chat-case-picker-head{display:flex;justify-content:space-between;gap:12px;margin-bottom:14px}.chat-case-picker-head strong{font-size:13px}.chat-case-picker-head span{font-size:10px;color:var(--muted)}.chat-case-shuffle{border:1px solid var(--line);background:#fff;border-radius:7px;padding:7px 9px;font-size:9px;font-weight:800}.chat-case-options{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.chat-case-option{border:1px solid var(--line);background:var(--paper);border-radius:8px;padding:0 0 13px;text-align:left;color:var(--ink);overflow:hidden}.chat-case-option:hover{border-color:#9db2e7}.chat-case-option.active{border-color:var(--blue);background:var(--blue-soft)}.chat-case-option>b,.chat-case-option>small{display:block;margin-left:14px;margin-right:14px}.chat-case-option>b{font-size:11px;line-height:1.4}.chat-case-option>small{margin-top:5px;font-size:9px;color:var(--muted)}.education-guide-preview-v19,.kobaco-picker-media,.topic-preview,.aioff-news-preview{width:100%;height:230px;min-height:230px;margin:0 0 12px;overflow:hidden;background:#eee9e1;position:relative}.education-guide-preview-v19 iframe{position:absolute;inset:0;width:calc(100% + 18px);height:calc(100% + 18px);border:0;background:#fff;pointer-events:none}.education-guide-preview-v19 .edu-chip{position:absolute;left:8px;bottom:8px;z-index:3;padding:4px 7px;border-radius:6px;background:rgba(22,31,43,.78);color:#fff;font-size:8px;font-weight:800}.kobaco-picker-media img,.aioff-news-preview img{display:block;width:100%;height:100%;object-fit:cover}.topic-preview{display:flex;flex-direction:column;justify-content:flex-end;padding:12px;background:#33465b;color:#fff}.chat-case-card{border:1px solid var(--line);border-radius:10px;background:#fff;overflow:hidden;margin:12px 0 18px}.chat-case-top{padding:11px 13px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px}.chat-case-kicker{font-size:9px;font-weight:900;color:var(--orange)}.chat-case-title{font-size:14px;font-weight:850}.chat-case-source{font-size:9px;color:var(--muted);margin-top:4px}.chat-case-link{font-size:10px;font-weight:800;color:var(--body);text-decoration:none;border:1px solid var(--line);padding:6px 8px;border-radius:7px}.chat-case-media{background:#eee9e1;display:flex;align-items:center;justify-content:center;overflow:hidden}.chat-case-caption{padding:7px 14px;border-top:1px solid var(--line);font-size:9px;color:var(--muted)}.kobaco-data-card{width:100%;background:#fff}.aisac-player-shell{height:clamp(440px,62vh,760px);max-height:760px;min-height:440px;background:#171513}.aisac-player-frame{width:100%;height:100%;border:0}.aisac-card-title{padding:11px 14px 5px;font-size:13px;font-weight:850}.context-actions{display:flex;gap:8px;flex-wrap:wrap;padding:8px 14px 12px}.context-actions a{padding:7px 10px;border-radius:7px;background:#2d2925;color:#fff!important;text-decoration:none;font-size:9px;font-weight:800}.context-actions a.alt{background:#fff;color:#2d2925!important;border:1px solid #cfc6ba}.fact-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:12px 14px;background:#f7f4ef}.fact-grid div{background:#fff;border:1px solid #ddd5ca;border-radius:8px;padding:10px}.fact-grid small{display:block;font-size:9px;color:#7b7168}.fact-grid b{display:block;margin-top:4px;font-size:11px}.aisac-result{padding:14px}.aisac-result small{font-size:9px;font-weight:900}.aisac-result strong{display:block;margin-top:6px;font-size:13px;line-height:1.6}.kobaco-data-table{border:1px solid #d9d2c8;background:#fff;border-radius:8px;overflow:hidden;margin:0 14px 14px}.kobaco-data-row{display:grid;grid-template-columns:120px 1fr;border-top:1px solid #ebe5dc}.kobaco-data-row:first-child{border-top:0}.kobaco-data-row b{padding:9px 11px;background:#faf8f4;font-size:9px}.kobaco-data-row span{padding:9px 11px;font-size:11px;line-height:1.45}.education-study-v21{border:1px solid #d9d2c9;border-radius:10px;background:#fff;overflow:hidden;width:100%}.education-study-v21-head{padding:18px 20px 15px;border-bottom:1px solid #e2dbd2;background:#f8fafc}.education-study-v21-head small{display:block;margin-bottom:5px;font-size:10px;font-weight:800;color:#58749b}.education-study-v21-head b{display:block;font-size:20px}.education-study-v21-status{padding:24px 20px;font-size:12px;color:#746d66}.education-study-v21-body{padding:20px}.education-study-v21-visual{margin:0 0 16px;border:1px solid #ddd6cd;border-radius:9px;overflow:hidden;background:#ece8e1}.education-study-v21-visual iframe{display:block;width:100%;height:clamp(620px,72vh,920px);border:0}.education-study-v21-reading{padding:17px 19px;border:1px solid #e2ddd6;border-radius:9px;background:#fffdf9}.education-study-v21-reading h4,.education-study-v21-questions h4{margin:0 0 11px;font-size:14px}.education-study-v21-reading p{margin:0 0 11px;font-size:14px;line-height:1.8}.education-study-v21-questions{margin-top:14px;padding:17px 19px;border:1px solid #eadbc8;border-radius:9px;background:#fff8ee}.education-study-v21-questions ol{padding-left:0;list-style:none}.education-study-v21-questions li{display:none;font-size:14px;line-height:1.7;font-weight:700}.education-study-v21-questions li.aioff-current-question{display:block}.education-study-v21-actions{display:flex;gap:8px;margin-top:12px}.education-study-v21-actions a{padding:8px 11px;border:1px solid #cfc6ba;border-radius:7px;background:#fff;color:#2d2925!important;text-decoration:none;font-size:10px;font-weight:800}.aioff-learning-columns{display:grid;grid-template-columns:minmax(0,1fr) clamp(320px,24vw,430px);min-height:calc(100vh - 150px)}.aioff-learning-columns>.chat-area{min-width:0;padding:18px 20px 18px 24px!important;border-right:1px solid var(--line)}.aioff-learning-columns .chat{height:calc(100vh - 205px)!important;min-height:760px!important;max-height:none!important}.aioff-composer-side{min-width:0;display:flex;flex-direction:column;background:#fffdf9}.aioff-composer-side-head{padding:18px;border-bottom:1px solid var(--line)}.aioff-side-question{margin-top:12px;padding:12px 13px;border:1px solid #eadbc8;border-radius:10px;background:#fff8ee}.aioff-side-question small{display:block;margin-bottom:5px;font-size:10px;font-weight:850;color:#9a5b30}.aioff-side-question b{display:block;font-size:13px;line-height:1.55}.aioff-composer-side .composer-wrap{flex:1;display:flex;flex-direction:column;padding:16px 18px 18px!important}.aioff-composer-side .composer{flex:1;display:flex!important;flex-direction:column!important;align-items:stretch!important;gap:12px!important;border-top:0!important}.aioff-composer-side .composer textarea{flex:1;width:100%!important;min-height:560px!important;max-height:none!important;resize:none!important}.aioff-composer-side .send-btn{align-self:flex-end;min-width:96px;height:46px!important}
@media(max-width:900px){.chat-case-options{grid-template-columns:1fr}.aioff-learning-columns{display:block}.aioff-learning-columns .chat{height:680px!important;min-height:680px!important}.aioff-composer-side .composer textarea{min-height:220px!important}.education-guide-preview-v19,.kobaco-picker-media,.topic-preview,.aioff-news-preview{height:170px;min-height:170px}}
</style>'''
    script=f'''<script>
const fixedTopicCases={topic_json};const fixedSamples={{}};let inlineLessonId=null,inlineCaseId=null;
function fixedShuffle(items){{const a=[...items];for(let i=a.length-1;i>0;i--){{const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]];}}return a;}}function fixedSample(id){{fixedSamples[id]=fixedShuffle(fixedTopicCases[id]||[]).slice(0,3);return fixedSamples[id];}}function compactTitle(t){{t=String(t||'');return t.length>36?t.slice(0,36)+'…':t;}}
function fixedPreview(c){{const id=String(c?.id||'');if(id.startsWith('education_'))return `<div class="education-guide-preview-v19"><iframe src="/api/education-file/${{encodeURIComponent(id)}}#page=1&toolbar=0&navpanes=0&scrollbar=0&view=Fit"></iframe><span class="edu-chip">${{esc([c.education_target||'',c.education_year||''].filter(Boolean).join(' · '))}}</span></div>`;if(id.startsWith('kobaco_aisac_'))return `<div class="kobaco-picker-media"><img src="/api/aioff-aisac-thumb/${{encodeURIComponent(id)}}"></div>`;if(id.startsWith('news_'))return `<div class="aioff-news-preview"><img src="/api/aioff-news-thumb/${{encodeURIComponent(id)}}"></div>`;return `<div class="topic-preview"><b>${{esc(c.label||'학습 사례')}}</b></div>`;}}
function fixedPickerHtml(id,active=null){{const cases=fixedSamples[id]||fixedSample(id),total=(fixedTopicCases[id]||[]).length;return `<div class="chat-case-picker"><div class="chat-case-picker-head"><div><strong>사례를 골라보세요</strong><br><span>전체 ${{total}}개 · 3개 선택</span></div><button class="chat-case-shuffle" data-shuffle-cases>다른 사례 보기</button></div><div class="chat-case-options">${{cases.map((c,i)=>`<button class="chat-case-option ${{c.id===active?'active':''}}" data-case-id="${{c.id}}">${{fixedPreview(c)}}<b>${{i+1}}. ${{esc(compactTitle(c.title))}}</b><small>${{esc(c.label||'')}}</small></button>`).join('')}}</div></div>`;}}function pickerHtml(id,a=null){{return fixedPickerHtml(id,a);}}
function bindCaseButtons(id){{chat.querySelectorAll('[data-case-id]').forEach(btn=>btn.addEventListener('click',()=>startCase(id,btn.dataset.caseId)));const sh=chat.querySelector('[data-shuffle-cases]');if(sh)sh.addEventListener('click',()=>{{sessionId=null;inlineCaseId=null;resetInlineState();fixedSample(id);chat.innerHTML=fixedPickerHtml(id);bindCaseButtons(id);}});}}function resetInlineState(){{questions=[];delegationMap={{}};aiOffStarted=false;hasResult=false;requestInFlight=false;input.value='';input.disabled=true;send.disabled=true;finish.disabled=true;}}
async function showCaseChooser(id){{inlineLessonId=id;inlineCaseId=null;sessionId=null;resetInlineState();if(id==='deepfake'){{try{{const r=await fetch('/api/aioff-education-cases'),d=r.ok?await r.json():{{}};if(Array.isArray(d.items)&&d.items.length){{fixedTopicCases.deepfake=d.items;delete fixedSamples.deepfake;}}}}catch(e){{}}}}fixedSample(id);chat.innerHTML=fixedPickerHtml(id);bindCaseButtons(id);input.placeholder='위에서 사례를 먼저 선택해 주세요.';stageText.textContent='사례를 선택하세요';}}
function fixedRows(c){{const o={{}};(c.data_rows||[]).forEach(r=>o[String(r.label||'').trim()]=String(r.value||'').trim());return o;}}function fixedRawRows(c){{return (c.data_rows||[]).map(r=>`<div class="kobaco-data-row"><b>${{esc(r.label||'항목')}}</b><span>${{esc(r.value||'-')}}</span></div>`).join('');}}
function aisacLearningCard(c){{const r=fixedRows(c);return `<div class="chat-case-media"><div class="kobaco-data-card"><div class="aisac-player-shell"><iframe class="aisac-player-frame" src="/api/aisac-player/${{encodeURIComponent(c.id)}}"></iframe></div><div class="aisac-card-title">${{esc(c.title||'-')}}</div><div class="context-actions"><a href="/api/aisac-open/${{encodeURIComponent(c.id)}}" target="_blank">원본 페이지 ↗</a><a class="alt" href="${{esc(c.aisac_search_url||c.source_url||'#')}}" target="_blank">검색 결과 ↗</a></div><div class="fact-grid"><div><small>등록일</small><b>${{esc(r['등록일']||c.registration_date||'-')}}</b></div><div><small>광고주</small><b>${{esc(r['광고주']||'-')}}</b></div><div><small>업종</small><b>${{esc(r['업종']||'-')}}</b></div></div><div class="aisac-result"><small>AiSAC이 인식한 키워드</small><strong>${{esc(r['키워드']||'-')}}</strong></div><div class="kobaco-data-table">${{fixedRawRows(c)}}</div></div></div>`;}}
function educationLearningCard(c){{const id=String(c.id||'');return `<div class="chat-case-media"><div class="education-study-v21" data-edu-v21="${{id}}" data-loaded="0"><div class="education-study-v21-head"><small>리터러시 교육 안내서</small><b data-title>${{esc(c.title||'학습 활동')}}</b></div><div class="education-study-v21-status" data-status>학습 내용을 준비하는 중...</div><div class="education-study-v21-body" data-content style="display:none"><div class="education-study-v21-visual" data-visual style="display:none"></div><div class="education-study-v21-reading"><h4>읽어보기</h4><div data-reading></div></div><div class="education-study-v21-questions"><h4>생각해보기</h4><ol data-questions></ol></div><div class="education-study-v21-actions"><a href="/api/education-file/${{id}}" target="_blank">원문 보기</a></div></div></div></div>`;}}
function caseMedia(c){{const id=String(c?.id||'');if(id.startsWith('education_'))return educationLearningCard(c);if(id.startsWith('kobaco_aisac_'))return aisacLearningCard(c);return `<div class="chat-case-media"><div class="kobaco-data-card"><div class="aisac-card-title">${{esc(c.title||'자료')}}</div></div></div>`;}}function caseCard(c){{return `<div class="chat-case-card"><div class="chat-case-top"><div><div class="chat-case-kicker">${{esc(c.label||'')}}</div><div class="chat-case-title">${{esc(c.title||'')}}</div><div class="chat-case-source">사례 출처 · ${{esc(c.source_name||'')}}</div></div>${{c.source_url?`<a class="chat-case-link" href="${{esc(c.source_url)}}" target="_blank">원문 보기 ↗</a>`:''}}</div>${{caseMedia(c)}}<div class="chat-case-caption">${{esc(c.media_caption||'')}}</div></div>`;}}
async function startCase(id,cid){{const st=document.getElementById('chatStatus');try{{const r=await fetch('/api/case-start',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{lesson_id:id,case_id:cid}})}}),d=await r.json();if(!r.ok)throw new Error(d.detail||'사례 시작 실패');sessionId=d.session_id;selectedLesson=id;inlineLessonId=id;inlineCaseId=cid;chat.innerHTML=fixedPickerHtml(id,cid)+caseCard(d.case);bindCaseButtons(id);addMsg('assistant',d.opening_question);input.disabled=false;send.disabled=false;finish.disabled=false;st.textContent='';}}catch(e){{setError(st,e.message);}}}}
</script><script>(()=>{{document.querySelector('.topbar .mode')?.setAttribute('style','display:none!important');[...document.querySelectorAll('.lesson-card')].forEach(old=>{{const card=old.cloneNode(true);old.replaceWith(card);card.addEventListener('click',async()=>{{selectedLesson=card.dataset.lesson;document.querySelectorAll('.lesson-card').forEach(x=>x.classList.toggle('selected',x===card));await showCaseChooser(selectedLesson)}})}})}})();</script><script>(()=>{{let activeCard=null,activeQ=[],idx=0,attempts=[];const nativeFetch=window.fetch.bind(window);function layout(){{const paper=document.querySelector('.study-paper');if(!paper||paper.querySelector('.aioff-learning-columns'))return;const a=paper.querySelector(':scope > .chat-area'),c=paper.querySelector(':scope > .composer-wrap');if(!a||!c)return;const cols=document.createElement('div');cols.className='aioff-learning-columns';paper.insertBefore(cols,a);cols.appendChild(a);const side=document.createElement('aside');side.className='aioff-composer-side';side.innerHTML='<div class="aioff-composer-side-head"><strong>생각 적기</strong><span>현재 질문 하나에 답해보세요.</span><div class="aioff-side-question" data-aioff-side-question style="display:none"><small data-aioff-side-progress></small><b data-aioff-side-text></b></div></div>';side.appendChild(c);cols.appendChild(side)}}async function hydrate(card){{if(card.dataset.loaded!=='0')return;card.dataset.loaded='loading';const id=card.dataset.eduV21,s=card.querySelector('[data-status]');try{{const r=await nativeFetch('/api/education-learning/'+encodeURIComponent(id)),d=await r.json(),p=d.pack||{{}};if(p.activity_title)card.querySelector('[data-title]').textContent=p.activity_title;if(p.visual_available){{const v=card.querySelector('[data-visual]');v.innerHTML=`<iframe src="/api/education-visual/${{encodeURIComponent(id)}}#page=${{p.page||1}}&toolbar=0&navpanes=0&view=FitH"></iframe>`;v.style.display='block'}}card.querySelector('[data-reading]').innerHTML=(p.reading||[]).map(x=>`<p>${{esc(x)}}</p>`).join('');card.querySelector('[data-questions]').innerHTML=(p.questions||[]).map(x=>`<li>${{esc(x)}}</li>`).join('');s.style.display='none';card.querySelector('[data-content]').style.display='block';card.dataset.loaded='1'}}catch(e){{s.textContent='학습 내용을 불러오지 못했습니다.';card.dataset.loaded='error'}}}}function update(state=''){{if(!activeCard||!activeQ.length)return;[...activeCard.querySelectorAll('.education-study-v21-questions li')].forEach((li,i)=>li.classList.toggle('aioff-current-question',i===idx));const side=document.querySelector('[data-aioff-side-question]'),p=document.querySelector('[data-aioff-side-progress]'),t=document.querySelector('[data-aioff-side-text]');if(side&&p&&t){{side.style.display='block';p.textContent=`질문 ${{idx+1}} / ${{activeQ.length}}`;t.textContent=activeQ[idx]||''}}}}function seq(){{const cards=[...document.querySelectorAll('.education-study-v21[data-loaded="1"]')];if(!cards.length)return;const c=cards[cards.length-1];if(c===activeCard&&c.dataset.seq==='1')return;const q=[...c.querySelectorAll('.education-study-v21-questions li')].map(x=>(x.textContent||'').trim()).filter(Boolean);if(!q.length)return;activeCard=c;activeQ=q;idx=0;attempts=new Array(q.length).fill(0);c.dataset.seq='1';update()}}window.fetch=async function(resource,init){{const url=typeof resource==='string'?resource:String(resource?.url||''),cid=String(inlineCaseId||'');let edu=false;if(url.includes('/api/chat-stream')&&cid.startsWith('education_')&&activeCard&&activeQ.length&&init&&typeof init.body==='string'){{try{{const b=JSON.parse(init.body);attempts[idx]=(attempts[idx]||0)+1;b.current_question=activeQ[idx]||'';b.question_attempt=attempts[idx];init={{...init,body:JSON.stringify(b)}};edu=true}}catch(e){{}}}}const r=await nativeFetch(resource,init);if(edu){{const v=(r.headers.get('X-AIOFF-Verdict')||'').toLowerCase();if(v==='pass'&&idx<activeQ.length-1){{idx++;setTimeout(update,100)}}else if(v)setTimeout(()=>update(v),100)}}return r}};function scan(){{layout();document.querySelectorAll('.education-study-v21[data-loaded="0"]').forEach(hydrate);seq()}}layout();scan();new MutationObserver(scan).observe(document.body,{{childList:true,subtree:true,attributes:true,attributeFilter:['data-loaded']}})}})();</script>'''
    page=page.replace("</style>","</style>"+css,1); page=page.replace("</body>",script+"\n</body>"); return page

base._remove_route("/","GET")
@app.get("/",response_class=HTMLResponse)
def aioff_ui_index(): return HTMLResponse(_render_index_aioff_ui())
