from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from fastapi.responses import HTMLResponse, RedirectResponse

import literacy_kobaco_app_4 as previous

# v4의 KOBACO DB 매칭/공식 상세링크/데이터 시각화는 유지합니다.
# v5는 공익광고 효과조사를 '광고 먼저 보기 -> 학생 1차 판단 -> 실제 조사값 공개 -> 해석 비교' 순서로 바꾸고,
# 개별 작품에 연결된 유튜브 영상이 DB에 없을 때도 공식 상세페이지/유튜브 검색에서 보수적으로 찾아 썸네일에 사용합니다.
app = previous.app
flow = previous.flow
base = previous.base


# ---------------------------------------------------------------------------
# 1) 공익광고 교육 흐름: 숫자를 먼저 보여주지 않고 작품을 먼저 읽게 함
# ---------------------------------------------------------------------------
def _case_rows(case):
    return {
        str(row.get("label") or "").strip(): str(row.get("value") or "").strip()
        for row in (case.get("data_rows") or [])
    }


for case in flow.CASE_LIBRARY.get("deepfake", []):
    title = str(case.get("archive_title") or case.get("title") or "공익광고").split(" · ", 1)[0].strip()
    category = str(case.get("archive_category") or "").strip()
    case["claim"] = (
        f"'{title}' 공익광고를 먼저 보고 내가 이해한 메시지와 기억에 남는 표현을 말한 뒤, "
        "실제 KOBACO 효과조사 결과와 비교해 해석하는 학습입니다."
    )
    case["source_excerpt"] = " · ".join(x for x in [title, str(case.get("archive_year") or "").strip(), category] if x)
    case["opening_questions"] = [
        f"먼저 '{title}' 광고의 썸네일이나 영상을 봐줘. 이 광고가 전달하려는 핵심 메시지를 네 말로 한 문장으로 말하고, 그렇게 느끼게 한 장면·문구·표현 하나를 골라줘.",
        f"'{title}' 광고를 처음 본 사람이라고 생각해보자. 가장 기억에 남을 것 같은 요소를 장면·스토리·문구·나레이션 중에서 고르고 이유를 말해줘.",
        f"이 광고를 친구에게 설명한다면 어떤 메시지의 광고라고 소개하겠어? 아직 조사 수치는 보지 말고 광고 자체에서 본 근거를 하나 같이 말해줘.",
    ]
    case["opening_question"] = case["opening_questions"][0]


# ---------------------------------------------------------------------------
# 2) 유튜브 영상 탐색: DB 링크 -> KOBACO 상세페이지 내 임베드 -> 유튜브 검색
# ---------------------------------------------------------------------------
_YOUTUBE_CACHE: dict[str, str] = {}


def _fetch_text(url: str, limit: int = 3_000_000) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
        },
    )
    with urlopen(req, timeout=6) as response:
        raw = response.read(limit)
    return raw.decode("utf-8", errors="ignore")


