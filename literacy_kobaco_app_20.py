from __future__ import annotations

import re
import sqlite3

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_19 as previous

app = previous.app
base = previous.base
flow = previous.flow


# ---------------------------------------------------------------------------
# 교육자료 처리 원칙
# - PDF/원문 페이지를 학습 화면에 그대로 보여주지 않는다.
# - 원문에서 "수업에 쓸 내용"과 "교재에 있는 질문"만 뽑아 학습 카드로 만든다.
# - 실제 자료에 없는 내용을 교재 내용처럼 추가하지 않는다.
# ---------------------------------------------------------------------------

_STRONG_ACTIVITY_TERMS = (
    "생각 펼치기", "생각펼치기", "생각 열기", "생각열기",
    "다음 상황을 보고", "함께 생각해", "생각해 볼까요", "생각해볼까요",
    "개인정보 찾기", "활동해", "실천해", "문제를 풀", "문제 풀기",
    "생각 키우기", "생각키우기", "함께 해볼까요", "해볼까요",
)

_LEARNING_TERMS = (
    "개인정보", "위치정보", "주소", "전화번호", "이름", "사진", "영상",
    "온라인", "인터넷", "게시", "공개", "공유", "친구", "댓글", "메시지",
    "디지털", "미디어", "정보", "판단", "선택", "보호", "안전", "책임",
    "사생활", "허위", "사실", "출처", "저작권", "비밀번호", "계정",
    "AI", "인공지능", "딥페이크", "알고리즘", "SNS",
)

_BAD_TERMS = (
    "목차", "차례", "발간사", "머리말", "저작권 안내", "참고문헌", "집필진",
    "연구진", "발행처", "ISBN", "CIP",
)

_QUESTION_START_RE = re.compile(
    r"(?:^|\s)(?:\d+\s*[.)]\s*)?([^?\n]{6,180}\?)"
)


def _clean_source_line(value: str) -> str:
    value = str(value or "").replace("\u00a0", " ").replace("？", "?")
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-•·")
    return value


def _source_questions_v20(raw: str) -> list[str]:
    raw = str(raw or "").replace("？", "?")
    out: list[str] = []

    try:
        for q in previous._extract_source_questions(raw):
            q = _clean_source_line(q)
            if q and q not in out:
                out.append(q)
    except Exception:
        pass

    for line in raw.splitlines():
        line = _clean_source_line(line)
        if "?" not in line:
            continue
        line = re.sub(r"^\d+\s*[.)]\s*", "", line)
        for match in _QUESTION_START_RE.findall(" " + line):
            q = _clean_source_line(match)
            if len(q) >= 8 and q not in out:
                out.append(q)
        if len(out) >= 4:
            break

    flat = _clean_source_line(raw)
    if len(out) < 4:
        for match in re.findall(r"([^?]{8,180}\?)", flat):
            q = _clean_source_line(match)
            q = re.sub(r"^\d+\s*[.)]\s*", "", q)
            if (
                len(q) >= 8
                and q not in out
                and not any(term in q for term in _BAD_TERMS)
            ):
                out.append(q)
            if len(out) >= 4:
                break

    return out[:4]


def _focus_info_v20(material_id: int) -> dict:
    result = {
        "attachment_id": None,
        "page": None,
        "page_end": None,
        "section": "",
        "text": "",
        "raw_text": "",
        "questions": [],
    }
    if not previous.EDU_DB.exists():
        return result

    conn = sqlite3.connect(previous.EDU_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            '''
            SELECT
              c.id, c.attachment_id, c.page_start, c.page_end, c.section, c.text,
              COALESCE(a.filename, '') AS filename
            FROM chunks c
            LEFT JOIN attachments a ON a.id=c.attachment_id
            WHERE c.material_id=?
            ORDER BY c.id
            ''',
            (int(material_id),),
        ).fetchall()
    finally:
        conn.close()

    ranked: list[tuple[int, sqlite3.Row, str, str, list[str]]] = []
    for row in rows:
        raw = str(row["text"] or "")
        text = _clean_source_line(raw)
        if not text:
            continue

        questions = _source_questions_v20(raw)
        filename = str(row["filename"] or "").lower()
        score = len(questions) * 40
        score += sum(18 for term in _STRONG_ACTIVITY_TERMS if term in text)
        score += sum(2 for term in _LEARNING_TERMS if term in text)

        if filename.endswith(".pdf") or ".pdf" in str(row["section"] or "").lower():
            score += 8
        if row["page_start"] and int(row["page_start"]) >= 3:
            score += 4
        if row["page_start"] and int(row["page_start"]) <= 2:
            score -= 12
        if any(term in text for term in _BAD_TERMS):
            score -= 40
        if not questions and not any(term in text for term in _STRONG_ACTIVITY_TERMS):
            score -= 10

        ranked.append((score, row, text, raw, questions))

    if not ranked:
        return result

    ranked.sort(
        key=lambda x: (
            x[0],
            len(x[4]),
            int(x[1]["page_start"] or 0),
        ),
        reverse=True,
    )
    _, row, text, raw, questions = ranked[0]
    return {
        "attachment_id": int(row["attachment_id"]) if row["attachment_id"] else None,
        "page": int(row["page_start"]) if row["page_start"] else None,
        "page_end": int(row["page_end"]) if row["page_end"] else None,
        "section": str(row["section"] or ""),
        "text": text[:1400],
        "raw_text": raw[:5000],
        "questions": questions,
    }


