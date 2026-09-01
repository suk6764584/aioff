from copy import deepcopy

from literacy_cases_2 import CASE_LIBRARY as _BASE_CASE_LIBRARY

# 기사·결정문 내용을 모델이 임의 요약하지 않고, 각 원문에서 짧게 직접 발췌한 문장만 표시합니다.
# 각 발췌는 원문 일부이며, 판단과 해설은 별도 AI 대화에서 진행합니다.
CASE_LIBRARY = deepcopy(_BASE_CASE_LIBRARY)

SOURCE_EXCERPTS = {
    "news_2020_protest": (
        "2020년 8월 페이스북과 트위터상에서 어느 대규모 시위 영상이 수십만 조회수를 기록했다. "
        "이 영상에는 한국의 수도 서울에서 열린 코로나19 규제 반대 시위라는 설명이 붙었다."
    ),
    "news_2024_pets": (
        "아이티 이민자들이 반려동물을 잡아먹는다는 근거 없는 소문이 소셜 미디어를 통해 퍼졌는데, "
        "도널드 트럼프 전 대통령 등 주요 정치인들이 이를 공개적으로 언급하면서 논란이 된 겁니다."
    ),
    "news_fake_generator": (
        "해당 메뉴를 누르면 ‘가짜뉴스 생성기’로 연결됩니다. 이용자가 뉴스 제목을 입력하고 ‘속보’, ‘단독’, ‘종합’ 등의 "
        "글머리를 선택한 뒤 사진을 고를 수 있도록 했습니다."
    ),
    "deepfake_school_196": (
        "올해 1월부터 지난 27일까지 각 시도교육청에 접수된 피해 현황은 모두 196건으로 이 가운데 179건에 대한 수사를 의뢰했습니다."
    ),
    "deepfake_kidnap_extortion": (
        "범인은 딸이 방 안에 감금된 채 울면서 살려달라고 하는 영상을 보내며, 우리 돈 8억 원을 요구했습니다. "
        "A 씨 부부는 곧바로 영사관을 통해 한국 경찰에 신고했습니다."
    ),
    "deepfake_voice_phishing": (
        "첨단 기술이 보이스 피싱 같은 범죄에 악용될 우려가 커지면서, 통신업계도 AI 판독 서비스를 제공하는 등 대응을 강화하고 있습니다."
    ),
    "ai_mata_avianca": (
        "Respondents abandoned their responsibilities when they submitted non-existent judicial opinions with fake quotes and citations created by the artificial intelligence tool ChatGPT."
    ),
    "ai_cohen_bard": (
        "There was only one problem: The cases do not exist."
    ),
    "ai_aircanada_chatbot": (
        "The chatbot suggested Mr. Moffatt could apply for bereavement fares retroactively."
    ),
}

# 첫 뉴스 사례는 한국언론진흥재단 2차 소개문이 아니라 확인 가능한 AFP 한국 원문으로 연결합니다.
for case in CASE_LIBRARY["news"]:
    if case["id"] == "news_2020_protest":
        case["source_name"] = "AFP 한국 팩트체크 · 2019년 10월 서울 집회 영상"
        case["source_url"] = "https://factcheckkorea.afp.com/i-yeongsangeun-jinan-2019nyeon-10weol-seouleseo-yeolrin-jogug-toejin-jibhoe-yeongsangida"

for cases in CASE_LIBRARY.values():
    for case in cases:
        case["source_excerpt"] = SOURCE_EXCERPTS.get(case["id"], "")
