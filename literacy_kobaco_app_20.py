from __future__ import annotations

import re
from io import BytesIO

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response
from pypdf import PdfReader, PdfWriter

import literacy_kobaco_app_19 as previous

app = previous.app
base = previous.base
flow = previous.flow


# ---------------------------------------------------------------------------
# 교육자료 처리 원칙
# - DB chunk의 page_start를 그대로 믿지 않는다. (chunk가 목차/표를 가리킬 수 있음)
# - 실제 PDF를 페이지별로 다시 읽어서 '학생 활동/생각하기/문제' 페이지를 고른다.
# - 목차·교육과정표·성취기준표·색인 같은 페이지는 강하게 제외한다.
# - 학습화면에는 선택된 실제 활동 1~2쪽 + 그 페이지에서 뽑은 질문/핵심만 보여준다.
# ---------------------------------------------------------------------------

_STRONG_ACTIVITY_TERMS = (
    "생각 펼치기", "생각펼치기", "생각 열기", "생각열기", "생각 키우기", "생각키우기",
    "다음 상황을 보고", "함께 생각해", "생각해 볼까요", "생각해볼까요",
    "개인정보 찾기", "찾아봅시다", "찾아보세요", "활동해", "실천해",
    "문제를 풀", "문제 풀기", "함께 해볼까요", "해볼까요", "생각해 봅시다",
)

_PROMPT_TERMS = (
    "왜", "무엇", "어떻게", "어떤", "마음", "생각", "골라", "선택", "적어",
    "써 보", "말해", "이야기해", "비교해", "찾아", "확인해", "판단해",
)

_LEARNING_TERMS = (
    "개인정보", "위치정보", "주소", "전화번호", "이름", "사진", "영상", "온라인",
    "인터넷", "게시", "공개", "공유", "친구", "댓글", "메시지", "디지털", "미디어",
    "정보", "판단", "선택", "보호", "안전", "책임", "사생활", "허위", "사실", "출처",
    "저작권", "비밀번호", "계정", "AI", "인공지능", "딥페이크", "알고리즘", "SNS",
)

_BAD_PAGE_TERMS = (
    "목차", "차례", "발간사", "머리말", "참고문헌", "집필진", "연구진", "발행처",
    "ISBN", "CIP", "성취기준", "교육과정", "교과 연계", "교과연계", "차시", "단원명",
    "관련 교과", "교과서", "핵심역량", "학습요소", "평가기준",
)

_TABLE_CODE_RE = re.compile(r"\[[0-9]{1,2}[가-힣A-Za-z]+[0-9\-~.]+\]")
_QUESTION_RE = re.compile(r"([^?？\n]{6,190}[?？])")


def _clean(value: str) -> str:
    value = str(value or "").replace("\u00a0", " ").replace("？", "?")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _questions(raw: str) -> list[str]:
    raw = _clean(raw)
    out: list[str] = []
    for line in raw.splitlines():
        line = re.sub(r"\s+", " ", line).strip(" -•·")
        line = re.sub(r"^\d+\s*[.)]\s*", "", line)
        if "?" not in line:
            continue
        for found in _QUESTION_RE.findall(line):
            q = re.sub(r"\s+", " ", found).strip(" -•·")
            if 8 <= len(q) <= 190 and q not in out:
                out.append(q)
        if len(out) >= 4:
            break
    if len(out) < 4:
        flat = re.sub(r"\s+", " ", raw)
        for found in _QUESTION_RE.findall(flat):
            q = re.sub(r"\s+", " ", found).strip(" -•·")
            if 8 <= len(q) <= 190 and q not in out:
                out.append(q)
            if len(out) >= 4:
                break
    return out[:4]


def _page_lines(raw: str) -> list[str]:
    result: list[str] = []
    for line in _clean(raw).splitlines():
        line = re.sub(r"\s+", " ", line).strip(" -•·")
        if len(line) < 5:
            continue
        if line not in result:
            result.append(line)
    return result


