from fastapi.responses import HTMLResponse

import literacy_media_app_3 as previous
from literacy_cases_3 import CASE_LIBRARY

# literacy_media_app_3에서 사용하던 실제 사례 선택/대화/AI OFF 흐름은 유지하고,
# 사례 카드에 '기사 내용 요약'을 추가한 버전입니다.
flow = previous.base  # literacy_media_app_2 module
app = previous.app

flow.CASE_LIBRARY.clear()
flow.CASE_LIBRARY.update(CASE_LIBRARY)
flow.CASE_BY_ID.clear()
flow.CASE_BY_ID.update({
    case["id"]: (lesson_id, case)
    for lesson_id, cases in flow.CASE_LIBRARY.items()
    for case in cases
})


def _public_case_with_summary(case):
    data = {
        key: case[key]
        for key in (
            "id", "label", "title", "claim", "source_name", "source_url",
            "media_type", "media_url", "media_caption"
        )
    }
    data["article_summary"] = case.get("article_summary", case["claim"])
    return data


# /api/case-start와 화면 payload가 같은 요약을 사용하도록 교체합니다.
flow._public_case = _public_case_with_summary


def _render_index_v4():
    html = flow._render_index()

    # 학생이 바로 진짜/가짜를 찍기 전에 기사 자체가 무엇을 다루는지 읽을 수 있도록
    # 사례 카드 안에 중립적인 기사 요약을 먼저 제시합니다.
    old = '<div class="chat-case-claim"><b>당시 퍼진 주장·상황</b>${esc(c.claim)}</div>'
    new = (
        '<div class="chat-case-summary"><b>기사 내용 요약</b>${esc(c.article_summary||c.claim)}</div>'
        '<div class="chat-case-claim"><b>판단할 주장·상황</b>${esc(c.claim)}</div>'
    )
    html = html.replace(old, new)

    css_old = '.chat-case-claim{padding:12px 14px;font-size:12px;line-height:1.58;color:var(--body);border-top:1px solid var(--line)}.chat-case-claim b{display:block;color:var(--ink);font-size:10px;margin-bottom:4px}'
    css_new = (
        '.chat-case-summary{padding:12px 14px;font-size:12px;line-height:1.62;color:var(--body);border-top:1px solid var(--line);background:#faf8f4}'
        '.chat-case-summary b{display:block;color:var(--ink);font-size:10px;margin-bottom:5px}'
        '.chat-case-claim{padding:12px 14px;font-size:12px;line-height:1.58;color:var(--body);border-top:1px solid var(--line)}'
        '.chat-case-claim b{display:block;color:var(--ink);font-size:10px;margin-bottom:4px}'
    )
    html = html.replace(css_old, css_new)

    html = html.replace(
        '사례를 선택하면 사진·기사·문서와 당시 주장을 보여주고 AI가 바로 첫 질문을 합니다.',
        '사례를 선택하면 사진·기사·문서와 기사 내용 요약, 판단할 주장을 먼저 보여주고 AI가 바로 첫 질문을 합니다.',
    )
    return html


# 이전 버전의 루트 화면만 제거하고 요약 보강 화면으로 다시 등록합니다.
flow.base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def inline_case_index_v4():
    return HTMLResponse(_render_index_v4())
