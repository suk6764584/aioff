from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

import literacy_kobaco_app_8 as previous

# v8의 학생용 UI는 유지합니다.
# v9는 (1) 공익광고 작품 중복 매칭 제거, (2) 썸네일 요청 시 외부 검색 제거,
# (3) 첫 학습 대화를 DB 기반 즉시 응답으로 바꿔 체감 속도를 줄입니다.
app = previous.app
base = previous.base
flow = previous.flow
v6 = previous.v6
v5 = previous.v5
v4 = v5.previous
v1 = v4.v1


# ---------------------------------------------------------------------------
# 1) 공익광고 효과조사 ↔ KOBACO 작품을 1:1로 다시 매칭
# ---------------------------------------------------------------------------
def _year(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _apply_unique_public_ad_matches() -> None:
    db = v1.get_kobaco_db()
    cases = list(flow.CASE_LIBRARY.get("deepfake", []))
    if db is None or not cases or not db.has_tables("public_ad_master"):
        return

    masters = db.query(
        '''
        SELECT "제작연도", "고유번호", "공익광고작품명", "대분류", "소분류",
               "영상링크-코바코 홈페이지" AS "코바코링크",
               "영상링크-유튜브" AS "유튜브링크",
               "썸네일 이미지 이름" AS "썸네일파일명"
        FROM public_ad_master
        WHERE NULLIF(TRIM(CAST("공익광고작품명" AS VARCHAR)), '') IS NOT NULL
          AND NULLIF(TRIM(CAST("영상링크-코바코 홈페이지" AS VARCHAR)), '') IS NOT NULL
        '''
    )

    pairs: list[tuple[float, int, int]] = []
    for ci, case in enumerate(cases):
        topic = str(case.get("title") or "").split(" · ", 1)[0].strip()
        survey_match = re.search(r"(20\d{2})", str(case.get("title") or ""))
        survey_year = int(survey_match.group(1)) if survey_match else None
        for mi, row in enumerate(masters):
            score = v4._match_score(topic, str(row.get("공익광고작품명") or ""))
            if score <= 0:
                continue
            master_year = _year(row.get("제작연도"))
            if survey_year and master_year:
                if master_year == survey_year:
                    score += 8
                elif abs(master_year - survey_year) <= 1:
                    score += 3
            if score >= 90:
                pairs.append((score, ci, mi))

    # 가장 정확한 조합부터 선택하되 같은 작품/영상은 두 사례에 사용하지 않습니다.
    pairs.sort(reverse=True, key=lambda x: x[0])
    used_cases: set[int] = set()
    used_master_keys: set[str] = set()
    used_video_ids: set[str] = set()
    matched: list[tuple[int, dict[str, Any]]] = []

    for score, ci, mi in pairs:
        if ci in used_cases:
            continue
        row = masters[mi]
        master_key = str(row.get("고유번호") or row.get("코바코링크") or mi)
        video_url = str(row.get("유튜브링크") or "").strip()
        yt_id = v4._youtube_id(video_url)
        if master_key in used_master_keys:
            continue
        if yt_id and yt_id in used_video_ids:
            continue

        case = cases[ci]
        archive_url = str(row.get("코바코링크") or "").strip()
        case["source_url"] = archive_url
        case["archive_url"] = archive_url
        case["video_url"] = video_url
        case["youtube_id"] = yt_id
        case["thumbnail_url"] = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg" if yt_id else ""
        case["archive_title"] = str(row.get("공익광고작품명") or "").strip()
        case["archive_year"] = str(row.get("제작연도") or "").strip()
        case["archive_category"] = " / ".join(
            x for x in [str(row.get("대분류") or "").strip(), str(row.get("소분류") or "").strip()] if x
        )
        case["thumbnail_file"] = str(row.get("썸네일파일명") or "").strip()
        case["match_score"] = round(score, 2)

        used_cases.add(ci)
        used_master_keys.add(master_key)
        if yt_id:
            used_video_ids.add(yt_id)
        matched.append((ci, case))

    # 개별 KOBACO 상세페이지가 정확히 연결된 사례만 학생용 공익광고 수업에 사용합니다.
    if len(matched) >= 3:
        matched.sort(key=lambda x: x[0])
        flow.CASE_LIBRARY["deepfake"] = [case for _, case in matched]
        flow.CASE_BY_ID.clear()
        flow.CASE_BY_ID.update({
            case["id"]: (lesson_id, case)
            for lesson_id, lesson_cases in flow.CASE_LIBRARY.items()
            for case in lesson_cases
        })


_apply_unique_public_ad_matches()

# 요청 때마다 YouTube/KOBACO 페이지를 검색하지 않습니다.
# DB에 저장된 영상 ID가 있으면 즉시 사용하고, 없으면 즉시 기본 이미지로 내려갑니다.
def _cached_video_id(case) -> str:
    return str(case.get("youtube_id") or "").strip()


v5._resolve_youtube_id = _cached_video_id
v4._page_image = lambda url: ""


# ---------------------------------------------------------------------------
# 2) 첫 3회는 모델 호출 없이 실제 DB 값으로 즉시 학습 피드백
# ---------------------------------------------------------------------------
def _rows(case: dict[str, Any]) -> dict[str, str]:
    return {
        str(row.get("label") or "").strip(): str(row.get("value") or "").strip()
        for row in (case.get("data_rows") or [])
    }


def _student_turns(session_id: str) -> int:
    return sum(1 for m in base.core.messages(session_id, 20) if m["role"] == "user")


def _instant_reply(case_id: str, case: dict[str, Any], turn: int, user_message: str) -> str | None:
    rows = _rows(case)
    clean_answer = " ".join(str(user_message or "").split())[:80]

    if case_id.startswith("kobaco_publicad_"):
        impact = rows.get("임팩트 1위", "-")
        trust = rows.get("신뢰성", "-")
        channel = rows.get("주요 인지경로", "-")
        if turn == 0:
            return (
                f"네가 적은 생각은 ‘{clean_answer}’이네요. "
                f"KOBACO 효과평가에서는 {impact}가 가장 강한 인상을 준 요소로 나타났어요. "
                "너에게도 이 요소가 가장 기억에 남았나요, 아니면 다른 장면이나 문구가 더 기억났나요?"
            )
        if turn == 1:
            return (
                f"이번에는 ‘신뢰성’ 값을 볼게요. 이 광고의 신뢰성 항목은 {trust}예요. "
                "여기서 신뢰성은 광고를 믿을 만하다고 느낀 정도를 살펴보는 항목이에요. "
                "이 숫자만 보고 ‘광고를 본 뒤 행동이 바뀌었다’고 말할 수 있을까요?"
            )
        if turn == 2:
            return (
                f"광고를 어디에서 접했는지도 따로 조사해요. 가장 높은 값은 {channel}예요. "
                "이 수치는 광고를 접한 매체를 보여주는 값이지, 광고가 얼마나 좋은지를 뜻하는 점수는 아니에요. "
                "이 자료로 확실하게 말할 수 있는 사실을 한 문장으로 적어볼까요?"
            )

    if case_id.startswith("kobaco_aisac_"):
        keywords = rows.get("키워드", "-")
        counts = rows.get("인식 횟수", "-")
        advertiser = rows.get("광고주", "-")
        if turn == 0:
            return (
                f"AiSAC이 이 광고에서 찾아낸 키워드는 ‘{keywords}’예요. "
                "이건 화면에서 AI가 찾아낸 요소이고, 광고가 전하려는 뜻과는 다를 수 있어요. "
                "이 키워드만 보고 광고의 뜻까지 정해도 될까요?"
            )
        if turn == 1:
            return (
                f"DB에는 광고주가 ‘{advertiser}’, AI 인식 횟수는 ‘{counts}’로 기록돼 있어요. "
                "이 값들은 관찰된 정보예요. 광고가 왜 이런 장면을 썼는지는 원본 영상이나 문구를 더 봐야 알 수 있어요. "
                "지금 화면에서 ‘확실한 사실’ 하나만 골라볼까요?"
            )
        if turn == 2:
            return (
                "정리하면 AI가 찾아낸 사물·장소·키워드와 사람이 이해하는 광고의 뜻은 구분해서 봐야 해요. "
                "AI 인식값은 단서로 쓰고, 중요한 해석은 원본과 비교하는 게 안전해요. "
                "이 기준을 다른 광고에도 적용할 수 있겠나요?"
            )

    if case_id.startswith("kobaco_ott_"):
        top = rows.get("이용비율 상위", "-")
        group = rows.get("연도·집단", case.get("title", "-"))
        sample = rows.get("사례수", "-")
        nonuse = rows.get("OTT 비이용", "-")
        if turn == 0:
            return (
                f"{group} 자료에서 이용 비율이 높은 서비스는 {top}로 나타났어요. "
                "여기서 중요한 말은 ‘이용 비율’이에요. 많이 이용했다고 해서 가장 좋아한다고 바로 말해도 될까요?"
            )
        if turn == 1:
            return (
                f"이 표의 사례수는 {sample}, OTT 비이용은 {nonuse}예요. "
                "통계를 읽을 때는 숫자뿐 아니라 누구를 조사했는지도 같이 봐야 해요. "
                "이 표가 어떤 집단의 결과인지 한 번 말해볼까요?"
            )
        if turn == 2:
            return (
                "이용률은 ‘얼마나 이용했는지’를 보여주고, 선호도는 ‘얼마나 좋아하는지’를 묻는 다른 개념이에요. "
                "그래서 이 표만으로 ‘가장 좋아하는 OTT’를 정하면 안 돼요. "
                "이 자료로 확실하게 말할 수 있는 문장을 하나 만들어볼까요?"
            )

    return None


# ---------------------------------------------------------------------------
# 3) 이후 대화도 프롬프트를 짧게: 최근 8개 메시지만 전달
# ---------------------------------------------------------------------------
def _compact_prompt(session_id: str, user_message: str, lesson_id: str, case: dict[str, Any]) -> str:
    lesson = base.LESSONS[lesson_id]
    prior = base.core.messages(session_id, 8)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '도우미'}: {m['content']}"
        for m in prior
    )
    rows = "\n".join(f"- {r.get('label')}: {r.get('value')}" for r in (case.get("data_rows") or []))
    criteria = "\n".join(f"- {x}" for x in lesson.get("criteria", [])[:4])
    return f"""초등 고학년~중학생용 공공 미디어 교육 도우미다.
짧고 쉬운 한국어로 2~4문장만 답한다. 한 번에 개념 하나만 다룬다.
과한 칭찬, 감탄, AI식 수식어를 쓰지 않는다. 마지막 질문은 하나만 한다.
자료에 없는 사실·의도·인과관계를 만들지 않는다.

[주제] {lesson['title']}
[사례] {case.get('title')}
[실제 KOBACO 값]
{rows}
[판단 기준]
{criteria}
[최근 대화]
{history or '(없음)'}
[학생 답]
{user_message}"""


