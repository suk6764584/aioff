from __future__ import annotations

import re
import sqlite3

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_19 as education_source
import literacy_kobaco_app_20 as previous

app = previous.app
base = previous.base
flow = previous.flow


# ---------------------------------------------------------------------------
# 교육자료: PDF 화면 자체가 아니라 DB에 추출된 본문에서 학습 내용과 문제를 고른다.
# 특정 자료명/페이지는 하드코딩하지 않는다.
# ---------------------------------------------------------------------------
_STUDENT_FILE_TERMS = (
    "학생용", "학습지", "활동지", "워크북", "교재", "학습자료", "활동자료", "실습",
)
_TEACHER_FILE_TERMS = (
    "교사용", "지도서", "교수학습", "수업지도", "지도안", "강사용", "매뉴얼",
)
_ACTIVITY_TERMS = (
    "생각 열기", "생각열기", "생각 펼치기", "생각펼치기", "생각 키우기", "생각키우기",
    "함께 생각", "다음 상황", "활동", "실천", "찾아보", "골라보", "선택해", "비교해",
    "이야기해", "말해보", "적어보", "써보", "확인해", "판단해", "해볼까요", "해봅시다",
)
_TEACHER_TEXT_TERMS = (
    "수업 전개 흐름", "수업전개흐름", "학습 목표", "학습목표", "교수·학습", "교수학습",
    "수업 개요", "수업개요", "지도상의 유의", "교사용", "지도서", "성취기준", "교육과정",
    "관련 교과", "교과 연계", "교과연계", "차시", "핵심역량", "평가기준",
)
_META_TERMS = (
    "목차", "차례", "발간사", "머리말", "참고문헌", "집필진", "연구진", "발행처", "ISBN", "CIP",
)
_PROMPT_TERMS = (
    "왜", "무엇", "어떻게", "어떤", "찾아보", "골라보", "선택해", "비교해", "이야기해",
    "말해보", "적어보", "써보", "생각해", "확인해", "판단해", "해볼까요", "해봅시다",
)
_TABLE_CODE_RE = re.compile(r"\[[0-9]{1,2}[가-힣A-Za-z]+[0-9\-~.]+\]")


def _clean_text(value: str) -> str:
    value = str(value or "").replace("\u00a0", " ").replace("？", "?")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _clean_lines(value: str) -> list[str]:
    out: list[str] = []
    for raw in _clean_text(value).splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" \t-•·")
        if len(line) < 5:
            continue
        if re.fullmatch(r"\d{1,3}", line):
            continue
        if line not in out:
            out.append(line)
    return out


def _is_prompt(line: str) -> bool:
    if "?" in line:
        return True
    return any(term in line for term in _PROMPT_TERMS) and 8 <= len(line) <= 220


def _source_prompts(text: str) -> list[str]:
    out: list[str] = []
    for line in _clean_lines(text):
        if any(term.lower() in line.lower() for term in _TEACHER_TEXT_TERMS + _META_TERMS):
            continue
        if not _is_prompt(line):
            continue
        line = re.sub(r"^\s*\d+\s*[.)]\s*", "", line).strip()
        if line and line not in out:
            out.append(line)
        if len(out) >= 4:
            break
    return out


def _section_role_score(section: str) -> int:
    text = str(section or "").lower()
    score = 0
    score += sum(70 for term in _STUDENT_FILE_TERMS if term.lower() in text)
    score -= sum(95 for term in _TEACHER_FILE_TERMS if term.lower() in text)
    return score


def _chunk_score(row: sqlite3.Row) -> tuple[int, list[str]]:
    text = _clean_text(row["text"] or "")
    lower = text.lower()
    prompts = _source_prompts(text)
    score = _section_role_score(str(row["section"] or ""))
    score += len(prompts) * 42
    score += sum(12 for term in _ACTIVITY_TERMS if term in text)
    score -= sum(55 for term in _TEACHER_TEXT_TERMS if term.lower() in lower)
    score -= sum(65 for term in _META_TERMS if term.lower() in lower)
    score -= min(8, len(_TABLE_CODE_RE.findall(text))) * 16
    if 180 <= len(text) <= 4200:
        score += 15
    if len(prompts) == 0 and not any(term in text for term in _ACTIVITY_TERMS):
        score -= 35
    return score, prompts


