from __future__ import annotations

import re
import sqlite3
from io import BytesIO

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response
from pypdf import PdfReader, PdfWriter

import literacy_kobaco_app_19 as previous

app = previous.app
base = previous.base
flow = previous.flow


# ---------------------------------------------------------------------------
# 1) 교육자료는 표지/전체 PDF가 아니라 실제 활동·문제 페이지를 우선 선택한다.
# ---------------------------------------------------------------------------
_STRONG_ACTIVITY_TERMS = (
    "생각 펼치기", "생각펼치기", "생각 열기", "생각열기",
    "다음 상황을 보고", "함께 생각해", "생각해 볼까요", "생각해볼까요",
    "개인정보 찾기", "활동해", "실천해", "문제를 풀", "문제 풀기",
)
_WEAK_ACTIVITY_TERMS = (
    "왜", "무엇", "어떻게", "마음", "상황", "활동", "실천",
    "문제", "퀴즈", "적어", "써 보", "골라", "선택", "생각",
)
_BAD_SECTION_TERMS = (
    "목차", "차례", "발간사", "머리말", "저작권", "참고문헌", "집필진",
)


def _source_questions_v20(text: str) -> list[str]:
    raw = str(text or "").replace("？", "?")
    out: list[str] = []

    # 기존 추출기를 먼저 사용한다.
    try:
        out.extend(previous._extract_source_questions(raw))
    except Exception:
        pass

    # 교재 문항은 줄 단위로 번호가 붙는 경우가 많아 별도로 보강한다.
    for line in raw.splitlines():
        line = re.sub(r"\s+", " ", line).strip(" -•·")
        line = re.sub(r"^\d+\s*[.)]\s*", "", line)
        if "?" not in line:
            continue
        for match in re.findall(r"([^?]{6,180}\?)", line):
            q = re.sub(r"\s+", " ", match).strip(" -•·")
            if len(q) >= 8 and q not in out:
                out.append(q)
        if len(out) >= 4:
            break

    return out[:4]


