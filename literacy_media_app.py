from fastapi.responses import HTMLResponse
import json

import literacy_app as base

app = base.app

# -----------------------------------------------------------------------------
# 실제 사례 기반 학습 자료
# - 기존 app.py / AI OFF 분석·문항·재채점 구조는 그대로 사용합니다.
# - 이 파일은 리터러시 학습 앞단에 실제 사례 미디어와 대화형 질문 흐름만 추가합니다.
# -----------------------------------------------------------------------------

REAL_CASES = {
    "news": {
        "case_label": "실제 팩트체크 사례",
        "case_title": "‘코로나 이동제한 항의 광화문 집회’로 퍼진 영상",
        "claim": "2020년 9월 유럽 SNS에서 한국 시민들이 코로나19 이동제한 조치에 항의해 서울 광화문에 모였다는 설명과 함께 집회 영상이 공유됐습니다.",
        "case_source_name": "한국언론진흥재단 기사 · AFP 한국 시위 영상 팩트체크 사례",
        "case_source_url": "https://www.kpf.or.kr/front/news/articleDetail/592620.do",
        "resolution": "한국언론진흥재단이 소개한 AFP 팩트체크에 따르면 해당 영상은 2020년 코로나19 항의 영상이 아니라 2019년 10월 3일 촬영된 다른 집회 영상이었습니다. 팩트체커는 이미지 검증, 영상 속 광화문글판 문구와 게시 기간 같은 단서를 교차 확인했습니다.",
        "clues": [
            "게시된 날짜와 실제 촬영 날짜가 같은지 확인",
            "영상의 이전 게시물·원본을 역이미지·영상 검색으로 추적",
            "간판·현수막·광고판 등 촬영 시점을 추정할 단서 확인",
            "독립된 보도와 1차 자료로 교차검증",
        ],
        "starter": "화면에 나온 실제 팩트체크 사례로 학습을 시작해줘. 정답은 바로 말하지 말고, 내가 먼저 판단할 수 있게 첫 질문 하나만 해줘.",
        "media_type": "image",
        "media_url": "https://upload.wikimedia.org/wikipedia/commons/f/f7/Taegukgirally_in_2019.png",
        "media_caption": "관련 2019년 집회 참고 이미지 · 문제의 원본 영상과 동일 장면은 아닙니다. 이미지: 남혜경박사TV / Wikimedia Commons / CC BY 3.0",
    },
    "deepfake": {
        "case_label": "실제 보도 사례",
        "case_title": "학교 현장에서 확인된 딥페이크 피해와 대응",
        "claim": "2024년 8월 YTN은 교육부가 파악한 학생·교원 딥페이크 피해 현황과 교육부 전담팀 구성을 보도했습니다. 학습에서는 피해 영상 자체가 아니라, 딥페이크 의심 콘텐츠를 접했을 때 어떤 근거와 출처를 확인해야 하는지 다룹니다.",
        "case_source_name": "YTN 자막뉴스 · 딥페이크 범죄 학생 피해 보도",
        "case_source_url": "https://www.youtube.com/watch?v=rHbZsEOgESY",
        "resolution": "이 모듈의 목적은 특정 영상의 합성 여부를 외형만 보고 맞히는 것이 아닙니다. 게시 계정, 최초 출처, 원본·전체 맥락, 공식 채널, 다른 신뢰할 만한 자료를 확인하고 근거가 부족하면 판단과 재공유를 보류하는 절차를 연습합니다.",
        "clues": [
            "영상을 올린 계정과 최초 게시 출처 확인",
            "원본 영상·전체 맥락 존재 여부 확인",
            "공식 계정·보도·기관 자료와 교차검증",
            "입모양이나 화질 같은 외형 단서 하나만으로 확정하지 않기",
            "확인 전 재공유·확산 보류",
        ],
        "starter": "화면의 실제 딥페이크 관련 보도를 바탕으로 학습을 시작해줘. 피해 내용을 자세히 묘사하지 말고, 의심 콘텐츠를 검증하는 방법을 내가 먼저 생각하도록 첫 질문 하나만 해줘.",
        "media_type": "youtube",
        "media_url": "https://www.youtube.com/embed/rHbZsEOgESY",
        "media_caption": "YTN 2024-08-28 보도 · 외부 YouTube 영상 임베드",
    },
    "ai": {
        "case_label": "실제 법원 사례",
        "case_title": "AI가 만든 ‘존재하지 않는 판례’를 그대로 인용한 문서",
        "claim": "미국 뉴욕남부연방법원의 2024년 의견서에는 법원 제출 문서에 존재하지 않는 판례 3건이 인용된 문제가 다뤄졌고, 법원은 생성형 AI가 만든 가짜 판례를 검증하지 않은 기존 사례도 언급했습니다.",
        "case_source_name": "U.S. District Court, Southern District of New York · 2024 Opinion",
        "case_source_url": "https://www.nysd.uscourts.gov/sites/default/files/2024-03/18cr602%20Cohen%20Opinion.pdf",
        "resolution": "실제 법원 문서에서도 존재하지 않는 판례 인용이 문제 된 사례가 확인됩니다. AI가 법률·통계·논문·출처를 제시했을 때는 출처가 실제 존재하는지, 원문에 같은 내용이 있는지, 인용이 주장을 실제로 뒷받침하는지를 사람이 다시 확인해야 합니다.",
        "clues": [
            "AI가 제시한 문헌·판례·통계 출처가 실제 존재하는지 확인",
            "제목·기관명만 보지 않고 원문을 직접 열어 확인",
            "원문 내용이 AI의 주장과 실제로 일치하는지 확인",
            "날짜·표본·조건·문맥이 생략되지 않았는지 확인",
            "중요한 판단은 독립된 다른 자료와 교차검증",
        ],
        "starter": "화면의 실제 AI 출처 오류 사례로 학습을 시작해줘. 결론부터 설명하지 말고, AI가 출처를 제시했을 때 내가 무엇부터 확인해야 하는지 첫 질문 하나만 해줘.",
        "media_type": "document",
        "media_url": "https://www.nysd.uscourts.gov/sites/default/files/2024-03/18cr602%20Cohen%20Opinion.pdf#page=9",
        "media_caption": "미국 뉴욕남부연방법원 2024년 의견서 · 실제 법원 문서",
    },
}

