from fastapi.responses import HTMLResponse

import literacy_media_app_7 as previous
from literacy_cases_7 import CASE_LIBRARY

# v7의 검증된 사례/랜덤 3개/채팅/AI OFF 흐름은 유지하고,
# YTN AI 합성 음성 사례의 실제 영상 썸네일 연결만 반영합니다.
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

flow.base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def inline_case_index_v8():
    return HTMLResponse(previous.previous._render_index_v6())