def _page_score(raw: str, page_no: int, image_count: int) -> tuple[int, list[str], dict]:
    text = _clean(raw)
    lines = _page_lines(text)
    qs = _questions(text)

    strong = sum(1 for term in _STRONG_ACTIVITY_TERMS if term in text)
    prompts = sum(1 for term in _PROMPT_TERMS if term in text)
    learning = sum(1 for term in _LEARNING_TERMS if term in text)
    bad = sum(1 for term in _BAD_PAGE_TERMS if term.lower() in text.lower())
    table_codes = len(_TABLE_CODE_RE.findall(text))

    score = 0
    score += len(qs) * 48
    score += strong * 34
    score += min(prompts, 8) * 5
    score += min(learning, 12) * 2
    score += min(image_count, 6) * 4

    # 실제 활동 페이지는 보통 질문/활동 지시 + 그림이 함께 있음.
    if qs and image_count:
        score += 18
    if strong and image_count:
        score += 15

    # 표지/초반 안내 페이지 감점.
    if page_no <= 2:
        score -= 24

    # 목차/성취기준/교육과정표 계열 강한 감점.
    score -= bad * 38
    score -= min(table_codes, 10) * 12
    if table_codes >= 3:
        score -= 55
    if any(term in text for term in ("목차", "차례")):
        score -= 120
    if sum(1 for term in ("성취기준", "교과", "차시", "단원", "교육과정") if term in text) >= 3:
        score -= 90

    # 긴 표/목록인데 질문·활동 지시가 없으면 학습 장면으로 쓰지 않는다.
    if len(lines) >= 30 and not qs and not strong:
        score -= 45
    if not qs and not strong:
        score -= 28

    meta = {
        "questions": qs,
        "strong": strong,
        "prompts": prompts,
        "learning": learning,
        "bad": bad,
        "table_codes": table_codes,
        "image_count": image_count,
        "lines": lines,
    }
    return score, qs, meta


def _activity_info(material_id: int) -> dict:
    result = {
        "attachment_id": None,
        "page": None,
        "page_end": None,
        "section": "",
        "text": "",
        "raw_text": "",
        "questions": [],
        "score": None,
    }

    pdf = previous._pdf_document(material_id)
    if not pdf:
        return result

    try:
        reader = PdfReader(str(pdf))
    except Exception:
        return result

    scored: list[dict] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        try:
            image_count = len(list(page.images))
        except Exception:
            image_count = 0
        score, qs, meta = _page_score(raw, idx, image_count)
        scored.append({
            "page": idx,
            "score": score,
            "raw": raw,
            "questions": qs,
            "meta": meta,
        })

    if not scored:
        return result

    # 활동성이 없는 페이지는 후보에서 제외. 그래도 하나도 없으면 가장 높은 페이지를 fallback.
    viable = [
        x for x in scored
        if x["score"] >= 25
        and x["meta"]["bad"] == 0
        and x["meta"]["table_codes"] < 3
        and (x["questions"] or x["meta"]["strong"])
    ]
    best = max(viable or scored, key=lambda x: x["score"])

    # 시나리오 페이지 + 바로 다음 문제 페이지처럼 붙어 있는 2쪽짜리 활동을 보존한다.
    start = best["page"]
    end = start
    neighbors = []
    for n in (start - 1, start + 1):
        if 1 <= n <= len(scored):
            row = scored[n - 1]
            if (
                row["score"] >= 22
                and row["meta"]["bad"] == 0
                and row["meta"]["table_codes"] < 3
                and (row["questions"] or row["meta"]["strong"] or row["meta"]["image_count"] >= 2)
            ):
                neighbors.append(row)
    if neighbors:
        neighbor = max(neighbors, key=lambda x: x["score"])
        start = min(start, neighbor["page"])
        end = max(end, neighbor["page"])

    chosen = scored[start - 1:end]
    raw_text = "\n".join(x["raw"] for x in chosen if x["raw"]).strip()
    qs: list[str] = []
    for row in chosen:
        for q in row["questions"]:
            if q not in qs:
                qs.append(q)
    if not qs:
        qs = _questions(raw_text)

    return {
        "attachment_id": None,
        "page": start,
        "page_end": end,
        "section": str(pdf.name),
        "text": re.sub(r"\s+", " ", raw_text)[:1800],
        "raw_text": raw_text[:9000],
        "questions": qs[:4],
        "score": best["score"],
    }


