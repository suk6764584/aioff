from fastapi.responses import HTMLResponse

import literacy_media_app_6 as previous
from literacy_cases_6 import CASE_LIBRARY

# v6의 랜덤 3개 표시/채팅/AI OFF 흐름은 그대로 유지하고,
# 원문 대조 후 교정한 사례 메타데이터만 사용합니다.
flow = previous.flow
app = previous.app

flow.CASE_LIBRARY.clear()
flow.CASE_LIBRARY.update(CASE_LIBRARY)
flow.CASE_BY_ID.clear()
flow.CASE_BY_ID.update({
    case["id"]: (lesson_id, case)
    for lesson_id, cases in flow.CASE_LIBRARY.items()
    for case in cases
})

# 이전 루트만 제거하고 동일한 랜덤 렌더러를 교정 데이터로 다시 등록합니다.
flow.base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def inline_case_index_v7():
    return HTMLResponse(previous._render_index_v6())