base._remove_route("/api/chat-stream", "POST")


@app.post("/api/chat-stream")
def kobaco_fast_chat_stream(req: base.LiteracyChatRequest):
    sid = req.session_id or str(base.core.uuid.uuid4())
    lesson_id = req.lesson_id if req.lesson_id in base.LESSONS else base._get_lesson_id(sid)
    if lesson_id not in base.LESSONS:
        raise HTTPException(400, "먼저 학습 자료를 선택해 주세요.")

    base._save_lesson(sid, lesson_id)
    case_id = flow._get_case_id(sid)
    found = flow.CASE_BY_ID.get(case_id) if case_id else None
    if not found:
        raise HTTPException(400, "먼저 사례를 선택해 주세요.")
    case = found[1]

    turn = _student_turns(sid)
    instant = _instant_reply(case_id, case, turn, req.message)
    if instant:
        base.core.save_chat_exchange(sid, req.message, instant)

        def immediate():
            yield instant

        return StreamingResponse(
            immediate(),
            media_type="text/plain; charset=utf-8",
            headers={"X-Session-Id": sid, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    prompt = _compact_prompt(sid, req.message, lesson_id, case)

    def generate():
        reply_parts = []
        emitted = False
        gemini_error = None
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
            base.core.save_chat_exchange(sid, req.message, reply)
            return
        except Exception as exc:
            gemini_error = exc
            if emitted:
                yield "\n\n응답이 중단됐어요. 같은 답을 한 번 더 보내주세요."
                return

        if base.core.groq_configured():
            try:
                client = base.core.groq_client()
                stream = client.chat.completions.create(
                    model=base.core.groq_model(),
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=320,
                    temperature=0.2,
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
                base.core.save_chat_exchange(sid, req.message, reply)
                return
            except Exception:
                pass

        yield f"응답을 만들지 못했어요. 잠시 뒤 다시 시도해 주세요. ({type(gemini_error).__name__})"

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={"X-Session-Id": sid, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