# 기존 정적 큐레이션 판단 기준은 유지하되, 첫 학습 사례와 출처를 실제 사례로 교체합니다.
base.LESSONS["news"].update({
    "source_name": "한국언론진흥재단 · AFP 한국 시위 영상 팩트체크 사례",
    "source_url": REAL_CASES["news"]["case_source_url"],
    "source_role": "실제 사례·판단 기준 참고",
    "source_note": "2020년 코로나19 이동제한 항의 영상으로 공유된 한국 집회 영상이 실제로는 2019년 10월 3일 촬영된 다른 집회 영상이었음을 이미지 검증과 현장 단서로 확인한 사례입니다.",
    "starter": REAL_CASES["news"]["starter"],
})
base.LESSONS["deepfake"].update({
    "starter": REAL_CASES["deepfake"]["starter"],
})
base.LESSONS["ai"].update({
    "source_name": "NIA 디지털정보격차 보고서 + 미국 뉴욕남부연방법원 실제 AI 출처 오류 사례",
    "source_role": "AI 정보 검증 배경·실제 사례 참고",
    "source_note": "AI 서비스 이용 맥락을 다룬 NIA 자료와, 존재하지 않는 판례 인용이 실제 법원 문서에서 문제가 된 사례를 함께 참고합니다. 특정 수치를 AI OFF 정답으로 사용하지 않습니다.",
    "starter": REAL_CASES["ai"]["starter"],
})


