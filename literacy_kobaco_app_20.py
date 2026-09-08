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


# 교육자료는 특정 자료명/페이지를 하드코딩하지 않는다.
# 사용자가 자료를 선택했을 때 그 PDF 하나만 페이지별로 분석해서
# 목차/교육과정표를 버리고 실제 활동·상황·질문 페이지를 고른다.
# 중요: 서버 시작 시 전체 PDF를 훑지 않는다. (502/긴 부팅 방지)

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
_ACTIVITY_CACHE: dict[int, dict] = {}


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


def _text_score(raw: str, page_no: int) -> tuple[int, list[str], dict]:
    text = _clean(raw)
    lines = _page_lines(text)
    qs = _questions(text)
    strong = sum(1 for term in _STRONG_ACTIVITY_TERMS if term in text)
    prompts = sum(1 for term in _PROMPT_TERMS if term in text)
    learning = sum(1 for term in _LEARNING_TERMS if term in text)
    bad = sum(1 for term in _BAD_PAGE_TERMS if term.lower() in text.lower())
    table_codes = len(_TABLE_CODE_RE.findall(text))

    score = len(qs) * 50 + strong * 36 + min(prompts, 8) * 5 + min(learning, 12) * 2
    if page_no <= 2:
        score -= 24
    score -= bad * 42
    score -= min(table_codes, 10) * 12
    if table_codes >= 3:
        score -= 70
    if any(term in text for term in ("목차", "차례")):
        score -= 160
    if sum(1 for term in ("성취기준", "교과", "차시", "단원", "교육과정") if term in text) >= 3:
        score -= 120
    if len(lines) >= 30 and not qs and not strong:
        score -= 55
    if not qs and not strong:
        score -= 30

    return score, qs, {
        "strong": strong,
        "prompts": prompts,
        "learning": learning,
        "bad": bad,
        "table_codes": table_codes,
        "lines": lines,
    }


def _activity_info(material_id: int) -> dict:
    if material_id in _ACTIVITY_CACHE:
        return dict(_ACTIVITY_CACHE[material_id])

    empty = {
        "page": None,
        "page_end": None,
        "raw_text": "",
        "questions": [],
        "score": None,
        "pdf": None,
    }
    pdf = previous._pdf_document(material_id)
    if not pdf:
        _ACTIVITY_CACHE[material_id] = empty
        return dict(empty)

    try:
        reader = PdfReader(str(pdf))
    except Exception:
        _ACTIVITY_CACHE[material_id] = empty
        return dict(empty)

    scored: list[dict] = []
    # 1차: 텍스트만 읽어서 후보를 좁힌다. 모든 페이지의 image 객체를 여는 작업은 하지 않는다.
    for idx, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        score, qs, meta = _text_score(raw, idx)
        scored.append({"page": idx, "score": score, "raw": raw, "questions": qs, "meta": meta})

    if not scored:
        _ACTIVITY_CACHE[material_id] = empty
        return dict(empty)

    viable = [
        row for row in scored
        if row["meta"]["bad"] == 0
        and row["meta"]["table_codes"] < 3
        and (row["questions"] or row["meta"]["strong"])
    ]
    candidates = sorted(viable or scored, key=lambda x: x["score"], reverse=True)[:12]

    # 2차: 상위 후보만 이미지 개수를 확인해 실제 활동/상황 그림 페이지를 우대한다.
    for row in candidates:
        try:
            image_count = len(list(reader.pages[row["page"] - 1].images))
        except Exception:
            image_count = 0
        row["image_count"] = image_count
        if image_count:
            row["score"] += min(image_count, 6) * 5
        if image_count and row["questions"]:
            row["score"] += 22
        if image_count and row["meta"]["strong"]:
            row["score"] += 18

    best = max(candidates, key=lambda x: x["score"])
    start = best["page"]
    end = start

    # 같은 활동이 앞/뒤 페이지에 이어지는 경우 최대 2쪽까지만 묶는다.
    neighbor_rows: list[dict] = []
    for n in (start - 1, start + 1):
        if not (1 <= n <= len(scored)):
            continue
        row = scored[n - 1]
        if row["meta"]["bad"] or row["meta"]["table_codes"] >= 3:
            continue
        if row["questions"] or row["meta"]["strong"]:
            neighbor_rows.append(row)
    if neighbor_rows:
        neighbor = max(neighbor_rows, key=lambda x: x["score"])
        start = min(start, neighbor["page"])
        end = max(end, neighbor["page"])

    chosen = scored[start - 1:end]
    raw_text = "\n".join(row["raw"] for row in chosen if row["raw"]).strip()
    qs: list[str] = []
    for row in chosen:
        for q in row["questions"]:
            if q not in qs:
                qs.append(q)
    if not qs:
        qs = _questions(raw_text)

    result = {
        "page": start,
        "page_end": end,
        "raw_text": raw_text[:12000],
        "questions": qs[:4],
        "score": best["score"],
        "pdf": str(pdf),
    }
    _ACTIVITY_CACHE[material_id] = result
    return dict(result)


