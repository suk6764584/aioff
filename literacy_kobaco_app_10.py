from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

import literacy_kobaco_app_9 as previous

# v9까지의 KOBACO DB/공익광고 1:1 매칭/AI OFF 흐름은 유지합니다.
# v10은 세 주제의 화면 진입을 하나로 통합하고,
# 학습 대화는 실제 KOBACO 값을 근거로 Gemini/Groq가 학생 답변에 맞춰 설명합니다.
app = previous.app
base = previous.base
flow = previous.flow
v5 = previous.v5
v6 = previous.v6
v4 = previous.v4


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
                    "claim": case.get("claim", ""),
                    "source_name": case.get("source_name", ""),
                    "source_url": case.get("source_url", ""),
                    "source_excerpt": case.get("source_excerpt", ""),
                    "media_type": case.get("media_type", ""),
                    "media_url": case.get("media_url", ""),
                    "media_caption": case.get("media_caption", ""),
                    "data_rows": case.get("data_rows", []),
                    "db_tables": case.get("db_tables", []),
                    "data_note": case.get("data_note", ""),
                })
        payload[lesson_id] = items
    return payload


def _rows(case: dict[str, Any]) -> dict[str, str]:
    return {
        str(row.get("label") or "").strip(): str(row.get("value") or "").strip()
        for row in (case.get("data_rows") or [])
    }


def _student_turns(session_id: str) -> int:
    return sum(1 for m in base.core.messages(session_id, 30) if m["role"] == "user")


def _case_kind(case_id: str) -> str:
    if case_id.startswith("kobaco_aisac_"):
        return "aisac"
    if case_id.startswith("kobaco_publicad_"):
        return "publicad"
    if case_id.startswith("kobaco_ott_"):
        return "ott"
    return "unknown"


