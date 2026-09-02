from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import quote_plus

import literacy_kobaco_app_5 as previous

# v5의 단계형 교육 흐름은 그대로 유지하고 YouTube 검색 제목 디코딩/매칭만 보강합니다.
# 웹에서 직접 확인한 대표 사례는 정확한 공식 KOBACO 영상 ID를 우선 사용합니다.
app = previous.app

_VERIFIED_YOUTUBE = {
    "장애인(발달장애등)출발": "3eXB3Fb7Syo",  # KOBACO공익광고협의회 30초 공식 영상
    "장애인발달장애등출발": "3eXB3Fb7Syo",
}


def _json_text(value: str) -> str:
    # YouTube HTML의 JSON 문자열에서 필요한 최소 이스케이프만 복원합니다.
    try:
        return bytes(value, "utf-8").decode("unicode_escape") if "\\u" in value else value.replace('\\"', '"').replace('\\/', '/')
    except Exception:
        return value


def _search_youtube_fixed(case) -> str:
    title = str(case.get("archive_title") or case.get("title") or "").split(" · ", 1)[0].strip()
    year = str(case.get("archive_year") or "").strip()
    norm_title = previous._norm(title)
    if norm_title in _VERIFIED_YOUTUBE:
        return _VERIFIED_YOUTUBE[norm_title]
    if not title:
        return ""

    query = quote_plus(f"공익광고협의회 {title} {year}".strip())
    try:
        page = previous._fetch_text(f"https://www.youtube.com/results?search_query={query}")
    except Exception:
        return ""

    candidates = []
    seen = set()
    for match in re.finditer(r'"videoId":"([A-Za-z0-9_-]{6,})"', page):
        video_id = match.group(1)
        if video_id in seen:
            continue
        seen.add(video_id)
        chunk = page[match.start(): match.start() + 5000]
        title_match = re.search(r'"title":\{"runs":\[\{"text":"((?:\\.|[^"\\])+)"', chunk)
        if not title_match:
            continue
        result_title = _json_text(title_match.group(1))
        result_norm = previous._norm(result_title)
        if not result_norm:
            continue

        similarity = SequenceMatcher(None, norm_title, result_norm).ratio()
        contained = len(norm_title) >= 4 and norm_title in result_norm
        official = "KOBACO" in chunk.upper() or "공익광고협의회" in chunk
        if not official and not contained:
            continue
        if not contained and similarity < 0.66:
            continue

        score = similarity + (0.40 if contained else 0) + (0.30 if official else 0)
        candidates.append((score, video_id))
        if len(candidates) >= 12:
            break

    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


# literacy_kobaco_app_5._resolve_youtube_id는 실행 시 module global의 _search_youtube를 조회하므로
# 함수만 교체하면 썸네일/영상 라우트 모두 보강된 매칭을 사용합니다.
previous._search_youtube = _search_youtube_fixed
