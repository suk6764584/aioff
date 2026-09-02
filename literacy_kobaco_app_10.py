from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

import literacy_kobaco_app_9 as previous

# v9의 1:1 공익광고 매칭/캐시 정책은 유지합니다.
# v10은 학생 화면에서 주제 클릭 이벤트를 하나로 통합하고,
# KOBACO 학습 대화는 외부 모델 호출 없이 즉시 응답하도록 정리합니다.
app = previous.app
base = previous.base
flow = previous.flow
v5 = previous.v5
v6 = previous.v6
v4 = previous.v4


# ---------------------------------------------------------------------------
# 1) 주제별 사례를 현재 CASE_LIBRARY에서 직접 직렬화
#    이전 스크립트의 중복 click listener / stale sample 상태에 의존하지 않습니다.
# ---------------------------------------------------------------------------
def _topic_payload() -> dict[str, list[dict[str, Any]]]:
    payload: dict[str, list[dict[str, Any]]] = {}
    for lesson_id in ("news", "deepfake", "ai"):
        items = []
        for case in flow.CASE_LIBRARY.get(lesson_id, []):
            try:
                items.append(flow._public_case(case))
            except Exception:
                items.append({
                    "id": case.get("id", ""),
                    "label": case.get("label", ""),
                    "title": case.get("title", ""),
                    "source_name": case.get("source_name", ""),
                    "source_url": case.get("source_url", ""),
                    "data_rows": case.get("data_rows", []),
                    "db_tables": case.get("db_tables", []),
                    "data_note": case.get("data_note", ""),
                })
        payload[lesson_id] = items
    return payload


# ---------------------------------------------------------------------------
# 2) 학습 채팅: 이 3개 KOBACO 모듈은 DB 값과 정해진 학습 순서로 즉시 응답
#    모델은 AI OFF 분석/문제 생성 단계에서 계속 사용합니다.
# ---------------------------------------------------------------------------
def _rows(case: dict[str, Any]) -> dict[str, str]:
    return {
        str(row.get("label") or "").strip(): str(row.get("value") or "").strip()
        for row in (case.get("data_rows") or [])
    }


def _student_turns(session_id: str) -> int:
    return sum(1 for m in base.core.messages(session_id, 30) if m["role"] == "user")


def _short(text: str, limit: int = 55) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _lesson_reply(case_id: str, case: dict[str, Any], turn: int, answer: str) -> str:
    rows = _rows(case)
    answer = _short(answer)

    if case_id.startswith("kobaco_publicad_"):
        impact = rows.get("임팩트 1위", "-")
        trust = rows.get("신뢰성", "-")
        channel = rows.get("주요 인지경로", "-")
        if turn == 0:
            return f"내 생각: {answer}\nKOBACO 조사에서는 {impact}가 가장 강한 인상을 준 요소로 나타났어요.\n내가 기억한 부분과 조사 결과가 같은지 비교해보세요."
        if turn == 1:
            return f"신뢰성 항목은 {trust}예요. 여기서는 광고를 믿을 만하다고 느낀 정도를 살펴봅니다.\n이 숫자는 행동이 바뀐 사람의 비율을 뜻하지 않아요."
        if turn == 2:
            return f"광고를 접한 경로 중 가장 높은 값은 {channel}예요.\n이 수치는 어디에서 광고를 접했는지를 보여주며, 광고의 좋고 나쁨을 매긴 점수는 아니에요."
        return "정리해볼게요. 광고 조사 숫자는 각각 묻는 내용이 달라요.\n숫자를 볼 때는 먼저 ‘무엇을 물어본 값인지’를 확인하면 됩니다."

    if case_id.startswith("kobaco_aisac_"):
        keywords = rows.get("키워드", "-")
        advertiser = rows.get("광고주", "-")
        counts = rows.get("인식 횟수", "-")
        if turn == 0:
            return f"AiSAC이 찾아낸 키워드는 {keywords}예요.\n이 키워드는 AI가 화면에서 찾은 요소이지, 광고의 뜻 자체는 아니에요."
        if turn == 1:
            return f"DB에는 광고주가 {advertiser}, AI 인식 횟수는 {counts}로 기록돼 있어요.\n이 값은 자료에 적힌 사실이고, 광고의 의도는 원본을 더 봐야 판단할 수 있어요."
        if turn == 2:
            return "AI가 찾은 사물·장소·키워드와 사람이 이해하는 광고의 뜻은 구분해서 봐야 해요.\nAI 인식값은 단서로 쓰고, 중요한 해석은 원본과 비교합니다."
        return "이 수업의 핵심은 간단해요. AI가 찾은 요소와 광고의 뜻을 같은 것으로 보지 않는 것입니다."

    if case_id.startswith("kobaco_ott_"):
        group = rows.get("연도·집단", str(case.get("title") or "-"))
        top = rows.get("이용비율 상위", "-")
        sample = rows.get("사례수", "-")
        nonuse = rows.get("OTT 비이용", "-")
        if turn == 0:
            return f"{group}의 이용 비율 상위 값은 {top}예요.\n여기서 보는 것은 ‘이용 비율’이며, ‘가장 좋아하는 서비스’를 묻는 선호도와는 달라요."
        if turn == 1:
            return f"이 표의 사례수는 {sample}, OTT 비이용은 {nonuse}예요.\n통계를 읽을 때는 숫자와 함께 누구를 조사했는지도 확인합니다."
        if turn == 2:
            return "이용률은 얼마나 이용했는지를 보여주는 값이에요.\n그래서 이 표만 보고 ‘가장 좋아하는 OTT’라고 바꾸어 말하면 안 됩니다."
        return "정리하면 이용률과 선호도는 다른 말이에요.\n표에 적힌 항목 이름 그대로 읽는 것이 가장 안전합니다."

    return "자료를 다시 선택해 주세요."