def _learning_prompt(
    session_id: str,
    user_message: str,
    lesson_id: str,
    case_id: str,
    case: dict[str, Any],
) -> str:
    lesson = base.LESSONS[lesson_id]
    prior = base.core.messages(session_id, 24)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '학습도우미'}: {m['content']}"
        for m in prior
    )
    turn = _student_turns(session_id)
    rows = _rows(case)
    db_values = "\n".join(
        f"- {label}: {value}" for label, value in rows.items()
    ) or "- 표시된 DB 값 없음"
    criteria = "\n".join(f"- {x}" for x in lesson.get("criteria", []))
    kind = _case_kind(case_id)

    if kind == "publicad":
        stage = f'''
[이 사례에서 가르칠 핵심]
학생은 실제 공익광고를 본 뒤 자신의 해석을 적고, 그 다음 KOBACO 효과평가 값을 비교한다.
학생이 적은 광고 해석과 조사 결과는 같은 종류의 정보가 아니다.

현재 학생 답변 횟수: {turn}

진행 규칙:
- 첫 답변(turn=0)에서는 학생이 광고에서 무엇을 느꼈는지와 그 근거 장면·문구를 먼저 다룬다.
- 학생이 '차별이 느껴진다', '희망적이다'처럼 해석을 말하면 그것을 KOBACO가 입증한 사실처럼 바꾸지 않는다.
- 첫 답변부터 퍼센트 숫자를 정답처럼 던지지 않는다. 필요하면 "조사 자료도 뒤에서 비교한다"고만 안내해도 된다.
- 조사값을 소개할 때는 반드시 항목 이름과 뜻을 먼저 설명한 뒤 전체 값을 함께 제시한다.
- '신뢰성', '광고를 접한 경로', '가장 강한 인상을 준 요소'는 서로 다른 질문의 값이다.
- 신뢰성 수치를 행동 변화 비율로, 인지경로 수치를 광고의 좋고 나쁨으로 바꾸어 설명하지 않는다.
- 2~3회 대화 후에는 학생이 '자료가 직접 말하는 사실'과 '내 해석'을 한 문장씩 구분해보게 한다.
- 이미 같은 판단 기준을 충분히 다뤘다면 반복 질문보다 핵심을 정리하고 AI OFF로 넘어갈 준비를 시킨다.
'''
    elif kind == "aisac":
        stage = f'''
[이 사례에서 가르칠 핵심]
AiSAC이 기록한 사물·장소·키워드는 AI가 광고 화면에서 인식한 관찰값이다.
그 값만으로 광고의 의도·메시지·감정까지 확정하면 안 된다.

현재 학생 답변 횟수: {turn}

진행 규칙:
- 학생 답변을 먼저 읽고, 학생이 말한 내용 중 'DB로 확인되는 것'과 '사람의 해석'을 구분한다.
- 키워드·광고주·인식 횟수를 한꺼번에 나열하지 말고, 학생 답에 필요한 값만 골라 설명한다.
- AI가 인식한 키워드와 사람이 광고에서 이해한 메시지가 왜 다를 수 있는지 구체적으로 설명한다.
- 중요한 해석은 원본 영상·문구·전체 맥락을 추가로 확인해야 한다는 기준을 실제 상황에 적용시킨다.
- 2~3회 대화 후에는 다른 광고에도 적용할 수 있는 'AI 인식값 ≠ 의미 확정' 기준을 학생 말로 정리하게 한다.
'''
    elif kind == "ott":
        stage = f'''
[이 사례에서 가르칠 핵심]
표는 특정 연도·연령집단의 OTT '이용 비율'을 보여준다.
이용 비율을 선호도·만족도·전체 청소년의 보편적 성향으로 바꾸어 말하지 않는 법을 가르친다.

현재 학생 답변 횟수: {turn}

진행 규칙:
- 학생이 표에서 읽은 결론을 먼저 확인하고, '이용률'과 '선호도'를 구분한다.
- 수치를 소개할 때는 연도·집단·사례수 등 조건과 함께 말한다.
- 학생이 '가장 좋아한다'처럼 표에 없는 개념으로 확대하면 왜 근거가 부족한지 설명한다.
- 표에서 직접 말할 수 있는 문장 하나와 추가 확인이 필요한 문장 하나를 구분하게 한다.
- 2~3회 대화 후에는 조사 조건을 확인하는 이유와 과잉 일반화를 피하는 기준을 정리한다.
'''
    else:
        stage = '''
[이 사례에서 가르칠 핵심]
제공된 사례와 DB 값만 사용해 학생의 판단 근거를 확인하고, 사실과 해석을 구분하게 한다.
'''

    return f'''너는 초등 고학년~중학생이 실제 자료를 읽으며 생각하는 법을 배우도록 돕는 AI 학습도우미다.
목표는 숫자나 정답을 대신 말해주는 것이 아니라, 학생 답변을 읽고 근거를 짚어주며 다음에도 쓸 수 있는 판단 방법을 가르치는 것이다.

[학습 주제]
{lesson.get('title', lesson_id)}

[현재 사례]
사례명: {case.get('title', '-')}
자료 출처: {case.get('source_name', '-')}
사례 설명: {case.get('claim', '-')}
자료 발췌: {case.get('source_excerpt', '-')}

[화면에 표시된 실제 KOBACO 값]
{db_values}

[이번 수업의 판단 기준]
{criteria}

{stage}

[반드시 지킬 응답 규칙]
1. 학생이 방금 쓴 내용을 먼저 이해하고 그 답에 직접 반응한다. 미리 정한 문장을 순서대로 재생하지 않는다.
2. 한 답변은 보통 3~6문장으로 쓴다. 설명 없이 질문만 던지지 않는다.
3. 학생이 틀리거나 자료보다 넓게 단정하면 왜 그런지 바로 교정한다. 무조건 동의하지 않는다.
4. 학생이 '모르겠다'고 하면 질문을 반복하지 말고 먼저 확인 방법이나 읽는 방법을 2~3개 설명한다.
5. 어려운 통계 용어를 먼저 쓰지 않는다. 필요하면 쉬운 뜻을 먼저 말하고 괄호 안에 공식 항목명을 붙인다.
6. 숫자를 말할 때는 반드시 '무엇을 측정한 값인지'와 함께 말한다. 숫자만 단독으로 던지지 않는다.
7. 제공된 DB/사례에 없는 사실, 광고 의도, 조사 방법, 인과효과를 만들어내지 않는다.
8. 실시간 웹검색이나 RAG를 했다고 말하지 않는다.
9. 같은 질문이나 같은 기준을 표현만 바꿔 반복하지 않는다.
10. 마지막 질문은 필요할 때 하나만 한다. 충분히 배웠으면 질문 대신 학습 기준을 정리해도 된다.
11. AI OFF 최종 3문제는 지금 미리 출제하지 않는다.
12. 학생의 지능·성격·장기 능력을 평가하지 않는다.

[지금까지 대화]
{history or '(없음)'}

[학생의 새 답변]
{user_message}
'''


