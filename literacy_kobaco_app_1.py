from __future__ import annotations

import html as html_lib
import json
import math
from typing import Any

from fastapi.responses import HTMLResponse

import literacy_media_app_10 as previous
from kobaco_db import get_kobaco_db, kobaco_status


flow = previous.flow
app = previous.app
base = flow.base


# ---------------------------------------------------------------------------
# 1) 학습 주제: KOBACO 실제 Parquet DB를 직접 읽는 3개 모듈
# ---------------------------------------------------------------------------
KOBACO_LESSONS = {
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
        "title": "공익광고 효과 수치 제대로 읽기",
        "short": "인지경로·신뢰성·기억요인처럼 서로 다른 조사 지표를 같은 '효과' 숫자로 뭉뚱그리지 않는 법을 연습합니다.",
        "source_name": "KOBACO 공익광고 효과평가 DB",
        "source_url": "https://www.kobaco.co.kr/site/main/archive/advertising/5",
        "source_role": "실제 KOBACO 공익광고 효과조사 데이터",
        "source_note": "공익광고 효과평가의 전달력, 인지경로, 임팩트 요인 등 서로 다른 지표를 Parquet DB에서 같은 조사·주제 기준으로 연결해 제시합니다.",
        "criteria": [
            "인지경로·신뢰성·만족도·기억요인처럼 지표 이름과 측정 대상을 먼저 구분한다.",
            "퍼센트 숫자만 보지 말고 무엇을 분모와 질문으로 측정한 비율인지 확인한다.",
            "인지경로 비중을 광고효과나 행동변화 비율로 바꾸어 말하지 않는다.",
            "조사 시점·공익광고 주제·세부 구분이 같은 값끼리 비교하는지 확인한다.",
            "표에 직접 없는 인과관계나 행동변화를 데이터가 증명한 것처럼 단정하지 않는다.",
        ],
        "skills": ["지표 의미 구분", "수치 과잉해석 방지", "조사 조건 확인"],
        "starter": "공익광고 효과평가의 실제 수치를 선택해 어떤 표현까지 데이터가 직접 뒷받침하는지 판단해봅니다.",
        "safety_note": "",
    },
    "ai": {
        "title": "청소년·OTT 통계에서 사실과 해석 구분하기",
        "short": "연령별 OTT 이용률을 보고 이용·선호·대표성을 혼동하지 않고 조사 조건을 확인합니다.",
        "source_name": "KOBACO 성별·연령별 OTT 이용비율 및 2025 청소년 미디어 이용 DB",
        "source_url": "https://www.data.go.kr",
        "source_role": "실제 미디어 이용 통계 DB",
        "source_note": "현재 사례는 의미가 명확한 성별·연령별 OTT 이용비율을 직접 조회하며, 같은 데이터 저장소에는 2025 청소년 미디어 이용조사 2,674행×472변수도 함께 적재되어 있습니다.",
        "criteria": [
            "이용률·이용경험과 선호도·만족도를 서로 다른 개념으로 구분한다.",
            "연도·연령구분·사례수 등 표의 조사 조건을 확인한 뒤 수치를 해석한다.",
            "여러 플랫폼 비율을 비교하거나 합칠 때 문항 방식과 복수 선택 가능 여부를 먼저 확인한다.",
            "표본·가중치·조사설계를 확인하지 않은 채 한 표의 값을 전체 청소년에게 무조건 일반화하지 않는다.",
            "다른 연도나 집단을 비교할 때 동일한 문항·조건인지 확인한다.",
        ],
        "skills": ["이용·선호 구분", "표본·조건 확인", "통계 일반화 판단"],
        "starter": "연령별 OTT 실제 이용률을 선택해 표가 말해주는 사실과 추가 확인이 필요한 해석을 나눠봅니다.",
        "safety_note": "",
    },
}


