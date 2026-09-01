from copy import deepcopy

from literacy_cases_5 import CASE_LIBRARY as _BASE_CASE_LIBRARY

# 주제별 9개 사례 풀은 유지하되, 원문 대조 과정에서 확인된 출처 표기만 교정합니다.
CASE_LIBRARY = deepcopy(_BASE_CASE_LIBRARY)

# 이 사례는 FTC가 작성한 문서가 아니라 미 상원 노령화특별위원회가 FTC 위원장에게 보낸
# 공식 서한이며, FTC 사이트에 공개된 문서입니다. 사례 자체와 9,400달러 금액은 서한에서 확인됩니다.
for case in CASE_LIBRARY["deepfake"]:
    if case["id"] == "deepfake_ftc_9400_grandson":
        case.update({
            "label": "미 상원 공식 서한 인용 사례 · 음성복제",
            "source_name": "U.S. Senate Special Committee on Aging · Letter to FTC Chair Lina Khan (May 18, 2023)",
            "media_caption": "미 상원 노령화특별위원회가 FTC 위원장에게 보낸 공식 서한에 인용된 음성복제 사기 사례입니다. 문서는 FTC 사이트에 공개되어 있습니다.",
        })

# 기존 링크는 CanLII의 AI·형사사법 보고서였으므로, 사건 자체의 직접 판결문으로 교체합니다.
for case in CASE_LIBRARY["ai"]:
    if case["id"] == "ai_zhang_chen":
        case.update({
            "source_name": "Supreme Court of British Columbia · Zhang v. Chen, 2024 BCSC 285",
            "source_url": "https://www.canlii.org/en/bc/bcsc/doc/2024/2024bcsc285/2024bcsc285.html",
            "media_caption": "브리티시컬럼비아 대법원의 Zhang v. Chen 판결문 원문입니다.",
        })

# 데이터 무결성 확인
for topic, cases in CASE_LIBRARY.items():
    assert len(cases) == 9, f"{topic}: expected 9 cases, got {len(cases)}"
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), f"{topic}: duplicate case id"