def _video_id_from_text(text: str) -> str:
    patterns = (
        r"youtube\.com/embed/([A-Za-z0-9_-]{6,})",
        r"youtube\.com/watch\?[^\"'<> ]*v=([A-Za-z0-9_-]{6,})",
        r"youtu\.be/([A-Za-z0-9_-]{6,})",
        r'"videoId"\s*:\s*"([A-Za-z0-9_-]{6,})"',
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return ""


def _norm(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())


def _search_youtube(case) -> str:
    title = str(case.get("archive_title") or case.get("title") or "").split(" · ", 1)[0].strip()
    year = str(case.get("archive_year") or "").strip()
    if not title:
        return ""
    query = quote_plus(f"공익광고협의회 {title} {year}".strip())
    try:
        page = _fetch_text(f"https://www.youtube.com/results?search_query={query}")
    except Exception:
        return ""

    # 검색 결과의 videoRenderer 일부를 읽고 작품명 일치도가 높은 결과만 채택합니다.
    candidates = []
    for match in re.finditer(r'"videoId":"([A-Za-z0-9_-]{6,})"', page):
        video_id = match.group(1)
        chunk = page[match.start(): match.start() + 4200]
        title_match = re.search(r'"title":\{"runs":\[\{"text":"([^\"]+)"', chunk)
        if not title_match:
            continue
        result_title = title_match.group(1).encode("utf-8").decode("unicode_escape", errors="ignore")
        target = _norm(title)
        result_norm = _norm(result_title)
        if not target or not result_norm:
            continue
        similarity = SequenceMatcher(None, target, result_norm).ratio()
        contained = len(target) >= 4 and target in result_norm
        if not contained and similarity < 0.66:
            continue
        channel_bonus = 0
        if "KOBACO" in chunk.upper() or "공익광고협의회" in chunk:
            channel_bonus = 0.25
        candidates.append((similarity + (0.35 if contained else 0) + channel_bonus, video_id))
        if len(candidates) >= 15:
            break
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def _resolve_youtube_id(case) -> str:
    case_id = str(case.get("id") or "")
    if case_id in _YOUTUBE_CACHE:
        return _YOUTUBE_CACHE[case_id]

    video_id = str(case.get("youtube_id") or "").strip()
    if not video_id:
        archive_url = str(case.get("archive_url") or "").strip()
        if archive_url:
            try:
                video_id = _video_id_from_text(_fetch_text(archive_url))
            except Exception:
                video_id = ""
    if not video_id:
        video_id = _search_youtube(case)

    _YOUTUBE_CACHE[case_id] = video_id
    return video_id


@app.get("/api/kobaco-media-thumb/{case_id}")
def kobaco_media_thumbnail(case_id: str):
    found = flow.CASE_BY_ID.get(case_id)
    if not found:
        return previous.Response(status_code=404)
    case = found[1]
    video_id = _resolve_youtube_id(case)
    if video_id:
        return RedirectResponse(f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg", status_code=302)
    return previous.kobaco_thumbnail(case_id)


@app.get("/api/kobaco-video/{case_id}")
def kobaco_video(case_id: str):
    found = flow.CASE_BY_ID.get(case_id)
    if not found:
        return previous.Response(status_code=404)
    case = found[1]
    video_id = _resolve_youtube_id(case)
    if video_id:
        return RedirectResponse(f"https://www.youtube.com/watch?v={video_id}", status_code=302)
    archive_url = str(case.get("archive_url") or case.get("source_url") or "").strip()
    return RedirectResponse(archive_url or "https://www.kobaco.co.kr/site/main/archive/advertising/5", status_code=302)


# ---------------------------------------------------------------------------
# 3) AI 튜터도 단계형으로 변경: 첫 답변 전에는 수치 해석을 요구하지 않음
# ---------------------------------------------------------------------------
_ORIGINAL_CASE_PROMPT = flow._case_chat_prompt


def _public_ad_prompt(session_id: str, user_message: str, lesson_id: str, case):
    prior = base.core.messages(session_id, 40)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '튜터'}: {m['content']}"
        for m in prior
    )
    student_turns = sum(1 for m in prior if m["role"] == "user")
    lesson = base.LESSONS[lesson_id]
    rows = _case_rows(case)
    criteria = "\n".join(f"- {x}" for x in lesson["criteria"])
    title = str(case.get("archive_title") or case.get("title") or "공익광고")

    metrics = f"""- 신뢰성: {rows.get('신뢰성', '-')}
- 주요 인지경로: {rows.get('주요 인지경로', '-')}
- 임팩트 1위: {rows.get('임팩트 1위', '-')}"""

    if student_turns == 0:
        stage = f"""학생은 방금 '{title}' 광고를 먼저 보고 자신의 1차 판단을 작성했다.
이 응답 시점에는 화면에 실제 조사결과가 함께 열리므로, 학생이 말한 '메시지/기억 요소'와 아래 실제 조사결과를 연결해 비교해준다.

[이제 공개할 실제 KOBACO 조사값]
{metrics}

첫 응답 규칙:
- 학생이 광고에서 읽은 메시지나 기억 요소를 먼저 인정/교정한다.
- 바로 정답처럼 수치를 읽어주지 말고, 학생의 판단과 '임팩트 1위'가 같은지/다른지 비교하게 한다.
- '신뢰성', '인지경로', '임팩트'가 각각 다른 지표라는 점을 짧게 설명한다.
- 마지막에는 실제 수치 중 하나를 골라 '이 숫자가 말해주는 것과 말해주지 않는 것'을 묻는 질문 하나만 한다."""
    else:
        stage = f"""학생은 이미 광고 자체를 먼저 보고 1차 판단을 했고, 현재는 실제 KOBACO 조사값을 함께 읽는 단계다.

[실제 KOBACO 조사값]
{metrics}

후속 규칙:
- 학생이 이미 말한 광고 메시지/기억 요소를 같은 표현으로 반복 질문하지 않는다.
- 지표 의미를 실제 값과 연결해 가르친다.
- 인지경로가 높다는 사실을 광고의 설득력이나 행동변화로 바꾸어 말하지 않도록 교정한다.
- 신뢰성이 높다는 사실만으로 행동 변화가 컸다고 단정하지 않게 한다.
- 임팩트 1위는 '기억에 남는 요소'에 관한 조사값이지 광고 전체 효과의 단일 점수가 아님을 분명히 한다.
- 2~3회 정도 데이터 해석을 연습했다면 반복 질문 대신 핵심을 정리하고 AI OFF 단계로 넘어갈 준비를 시킨다."""

    return f"""너는 중·고등학생을 위한 미디어·데이터 리터러시 튜터다.
이번 사례는 KOBACO 실제 공익광고 작품과 효과조사 DB를 연결한 학습이다.

[공익광고 작품]
작품명: {title}
공식 분류: {case.get('archive_category') or '-'}
제작연도: {case.get('archive_year') or '-'}

[학습 판단 기준]
{criteria}

{stage}

[대화 원칙]
1. 광고를 보지 않은 채 숫자부터 맞히는 퀴즈로 만들지 않는다.
2. 학생의 광고 해석과 조사 데이터의 의미를 구분한다.
3. DB에 없는 사실·수치·광고 의도를 새로 만들어내지 않는다.
4. 광고의 '의도'를 단정해야 할 때는 공식 상세페이지/영상에서 직접 확인한 범위만 사용하고, 그렇지 않으면 학생의 해석으로 표현한다.
5. 한 답변은 보통 3~6문장으로 쓰고, 설명 없이 질문만 연속으로 던지지 않는다.
6. 학생이 모르겠다고 하면 먼저 지표 읽는 방법을 2~3개 구체적으로 설명한 뒤 짧게 적용시킨다.
7. 학생의 전체 능력이나 성향을 평가하지 않는다.
8. AI OFF 최종 3문제는 대화 중 미리 출제하지 않는다.

[이전 대화]
{history or '(없음)'}

[학생의 새 답변]
{user_message}"""