def _actual_lesson_prompt(session_id: str, user_message: str, lesson_id: str):
    lesson = base.LESSONS[lesson_id]
    case = REAL_CASES[lesson_id]
    prior = base.core.messages(session_id, 12)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '튜터'}: {m['content']}"
        for m in prior
    )
    prior_user_turns = sum(1 for m in prior if m["role"] == "user")
    criteria = "\n".join(f"- {x}" for x in lesson["criteria"])
    clues = "\n".join(f"- {x}" for x in case["clues"])

    # 첫 두 학생 응답 전에는 사례의 최종 검증 결과를 모델에 주지 않아 정답 선공개를 막습니다.
    if prior_user_turns < 2:
        resolution_block = "[최종 검증 결과]\n아직 공개하지 않는다. 학생이 먼저 확인 기준과 이유를 말하도록 질문한다."
    else:
        resolution_block = f"[최종 검증 결과 - 학생이 충분히 시도한 뒤에만 설명 가능]\n{case['resolution']}"

    safety = lesson.get("safety_note") or ""
    return f"""너는 중·고등학생을 위한 디지털 리터러시 튜터다.
이번 학습 주제는 '{lesson['title']}'이고, 화면에는 실제 사례 미디어가 이미 제시되어 있다.

[화면에 제시된 실제 사례]
사례명: {case['case_title']}
학생에게 보이는 주장/상황: {case['claim']}
사례 출처: {case['case_source_name']}

[이번 학습의 정적 판단 기준]
{criteria}

[사례를 검증할 때 사용할 수 있는 단서]
{clues}

{resolution_block}

대화 규칙:
1. 강의부터 하지 말고 학생이 화면의 사례를 보고 먼저 판단하게 한다.
2. 한 번의 답변에서는 질문을 하나만 한다. 학생 답변 → 짧은 피드백 → 다음 질문 순서로 이어간다.
3. 첫 질문은 '진짜인가요/가짜인가요?'보다 '무엇을 먼저 확인할까요?'처럼 검증 행동을 묻는다.
4. 학생이 말한 기준이 적절하면 인정하고, 빠진 기준 하나만 다음 질문으로 이어간다.
5. 출처·원문·게시 시점·근거·교차검증·불확실성을 실제 사례에 적용하게 한다.
6. 최종 검증 결과는 학생이 최소 두 번 이상 자신의 판단 기준을 말하기 전에는 공개하지 않는다.
7. 실제 사례에 없는 사실·인물·수치·출처를 새로 만들어내지 않는다.
8. 실시간 웹검색이나 RAG를 수행했다고 말하지 않는다. 화면에 적힌 사례 정보와 정적 기준만 사용한다.
9. 학생이 충분히 판단한 뒤에는 실제 사례의 검증 결과와 사용된 단서를 짧게 정리한다.
10. AI OFF 단계에서는 별도로 문제 3개가 생성되므로, 대화 중 시험문제 3개를 미리 만들지 않는다.
11. 학생의 장기적인 능력이나 성향을 평가하지 않는다.
12. 한국어로 자연스럽고 짧게 답한다.
{('13. ' + safety) if safety else ''}

[이전 대화]
{history or '(없음)'}

[학생의 새 메시지]
{user_message}"""


# literacy_app에 이미 등록된 chat route가 실행 시 이 함수를 참조하도록 교체합니다.
base._lesson_chat_prompt = _actual_lesson_prompt


def _case_payload():
    return {
        lesson_id: {
            "case_label": case["case_label"],
            "case_title": case["case_title"],
            "claim": case["claim"],
            "case_source_name": case["case_source_name"],
            "case_source_url": case["case_source_url"],
            "starter": case["starter"],
            "media_type": case["media_type"],
            "media_url": case["media_url"],
            "media_caption": case["media_caption"],
        }
        for lesson_id, case in REAL_CASES.items()
    }


