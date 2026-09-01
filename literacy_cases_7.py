from copy import deepcopy

from literacy_cases_6 import CASE_LIBRARY as _BASE_CASE_LIBRARY

# 원문 검증/교정 데이터는 그대로 유지하고,
# YTN AI 합성 음성 사례에 기사 내 실제 영상의 YouTube 썸네일을 연결합니다.
CASE_LIBRARY = deepcopy(_BASE_CASE_LIBRARY)

for case in CASE_LIBRARY["deepfake"]:
    if case["id"] == "deepfake_voice_phishing":
        case.update({
            "media_type": "image",
            "media_url": "https://img.youtube.com/vi/WNyV88-3shQ/hqdefault.jpg",
            "media_caption": "YTN 보도 영상 썸네일입니다. YTN 기사 본문에 연결된 실제 영상(WNyV88-3shQ)의 YouTube 썸네일을 사용합니다.",
        })

for topic, cases in CASE_LIBRARY.items():
    assert len(cases) == 9, f"{topic}: expected 9 cases, got {len(cases)}"
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), f"{topic}: duplicate case id"