def _learning_pack(case: dict) -> dict:
    material_id = int(case.get("education_material_id") or 0)
    focus = _activity_info(material_id)
    raw = str(focus.get("raw_text") or "")
    lines = _page_lines(raw)
    questions = list(focus.get("questions") or [])

    candidates: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        if "?" in line:
            continue
        if any(term.lower() in line.lower() for term in _BAD_PAGE_TERMS):
            continue
        if _TABLE_CODE_RE.search(line):
            continue
        score = sum(9 for term in _STRONG_ACTIVITY_TERMS if term in line)
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
        if any(compact in re.sub(r"\s+", "", old) or re.sub(r"\s+", "", old) in compact for _, old in picked):
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

    points = [line[:320] for _, line in picked]
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


for path in ("/api/education-learning/{case_id}", "/api/education-activity-pdf/{case_id}"):
    base._remove_route(path, "GET")


@app.get("/api/education-learning/{case_id}")
def education_learning_v20(case_id: str):
    case = previous._education_case(case_id)
    return {"ok": True, "pack": _learning_pack(case)}


@app.get("/api/education-activity-pdf/{case_id}")
def education_activity_pdf_v20(case_id: str):
    case = previous._education_case(case_id)
    material_id = int(case.get("education_material_id") or 0)
    focus = _activity_info(material_id)
    pdf_path = focus.get("pdf")
    if not pdf_path:
        raise HTTPException(404, "학습 활동 페이지를 찾을 수 없습니다.")

    try:
        reader = PdfReader(str(pdf_path))
    except Exception as exc:
        raise HTTPException(500, "학습 활동 페이지를 읽지 못했습니다.") from exc

    start = max(1, min(int(focus.get("page") or 1), len(reader.pages)))
    end = max(start, min(int(focus.get("page_end") or start), start + 1, len(reader.pages)))
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
/* 로그인 상태: 자체 점 하나만 사용. OFF 회색 / ON 파랑. */
.aioff-login-indicator{display:none!important}
.aioff-auth-state:before{content:""!important;display:inline-block!important;width:7px!important;height:7px!important;border-radius:50%!important;margin-right:6px!important;background:#aaa39a!important;vertical-align:1px!important}
.aioff-auth-dock.is-on .aioff-auth-state:before{background:#2f75e8!important}
.aioff-auth-dock.is-on{display:inline-flex!important;flex-direction:row!important;align-items:center!important;gap:8px!important}
.aioff-auth-dock.is-on .aioff-auth-links{position:static!important;display:inline-flex!important;align-items:center!important;width:auto!important;height:auto!important;padding:0!important;margin:0!important;background:transparent!important;border:0!important;box-shadow:none!important}
.aioff-auth-dock.is-on .aioff-auth-links span{display:none!important}
.aioff-auth-dock.is-on .aioff-auth-links button,.aioff-auth-dock.is-on .aioff-auth-links button:first-of-type{min-width:68px!important;height:30px!important;padding:0 10px!important;margin:0!important;border:1px solid #cfc7bc!important;border-radius:8px!important;background:#f7f3ed!important;color:#514b45!important;font-size:10px!important;font-weight:800!important}

.education-lazy-card{border:1px solid #d8d1c8;border-radius:10px;background:#fff;overflow:hidden}
.education-lazy-head{padding:13px 16px;background:#f6f8fc;border-bottom:1px solid #dfe5ee}
.education-lazy-head small{display:block;font-size:8px;color:#66758a;margin-bottom:4px;font-weight:800}.education-lazy-head b{font-size:15px;line-height:1.45}
.education-lazy-status{padding:16px;font-size:10px;color:#746d66;background:#fff8ef}
.education-lazy-guide{padding:10px 15px;background:#fff8ef;border-bottom:1px solid #eadfce;font-size:10px;line-height:1.55;color:#5d4b3e}
.education-lazy-page{height:clamp(480px,68vh,760px);background:#dedbd5;border-bottom:1px solid #ddd5cb}
.education-lazy-page iframe{display:block;width:100%;height:100%;border:0;background:#dedbd5}
.education-lazy-body{padding:14px 16px;background:#fff}.education-lazy-lead{padding:12px 13px;background:#fff7ec;border-left:3px solid #ef7b45;border-radius:0 8px 8px 0;font-size:11px;line-height:1.7;color:#3c332c;font-weight:700}
.education-lazy-points{display:grid;gap:7px;margin-top:12px}.education-lazy-point{padding:9px 10px;border:1px solid #e4ddd4;border-radius:8px;background:#faf9f7;font-size:10px;line-height:1.6;color:#403a35}
.education-lazy-questions{margin-top:14px}.education-lazy-questions small{display:block;margin-bottom:7px;font-size:9px;font-weight:900;color:#6b625a}.education-lazy-questions ol{margin:0;padding-left:21px}.education-lazy-questions li{margin:6px 0;font-size:12px;line-height:1.65;color:#2f2a26;font-weight:800}.education-lazy-note{font-size:8px;color:#8a8178;margin-top:5px}
.education-lazy-meta{display:flex;gap:6px;flex-wrap:wrap;padding:10px 14px;background:#faf8f4;border-top:1px solid #e7e0d7}.education-lazy-meta span{padding:5px 8px;border:1px solid #ded6cb;border-radius:999px;background:#fff;font-size:9px;color:#645c54}
.education-lazy-actions{display:flex;gap:8px;padding:0 14px 13px;background:#faf8f4}.education-lazy-actions a{font-size:9px;color:#2d66ba;text-decoration:none}
</style>
<script>
(() => {
  function cleanLegacyDots(){
    document.querySelectorAll('.aioff-login-indicator').forEach(el=>el.remove());
    const dock=document.querySelector('.aioff-auth-dock');
    if(!dock) return;
    [dock.previousElementSibling,dock.nextElementSibling].forEach(el=>{
      if(!el) return;
      const t=(el.textContent||'').trim();
      const r=el.getBoundingClientRect();
      if(!t && r.width<=18 && r.height<=18) el.style.display='none';
    });
  }
  cleanLegacyDots();
  setTimeout(cleanLegacyDots,300);

  const mediaBeforeV20=window.caseMedia;
  window.caseMedia=function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return mediaBeforeV20(c);
    const rows={};(c.data_rows||[]).forEach(r=>rows[String(r.label||'')]=String(r.value||''));
    return `<div class="chat-case-media"><div class="education-lazy-card" data-edu-case="${esc(id)}" data-edu-loaded="0">
      <div class="education-lazy-head"><small>리터러시 교육 안내서 · 실제 활동 학습</small><b data-edu-title>${esc(c.title||'디지털 리터러시 활동')}</b></div>
      <div class="education-lazy-status" data-edu-status>이 자료에서 실제 활동·상황·문제 페이지를 찾고 있습니다.</div>
      <div data-edu-content style="display:none">
        <div class="education-lazy-guide">전체 목차가 아니라, 이 자료에서 학습에 직접 쓰는 활동 페이지만 보여줍니다.</div>
        <div class="education-lazy-page"><iframe data-edu-frame title="교육자료 활동 페이지"></iframe></div>
        <div class="education-lazy-body"><div class="education-lazy-lead" data-edu-lead></div><div class="education-lazy-points" data-edu-points></div><div class="education-lazy-questions"><small>생각해볼 문제</small><ol data-edu-questions></ol><div class="education-lazy-note" data-edu-note></div></div></div>
      </div>
      <div class="education-lazy-meta"><span>대상 ${esc(rows['대상']||'-')}</span><span>${esc(rows['연도']||'연도 -')}</span><span>${esc(rows['자료유형']||'자료유형 -')}</span></div>
      <div class="education-lazy-actions"><a href="/api/education-file/${encodeURIComponent(id)}" target="_blank" rel="noopener">원문 전체 보기 ↗</a>${c.source_url?`<a href="${esc(c.source_url)}" target="_blank" rel="noopener">공식 자료 페이지 ↗</a>`:''}</div>
    </div></div>`;
  };

  async function hydrate(card){
    if(card.dataset.eduLoaded!=='0') return;
    card.dataset.eduLoaded='loading';
    const id=card.dataset.eduCase;
    const status=card.querySelector('[data-edu-status]');
    try{
      const r=await fetch('/api/education-learning/'+encodeURIComponent(id),{credentials:'same-origin'});
      if(!r.ok) throw new Error('HTTP '+r.status);
      const data=await r.json();const p=data.pack||{};
      card.querySelector('[data-edu-title]').textContent=p.activity_title||card.querySelector('[data-edu-title]').textContent;
      const lead=card.querySelector('[data-edu-lead]');lead.textContent=p.lead||'선택된 활동 페이지를 보고 상황과 핵심 정보를 먼저 확인해보세요.';
      const points=card.querySelector('[data-edu-points]');points.innerHTML=(p.points||[]).map(x=>`<div class="education-lazy-point">${esc(x)}</div>`).join('');
      const qs=card.querySelector('[data-edu-questions]');qs.innerHTML=(p.questions||[]).map(x=>`<li>${esc(x)}</li>`).join('');
      card.querySelector('[data-edu-note]').textContent=p.question_source==='source'?'교재에 실제로 제시된 질문':'선택된 교재 내용을 바탕으로 만든 AI OFF 질문';
      const frame=card.querySelector('[data-edu-frame]');frame.src='/api/education-activity-pdf/'+encodeURIComponent(id)+'#toolbar=0&navpanes=0&view=FitH';
      status.style.display='none';card.querySelector('[data-edu-content]').style.display='block';card.dataset.eduLoaded='1';
    }catch(e){status.textContent='학습 활동을 불러오지 못했습니다. 원문 전체 보기를 이용해 주세요.';card.dataset.eduLoaded='error';}
  }
  function scan(){document.querySelectorAll('.education-lazy-card[data-edu-loaded="0"]').forEach(hydrate)}
  new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});
  scan();
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v20():
    return HTMLResponse(_render_index_kobaco_v20())