def _render_media_index():
    html = base._render_index()
    case_json = json.dumps(_case_payload(), ensure_ascii=False).replace("</", "<\\/")

    extra_css = r"""
.case-panel{background:var(--paper);border:1px solid var(--line);border-radius:10px;margin:0 0 28px;overflow:hidden}
.case-panel.hidden{display:none}.case-head{padding:20px 24px 15px;border-bottom:1px solid var(--line);display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.case-kicker{font-size:11px;font-weight:900;color:var(--orange);margin-bottom:5px}.case-head h2{margin:0;font-size:21px;letter-spacing:-.5px}.case-head p{margin:6px 0 0;font-size:12px;color:var(--body);line-height:1.55}.case-source{border:1px solid var(--line-strong);background:#fff;color:var(--body);border-radius:8px;padding:8px 10px;text-decoration:none;font-size:11px;font-weight:800;white-space:nowrap}.case-body{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(290px,.85fr);gap:0}.case-media{min-height:330px;background:#ebe7df;border-right:1px solid var(--line);display:flex;align-items:center;justify-content:center;overflow:hidden}.case-media img{width:100%;height:330px;object-fit:cover;display:block}.case-media iframe{width:100%;height:330px;border:0;display:block}.case-doc{width:88%;max-width:560px;background:#fff;border:1px solid #d6d1c9;box-shadow:0 12px 28px rgba(32,28,24,.08);padding:27px 30px}.case-doc small{display:block;color:var(--muted);font-size:10px;font-weight:800;margin-bottom:16px}.case-doc .doc-rule{height:2px;background:var(--ink);margin-bottom:20px}.case-doc strong{display:block;font-size:22px;line-height:1.35;margin-bottom:14px}.case-doc p{font-size:12px;line-height:1.65;color:var(--body);margin:0}.case-info{padding:22px 24px}.case-claim-label{font-size:10px;font-weight:900;color:var(--muted);letter-spacing:.2px;margin-bottom:6px}.case-claim{font-size:14px;line-height:1.65;color:var(--ink);margin:0 0 18px}.case-question{border-left:3px solid var(--orange);background:#fff7ed;padding:11px 13px;font-size:12px;line-height:1.55;color:var(--body);margin-bottom:15px}.case-start{width:100%;border:0;background:var(--ink);color:#fff;border-radius:9px;padding:12px 14px;font-weight:850}.media-caption{padding:8px 12px;background:#fff;font-size:10px;line-height:1.45;color:var(--muted);border-top:1px solid var(--line)}.case-media-wrap{width:100%;align-self:stretch;display:flex;flex-direction:column;justify-content:center}.case-media-wrap .case-media{border-right:0;flex:1}.case-media-side{border-right:1px solid var(--line)}
@media(max-width:850px){.case-body{grid-template-columns:1fr}.case-media-side{border-right:0;border-bottom:1px solid var(--line)}.case-head{flex-direction:column}.case-source{white-space:normal}.case-media,.case-media img,.case-media iframe{height:280px;min-height:280px}}
"""
    html = html.replace("</style>", extra_css + "\n</style>")

    panel = """
  <section id="realCasePanel" class="case-panel hidden">
    <div class="case-head">
      <div><div id="caseKicker" class="case-kicker">실제 사례</div><h2 id="caseTitle"></h2><p id="caseSourceName"></p></div>
      <a id="caseSourceLink" class="case-source" href="#" target="_blank" rel="noopener">원문 확인 ↗</a>
    </div>
    <div class="case-body">
      <div class="case-media-side"><div id="caseMediaWrap" class="case-media-wrap"></div></div>
      <div class="case-info">
        <div class="case-claim-label">당시 퍼진 주장·상황</div>
        <p id="caseClaim" class="case-claim"></p>
        <div class="case-question"><b>먼저 내가 판단합니다.</b><br>정답이나 해설은 바로 보여주지 않습니다. 미디어를 보고 무엇을 확인해야 하는지 먼저 생각한 뒤 AI와 질문을 이어갑니다.</div>
        <button id="startRealCase" type="button" class="case-start">이 사례로 AI 학습 시작 →</button>
      </div>
    </div>
  </section>
"""
    html = html.replace('<div class="workspace">', panel + '\n  <div class="workspace">')

    script = f"""
<script>
const realCaseData={case_json};
let currentCaseId=null;
function renderRealCase(lessonId){{
  const c=realCaseData[lessonId];if(!c)return;
  currentCaseId=lessonId;
  const panel=document.getElementById('realCasePanel');
  document.getElementById('caseKicker').textContent=c.case_label;
  document.getElementById('caseTitle').textContent=c.case_title;
  document.getElementById('caseSourceName').textContent='사례 출처 · '+c.case_source_name;
  const sourceLink=document.getElementById('caseSourceLink');sourceLink.href=c.case_source_url;
  document.getElementById('caseClaim').textContent=c.claim;
  const wrap=document.getElementById('caseMediaWrap');
  let media='';
  if(c.media_type==='image'){{
    media=`<div class="case-media"><img src="${{c.media_url}}" alt="${{c.case_title}} 관련 참고 이미지"></div>`;
  }}else if(c.media_type==='youtube'){{
    media=`<div class="case-media"><iframe src="${{c.media_url}}" title="${{c.case_title}}" loading="lazy" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe></div>`;
  }}else{{
    media=`<div class="case-media"><div class="case-doc"><small>U.S. DISTRICT COURT · ACTUAL CASE</small><div class="doc-rule"></div><strong>존재하지 않는 판례 3건이<br>법원 제출 문서에 인용됨</strong><p>AI가 제시한 출처를 실제 원문과 대조하지 않으면 어떤 문제가 생길 수 있는지 살펴보는 실제 사례입니다.</p></div></div>`;
  }}
  wrap.innerHTML=media+`<div class="media-caption">${{c.media_caption}}</div>`;
  panel.classList.remove('hidden');
  setTimeout(()=>panel.scrollIntoView({{behavior:'smooth',block:'start'}}),80);
}}

document.querySelectorAll('.lesson-card').forEach(card=>{{
  card.addEventListener('click',()=>renderRealCase(card.dataset.lesson));
}});

document.getElementById('startRealCase').addEventListener('click',()=>{{
  if(!currentCaseId)return;
  const c=realCaseData[currentCaseId];
  input.value=c.starter;
  input.placeholder='사례를 보고 떠오른 판단이나 질문을 적어보세요.';
  send.click();
  document.querySelector('.study-paper')?.scrollIntoView({{behavior:'smooth',block:'start'}});
}});
</script>
"""
    html = html.replace("</body>", script + "\n</body>")
    return html


# literacy_app이 등록한 루트 화면만 교체합니다. 채팅/분석/AI OFF/재채점 API는 그대로 재사용합니다.
base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def media_literacy_index():
    return HTMLResponse(_render_media_index())
