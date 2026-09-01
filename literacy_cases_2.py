from copy import deepcopy

from literacy_cases import CASE_LIBRARY as _BASE_CASE_LIBRARY

# 기존 검증된 사례 내용은 유지하고, 뉴스·허위정보 사례 중 이미지가 없던 2건에만
# 학습용 썸네일을 보강합니다. 이미지 자체를 사실 근거로 사용하지 않습니다.
CASE_LIBRARY = deepcopy(_BASE_CASE_LIBRARY)

for case in CASE_LIBRARY["news"]:
    if case["id"] == "news_2024_pets":
        case.update({
            "media_type": "image",
            "media_url": "https://commons.wikimedia.org/wiki/Special:FilePath/New%20City%20Hall%2C%20Springfield%2C%20Ohio.jpg?width=1200",
            "media_caption": "소문이 확산된 미국 오하이오주 스프링필드의 시청 참고 이미지입니다. 주장 자체의 증거 이미지는 아닙니다. Cindy Funk / Wikimedia Commons / CC BY 2.0",
        })
    elif case["id"] == "news_fake_generator":
        case.update({
            "media_type": "image",
            "media_url": "https://img1.newsis.com/2024/03/22/NISI20240322_0001508571_web.jpg",
            "media_caption": "언론 기사처럼 보이는 가짜뉴스 생성 화면을 다룬 관련 보도 이미지입니다. 학습의 사실 근거와 해설은 YTN 팩트체크 원문을 기준으로 합니다. 이미지 출처: 뉴시스",
        })