def _learning_pack(case: dict) -> dict:
    material_id = int(case.get("education_material_id") or 0)
    focus = _activity_info(material_id)
    raw = str(focus.get("raw_text") or "")
    lines = _page_lines(raw)
    questions = list(focus.get("questions") or [])

    # 학습 핵심은 선택된 실제 활동 페이지의 문장만 사용한다.
    candidates: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        if "?" in line:
            continue
        if any(term.lower() in line.lower() for term in _BAD_PAGE_TERMS):
            continue
        if _TABLE_CODE_RE.search(line):
            continue
        score = 0
        score += sum(9 for term in _STRONG_ACTIVITY_TERMS if term in line)
        score += sum(4 for term in _LEARNING_TERMS if term in line)
        score += sum(2 for term in _PROMPT_TERMS if term in line)
        if 18 <= len(line) <= 180:
            score += 6
        elif len(line) > 260:
            score -= 6
        if score > 5:
            candidates.append((score, idx, line))

    candidates.sort(key=lambda x: (-x[0], x[1]))
    picked: list[tuple[int, str]] = []
    for _, idx, line in candidates:
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
    picked.sort(key=lambda x: x[0])

    activity_title = ""
    for line in lines:
        if any(term in line for term in _STRONG_ACTIVITY_TERMS) and len(line) <= 110:
            activity_title = line
            break
    if not activity_title:
        activity_title = str(case.get("title") or "디지털 리터러시 활동")

    points = [line[:300] for _, line in picked]
    lead = points[0] if points else ""
    rest = points[1:4] if len(points) > 1 else []

    if questions:
        question_source = "source"
    else:
        questions = [
            "이 활동에서 가장 먼저 확인해야 할 정보는 무엇인가요?",
            "그 정보를 온라인에 공개하거나 공유할 때 무엇을 조심해야 할까요?",
        ]
        question_source = "aioff"

    return {
        "activity_title": activity_title[:150],
        "lead": lead,
        "points": rest,
        "questions": questions[:3],
        "question_source": question_source,
        "page": focus.get("page") or "",
        "page_end": focus.get("page_end") or "",
        "score": focus.get("score"),
    }


# v19 route들이 참조하는 focus helper를 실제 PDF 페이지 판별기로 교체한다.
previous._EDU_FOCUS_CACHE.clear()
previous._focus_info = _activity_info
previous._apply_focus_to_cases()

for _case in flow.CASE_LIBRARY.get("deepfake", []):
    if not str(_case.get("id") or "").startswith("education_"):
        continue
    pack = _learning_pack(_case)
    _case["education_learning_pack"] = pack
    _case["education_source_questions"] = list(pack["questions"])
    _case["education_focus_page"] = pack.get("page") or ""
    _case["opening_questions"] = list(pack["questions"])
    _case["opening_question"] = pack["questions"][0]

_OLD_PUBLIC_CASE_V20 = flow._public_case


def _public_case_v20(case):
    data = dict(_OLD_PUBLIC_CASE_V20(case))
    if str(case.get("id") or "").startswith("education_"):
        data["education_learning_pack"] = case.get("education_learning_pack") or {}
        data["education_source_questions"] = case.get("education_source_questions") or []
        data["education_focus_page"] = case.get("education_focus_page") or ""
    return data


flow._public_case = _public_case_v20


base._remove_route("/api/education-activity-page/{case_id}", "GET")


@app.get("/api/education-activity-page/{case_id}")
def education_activity_page_v20(case_id: str):
    case = previous._education_case(case_id)
    material_id = int(case.get("education_material_id") or 0)
    info = _activity_info(material_id)
    pdf = previous._pdf_document(material_id)
    if not pdf or not info.get("page"):
        raise HTTPException(404, "선택된 학습 활동 페이지가 없습니다.")

    try:
        reader = PdfReader(str(pdf))
    except Exception as exc:
        raise HTTPException(500, "학습 활동 페이지를 읽지 못했습니다.") from exc

    start = max(1, min(int(info["page"]), len(reader.pages)))
    end = max(start, min(int(info.get("page_end") or start), len(reader.pages), start + 1))
    writer = PdfWriter()
    for page_no in range(start, end + 1):
        writer.add_page(reader.pages[page_no - 1])
    buf = BytesIO()
    writer.write(buf)
    return Response(
        buf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": "inline", "Cache-Control": "public, max-age=1800"},
    )