def _case_chat_prompt_v5(session_id: str, user_message: str, lesson_id: str):
    case_id = flow._get_case_id(session_id)
    found = flow.CASE_BY_ID.get(case_id) if case_id else None
    if found and str(case_id).startswith("kobaco_publicad_") and lesson_id in base.LESSONS:
        return _public_ad_prompt(session_id, user_message, lesson_id, found[1])
    return _ORIGINAL_CASE_PROMPT(session_id, user_message, lesson_id)


flow._case_chat_prompt = _case_chat_prompt_v5
base._lesson_chat_prompt = _case_chat_prompt_v5


# ---------------------------------------------------------------------------
# 4) 화면: 작품/영상 먼저, 첫 답변 후 실제 조사 데이터가 자동으로 열림
# ---------------------------------------------------------------------------
def _render_index_kobaco_v5():
    page = previous._render_index_kobaco_v4()
    page = page.replace("원문 보기 ↗", "출처 보기 ↗")

    extra_css = r"""
.kobaco-ad-actions{display:flex;gap:7px;flex-wrap:wrap;padding:11px 14px;background:#fff;border-bottom:1px solid #e2dbd1}
.kobaco-ad-action{display:inline-flex;align-items:center;gap:5px;text-decoration:none;border:1px solid #d8d0c5;border-radius:7px;padding:7px 10px;color:#37312b;background:#fff;font-size:9px;font-weight:850}.kobaco-ad-action.video{background:#2b2722;color:#fff;border-color:#2b2722}.kobaco-ad-action:hover{transform:translateY(-1px)}
.kobaco-learn-step{margin:0;padding:14px 16px;border-bottom:1px solid #e3dcd2;background:#fff}.kobaco-learn-step b{display:block;font-size:11px;margin-bottom:5px;color:#24211d}.kobaco-learn-step p{margin:0;font-size:11px;line-height:1.58;color:#655e56}.kobaco-step-no{display:inline-flex;width:20px;height:20px;align-items:center;justify-content:center;border-radius:50%;background:#f06a3c;color:#fff;font-size:9px;margin-right:6px}
.kobaco-after-answer{display:none}.kobaco-after-answer.revealed{display:block;animation:kobacoReveal .28s ease-out}.kobaco-data-lock{padding:11px 14px;background:#f8f5ef;border-bottom:1px solid #ddd5ca;font-size:9px;color:#746b62}.kobaco-data-lock b{color:#2e2924}
.kobaco-reveal-note{padding:10px 14px;background:#edf3ff;border-bottom:1px solid #d9e3fb;font-size:9px;color:#45608f;font-weight:750}
@keyframes kobacoReveal{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:none}}
"""
    page = page.replace("</style>", extra_css + "\n</style>")

    script = r'''
<script>
const caseMediaV4 = caseMedia;
const pickerPreviewV4 = kobacoPickerPreview;

function kobacoArchiveButton(c){
  const archive=c.archive_url||c.source_url||'';
  if(!archive)return '';
  return `<a class="kobaco-ad-action" href="${kobacoEsc(archive)}" target="_blank" rel="noopener">공식 상세페이지 ↗</a>`;
}
function kobacoVideoButton(c){
  return `<a class="kobaco-ad-action video" href="/api/kobaco-video/${encodeURIComponent(c.id)}" target="_blank" rel="noopener">▶ 광고 영상 보기</a>`;
}
function kobacoPublicLearningCard(c){
  const rowsMap=kobacoRows(c);
  const trust=kobacoPct(rowsMap['신뢰성']);
  const channel=kobacoPct(rowsMap['주요 인지경로']);
  const impact=kobacoPct(rowsMap['임팩트 1위']);
  const metric=(label,val)=>`<div class="kobaco-thumb-metric"><small>${kobacoEsc(label)}</small><b>${val.toFixed(1)}%</b><div class="kobaco-thumb-meter"><i style="width:${val}%"></i></div></div>`;
  const tables=(c.db_tables||[]).map(x=>kobacoEsc(x)).join(' · ');
  const rawRows=(c.data_rows||[]).map(r=>`<div class="kobaco-data-row"><b>${kobacoEsc(r.label||'항목')}</b><span>${kobacoEsc(r.value||'-')}</span></div>`).join('');
  return `<div class="chat-case-media"><div class="kobaco-data-card">
    <div class="kobaco-thumb-stage"><img src="/api/kobaco-media-thumb/${encodeURIComponent(c.id)}" alt="${kobacoEsc(c.archive_title||c.title)} 광고 영상 썸네일" loading="eager"><div class="kobaco-thumb-copy"><div class="kobaco-thumb-kicker">KOBACO PUBLIC AD · STEP 1</div><div class="kobaco-thumb-title">${kobacoEsc(c.archive_title||String(c.title||'').split(' · ')[0])}</div><div class="kobaco-thumb-meta">${kobacoEsc([c.archive_year,c.archive_category].filter(Boolean).join(' · '))}</div></div></div>
    <div class="kobaco-ad-actions">${kobacoArchiveButton(c)}${kobacoVideoButton(c)}</div>
    <div class="kobaco-learn-step"><b><span class="kobaco-step-no">1</span>광고를 먼저 보고 내 판단 만들기</b><p>아직 조사 수치를 보지 않습니다. 썸네일 또는 광고 영상을 보고 핵심 메시지와 기억에 남는 장면·문구·표현을 먼저 내 말로 설명해보세요.</p></div>
    <div class="kobaco-data-lock"><b>실제 조사 결과는 첫 답변을 보낸 뒤 열립니다.</b> 먼저 광고 자체를 읽어야 내 판단과 조사 결과를 비교할 수 있습니다.</div>
    <div class="kobaco-after-answer" data-kobaco-after-answer>
      <div class="kobaco-reveal-note">첫 판단 완료 · 이제 실제 KOBACO 효과조사 결과와 비교합니다.</div>
      <div class="kobaco-learn-step"><b><span class="kobaco-step-no">2</span>실제 조사 결과와 비교하기</b><p>신뢰성·인지경로·임팩트는 서로 다른 질문에서 나온 지표입니다. 내가 느낀 메시지와 어떤 점이 같고 다른지 보면서 숫자가 말해주는 범위를 구분합니다.</p></div>
      <div class="kobaco-thumb-metrics">${metric('신뢰성',trust)}${metric('주요 인지경로',channel)}${metric('임팩트 1위',impact)}</div>
      <div class="kobaco-data-body"><div class="kobaco-data-kicker">PARQUET / DUCKDB · ${tables}</div><div class="kobaco-data-table">${rawRows}</div><div class="kobaco-data-note">${kobacoEsc(c.data_note||'KOBACO 실제 데이터 조회값')}</div></div>
      <div class="kobaco-learn-step"><b><span class="kobaco-step-no">3</span>숫자를 과장하지 않고 설명하기</b><p>인지경로를 설득력으로, 신뢰성을 행동변화로 바꿔 말하지 않는지 확인합니다. 각 지표가 직접 말해주는 사실까지만 표현해봅니다.</p></div>
    </div>
  </div></div>`;
}
function caseMedia(c){
  if(c && String(c.id||'').startsWith('kobaco_publicad_')) return kobacoPublicLearningCard(c);
  return caseMediaV4(c);
}
function kobacoPickerPreview(c){
  if(c && String(c.id||'').startsWith('kobaco_publicad_')) return `<div class="kobaco-picker-media"><img src="/api/kobaco-media-thumb/${encodeURIComponent(c.id)}" alt="${kobacoEsc(c.title)} 광고 썸네일" loading="lazy"></div>`;
  return pickerPreviewV4(c);
}
function revealKobacoSurvey(){
  document.querySelectorAll('[data-kobaco-after-answer]').forEach(el=>el.classList.add('revealed'));
  document.querySelectorAll('.kobaco-data-lock').forEach(el=>el.style.display='none');
}
document.addEventListener('click',e=>{
  const target=e.target.closest('#send');
  if(target && inlineCaseId && String(inlineCaseId).startsWith('kobaco_publicad_') && input && input.value.trim()){
    window.setTimeout(revealKobacoSurvey,80);
  }
});
document.addEventListener('keydown',e=>{
  if(e.key==='Enter' && !e.shiftKey && e.target===input && inlineCaseId && String(inlineCaseId).startsWith('kobaco_publicad_') && input.value.trim()){
    window.setTimeout(revealKobacoSurvey,80);
  }
});
</script>
'''
    page = page.replace("</body>", script + "\n</body>")
    return page


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v5():
    return HTMLResponse(_render_index_kobaco_v5())