def _stream_model_reply(prompt: str, sid: str, user_message: str):
    emitted = False
    reply_parts: list[str] = []
    gemini_error: Exception | None = None

    try:
        client = base.core.gemini_client()
        stream = client.models.generate_content_stream(
            model=base.core.gemini_model(),
            contents=prompt,
        )
        for chunk in stream:
            text = getattr(chunk, "text", None) or ""
            if text:
                emitted = True
                reply_parts.append(text)
                yield text
        reply = "".join(reply_parts).strip()
        if not reply:
            raise ValueError("gemini_empty_response")
        base.core.save_chat_exchange(sid, user_message, reply)
        return
    except Exception as exc:
        gemini_error = exc
        if emitted:
            yield "\n\nAI 응답 전송이 중단되었습니다. 같은 답변을 다시 보내주세요."
            return

    if base.core.groq_configured():
        try:
            client = base.core.groq_client()
            stream = client.chat.completions.create(
                model=base.core.groq_model(),
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=700,
                temperature=0.25,
                stream=True,
            )
            reply_parts = []
            for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                text = getattr(delta, "content", None) or ""
                if text:
                    reply_parts.append(text)
                    yield text
            reply = "".join(reply_parts).strip()
            if not reply:
                raise ValueError("groq_empty_response")
            base.core.save_chat_exchange(sid, user_message, reply)
            return
        except Exception as groq_error:
            base.core.logger.warning(
                "Groq KOBACO learning fallback failed: %s",
                type(groq_error).__name__,
            )
            yield "AI 학습도우미 연결에 실패했습니다. 잠시 후 같은 답변을 다시 보내주세요."
            return

    base.core.logger.warning(
        "Gemini KOBACO learning failed: %s",
        type(gemini_error).__name__ if gemini_error else "UnknownError",
    )
    yield "AI 학습도우미 연결에 실패했습니다. 잠시 후 같은 답변을 다시 보내주세요."


base._remove_route("/api/chat-stream", "POST")