def _render_index_kobaco_v20():
    page = previous._render_index_kobaco_v19()
    patch = r'''
<style>
/* LOGIN OFF 회색 점 / LOGIN ON 파란 점, 중복 점 제거 */
.aioff-login-indicator{display:none!important}
.aioff-auth-host::before,.aioff-auth-host::after{display:none!important;content:none!important}
.aioff-auth-state:before{content:""!important;display:inline-block!important;width:7px!important;height:7px!important;border-radius:50%!important;margin-right:6px!important;flex:0 0 7px!important;background:#aaa39a!important;vertical-align:1px!important}
.aioff-auth-dock.is-on .aioff-auth-state:before{background:#2f75e8!important}
.aioff-auth-dock.is-on{display:inline-flex!important;flex-direction:row!important;align-items:center!important;justify-content:flex-end!important;gap:8px!important}
.aioff-auth-dock.is-on .aioff-auth-links{position:static!important;display:inline-flex!important;align-items:center!important;width:auto!important;height:auto!important;padding:0!important;margin:0!important;background:transparent!important;border:0!important;box-shadow:none!important}
.aioff-auth-dock.is-on .aioff-auth-links span{display:none!important}
.aioff-auth-dock.is-on .aioff-auth-links button,.aioff-auth-dock.is-on .aioff-auth-links button:first-of-type{width:auto!important;min-width:68px!important;height:30px!important;min-height:30px!important;padding:0 10px!important;margin:0!important;border:1px solid #cfc7bc!important;border-radius:8px!important;background:#f7f3ed!important;color:#514b45!important;font-size:10px!important;font-weight:800!important}

/* 실제 활동 페이지 중심 학습 */
.education-lesson-card{border:1px solid #d8d1c8;border-radius:10px;background:#fff;overflow:hidden}
.education-lesson-head{padding:13px 16px;background:#f6f8fc;border-bottom:1px solid #dfe5ee}
.education-lesson-head small{display:block;font-size:8px;color:#66758a;margin-bottom:4px;font-weight:800}.education-lesson-head b{display:block;font-size:15px;line-height:1.45;color:#222a34}
.education-lesson-guide{padding:10px 15px;background:#fff8ef;border-bottom:1px solid #eadfce;font-size:10px;line-height:1.55;color:#5d4b3e}
.education-lesson-page{height:clamp(500px,70vh,780px);background:#dedbd5;border-bottom:1px solid #ddd5cb}
.education-lesson-page iframe{display:block;width:100%;height:100%;border:0;background:#dedbd5}
.education-lesson-body{padding:14px 16px;background:#fff}
.education-lesson-lead{padding:12px 13px;background:#fff7ec;border-left:3px solid #ef7b45;border-radius:0 8px 8px 0;font-size:11px;line-height:1.7;color:#3c332c;font-weight:700}
.education-lesson-section{margin-top:14px}.education-lesson-section>small{display:block;margin-bottom:7px;font-size:9px;font-weight:900;color:#6b625a}
.education-lesson-points{display:grid;gap:7px}.education-lesson-point{padding:9px 11px;border:1px solid #e4ddd4;border-radius:8px;background:#faf9f7;font-size:10px;line-height:1.65;color:#403a35}
.education-lesson-questions{margin:0;padding-left:22px}.education-lesson-questions li{margin:7px 0;font-size:12px;line-height:1.65;color:#2f2a26;font-weight:800}
.education-lesson-note{font-size:8px;color:#8a8178;margin-top:5px}
.education-lesson-meta{display:flex;gap:6px;flex-wrap:wrap;padding:10px 14px;background:#faf8f4;border-top:1px solid #e7e0d7}.education-lesson-meta span{padding:5px 8px;border:1px solid #ded6cb;border-radius:999px;background:#fff;font-size:9px;color:#645c54}
.education-lesson-actions{display:flex;gap:8px;padding:0 14px 13px;background:#faf8f4}.education-lesson-actions a{font-size:9px;color:#2d66ba;text-decoration:none}.education-lesson-actions a:hover{text-decoration:underline}
@media(max-width:700px){.education-lesson-page{height:60vh;min-height:430px}}
</style>
<script>
(() => {
  function cleanLegacyAuthDots(){
    document.querySelectorAll('.aioff-login-indicator').forEach(el=>el.remove());
    const dock=document.querySelector('.aioff-auth-dock');
    if(!dock) return;
    const host=dock.parentElement;
    if(host){host.classList.add('aioff-auth-host');[...host.children].forEach(el=>{if(el!==dock&&!(el.textContent||'').trim())el.style.display='none';});}
  }
  cleanLegacyAuthDots();setTimeout(cleanLegacyAuthDots,300);

  const previewBeforeV20=window.fixedPreview;
  window.fixedPreview=function(c){
    const id=String(c?.id||'');if(!id.startsWith('education_'))return previewBeforeV20(c);
    const target=c.education_target||'';const year=c.education_year||'';
    return `<div class="education-guide-preview-v19"><img src="/api/education-focus/${encodeURIComponent(id)}" alt="${esc(c.title||'교육자료')} 실제 활동 미리보기" loading="lazy"><span class="edu-chip">${esc([target,year].filter(Boolean).join(' · '))}</span></div>`;
  };

  const mediaBeforeV20=window.caseMedia;
  window.caseMedia=function(c){
    const id=String(c?.id||'');if(!id.startsWith('education_'))return mediaBeforeV20(c);
    const pack=c.education_learning_pack||{};
    const rows={};(c.data_rows||[]).forEach(r=>rows[String(r.label||'')]=String(r.value||''));
    const points=Array.isArray(pack.points)?pack.points.filter(Boolean):[];
    const questions=Array.isArray(pack.questions)?pack.questions.filter(Boolean):[];
    const pointsHtml=points.map(x=>`<div class="education-lesson-point">${esc(x)}</div>`).join('');
    const qHtml=questions.map(q=>`<li>${esc(q)}</li>`).join('');
    const qNote=pack.question_source==='source'?'위 문제는 선택된 교재 활동 페이지에 실제로 제시된 문항입니다.':'교재에 문항이 없어 선택된 활동 내용을 바탕으로 AI OFF가 만든 질문입니다.';
    const range=pack.page?`원문 ${esc(String(pack.page))}${pack.page_end&&pack.page_end!==pack.page?`~${esc(String(pack.page_end))}`:''}쪽`:'';
    const source=c.source_url?`<a href="${esc(c.source_url)}" target="_blank" rel="noopener">공식 자료 출처 ↗</a>`:'';

    return `<div class="chat-case-media"><div class="education-lesson-card">
      <div class="education-lesson-head"><small>리터러시 교육 안내서 · 실제 수업 활동</small><b>${esc(pack.activity_title||c.title||'디지털 리터러시 활동')}</b></div>
      <div class="education-lesson-guide"><b>목차가 아니라 교재에서 실제 학생이 보고 활동하는 페이지를 골랐습니다.</b>${range?` · ${range}`:''}</div>
      <div class="education-lesson-page"><iframe src="/api/education-activity-page/${encodeURIComponent(id)}#toolbar=0&navpanes=0&view=FitH" title="${esc(c.title||'교육자료')} 실제 활동 페이지"></iframe></div>
      <div class="education-lesson-body">
        ${pack.lead?`<div class="education-lesson-lead">${esc(pack.lead)}</div>`:''}
        ${pointsHtml?`<div class="education-lesson-section"><small>이 활동에서 확인할 내용</small><div class="education-lesson-points">${pointsHtml}</div></div>`:''}
        <div class="education-lesson-section"><small>활동 문제</small><ol class="education-lesson-questions">${qHtml}</ol><div class="education-lesson-note">${esc(qNote)}</div></div>
      </div>
      <div class="education-lesson-meta"><span>대상 ${esc(rows['대상']||'-')}</span><span>${esc(rows['연도']||'연도 -')}</span><span>${esc(rows['자료유형']||'자료유형 -')}</span></div>
      <div class="education-lesson-actions">${source}<a href="/api/education-file/${encodeURIComponent(id)}" target="_blank" rel="noopener">원문 전체 보기 ↗</a></div>
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