base._remove_route("/api/chat-stream", "POST")


@app.post("/api/chat-stream")
def kobaco_instant_chat_stream(req: base.LiteracyChatRequest):
    sid = req.session_id or str(base.core.uuid.uuid4())
    lesson_id = req.lesson_id if req.lesson_id in base.LESSONS else base._get_lesson_id(sid)
    if lesson_id not in base.LESSONS:
        raise HTTPException(400, "먼저 학습 주제를 선택해 주세요.")

    base._save_lesson(sid, lesson_id)
    case_id = flow._get_case_id(sid)
    found = flow.CASE_BY_ID.get(case_id) if case_id else None
    if not found:
        raise HTTPException(400, "먼저 사례를 선택해 주세요.")
    found_lesson, case = found
    if found_lesson != lesson_id:
        raise HTTPException(400, "선택한 주제와 사례가 맞지 않습니다. 사례를 다시 선택해 주세요.")

    turn = _student_turns(sid)
    reply = _lesson_reply(case_id, case, turn, req.message)
    base.core.save_chat_exchange(sid, req.message, reply)

    def immediate():
        yield reply

    return StreamingResponse(
        immediate(),
        media_type="text/plain; charset=utf-8",
        headers={"X-Session-Id": sid, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 3) 루트 화면: v5의 기본 화면을 사용해 최근 강제 글꼴/볼드 CSS는 제외하고,
#    마지막 스크립트에서 기존 lesson-card 노드를 복제해 중복 listener를 제거합니다.
# ---------------------------------------------------------------------------
def _render_index_kobaco_v10():
    page = v5._render_index_kobaco_v5()
    topic_json = json.dumps(_topic_payload(), ensure_ascii=False).replace("</", "<\\/")

    # 학생 화면에 필요 없는 개발/반복 문구만 간단히 정리합니다.
    replacements = {
        "실제 KOBACO 데이터에서 바로 시작합니다.": "실제 KOBACO 자료로 배워요.",
        "주제를 고르면 KOBACO Parquet DB에서 구성한 실제 데이터 사례가 무작위로 나타납니다.": "주제를 고르면 실제 자료 사례 3개가 나타납니다.",
        "사례를 선택하면 사진·기사·문서와 DB 조회값, 판단할 주장을 보여주고 AI가 바로 첫 질문을 합니다.": "사례를 선택하고 자료를 살펴본 뒤 질문에 답해보세요.",
        "아직 조사 수치를 보지 않습니다. 썸네일 또는 광고 영상을 보고 핵심 메시지와 기억에 남는 장면·문구·표현을 먼저 내 말로 설명해보세요.": "",
        "실제 조사 결과는 첫 답변을 보낸 뒤 열립니다. 먼저 광고 자체를 읽어야 내 판단과 조사 결과를 비교할 수 있습니다.": "",
        "광고를 먼저 보고 내 판단 만들기": "광고 보기",
        "DB 조회값": "자료 값",
        "판단할 해석·상황": "생각해 볼 점",
    }
    for old, new in replacements.items():
        page = page.replace(old, new)

    script = f'''
<script>
const fixedTopicCases={topic_json};
const fixedSamples={{}};

function fixedShuffle(items){{
  const a=[...items];
  for(let i=a.length-1;i>0;i--){{const j=Math.floor(Math.random()*(i+1));[a[i],a[j]]=[a[j],a[i]];}}
  return a;
}}
function fixedSample(lessonId){{
  fixedSamples[lessonId]=fixedShuffle(fixedTopicCases[lessonId]||[]).slice(0,3);
  return fixedSamples[lessonId];
}}
function fixedPickerHtml(lessonId,activeId=null){{
  const cases=fixedSamples[lessonId]||fixedSample(lessonId);
  const total=(fixedTopicCases[lessonId]||[]).length;
  if(!total)return `<div class="chat-case-picker"><div class="chat-case-picker-head"><div><strong>이 주제의 사례를 불러오지 못했습니다.</strong><br><span>다른 주제를 선택하거나 새로고침해 주세요.</span></div></div></div>`;
  return `<div class="chat-case-picker"><div class="chat-case-picker-head"><div><strong>사례를 골라보세요</strong><br><span>전체 ${{total}}개 중 3개를 보여줍니다.</span></div><button type="button" class="chat-case-shuffle" data-shuffle-cases>다른 사례 보기</button></div><div class="chat-case-options">${{cases.map((c,i)=>`<button type="button" class="chat-case-option ${{c.id===activeId?'active':''}}" data-case-id="${{c.id}}">${{typeof kobacoPickerPreview==='function'?kobacoPickerPreview(c):''}}<b>${{i+1}}. ${{esc(compactTitle(c.title))}}</b><small>${{esc(c.label||'')}}</small></button>`).join('')}}</div></div>`;
}}
function pickerHtml(lessonId,activeId=null){{return fixedPickerHtml(lessonId,activeId);}}
function showCaseChooser(lessonId){{
  selectedLesson=lessonId;inlineLessonId=lessonId;inlineCaseId=null;sessionId=null;resetInlineState();
  fixedSample(lessonId);
  chat.innerHTML=fixedPickerHtml(lessonId);
  bindCaseButtons(lessonId);
  const shuffle=chat.querySelector('[data-shuffle-cases]');
  if(shuffle)shuffle.addEventListener('click',()=>{{fixedSample(lessonId);chat.innerHTML=fixedPickerHtml(lessonId);bindCaseButtons(lessonId);showCaseShuffleButton(lessonId);}});
  input.placeholder='위에서 사례를 먼저 선택해 주세요.';
  stageText.textContent='사례를 선택하세요';
  chat.scrollTop=0;
}}
function showCaseShuffleButton(lessonId){{
  const shuffle=chat.querySelector('[data-shuffle-cases]');
  if(shuffle)shuffle.addEventListener('click',()=>{{fixedSample(lessonId);chat.innerHTML=fixedPickerHtml(lessonId);bindCaseButtons(lessonId);showCaseShuffleButton(lessonId);}});
}}

// 앞 버전들이 lesson-card에 붙인 여러 click listener를 제거합니다.
const oldCards=[...document.querySelectorAll('.lesson-card')];
oldCards.forEach(old=>{{
  const card=old.cloneNode(true);
  old.replaceWith(card);
  card.addEventListener('click',()=>{{
    selectedLesson=card.dataset.lesson;
    document.querySelectorAll('.lesson-card').forEach(x=>x.classList.toggle('selected',x===card));
    const d=(typeof lessonData!=='undefined'&&lessonData[selectedLesson])?lessonData[selectedLesson]:null;
    if(d){{
      const line=document.getElementById('lessonLine');if(line)line.textContent=`${{d.title}} 사례를 살펴봅니다.`;
      const detail=document.getElementById('lessonDetail');if(detail)detail.classList.remove('show');
    }}
    showCaseChooser(selectedLesson);
  }});
}});
</script>
'''
    page = page.replace("</body>", script + "\n</body>")
    return page


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v10():
    return HTMLResponse(_render_index_kobaco_v10())