def _text(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    return value if value else fallback


def _num(value: Any) -> float | None:
    try:
        n = float(value)
        if not math.isfinite(n):
            return None
        return n
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> str:
    n = _num(value)
    return "-" if n is None else f"{n:.1f}%"


def _int_text(value: Any) -> str:
    n = _num(value)
    return "-" if n is None else f"{int(round(n)):,}"


def _compact_keywords(value: Any, limit: int = 180) -> str:
    text = _text(value, "")
    text = text.replace("\r", " ").replace("\n", " ").replace("'", "")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _common_case(
    *,
    case_id: str,
    label: str,
    title: str,
    claim: str,
    source_name: str,
    source_url: str,
    source_excerpt: str,
    clues: list[str],
    resolution: str,
    opening_questions: list[str],
    db_tables: list[str],
    data_rows: list[dict[str, str]],
    data_note: str,
) -> dict[str, Any]:
    return {
        "id": case_id,
        "label": label,
        "title": title,
        "claim": claim,
        "source_name": source_name,
        "source_url": source_url,
        "source_excerpt": source_excerpt,
        "media_type": "data",
        "media_url": "",
        "media_caption": f"KOBACO Parquet DB 실조회값 · {' · '.join(db_tables)}",
        "clues": clues,
        "resolution": resolution,
        "opening_question": opening_questions[0],
        "opening_questions": opening_questions,
        "db_tables": db_tables,
        "data_rows": data_rows,
        "data_note": data_note,
    }


def _build_aisac_cases(db) -> list[dict[str, Any]]:
    required = ("aisac_ad_info", "aisac_ai_keywords")
    if not db.has_tables(*required):
        return []
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
              PARTITION BY COALESCE(a."대업종 분류", '기타')
              ORDER BY a."광고소재등록일" DESC, a."광고소재명"
            ) AS rn
          FROM aisac_ad_info a
          JOIN aisac_ai_keywords k
            ON a."광고소재명" = k."광고소재명"
           AND a."광고소재등록일" = k."광고소재등록일"
          WHERE NULLIF(TRIM(CAST(k."키워드" AS VARCHAR)), '') IS NOT NULL
            AND COALESCE(k."키워드 개수", 0) >= 3
        )
        SELECT * EXCLUDE (rn)
        FROM joined
        WHERE rn = 1
        ORDER BY "대업종", "광고소재명"
        LIMIT 9
        '''
    )
    cases = []
    for idx, row in enumerate(rows, 1):
        name = _text(row.get("광고소재명"))
        keywords = _compact_keywords(row.get("키워드"))
        category = " / ".join(x for x in [_text(row.get("대업종"), ""), _text(row.get("중업종"), "")] if x)
        cases.append(
            _common_case(
                case_id=f"kobaco_aisac_{idx:02d}",
                label="AiSAC 실제 데이터",
                title=name,
                claim=f"'{name}' 광고를 설명할 때 AiSAC이 인식한 키워드를 광고의 핵심 메시지로 그대로 사용해도 되는지 판단하는 상황입니다.",
                source_name="KOBACO AiSAC",
                source_url="https://aisac.kobaco.co.kr",
                source_excerpt=f"AI 인식 키워드: {keywords}",
                clues=[
                    f"광고소재등록일: {_text(row.get('광고소재등록일'))}",
                    f"업종: {category or '-'} / 광고주: {_text(row.get('광고주명'))}",
                    f"AiSAC 키워드 개수: {_int_text(row.get('키워드 개수'))}",
                    f"사물인식 개수: {_int_text(row.get('사물인식 개수'))}, 장소인식 개수: {_int_text(row.get('장소인식 개수'))}",
                    f"DB 키워드 원문: {keywords}",
                ],
                resolution="이 DB가 직접 확인해주는 것은 광고소재 메타데이터와 AiSAC의 인식 결과입니다. 키워드·사물·장소 인식값만으로 광고의 의도나 핵심 메시지를 확정할 수 없으므로, 의미를 설명하려면 원본 영상·문구와 전체 맥락을 추가로 확인해야 합니다.",
                opening_questions=[
                    "발표자료에 이 광고를 설명해야 한다면, 화면의 DB 값 중 어디까지는 그대로 사실로 쓸 수 있고 어디부터는 원본 광고를 더 확인해야 할까?",
                    "AiSAC이 찾아낸 키워드와 사람이 이해하는 광고 메시지를 나눠보자. 지금 데이터만으로 확실히 말할 수 있는 것 하나와 아직 말할 수 없는 것 하나를 골라줘.",
                    "이 키워드만 보고 광고 의도를 한 문장으로 정리해달라는 요청을 받았다면 바로 작성할지, 원본을 확인한 뒤 작성할지 정하고 이유를 말해줘.",
                ],
                db_tables=list(required),
                data_rows=[
                    {"label": "광고주", "value": _text(row.get("광고주명"))},
                    {"label": "업종", "value": category or "-"},
                    {"label": "키워드", "value": keywords},
                    {"label": "인식 횟수", "value": f"사물 {_int_text(row.get('사물인식 개수'))} · 장소 {_int_text(row.get('장소인식 개수'))}"},
                ],
                data_note="표시 값은 AiSAC 광고소재 메타데이터와 AI 인식결과 Parquet에서 직접 조회합니다.",
            )
        )
    return cases


def _build_public_ad_cases(db) -> list[dict[str, Any]]:
    required = ("public_ad_effect_persuasiveness", "public_ad_effect_channel", "public_ad_effect_impact")
    if not db.has_tables(*required):
        return []
    rows = db.query(
        '''
        WITH p AS (
          SELECT
            "조사", "주제",
            MAX(CASE WHEN "구분"='전체' AND "세부"='신뢰성' THEN "비율" END) AS "신뢰성",
            MAX(CASE WHEN "구분"='전체' AND "세부"='전반적 만족도' THEN "비율" END) AS "만족도"
          FROM public_ad_effect_persuasiveness
          GROUP BY "조사", "주제"
        ),
        ch AS (
          SELECT "조사", "주제", "매체", "비중",
                 ROW_NUMBER() OVER (PARTITION BY "조사", "주제" ORDER BY "비중" DESC, "매체") AS rn
          FROM public_ad_effect_channel
        ),
        imp AS (
          SELECT "조사", "주제", "구분" AS "임팩트요인", "비율" AS "임팩트비율",
                 ROW_NUMBER() OVER (PARTITION BY "조사", "주제" ORDER BY "비율" DESC, "구분") AS rn
          FROM public_ad_effect_impact
        )
        SELECT p."조사", p."주제", p."신뢰성", p."만족도",
               ch."매체" AS "주요인지경로", ch."비중" AS "인지경로비중",
               imp."임팩트요인", imp."임팩트비율"
        FROM p
        JOIN ch ON p."조사"=ch."조사" AND p."주제"=ch."주제" AND ch.rn=1
        JOIN imp ON p."조사"=imp."조사" AND p."주제"=imp."주제" AND imp.rn=1
        WHERE p."신뢰성" IS NOT NULL
        ORDER BY p."조사" DESC, p."주제"
        LIMIT 9
        '''
    )
    cases = []
    for idx, row in enumerate(rows, 1):
        topic = _text(row.get("주제"))
        survey = _text(row.get("조사"))
        channel = _text(row.get("주요인지경로"))
        impact = _text(row.get("임팩트요인"))
        cases.append(
            _common_case(
                case_id=f"kobaco_publicad_{idx:02d}",
                label="공익광고 효과조사",
                title=f"{topic} · {survey}",
                claim=f"'{topic}' 조사 수치를 한 문장으로 요약하면서 인지경로·신뢰성·기억요인을 모두 '광고 효과'라고 표현해도 되는지 판단하는 상황입니다.",
                source_name="KOBACO 공익광고 효과평가",
                source_url="https://www.kobaco.co.kr/site/main/archive/advertising/5",
                source_excerpt=(
                    f"신뢰성 {_pct(row.get('신뢰성'))} · 주요 인지경로 {channel} {_pct(row.get('인지경로비중'))} · "
                    f"가장 큰 임팩트 요인 {impact} {_pct(row.get('임팩트비율'))}"
                ),
                clues=[
                    f"조사: {survey} / 주제: {topic}",
                    f"전달력 지표 '신뢰성': {_pct(row.get('신뢰성'))}",
                    f"인지경로 1위: {channel} {_pct(row.get('인지경로비중'))}",
                    f"임팩트 요인 1위: {impact} {_pct(row.get('임팩트비율'))}",
                    "각 값은 서로 다른 조사 항목에서 나온 별도 지표다.",
                ],
                resolution="인지경로 비중, 신뢰성, 임팩트 요인은 서로 측정 대상이 다른 지표입니다. 따라서 한 숫자를 다른 지표의 의미로 바꾸거나, 표에 없는 행동변화·인과효과까지 증명한 것처럼 표현하면 안 됩니다. 보고서에서는 지표명을 그대로 밝히고 조사·주제 조건과 함께 해석해야 합니다.",
                opening_questions=[
                    "이 수치들로 보고서 한 문장을 쓴다면 어떤 표현까지는 DB가 직접 뒷받침하고, 어떤 표현부터는 추가 근거가 필요할까?",
                    "인지경로, 신뢰성, 임팩트 요인 중 서로 같은 뜻처럼 바꾸어 써도 되는 값이 있는지 구분해서 말해줘.",
                    "누군가 이 표를 보고 '이 공익광고의 효과는 이 정도다'라고 숫자 하나로 요약하려 해. 먼저 어떤 지표의 의미부터 확인해야 할까?",
                ],
                db_tables=list(required),
                data_rows=[
                    {"label": "조사", "value": survey},
                    {"label": "신뢰성", "value": _pct(row.get("신뢰성"))},
                    {"label": "주요 인지경로", "value": f"{channel} · {_pct(row.get('인지경로비중'))}"},
                    {"label": "임팩트 1위", "value": f"{impact} · {_pct(row.get('임팩트비율'))}"},
                ],
                data_note="전달력·인지경로·임팩트 테이블을 조사명과 주제로 연결한 실제 조회값입니다.",
            )
        )
    return cases


def _build_ott_cases(db) -> list[dict[str, Any]]:
    required = ("ott_usage_by_demographic",)
    if not db.has_tables(*required):
        return []
    rows = db.query(
        '''
        SELECT *
        FROM ott_usage_by_demographic
        WHERE "구분1"='연령별'
        ORDER BY "연도" DESC,
                 CASE WHEN "구분2"='13-19세' THEN 0 ELSE 1 END,
                 "구분2"
        LIMIT 9
        '''
    )
    service_columns = [
        "유튜브", "넷플릭스", "티빙", "웨이브", "SOOP(구 아프리카TV)", "카카오TV",
        "왓챠", "쿠팡플레이", "NAVER TV(구 NOW)", "디즈니플러스", "U플러스모바일TV", "애플TV플러스",
    ]
    cases = []
    for idx, row in enumerate(rows, 1):
        ranked = []
        for col in service_columns:
            n = _num(row.get(col))
            if n is not None:
                ranked.append((n, col))
        ranked.sort(reverse=True)
        top = ranked[:3]
        if not top:
            continue
        top_value, top_service = top[0]
        group = _text(row.get("구분2"))
        year = _text(row.get("연도"))
        top_text = " · ".join(f"{name} {value:.1f}%" for value, name in top)
        cases.append(
            _common_case(
                case_id=f"kobaco_ott_{idx:02d}",
                label="연령별 OTT 실제 통계",
                title=f"{year} · {group}",
                claim=f"{group}에서 {top_service} 이용률이 {top_value:.1f}%로 가장 높게 나타난 표를 보고, 이를 '{group}가 {top_service}를 가장 선호한다'고 요약하려는 상황입니다.",
                source_name="KOBACO 성별·연령별 OTT 이용비율",
                source_url="https://www.data.go.kr",
                source_excerpt=f"사례수 {_int_text(row.get('사례수'))}명 · {top_text} · OTT 비이용 {_pct(row.get('OTT 비이용'))}",
                clues=[
                    f"연도: {year} / 구분: {group} / 사례수: {_int_text(row.get('사례수'))}명",
                    f"플랫폼 이용비율 상위 값: {top_text}",
                    f"OTT 비이용: {_pct(row.get('OTT 비이용'))}",
                    "DB 컬럼명은 각 플랫폼의 '이용 비율'이며 '선호도' 컬럼은 아니다.",
                ],
                resolution=f"이 표가 직접 제공하는 값은 {group}의 플랫폼별 이용 비율입니다. {top_service} 이용률이 가장 높다는 사실은 말할 수 있지만, 이용률만으로 '가장 선호한다'는 선호도까지 확정할 수는 없습니다. 연도·사례수·문항 정의와 조사설계를 확인한 뒤 필요한 범위까지만 해석해야 합니다.",
                opening_questions=[
                    f"이 표를 보고 '{group}가 가장 좋아하는 플랫폼은 {top_service}'라고 보고서에 써도 될까? 이용률과 선호도를 나눠서 판단해줘.",
                    "친구에게 이 표를 설명한다면 지금 확실히 말할 수 있는 사실 하나와 추가 확인이 필요한 해석 하나를 나눠 말해줘.",
                    f"보고서 제목을 '{group}가 가장 선호하는 OTT'로 붙이려 한다면 그대로 쓸지 수정할지 결정하고, 화면의 어떤 필드가 근거인지 말해줘.",
                ],
                db_tables=list(required),
                data_rows=[
                    {"label": "연도·집단", "value": f"{year} · {group}"},
                    {"label": "사례수", "value": f"{_int_text(row.get('사례수'))}명"},
                    {"label": "이용비율 상위", "value": top_text},
                    {"label": "OTT 비이용", "value": _pct(row.get("OTT 비이용"))},
                ],
                data_note="성별·연령별 OTT 서비스 이용비율 Parquet의 연령별 행을 직접 조회한 값입니다.",
            )
        )
    return cases


def _build_case_library() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    db = get_kobaco_db()
    if db is None:
        return {}, kobaco_status()
    try:
        library = {
            "news": _build_aisac_cases(db),
            "deepfake": _build_public_ad_cases(db),
            "ai": _build_ott_cases(db),
        }
        if not all(library.values()):
            missing = [lesson_id for lesson_id, cases in library.items() if not cases]
            status = db.status()
            status["available"] = False
            status["error"] = f"KOBACO case build incomplete: {', '.join(missing)}"
            return {}, status
        status = db.status()
        status["case_counts"] = {k: len(v) for k, v in library.items()}
        return library, status
    except Exception as exc:
        status = db.status()
        status["available"] = False
        status["error"] = f"{type(exc).__name__}: {exc}"
        return {}, status


KOBACO_CASE_LIBRARY, KOBACO_STATUS = _build_case_library()
KOBACO_ACTIVE = bool(KOBACO_CASE_LIBRARY)

if KOBACO_ACTIVE:
    base.LESSONS.clear()
    base.LESSONS.update(KOBACO_LESSONS)
    flow.CASE_LIBRARY.clear()
    flow.CASE_LIBRARY.update(KOBACO_CASE_LIBRARY)
    flow.CASE_BY_ID.clear()
    flow.CASE_BY_ID.update({
        case["id"]: (lesson_id, case)
        for lesson_id, cases in flow.CASE_LIBRARY.items()
        for case in cases
    })


# app5의 고정 payload에 KOBACO 데이터 카드용 필드를 추가합니다.
def _public_kobaco_case(case: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "label", "title", "claim", "source_name", "source_url",
        "source_excerpt", "media_type", "media_url", "media_caption",
        "db_tables", "data_rows", "data_note",
    )
    return {key: case.get(key, "") for key in keys}


if KOBACO_ACTIVE:
    flow._public_case = _public_kobaco_case


@app.get("/api/kobaco-status")
def api_kobaco_status():
    return KOBACO_STATUS


# ---------------------------------------------------------------------------
# 2) 화면: 기사 썸네일 대신 실제 DB 조회값 카드 표시
# ---------------------------------------------------------------------------
def _render_index_kobaco():
    html = previous._render_index_v9()

    replacements = {
        "디지털 리터러시 × AI OFF": "KOBACO DATA × AI OFF",
        "AI와 판단 기준을 배우고,<br>마지막에는 내가 직접 확인합니다.": "실제 미디어 데이터를 읽고,<br>AI와 해석 기준을 연습합니다.",
        "3개 주제 · 주제별 실제 사례 9개 중 3개 랜덤": "3개 주제 · KOBACO 실제 DB 사례 랜덤",
        "주제를 고르면 9개의 실제 사례 풀에서 3개가 무작위로 나타납니다.": "주제를 고르면 KOBACO Parquet DB에서 구성한 실제 데이터 사례가 무작위로 나타납니다.",
        "주제를 고르면 아래 채팅창에 9개 실제 사례 중 3개가 무작위로 표시됩니다.": "주제를 고르면 아래 채팅창에 KOBACO 실제 데이터 사례 3개가 표시됩니다.",
        "원문 발췌": "DB 조회값",
        "판단할 주장·상황": "판단할 해석·상황",
        "실제 사례에서 바로 시작합니다.": "실제 KOBACO 데이터에서 바로 시작합니다.",
        "사진·기사·문서와 원문 발췌, 판단할 주장을": "실제 DB 조회값과 판단할 해석을",
    }
    for old, new in replacements.items():
        html = html.replace(old, new)

    status_text = "KOBACO DB 연동 완료" if KOBACO_ACTIVE else "KOBACO DB 대기 중"
    status_detail = (
        "AiSAC · 공익광고 효과평가 · OTT 이용통계를 Parquet/DuckDB로 직접 조회합니다."
        if KOBACO_ACTIVE
        else "서버에 raw_data/parquet_db를 복사하면 KOBACO 데이터 사례로 자동 전환됩니다. 현재는 기존 사례가 임시 표시됩니다."
    )
    banner = (
        '<div class="kobaco-db-banner">'
        f'<strong>{html_lib.escape(status_text)}</strong>'
        f'<span>{html_lib.escape(status_detail)}</span>'
        '</div>'
    )
    html = html.replace('<main>', '<main>' + banner, 1)

    extra_css = r"""
.kobaco-db-banner{display:flex;justify-content:space-between;gap:18px;align-items:center;margin:0 0 16px;padding:10px 14px;border:1px solid #d9d2c8;border-radius:9px;background:#f8f5ef;color:#3a352f;font-size:10px}.kobaco-db-banner strong{font-size:11px}.kobaco-db-banner span{color:#71695f;text-align:right}
.kobaco-data-card{width:100%;background:#f7f4ee;padding:16px}.kobaco-data-kicker{font-size:9px;font-weight:900;letter-spacing:.05em;color:#7a6d5d;margin-bottom:9px}.kobaco-data-table{border:1px solid #d9d2c8;background:#fff;border-radius:8px;overflow:hidden}.kobaco-data-row{display:grid;grid-template-columns:120px 1fr;border-top:1px solid #ebe5dc}.kobaco-data-row:first-child{border-top:0}.kobaco-data-row b{padding:9px 11px;background:#faf8f4;color:#6b635a;font-size:9px}.kobaco-data-row span{padding:9px 11px;color:#2d2925;font-size:11px;line-height:1.45;word-break:break-word}.kobaco-data-note{font-size:9px;line-height:1.45;color:#7b7369;margin-top:8px}
@media(max-width:650px){.kobaco-db-banner{align-items:flex-start;flex-direction:column}.kobaco-db-banner span{text-align:left}.kobaco-data-row{grid-template-columns:92px 1fr}}
"""
    html = html.replace("</style>", extra_css + "\n</style>")

    # v9가 마지막에 정의한 caseMedia를 다시 덮어써 DB 값 자체가 보이게 합니다.
    script = r'''
<script>
function caseMedia(c){
  if(!c || !Array.isArray(c.data_rows) || !c.data_rows.length){
    return `<div class="chat-case-media"><img src="/api/case-thumb/${encodeURIComponent(c.id)}" alt="${esc(c.title)} 미리보기" loading="eager"></div>`;
  }
  const tables=(c.db_tables||[]).map(x=>esc(x)).join(' · ');
  const rows=c.data_rows.map(r=>`<div class="kobaco-data-row"><b>${esc(r.label||'항목')}</b><span>${esc(r.value||'-')}</span></div>`).join('');
  return `<div class="chat-case-media"><div class="kobaco-data-card"><div class="kobaco-data-kicker">PARQUET / DUCKDB · ${tables}</div><div class="kobaco-data-table">${rows}</div><div class="kobaco-data-note">${esc(c.data_note||'KOBACO 실제 데이터 조회값')}</div></div></div>`;
}
</script>
'''
    html = html.replace("</body>", script + "\n</body>")
    return html


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index():
    return HTMLResponse(_render_index_kobaco())
