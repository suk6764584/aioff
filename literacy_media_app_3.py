from fastapi.responses import HTMLResponse

import literacy_media_app_2 as base
from literacy_cases_2 import CASE_LIBRARY

app = base.app

# literacy_media_app_2의 채팅 내 사례 UI/AI OFF 흐름은 그대로 사용하고,
# 사례 데이터만 썸네일 보강본으로 교체합니다.
base.CASE_LIBRARY.clear()
base.CASE_LIBRARY.update(CASE_LIBRARY)
base.CASE_BY_ID.clear()
base.CASE_BY_ID.update({
    case["id"]: (lesson_id, case)
    for lesson_id, cases in base.CASE_LIBRARY.items()
    for case in cases
})

# 기존 / 화면만 제거하고 같은 렌더러를 보강된 사례 데이터로 다시 등록합니다.
base.base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def inline_case_index_v3():
    return HTMLResponse(base._render_index())