def _focus_info_v20(material_id: int) -> dict:
    if material_id in previous._EDU_FOCUS_CACHE:
        return dict(previous._EDU_FOCUS_CACHE[material_id])

    result = {
        "attachment_id": None,
        "page": None,
        "page_end": None,
        "section": "",
        "text": "",
        "questions": [],
    }
    if not previous.EDU_DB.exists():
        previous._EDU_FOCUS_CACHE[material_id] = result
        return dict(result)

    conn = sqlite3.connect(previous.EDU_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
              c.id, c.attachment_id, c.page_start, c.page_end, c.section, c.text,
              COALESCE(a.filename, '') AS filename
            FROM chunks c
            LEFT JOIN attachments a ON a.id=c.attachment_id
            WHERE c.material_id=?
            ORDER BY c.id
            """,
            (int(material_id),),
        ).fetchall()
    finally:
        conn.close()

    ranked: list[tuple[int, sqlite3.Row, str, list[str]]] = []
    for row in rows:
        raw = str(row["text"] or "")
        text = " ".join(raw.split())
        if not text:
            continue
        low = text.lower()
        filename = str(row["filename"] or "").lower()
        questions = _source_questions_v20(raw)

        score = len(questions) * 35
        score += sum(14 for term in _STRONG_ACTIVITY_TERMS if term in text)
        score += sum(3 for term in _WEAK_ACTIVITY_TERMS if term in text)
        if filename.endswith(".pdf") or ".pdf" in str(row["section"] or "").lower():
            score += 18
        if row["page_start"] and int(row["page_start"]) >= 3:
            score += 6
        if row["page_start"] and int(row["page_start"]) <= 2:
            score -= 12
        if 120 <= len(text) <= 2800:
            score += 4
        if any(term in low for term in _BAD_SECTION_TERMS):
            score -= 35
        if not questions and not any(term in text for term in _STRONG_ACTIVITY_TERMS):
            score -= 8

        ranked.append((score, row, text, questions))

    if ranked:
        ranked.sort(key=lambda x: (x[0], len(x[3]), int(x[1]["page_start"] or 0)), reverse=True)
        _, row, text, questions = ranked[0]
        result = {
            "attachment_id": int(row["attachment_id"]) if row["attachment_id"] else None,
            "page": int(row["page_start"]) if row["page_start"] else None,
            "page_end": int(row["page_end"]) if row["page_end"] else None,
            "section": str(row["section"] or ""),
            "text": text[:1000],
            "questions": questions,
        }

    previous._EDU_FOCUS_CACHE[material_id] = result
    return dict(result)


# v19의 route/case helper들이 실행 시 참조하는 module global을 교체한다.
previous._EDU_FOCUS_CACHE.clear()
previous._focus_info = _focus_info_v20
previous._apply_focus_to_cases()


base._remove_route("/api/education-focus-pdf/{case_id}", "GET")


@app.get("/api/education-focus-pdf/{case_id}")
def education_focus_pdf_v20(case_id: str):
    case = previous._education_case(case_id)
    material_id = int(case.get("education_material_id") or 0)
    focus = previous._focus_info(material_id)
    source_pdf = previous._focus_pdf(material_id, focus)
    if not source_pdf:
        raise HTTPException(404, "학습 활동 페이지 PDF를 찾을 수 없습니다.")

    try:
        reader = PdfReader(str(source_pdf))
    except Exception as exc:
        raise HTTPException(500, "학습 활동 페이지를 읽지 못했습니다.") from exc
    if not reader.pages:
        raise HTTPException(404, "학습 활동 페이지가 비어 있습니다.")

    start = max(1, int(focus.get("page") or 1))
    start = min(start, len(reader.pages))
    end = int(focus.get("page_end") or start)
    end = max(start, min(end, start + 1, len(reader.pages)))

    # 질문이 한 개뿐이면 바로 다음 페이지에 이어지는 활동 문항이 있을 수 있어 2쪽까지만 보여준다.
    if end == start and len(focus.get("questions") or []) <= 1 and start < len(reader.pages):
        end = start + 1

    writer = PdfWriter()
    for page_no in range(start, end + 1):
        writer.add_page(reader.pages[page_no - 1])
    buf = BytesIO()
    writer.write(buf)
    return Response(
        buf.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "public, max-age=1800",
        },
    )


# ---------------------------------------------------------------------------
# 2) UI: 로그인 점 중복 제거 + 교육자료를 '활동 페이지 → 원문 문항 → 답변'으로 표시.
# ---------------------------------------------------------------------------
def _render_index_kobaco_v20():
    page = previous._render_index_kobaco_v19()
    patch = r'''
<style>
/* auth: 기존 AI ON/OFF 호스트에 남아 있던 점은 제거하고 이 점 하나만 사용한다. */
.aioff-login-indicator{display:none!important}
.aioff-auth-host::before{display:none!important;content:none!important}
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

/* 교육 학습: 전체 파일 탐색기가 아니라 교재 속 실제 활동 1~2쪽만 제시한다. */
.education-activity-card{border:1px solid #d9d2c9;border-radius:9px;background:#fff;overflow:hidden}
.education-activity-head{padding:12px 15px;background:#f7f9fc;border-bottom:1px solid #dfe5ee}
.education-activity-head small{display:block;font-size:8px;color:#66758a;margin-bottom:4px}.education-activity-head b{font-size:14px;line-height:1.4}
.education-activity-guide{padding:10px 15px;background:#fff8ef;border-bottom:1px solid #eadfce;font-size:10px;line-height:1.55;color:#5d4b3e}
.education-activity-page{height:clamp(470px,68vh,760px);background:#dedbd5;border-bottom:1px solid #ddd5cb}
.education-activity-page iframe{display:block;width:100%;height:100%;border:0;background:#dedbd5}
.education-activity-questions{padding:13px 16px 15px;background:#fff;border-bottom:1px solid #e7e0d7}
.education-activity-questions small{display:block;font-size:9px;font-weight:900;color:#6c6259;margin-bottom:7px}
.education-activity-questions ol{margin:0;padding-left:21px}.education-activity-questions li{font-size:12px;line-height:1.65;color:#302a25;margin:5px 0;font-weight:750}
.education-activity-meta{display:flex;gap:6px;flex-wrap:wrap;padding:9px 14px;background:#faf8f4;border-bottom:1px solid #e7e0d7}
.education-activity-meta span{padding:5px 8px;border:1px solid #ded6cb;border-radius:999px;background:#fff;font-size:9px;color:#645c54}
.education-activity-actions{display:flex;gap:8px;padding:10px 14px 13px;flex-wrap:wrap}.education-activity-actions a{display:inline-flex;padding:7px 10px;border-radius:7px;text-decoration:none;font-size:9px;font-weight:850;background:#26221f;color:#fff!important}.education-activity-actions a.alt{background:#fff;color:#2d2925!important;border:1px solid #cfc6ba}
@media(max-width:700px){.education-activity-page{height:58vh;min-height:420px}}
</style>
<script>
(() => {
  function cleanLegacyAuthDot(){
    document.querySelectorAll('.aioff-login-indicator').forEach(el=>el.remove());
    const dock=document.querySelector('.aioff-auth-dock');
    if(!dock) return;
    const host=dock.parentElement;
    if(host) host.classList.add('aioff-auth-host');

    /* AI ON 텍스트만 replaceWith 했을 때 남는 작은 원형 sibling을 제거한다. */
    [dock.previousElementSibling,dock.nextElementSibling].forEach(el=>{
      if(!el) return;
      const text=(el.textContent||'').trim();
      const r=el.getBoundingClientRect();
      if(!text && r.width<=18 && r.height<=18) el.style.display='none';
    });
  }
  cleanLegacyAuthDot();
  const authDock=document.querySelector('.aioff-auth-dock');
  if(authDock) new MutationObserver(cleanLegacyAuthDot).observe(authDock,{childList:true,subtree:true});
  setTimeout(cleanLegacyAuthDot,300);

  /* 카드 썸네일부터 표지가 아니라 선택된 실제 활동 장면을 보여준다. */
  const previewBeforeV20=window.fixedPreview;
  window.fixedPreview=function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return previewBeforeV20(c);
    const target=c.education_target||'';const year=c.education_year||'';
    return `<div class="education-guide-preview-v19"><img src="/api/education-focus/${encodeURIComponent(id)}" alt="${esc(c.title||'교육자료')} 활동 미리보기" loading="lazy"><span class="edu-chip">${esc([target,year].filter(Boolean).join(' · '))}</span></div>`;
  };

  const mediaBeforeV20=window.caseMedia;
  window.caseMedia=function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return mediaBeforeV20(c);

    const rows={};(c.data_rows||[]).forEach(r=>rows[String(r.label||'')]=String(r.value||''));
    let questions=Array.isArray(c.education_source_questions)?c.education_source_questions.filter(Boolean):[];
    if(!questions.length){
      const q=c.opening_question||(Array.isArray(c.opening_questions)?c.opening_questions[0]:'')||'위 활동을 보고 자료에서 확인한 내용과 자신의 생각을 나누어 적어보세요.';
      questions=[q];
    }
    const qhtml=questions.slice(0,3).map(q=>`<li>${esc(q)}</li>`).join('');
    const page=c.education_focus_page?` · 원문 ${esc(String(c.education_focus_page))}쪽 부근`:'';
    const source=c.source_url?`<a class="alt" href="${esc(c.source_url)}" target="_blank" rel="noopener">공식 자료 페이지 ↗</a>`:'';

    return `<div class="chat-case-media"><div class="education-activity-card">
      <div class="education-activity-head"><small>리터러시 교육 안내서 · 교재 속 실제 활동${page}</small><b>${esc(c.title||'디지털윤리 교육자료')}</b></div>
      <div class="education-activity-guide"><b>아래 활동 장면만 보고 먼저 생각해보세요.</b> 교재 전체를 읽는 방식이 아니라, 실제 수업에서 쓰는 활동·문제 페이지를 그대로 사용합니다.</div>
      <div class="education-activity-page"><iframe src="/api/education-focus-pdf/${encodeURIComponent(id)}#toolbar=0&navpanes=0&view=FitH" title="${esc(c.title||'교육자료')} 활동 페이지"></iframe></div>
      <div class="education-activity-questions"><small>교재에 제시된 문제</small><ol>${qhtml}</ol></div>
      <div class="education-activity-meta"><span>대상 ${esc(rows['대상']||'-')}</span><span>${esc(rows['연도']||'연도 -')}</span><span>${esc(rows['자료유형']||'자료유형 -')}</span></div>
      <div class="education-activity-actions"><a href="/api/education-focus-pdf/${encodeURIComponent(id)}" target="_blank" rel="noopener">활동 페이지 크게 보기 ↗</a><a class="alt" href="/api/education-file/${encodeURIComponent(id)}" target="_blank" rel="noopener">원문 전체 보기 ↗</a>${source}</div>
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