def _education_body_pack(case: dict) -> dict:
    material_id = int(case.get("education_material_id") or 0)
    db_path = education_source.EDU_DB
    if not material_id or not db_path.exists():
        return {
            "activity_title": str(case.get("title") or "리터러시 활동"),
            "body": [],
            "questions": [],
            "source_section": "",
            "page": "",
        }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, attachment_id, page_start, page_end, section, text
            FROM chunks
            WHERE material_id=? AND TRIM(text)<>''
            ORDER BY id
            """,
            (material_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "activity_title": str(case.get("title") or "리터러시 활동"),
            "body": [],
            "questions": [],
            "source_section": "",
            "page": "",
        }

    ranked: list[tuple[int, sqlite3.Row, list[str]]] = []
    for row in rows:
        score, prompts = _chunk_score(row)
        ranked.append((score, row, prompts))
    ranked.sort(key=lambda x: x[0], reverse=True)

    # 질문/활동이 있는 본문을 우선한다. 그래도 없으면 가장 점수가 높은 본문을 사용한다.
    usable = [x for x in ranked if x[2] or any(term in str(x[1]["text"] or "") for term in _ACTIVITY_TERMS)]
    _, best, prompts = (usable or ranked)[0]
    raw = _clean_text(best["text"] or "")
    lines = _clean_lines(raw)

    title = ""
    for line in lines:
        if any(term.lower() in line.lower() for term in _TEACHER_TEXT_TERMS + _META_TERMS):
            continue
        if _TABLE_CODE_RE.search(line) or _is_prompt(line):
            continue
        if 6 <= len(line) <= 90 and any(term in line for term in _ACTIVITY_TERMS):
            title = line
            break
    if not title:
        title = str(case.get("title") or "리터러시 활동")

    body: list[str] = []
    for line in lines:
        lower = line.lower()
        if line == title or _is_prompt(line):
            continue
        if any(term.lower() in lower for term in _TEACHER_TEXT_TERMS + _META_TERMS):
            continue
        if _TABLE_CODE_RE.search(line):
            continue
        if len(line) < 14 or len(line) > 360:
            continue
        compact = re.sub(r"\s+", "", line)
        if any(compact in re.sub(r"\s+", "", old) or re.sub(r"\s+", "", old) in compact for old in body):
            continue
        body.append(line)
        if len(body) >= 7:
            break

    # 현재 chunk에서 문제가 없으면 상위 후보들의 실제 문장만 추가 탐색한다.
    if not prompts:
        for _, row, row_prompts in ranked[:8]:
            for prompt in row_prompts:
                if prompt not in prompts:
                    prompts.append(prompt)
                if len(prompts) >= 3:
                    break
            if len(prompts) >= 3:
                break

    section = str(best["section"] or "")
    page_start = best["page_start"]
    page_end = best["page_end"]
    if page_start and page_end and page_end != page_start:
        page = f"{page_start}~{page_end}쪽"
    elif page_start:
        page = f"{page_start}쪽"
    else:
        page = ""

    return {
        "activity_title": title[:150],
        "body": body[:7],
        "questions": prompts[:3],
        "source_section": section,
        "page": page,
    }


base._remove_route("/api/education-learning/{case_id}", "GET")


@app.get("/api/education-learning/{case_id}")
def education_learning_v21(case_id: str):
    case = education_source._education_case(case_id)
    return {"ok": True, "pack": _education_body_pack(case)}


# ---------------------------------------------------------------------------
# 화면 정리
# ---------------------------------------------------------------------------
def _render_index_kobaco_v21():
    page = previous._render_index_kobaco_v20()

    # 상단 단계 표시와 오른쪽 상태 사이드바는 화면에서 제거한다.
    page = re.sub(
        r'\s*<section class="process" aria-label="이용 순서">.*?</section>\s*',
        "\n",
        page,
        count=1,
        flags=re.S,
    )
    hidden_state = '''
    <div id="aioff-hidden-state" hidden aria-hidden="true">
      <div id="process1"></div><div id="process2"></div><div id="process3"></div><div id="process4"></div>
      <span id="stageStep">1 / 4</span><span id="stageText"></span>
      <div id="skills"></div><div id="analysisSummary"></div>
    </div>
    '''
    page = re.sub(
        r'\s*<aside class="study-side">.*?</aside>\s*',
        "\n" + hidden_state + "\n",
        page,
        count=1,
        flags=re.S,
    )

    # 설명투 문구는 짧고 실제 사용 행동이 드러나는 문장으로 바꾼다.
    page = re.sub(
        r'<div class="guide-strip"><strong>실제 KOBACO 자료로 배워요\.</strong>.*?</div>',
        '<div class="guide-strip"><strong>사례를 하나 선택하세요.</strong> 자료를 살펴본 뒤 아래 질문에 답해보세요.</div>',
        page,
        count=1,
        flags=re.S,
    )

    patch = r'''
<style>
.workspace{grid-template-columns:minmax(0,1fr)!important;gap:0!important}
.study-paper{width:100%!important;max-width:none!important}

/* 사례/학습 화면을 세로로 더 넉넉하게 사용 */
.chat{height:clamp(610px,72vh,900px)!important}
.chat-case-picker{padding:16px!important}
.chat-case-picker-head{margin-bottom:12px!important}
.chat-case-options{gap:12px!important}
.chat-case-option{min-height:218px!important;padding:12px!important}
.topic-preview,.kobaco-picker-media{height:150px!important;min-height:150px!important}
.kobaco-picker-media img{width:100%!important;height:100%!important;object-fit:cover!important}
.education-guide-preview-v19{height:168px!important;margin:-12px -12px 10px!important}

/* 학교 자동완성 화살표를 실제 버튼으로 사용 */
.aioff-school-search.aioff-school-combobox:after{display:none!important}
#aioff-school-toggle-v21{position:absolute;right:1px;top:1px;width:42px;height:40px;border:0;background:transparent;z-index:140;padding:0;cursor:pointer}
#aioff-school-toggle-v21:before{content:"";position:absolute;left:15px;top:14px;width:8px;height:8px;border-right:1.5px solid #302c28;border-bottom:1.5px solid #302c28;transform:rotate(45deg)}
.aioff-school-combobox.is-open #aioff-school-toggle-v21:before{top:18px;transform:rotate(225deg)}

/* 교육자료는 PDF 뷰어가 아니라 추출한 본문과 원문 문제를 메인으로 표시 */
.education-study-v21{border:1px solid #d9d2c9;border-radius:10px;background:#fff;overflow:hidden}
.education-study-v21-head{padding:18px 20px 15px;border-bottom:1px solid #e2dbd2;background:#f8fafc}
.education-study-v21-head small{display:block;margin-bottom:5px;font-size:10px;font-weight:800;color:#58749b}
.education-study-v21-head b{display:block;font-size:19px;line-height:1.45;color:#27231f}
.education-study-v21-status{padding:24px 20px;font-size:12px;color:#746d66}
.education-study-v21-body{padding:20px;background:#fff}
.education-study-v21-reading{padding:16px 18px;border:1px solid #e2ddd6;border-radius:9px;background:#fffdf9}
.education-study-v21-reading h4,.education-study-v21-questions h4{margin:0 0 10px;font-size:13px;color:#2d2925}
.education-study-v21-reading p{margin:0 0 10px;font-size:14px;line-height:1.75;color:#403a35}
.education-study-v21-reading p:last-child{margin-bottom:0}
.education-study-v21-questions{margin-top:14px;padding:16px 18px;border:1px solid #eadbc8;border-radius:9px;background:#fff8ee}
.education-study-v21-questions ol{margin:0;padding-left:22px}
.education-study-v21-questions li{margin:8px 0;font-size:14px;line-height:1.65;font-weight:700;color:#342d27}
.education-study-v21-source{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:13px;font-size:10px;color:#857b72}
.education-study-v21-actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.education-study-v21-actions a{display:inline-flex;padding:8px 11px;border:1px solid #cfc6ba;border-radius:7px;background:#fff;color:#2d2925!important;text-decoration:none;font-size:10px;font-weight:800}
@media(max-width:700px){.chat{height:620px!important}.chat-case-option{min-height:190px!important}.topic-preview,.kobaco-picker-media{height:125px!important;min-height:125px!important}}
</style>
<script>
(() => {
  /* 학교 입력 오른쪽 화살표: 열기/닫기 둘 다 클릭 가능 */
  const input=document.getElementById('aioff-school-name');
  const wrap=input?.closest('.aioff-school-search');
  const box=document.getElementById('aioff-school-results');
  if(input&&wrap&&box&&!document.getElementById('aioff-school-toggle-v21')){
    const toggle=document.createElement('button');
    toggle.type='button';toggle.id='aioff-school-toggle-v21';toggle.setAttribute('aria-label','학교 목록 열기 또는 닫기');
    wrap.appendChild(toggle);
    toggle.addEventListener('mousedown',e=>e.preventDefault());
    toggle.addEventListener('click',()=>{
      if(box.classList.contains('open')){
        box.classList.remove('open');
        wrap.classList.remove('is-open');
        input.setAttribute('aria-expanded','false');
      }else{
        input.focus();
        input.dispatchEvent(new MouseEvent('click',{bubbles:true}));
      }
    });
  }

  /* 교사용/지도서 자료는 학생 사례 목록에서 제외한다. */
  try{
    if(typeof educationPool19!=='undefined'&&Array.isArray(educationPool19)){
      const clean=educationPool19.filter(c=>!/(교사용|지도서|교사\s*용|강사용|수업지도|지도안)/.test(String(c?.title||'')));
      if(clean.length>=3) educationPool19.splice(0,educationPool19.length,...clean);
    }
  }catch(e){}

  /* 사례 선택창의 설명문도 짧게 정리 */
  function cleanPickerCopy(){
    document.querySelectorAll('.chat-case-picker-head span').forEach(el=>{
      const m=(el.textContent||'').match(/전체\s*(\d+)개\s*중\s*3개/);
      if(m) el.textContent=`전체 ${m[1]}개 · 3개 선택`;
    });
  }
  new MutationObserver(cleanPickerCopy).observe(document.body,{childList:true,subtree:true});
  cleanPickerCopy();

  /* 교육자료 선택 후: PDF 전체 화면 대신 본문에서 뽑은 읽을거리 + 자료 속 문제 */
  const mediaBeforeV21=window.caseMedia;
  window.caseMedia=function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return mediaBeforeV21(c);
    const source=c.source_url?`<a href="${esc(c.source_url)}" target="_blank" rel="noopener">공식 자료 페이지</a>`:'';
    return `<div class="chat-case-media"><div class="education-study-v21" data-edu-v21="${esc(id)}" data-loaded="0">
      <div class="education-study-v21-head"><small>리터러시 교육 안내서</small><b data-title>${esc(c.title||'학습 활동')}</b></div>
      <div class="education-study-v21-status" data-status>학습 내용을 불러오는 중...</div>
      <div class="education-study-v21-body" data-content style="display:none">
        <div class="education-study-v21-reading"><h4>읽어보기</h4><div data-reading></div></div>
        <div class="education-study-v21-questions" data-qwrap><h4>생각해보기</h4><ol data-questions></ol></div>
        <div class="education-study-v21-source" data-source></div>
        <div class="education-study-v21-actions"><a href="/api/education-file/${encodeURIComponent(id)}" target="_blank" rel="noopener">원문 보기</a>${source}</div>
      </div>
    </div></div>`;
  };

  async function hydrate(card){
    if(card.dataset.loaded!=='0') return;
    card.dataset.loaded='loading';
    const id=card.dataset.eduV21;
    const status=card.querySelector('[data-status]');
    try{
      const r=await fetch('/api/education-learning/'+encodeURIComponent(id),{credentials:'same-origin'});
      if(!r.ok) throw new Error('HTTP '+r.status);
      const data=await r.json();const p=data.pack||{};
      if(p.activity_title) card.querySelector('[data-title]').textContent=p.activity_title;
      const reading=card.querySelector('[data-reading]');
      const body=Array.isArray(p.body)?p.body.filter(Boolean):[];
      reading.innerHTML=body.length?body.map(x=>`<p>${esc(x)}</p>`).join(''):'<p>이 자료에서 바로 사용할 학습 본문을 찾지 못했습니다. 원문 보기를 이용해 주세요.</p>';
      const qs=Array.isArray(p.questions)?p.questions.filter(Boolean):[];
      const qwrap=card.querySelector('[data-qwrap]');
      if(qs.length){card.querySelector('[data-questions]').innerHTML=qs.map(x=>`<li>${esc(x)}</li>`).join('');}
      else qwrap.style.display='none';
      const ref=[p.source_section||'',p.page||''].filter(Boolean).join(' · ');
      card.querySelector('[data-source]').textContent=ref?`출처 위치 · ${ref}`:'';
      status.style.display='none';card.querySelector('[data-content]').style.display='block';card.dataset.loaded='1';
      const composer=document.getElementById('input');if(composer) composer.placeholder='자료를 읽고 생각한 내용을 적어보세요.';
    }catch(e){status.textContent='학습 내용을 불러오지 못했습니다.';card.dataset.loaded='error';}
  }
  function scan(){document.querySelectorAll('.education-study-v21[data-loaded="0"]').forEach(hydrate)}
  new MutationObserver(scan).observe(document.body,{childList:true,subtree:true});
  scan();
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v21():
    return HTMLResponse(_render_index_kobaco_v21())
