from copy import deepcopy

from literacy_cases_7 import CASE_LIBRARY as _BASE_CASE_LIBRARY

# 사실관계/출처/원문 발췌는 기존 검증본을 그대로 유지합니다.
# 첫 질문만 '믿어도 될까?'처럼 정답을 암시하지 않도록 실제 행동·사용 결정을 묻는 방식으로 바꿉니다.
CASE_LIBRARY = deepcopy(_BASE_CASE_LIBRARY)

NEWS_OPENERS = [
    "이 게시물을 단체 채팅방에서 처음 봤다고 가정해보자. 지금 상태에서 '그대로 공유', '확인 후 공유', '일단 보류' 중 하나를 고르고, 그렇게 판단한 단서 한 가지를 말해줘.",
    "친구가 이 내용이 사실인지 묻는다면 지금 가진 정보만으로 뭐라고 답하겠어? 확실히 말할 수 있는 부분과 아직 확인이 필요한 부분을 하나씩 나눠 말해줘.",
    "이 내용을 발표 자료에 넣어야 한다면 지금 바로 인용할지, 추가 확인 뒤 인용할지 결정해봐. 가장 먼저 확인할 항목도 하나 골라줘.",
]

DEEPFAKE_OPENERS = [
    "이 상황을 실제로 마주쳤다고 가정해보자. 지금 가장 먼저 할 행동 하나를 정하고, 화면에 보이는 정보 중 그 행동을 선택하게 만든 근거를 말해줘.",
    "상대가 지금 당장 판단이나 행동을 요구하고 있어. 너라면 바로 대응할지, 별도 경로로 확인할지, 잠시 보류할지 하나를 고르고 이유를 말해줘.",
    "이 자료를 처음 받았을 때 무엇을 사실로 받아들이고 무엇을 아직 미확인 상태로 둘지 나눠봐. 그다음 첫 확인 행동도 하나 정해줘.",
]

AI_OPENERS = [
    "이 AI 답변을 과제나 업무 문서에 넣기 직전이라고 가정해보자. '그대로 사용', '일부만 사용', '원문 확인 후 사용' 중 하나를 고르고 가장 먼저 확인할 부분을 말해줘.",
    "이 답변 때문에 실제 결정을 내려야 한다면 지금 어느 부분까지 활용하겠어? 그대로 쓸 부분과 직접 확인할 부분을 하나씩 나눠 말해줘.",
    "AI가 꽤 구체적인 근거까지 제시했어. 이 내용을 다른 사람에게 전달하기 전에 네가 직접 확인할 항목을 우선순위대로 하나만 골라줘.",
]

for topic, cases in CASE_LIBRARY.items():
    variants = NEWS_OPENERS if topic == "news" else DEEPFAKE_OPENERS if topic == "deepfake" else AI_OPENERS
    for idx, case in enumerate(cases):
        # 같은 주제에서도 첫 문장이 반복돼 보이지 않도록 사례마다 시작 위치를 조금씩 다르게 둡니다.
        case["opening_questions"] = variants[idx % len(variants):] + variants[:idx % len(variants)]

for topic, cases in CASE_LIBRARY.items():
    assert len(cases) == 9, f"{topic}: expected 9 cases, got {len(cases)}"
    assert all(len(case.get("opening_questions", [])) == 3 for case in cases)