@app.post("/api/chat-stream")
def kobaco_ai_chat_stream(req: base.LiteracyChatRequest):
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

    prompt = _learning_prompt(sid, req.message, lesson_id, case_id, case)

    return StreamingResponse(
        _stream_model_reply(prompt, sid, req.message),
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Session-Id": sid,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _render_index_kobaco_v10():
    page = v5._render_index_kobaco_v5()
    topic_json = json.dumps(_topic_payload(), ensure_ascii=False).replace("</", "<\\/")

    replacements = {
        "실제 KOBACO 데이터에서 바로 시작합니다.": "실제 KOBACO 자료로 배워요.",
        "주제를 고르면 KOBACO Parquet DB에서 구성한 실제 데이터 사례가 무작위로 나타납니다.": "주제를 고르면 실제 자료 사례 3개가 나타납니다.",
        "사례를 선택하면 사진·기사·문서와 DB 조회값, 판단할 주장을 보여주고 AI가 바로 첫 질문을 합니다.": "사례를 선택하고 자료를 살펴본 뒤 내 생각을 적으면 AI가 답에 맞춰 함께 읽어줍니다.",
        "아직 조사 수치를 보지 않습니다. 썸네일 또는 광고 영상을 보고 핵심 메시지와 기억에 남는 장면·문구·표현을 먼저 내 말로 설명해보세요.": "먼저 광고 자체를 봅니다. 어떤 메시지로 느꼈는지와 그렇게 느낀 장면·문구를 내 말로 적어보세요. 조사 수치는 첫 답변 뒤에 비교합니다.",
        "실제 조사 결과는 첫 답변을 보낸 뒤 열립니다. 먼저 광고 자체를 읽어야 내 판단과 조사 결과를 비교할 수 있습니다.": "첫 답변 뒤 KOBACO 조사 자료가 열립니다. 내 해석과 조사 결과를 같은 것으로 보지 않고 서로 비교합니다.",
        "광고를 먼저 보고 내 판단 만들기": "광고를 보고 내 해석 만들기",
        "DB 조회값": "실제 조사·인식 데이터",
        "판단할 해석·상황": "생각해 볼 점",
    }
    for old, new in replacements.items():
        page = page.replace(old, new)

    extra_css = r'''
.kobaco-readable-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;padding:14px;background:#f8f5ef;border-bottom:1px solid #ddd5ca}
.kobaco-readable-metric{background:#fff;border:1px solid #ddd5ca;border-radius:9px;padding:12px}
.kobaco-readable-metric small{display:block;font-size:9px;font-weight:850;color:#776d63;line-height:1.4;margin-bottom:6px}
.kobaco-readable-metric strong{display:block;font-size:14px;line-height:1.4;color:#28231f;margin-bottom:7px;word-break:keep-all}
.kobaco-readable-metric p{margin:0;font-size:10px;line-height:1.55;color:#70675f}
.kobaco-why{padding:13px 15px;background:#fff;border-bottom:1px solid #e4ddd3;font-size:11px;line-height:1.65;color:#5f574f}
.kobaco-why b{display:block;color:#2d2925;margin-bottom:4px}
.kobaco-topic-preview{height:86px;margin:-10px -10px 9px;border-radius:7px 7px 4px 4px;padding:11px;display:flex;flex-direction:column;justify-content:flex-end;background:#302b26;color:#fff}
.kobaco-topic-preview b{font-size:10px;line-height:1.3;margin:0 0 3px!important;color:#fff}
.kobaco-topic-preview span{font-size:8px;line-height:1.35;color:rgba(255,255,255,.7)}
.kobaco-topic-preview.aisac{background:linear-gradient(135deg,#29313d,#3e536b)}
.kobaco-topic-preview.ott{background:linear-gradient(135deg,#35302b,#665448)}
.kobaco-fixed-data{width:100%;background:#fff}
.kobaco-fixed-head{padding:15px 16px 11px;border-bottom:1px solid #e2dbd1;background:#f8f5ef}
.kobaco-fixed-head small{display:block;font-size:9px;font-weight:900;color:#74695f;margin-bottom:5px}.kobaco-fixed-head strong{display:block;font-size:16px;line-height:1.4;color:#27231f}
.kobaco-fixed-intro{padding:12px 16px;font-size:11px;line-height:1.6;color:#625a52;border-bottom:1px solid #e6dfd5}
@media(max-width:650px){.kobaco-readable-metrics{grid-template-columns:1fr}.kobaco-topic-preview{height:72px}}
'''
    page = page.replace("</style>", extra_css + "\n</style>")

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
function fixedPreview(c){{
  const id=String(c.id||'');
  if(id.startsWith('kobaco_publicad_')) return `<div class="kobaco-picker-media"><img src="/api/kobaco-media-thumb/${{encodeURIComponent(c.id)}}" alt="${{esc(c.title||'공익광고')}} 썸네일" loading="lazy"></div>`;
  if(id.startsWith('kobaco_aisac_')) return `<div class="kobaco-topic-preview aisac"><b>AI가 읽은 광고</b><span>AiSAC 인식값과 사람의 해석을 구분합니다.</span></div>`;
  if(id.startsWith('kobaco_ott_')) return `<div class="kobaco-topic-preview ott"><b>청소년·OTT 통계</b><span>이용률과 선호도를 구분하고 조사 조건을 확인합니다.</span></div>`;
  return '';
}}
function fixedPickerHtml(lessonId,activeId=null){{
  const cases=fixedSamples[lessonId]||fixedSample(lessonId);
  const total=(fixedTopicCases[lessonId]||[]).length;
  if(!total)return `<div class="chat-case-picker"><div class="chat-case-picker-head"><div><strong>이 주제의 사례를 불러오지 못했습니다.</strong><br><span>다른 주제를 선택하거나 새로고침해 주세요.</span></div></div></div>`;
  return `<div class="chat-case-picker"><div class="chat-case-picker-head"><div><strong>사례를 골라보세요</strong><br><span>전체 ${{total}}개 중 3개를 보여줍니다.</span></div><button type="button" class="chat-case-shuffle" data-shuffle-cases>다른 사례 보기</button></div><div class="chat-case-options">${{cases.map((c,i)=>`<button type="button" class="chat-case-option ${{c.id===activeId?'active':''}}" data-case-id="${{c.id}}">${{fixedPreview(c)}}<b>${{i+1}}. ${{esc(compactTitle(c.title))}}</b><small>${{esc(c.label||'')}}</small></button>`).join('')}}</div></div>`;
}}
function pickerHtml(lessonId,activeId=null){{return fixedPickerHtml(lessonId,activeId);}}

function bindCaseButtons(lessonId){{
  chat.querySelectorAll('[data-case-id]').forEach(btn=>btn.addEventListener('click',()=>startCase(lessonId,btn.dataset.caseId)));
  const shuffle=chat.querySelector('[data-shuffle-cases]');
  if(shuffle)shuffle.addEventListener('click',()=>{{
    if(sessionId&&inlineCaseId&&!confirm('다른 사례를 보면 현재 대화가 새로 시작됩니다. 바꿀까요?'))return;
    sessionId=null;inlineCaseId=null;resetInlineState();fixedSample(lessonId);
    chat.innerHTML=fixedPickerHtml(lessonId);bindCaseButtons(lessonId);
    input.disabled=true;send.disabled=true;finish.disabled=true;
    input.placeholder='위에서 사례를 먼저 선택해 주세요.';stageText.textContent='사례를 선택하세요';chat.scrollTop=0;
  }});
}}
function showCaseChooser(lessonId){{
  selectedLesson=lessonId;inlineLessonId=lessonId;inlineCaseId=null;sessionId=null;resetInlineState();
  fixedSample(lessonId);chat.innerHTML=fixedPickerHtml(lessonId);bindCaseButtons(lessonId);
  input.placeholder='위에서 사례를 먼저 선택해 주세요.';stageText.textContent='사례를 선택하세요';chat.scrollTop=0;
}}

function fixedRows(c){{
  const out={{}};
  (c.data_rows||[]).forEach(r=>{{out[String(r.label||'').trim()]=String(r.value||'').trim();}});
  return out;
}}
function fixedRawRows(c){{
  return (c.data_rows||[]).map(r=>`<div class="kobaco-data-row"><b>${{esc(r.label||'항목')}}</b><span>${{esc(r.value||'-')}}</span></div>`).join('');
}}
function fixedDataMedia(c,kind,title,intro){{
  const tables=(c.db_tables||[]).map(x=>esc(x)).join(' · ');
  return `<div class="chat-case-media"><div class="kobaco-fixed-data"><div class="kobaco-fixed-head"><small>${{esc(kind)}}</small><strong>${{esc(title)}}</strong></div><div class="kobaco-fixed-intro">${{esc(intro)}}</div><div class="kobaco-data-body"><div class="kobaco-data-kicker">KOBACO 실제 데이터 · ${{tables}}</div><div class="kobaco-data-table">${{fixedRawRows(c)}}</div><div class="kobaco-data-note">${{esc(c.data_note||'KOBACO 실제 데이터 조회값')}}</div></div></div></div>`;
}}
function fixedArchiveButton(c){{
  const url=c.archive_url||c.source_url||'';
  if(!url)return '';
  return `<a class="kobaco-ad-action" href="${{esc(url)}}" target="_blank" rel="noopener">공식 상세페이지 ↗</a>`;
}}
function fixedVideoButton(c){{
  return `<a class="kobaco-ad-action video" href="/api/kobaco-video/${{encodeURIComponent(c.id)}}" target="_blank" rel="noopener">▶ 광고 영상 보기</a>`;
}}
function kobacoPublicLearningCard(c){{
  const rowsMap=fixedRows(c);
  const trust=rowsMap['신뢰성']||'-';
  const channel=rowsMap['주요 인지경로']||'-';
  const impact=rowsMap['임팩트 1위']||'-';
  const tables=(c.db_tables||[]).map(x=>esc(x)).join(' · ');
  const metric=(label,value,meaning)=>`<div class="kobaco-readable-metric"><small>${{esc(label)}}</small><strong>${{esc(value)}}</strong><p>${{esc(meaning)}}</p></div>`;

  return `<div class="chat-case-media"><div class="kobaco-data-card">
    <div class="kobaco-thumb-stage"><img src="/api/kobaco-media-thumb/${{encodeURIComponent(c.id)}}" alt="${{esc(c.archive_title||c.title)}} 광고 영상 썸네일" loading="eager"><div class="kobaco-thumb-copy"><div class="kobaco-thumb-kicker">KOBACO 공익광고</div><div class="kobaco-thumb-title">${{esc(c.archive_title||String(c.title||'').split(' · ')[0])}}</div><div class="kobaco-thumb-meta">${{esc([c.archive_year,c.archive_category].filter(Boolean).join(' · '))}}</div></div></div>
    <div class="kobaco-ad-actions">${{fixedArchiveButton(c)}}${{fixedVideoButton(c)}}</div>
    <div class="kobaco-learn-step"><b><span class="kobaco-step-no">1</span>광고를 보고 내 해석 만들기</b><p>광고가 무엇을 말한다고 느꼈는지 적고, 그렇게 느낀 장면이나 문구를 하나 근거로 골라보세요. 이 단계의 내 해석은 조사 결과와 구분합니다.</p></div>
    <div class="kobaco-data-lock"><b>첫 답변 뒤 실제 조사 자료가 열립니다.</b> 숫자를 맞히는 문제가 아니라, 내가 본 내용과 조사에서 측정한 내용을 비교하는 학습입니다.</div>
    <div class="kobaco-after-answer" data-kobaco-after-answer>
      <div class="kobaco-reveal-note">첫 판단 완료 · 실제 KOBACO 효과평가와 비교합니다.</div>
      <div class="kobaco-why"><b>왜 이 자료를 보나요?</b>같은 광고라도 ‘믿을 만했는지’, ‘어디에서 봤는지’, ‘무엇이 가장 기억에 남았는지’는 서로 다른 질문입니다. 숫자를 보기 전에 무엇을 측정한 값인지부터 구분합니다.</div>
      <div class="kobaco-readable-metrics">${{metric('광고의 신뢰성을 평가한 항목',trust,'광고를 믿을 만하다고 평가한 조사 항목입니다. 행동이 바뀐 사람의 비율이라는 뜻은 아닙니다.')}}${{metric('광고를 접한 경로 중 가장 높은 항목',channel,'어디에서 광고를 접했는지를 나타냅니다. 광고의 좋고 나쁨을 평가한 점수가 아닙니다.')}}${{metric('가장 강한 인상을 준 요소',impact,'기억에 남은 요소를 묻는 조사 항목입니다. 광고 전체 효과를 하나의 숫자로 나타낸 값이 아닙니다.')}}</div>
      <details class="kobaco-evidence" open><summary>실제 조사 원자료 항목 보기</summary><div class="kobaco-data-body"><div class="kobaco-data-kicker">KOBACO 데이터 · ${{tables}}</div><div class="kobaco-data-table">${{fixedRawRows(c)}}</div><div class="kobaco-data-note">${{esc(c.data_note||'KOBACO 실제 데이터 조회값')}}</div></div></details>
      <div class="kobaco-learn-step"><b><span class="kobaco-step-no">3</span>자료가 말하는 사실과 내 해석 나누기</b><p>AI와 대화하면서 조사값이 직접 말해주는 범위와 내가 광고에서 해석한 의미를 나눠봅니다. 마지막에는 같은 기준을 AI 없이 직접 적용합니다.</p></div>
    </div>
  </div></div>`;
}}

// 이전 v5의 caseMedia는 비공익광고에서 자기 자신을 다시 호출할 수 있었습니다.
// 세 데이터 유형을 여기서 직접 렌더링해 재귀 호출을 완전히 끊습니다.
function caseMedia(c){{
  const id=String(c?.id||'');
  if(id.startsWith('kobaco_publicad_'))return kobacoPublicLearningCard(c);
  if(id.startsWith('kobaco_aisac_'))return fixedDataMedia(c,'AI가 읽은 광고',c.title||'AiSAC 광고 인식','AI가 광고에서 인식한 키워드·사물·장소는 관찰값입니다. 이 값과 사람이 이해한 광고의 의미를 구분해봅니다.');
  if(id.startsWith('kobaco_ott_'))return fixedDataMedia(c,'청소년·OTT 통계',c.title||'연령별 OTT 이용','이 표는 특정 연도와 연령집단의 이용 비율을 보여줍니다. 이용률을 선호도나 전체 청소년의 성향으로 바꾸어 말하지 않는 법을 연습합니다.');
  return fixedDataMedia(c,'KOBACO 실제 자료',c.title||'실제 자료','화면에 표시된 데이터가 직접 말해주는 범위와 추가 해석이 필요한 부분을 구분합니다.');
}}

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