def _candidate_lines(raw: str) -> list[str]:
    lines: list[str] = []
    for raw_line in str(raw or "").splitlines():
        line = _clean_source_line(raw_line)
        if len(line) < 12:
            continue
        if re.fullmatch(r"[\d\s./~\-:()]+", line):
            continue
        if "http://" in line.lower() or "https://" in line.lower():
            continue
        if any(term in line for term in _BAD_TERMS):
            continue
        if line not in lines:
            lines.append(line)

    if len(lines) < 4:
        flat = _clean_source_line(raw)
        for part in re.split(r"(?<=[.!?])\s+|[•●■▪▶]\s*", flat):
            line = _clean_source_line(part)
            if len(line) < 12 or any(term in line for term in _BAD_TERMS):
                continue
            if line not in lines:
                lines.append(line)
    return lines


def _learning_pack_v20(case: dict) -> dict:
    material_id = int(case.get("education_material_id") or 0)
    focus = _focus_info_v20(material_id)
    raw = str(focus.get("raw_text") or focus.get("text") or "")
    lines = _candidate_lines(raw)
    questions = [q for q in (focus.get("questions") or []) if q]

    explanatory = [
        line for line in lines
        if "?" not in line
        and not any(line.startswith(q[:18]) for q in questions if len(q) >= 18)
    ]

    title_terms = [
        str(x).strip()
        for x in (case.get("education_topics") or [])
        if str(x).strip()
    ]

    def score_line(line: str, idx: int) -> int:
        score = 0
        score += sum(9 for term in _STRONG_ACTIVITY_TERMS if term in line)
        score += sum(3 for term in _LEARNING_TERMS if term in line)
        score += sum(4 for term in title_terms if term and term in line)
        if 25 <= len(line) <= 180:
            score += 6
        elif len(line) > 260:
            score -= 5
        score += max(0, 3 - idx // 3)
        return score

    ranked = sorted(
        enumerate(explanatory),
        key=lambda item: score_line(item[1], item[0]),
        reverse=True,
    )

    picked: list[tuple[int, str]] = []
    for idx, line in ranked:
        compact = re.sub(r"\s+", "", line)
        if any(
            compact in re.sub(r"\s+", "", old)
            or re.sub(r"\s+", "", old) in compact
            for _, old in picked
        ):
            continue
        picked.append((idx, line))
        if len(picked) >= 4:
            break

    ordered_points = [line for _, line in sorted(picked, key=lambda x: x[0])]

    activity_title = ""
    for line in lines:
        if any(term in line for term in _STRONG_ACTIVITY_TERMS) and len(line) <= 90:
            activity_title = line
            break

    if not activity_title:
        topics = " · ".join(title_terms[:3])
        activity_title = topics or str(case.get("title") or "디지털 리터러시 활동")

    lead = ordered_points[0] if ordered_points else str(focus.get("text") or "")[:260]
    points = ordered_points[1:4] if len(ordered_points) > 1 else ordered_points[:3]

    if not questions:
        questions = [
            "위 자료에서 가장 중요하다고 생각한 내용은 무엇인가요?",
            "그 내용을 실제 온라인 생활에서 어떻게 적용할 수 있을까요?",
        ]
        question_source = "aioff"
    else:
        question_source = "source"

    return {
        "activity_title": activity_title[:140],
        "lead": lead[:420],
        "points": [x[:320] for x in points[:3]],
        "questions": questions[:3],
        "question_source": question_source,
        "page": focus.get("page") or "",
        "has_source_image": bool(focus.get("attachment_id")),
    }


previous._EDU_FOCUS_CACHE.clear()
previous._focus_info = _focus_info_v20
previous._apply_focus_to_cases()

for _case in flow.CASE_LIBRARY.get("deepfake", []):
    if not str(_case.get("id") or "").startswith("education_"):
        continue
    pack = _learning_pack_v20(_case)
    _case["education_learning_pack"] = pack
    _case["education_source_questions"] = list(pack["questions"])
    _case["opening_questions"] = list(pack["questions"])
    _case["opening_question"] = pack["questions"][0]

_OLD_PUBLIC_CASE_V20 = flow._public_case


def _public_case_v20(case):
    data = dict(_OLD_PUBLIC_CASE_V20(case))
    if str(case.get("id") or "").startswith("education_"):
        data["education_learning_pack"] = case.get("education_learning_pack") or {}
        data["education_source_questions"] = case.get("education_source_questions") or []
    return data


flow._public_case = _public_case_v20


def _render_index_kobaco_v20():
    page = previous._render_index_kobaco_v19()
    patch = r'''
<style>
.aioff-login-indicator{display:none!important}
.aioff-auth-host::before,.aioff-auth-host::after{display:none!important;content:none!important}
.aioff-auth-state:before{
  content:""!important;display:inline-block!important;width:7px!important;height:7px!important;
  border-radius:50%!important;margin-right:6px!important;flex:0 0 7px!important;
  background:#aaa39a!important;vertical-align:1px!important;
}
.aioff-auth-dock.is-on .aioff-auth-state:before{background:#2f75e8!important}
.aioff-auth-dock.is-on{display:inline-flex!important;flex-direction:row!important;align-items:center!important;justify-content:flex-end!important;gap:8px!important}
.aioff-auth-dock.is-on .aioff-auth-state{display:inline-flex!important;align-items:center!important;margin:0!important;padding:0!important}
.aioff-auth-dock.is-on .aioff-auth-links{position:static!important;display:inline-flex!important;align-items:center!important;width:auto!important;height:auto!important;padding:0!important;margin:0!important;background:transparent!important;border:0!important;box-shadow:none!important}
.aioff-auth-dock.is-on .aioff-auth-links span{display:none!important}
.aioff-auth-dock.is-on .aioff-auth-links button,.aioff-auth-dock.is-on .aioff-auth-links button:first-of-type{
  width:auto!important;min-width:68px!important;height:30px!important;min-height:30px!important;padding:0 10px!important;margin:0!important;
  border:1px solid #cfc7bc!important;border-radius:8px!important;background:#f7f3ed!important;color:#514b45!important;font-size:10px!important;font-weight:800!important;
}

.education-extract-card{border:1px solid #d8d1c8;border-radius:10px;background:#fff;overflow:hidden}
.education-extract-head{padding:13px 16px;background:#f6f8fc;border-bottom:1px solid #dfe5ee}
.education-extract-head small{display:block;font-size:8px;color:#66758a;margin-bottom:4px;font-weight:800}
.education-extract-head b{display:block;font-size:15px;line-height:1.45;color:#222a34}
.education-extract-body{padding:14px 16px;background:#fff}
.education-extract-lead{padding:13px 14px;background:#fff7ec;border-left:3px solid #ef7b45;border-radius:0 8px 8px 0;font-size:12px;line-height:1.7;color:#3c332c;font-weight:700}
.education-extract-image{margin:13px 0 0;background:#f1eee8;border:1px solid #e1dad0;border-radius:9px;overflow:hidden}
.education-extract-image img{display:block;width:100%;max-height:420px;object-fit:contain;background:#fff}
.education-extract-section{margin-top:14px}
.education-extract-section>small{display:block;margin-bottom:7px;font-size:9px;font-weight:900;color:#6b625a}
.education-extract-points{display:grid;gap:7px}
.education-extract-point{padding:10px 11px;border:1px solid #e4ddd4;border-radius:8px;background:#faf9f7;font-size:11px;line-height:1.65;color:#403a35}
.education-extract-questions{margin:0;padding-left:22px}
.education-extract-questions li{margin:7px 0;font-size:12px;line-height:1.65;color:#2f2a26;font-weight:800}
.education-extract-question-note{font-size:8px;color:#8a8178;margin-top:5px}
.education-extract-meta{display:flex;gap:6px;flex-wrap:wrap;padding:10px 14px;background:#faf8f4;border-top:1px solid #e7e0d7}
.education-extract-meta span{padding:5px 8px;border:1px solid #ded6cb;border-radius:999px;background:#fff;font-size:9px;color:#645c54}
.education-extract-source{padding:0 14px 13px;background:#faf8f4}
.education-extract-source a{font-size:9px;color:#2d66ba;text-decoration:none}.education-extract-source a:hover{text-decoration:underline}
</style>
<script>
(() => {
  function cleanLegacyAuthDots(){
    document.querySelectorAll('.aioff-login-indicator').forEach(el=>el.remove());
    const dock=document.querySelector('.aioff-auth-dock');
    if(!dock) return;
    const host=dock.parentElement;
    if(host){
      host.classList.add('aioff-auth-host');
      [...host.children].forEach(el=>{
        if(el===dock) return;
        if(!(el.textContent||'').trim()) el.style.display='none';
      });
    }
  }
  cleanLegacyAuthDots();
  const authDock=document.querySelector('.aioff-auth-dock');
  if(authDock) new MutationObserver(cleanLegacyAuthDots).observe(authDock,{childList:true,subtree:true});
  setTimeout(cleanLegacyAuthDots,300);

  const previewBeforeV20=window.fixedPreview;
  window.fixedPreview=function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return previewBeforeV20(c);
    const target=c.education_target||'';
    const year=c.education_year||'';
    return `<div class="education-guide-preview-v19"><img src="/api/education-focus/${encodeURIComponent(id)}" alt="${esc(c.title||'교육자료')} 활동 미리보기" loading="lazy"><span class="edu-chip">${esc([target,year].filter(Boolean).join(' · '))}</span></div>`;
  };

  const mediaBeforeV20=window.caseMedia;
  window.caseMedia=function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return mediaBeforeV20(c);

    const pack=c.education_learning_pack||{};
    const rows={};(c.data_rows||[]).forEach(r=>rows[String(r.label||'')]=String(r.value||''));
    const points=Array.isArray(pack.points)?pack.points.filter(Boolean):[];
    const questions=Array.isArray(pack.questions)?pack.questions.filter(Boolean):[];
    const pointsHtml=points.map(x=>`<div class="education-extract-point">${esc(x)}</div>`).join('');
    const qHtml=questions.map(q=>`<li>${esc(q)}</li>`).join('');
    const sourceNote=pack.question_source==='source'?'교재에 실제로 제시된 질문':'교재 내용을 바탕으로 만든 AI OFF 질문';
    const source=c.source_url?`<a href="${esc(c.source_url)}" target="_blank" rel="noopener">공식 자료 출처 확인 ↗</a>`:'';

    return `<div class="chat-case-media"><div class="education-extract-card">
      <div class="education-extract-head">
        <small>리터러시 교육 안내서에서 뽑은 오늘의 학습</small>
        <b>${esc(pack.activity_title||c.title||'디지털 리터러시 활동')}</b>
      </div>
      <div class="education-extract-body">
        ${pack.lead?`<div class="education-extract-lead">${esc(pack.lead)}</div>`:''}
        <div class="education-extract-image"><img src="/api/education-focus/${encodeURIComponent(id)}" alt="자료 속 활동 이미지" loading="lazy"></div>
        ${pointsHtml?`<div class="education-extract-section"><small>자료에서 확인할 핵심</small><div class="education-extract-points">${pointsHtml}</div></div>`:''}
        <div class="education-extract-section">
          <small>생각해볼 문제</small>
          <ol class="education-extract-questions">${qHtml}</ol>
          <div class="education-extract-question-note">${esc(sourceNote)}</div>
        </div>
      </div>
      <div class="education-extract-meta">
        <span>대상 ${esc(rows['대상']||'-')}</span>
        <span>${esc(rows['연도']||'연도 -')}</span>
        <span>${esc(rows['자료유형']||'자료유형 -')}</span>
      </div>
      <div class="education-extract-source">${source}</div>
    </div></div>`;
  };
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v20():
    return HTMLResponse(_render_index_kobaco_v20())
