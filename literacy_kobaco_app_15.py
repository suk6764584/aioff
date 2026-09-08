from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from fastapi.responses import HTMLResponse

import literacy_kobaco_app_14 as previous

app = previous.app
base = previous.base
flow = previous.flow

EDU_DB = Path(__file__).resolve().parent / "data" / "education" / "education.db"
ARCHIVE_URL = "https://xn--2z1b40gs9nlqcf0n.kr/front/archive/archiveMainList.do"


def _education_cases() -> list[dict]:
    if not EDU_DB.exists():
        return []

    conn = sqlite3.connect(EDU_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        '''
        SELECT
          m.id, m.title, m.target, m.year, m.material_type,
          m.topics_json, m.source_url, COUNT(c.id) AS chunk_count,
          SUM(CASE WHEN c.embedding IS NOT NULL THEN 1 ELSE 0 END) AS embedded_chunk_count
        FROM materials m
        JOIN chunks c ON c.material_id=m.id
        GROUP BY m.id
        ORDER BY
          CASE
            WHEN m.title LIKE '%교육 안내서%' THEN 0
            WHEN m.title LIKE '%안내서%' THEN 1
            WHEN m.title LIKE '%가이드%' THEN 2
            ELSE 3
          END,
          m.year DESC,
          m.title
        LIMIT 60
        '''
    ).fetchall()

    old_cases = flow.CASE_LIBRARY.get("deepfake") or flow.CASE_LIBRARY.get("news") or []
    if not old_cases:
        conn.close()
        return []
    template = dict(old_cases[0])

    cases: list[dict] = []
    for row in rows:
        snippets = conn.execute(
            '''
            SELECT text
            FROM chunks
            WHERE material_id=?
            ORDER BY CASE WHEN embedding IS NOT NULL THEN 0 ELSE 1 END, id
            LIMIT 3
            ''',
            (row["id"],),
        ).fetchall()
        clues = []
        for item in snippets:
            text = " ".join(str(item["text"] or "").split())
            if text:
                clues.append(text[:420])
        if not clues:
            continue

        try:
            topics = json.loads(row["topics_json"] or "[]")
        except Exception:
            topics = []
        topics = [str(x) for x in topics if str(x).strip()]

        title = str(row["title"] or "").strip()
        target = str(row["target"] or "").strip()
        year = str(row["year"] or "").strip()
        material_type = str(row["material_type"] or "").strip()
        source_url = str(row["source_url"] or "").strip() or ARCHIVE_URL
        opening = (
            f"'{title}' 자료에서 가장 먼저 확인하고 싶은 개념이나 활동을 하나 골라, "
            "자료에 적힌 내용을 근거로 자신의 생각을 설명해보세요."
        )

        case = dict(template)
        for key in (
            "archive_url", "archive_title", "archive_year", "archive_category",
            "video_url", "youtube_id", "context_url", "context_label", "context_summary",
        ):
            case.pop(key, None)
        case.update(
            {
                "id": f"education_{int(row['id']):04d}",
                "label": "리터러시 교육 안내서",
                "title": title,
                "claim": "공식 디지털윤리 교육자료의 개념과 활동을 읽고 직접 적용하는 학습 자료입니다.",
                "source_name": "디지털윤리 교육자료실",
                "source_url": source_url,
                "source_excerpt": " · ".join(x for x in (target, year, material_type) if x),
                "clues": clues,
                "resolution": "이 자료의 원문과 활동 문항을 근거로 개념을 이해하고, 자신의 판단과 행동으로 직접 적용합니다.",
                "opening_questions": [opening],
                "opening_question": opening,
                "db_tables": ["education.materials", "education.chunks"],
                "data_rows": [
                    {"label": "대상", "value": target or "-"},
                    {"label": "연도", "value": year or "-"},
                    {"label": "자료유형", "value": material_type or "-"},
                    {"label": "주제", "value": " · ".join(topics) if topics else "-"},
                    {
                        "label": "임베딩",
                        "value": f"{int(row['embedded_chunk_count'] or 0)}/{int(row['chunk_count'])}",
                    },
                ],
                "data_note": "디지털윤리 교육자료실에서 수집·추출한 초·중·고 대상 공식 교육자료를 사용합니다.",
                "education_material_id": int(row["id"]),
                "education_target": target,
                "education_year": year,
                "education_material_type": material_type,
                "education_topics": topics,
                "education_chunk_count": int(row["chunk_count"]),
                "education_embedded_chunk_count": int(row["embedded_chunk_count"] or 0),
            }
        )
        cases.append(case)

    conn.close()
    return cases


def _education_fts_context(case: dict, user_message: str, limit: int = 4) -> list[str]:
    # Retrieve grounded chunks from the selected official material without any API call.
    material_id = int(case.get("education_material_id") or 0)
    if not material_id or not EDU_DB.exists():
        return [str(x) for x in (case.get("clues") or []) if str(x).strip()][:limit]

    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", str(user_message or ""))
    tokens = list(dict.fromkeys(tokens))[:10]
    if not tokens:
        return [str(x) for x in (case.get("clues") or []) if str(x).strip()][:limit]

    match = " OR ".join(f'"{token.replace(chr(34), " ")}"' for token in tokens)
    conn = sqlite3.connect(EDU_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            '''
            SELECT c.text, c.page_start, c.page_end, bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.id=chunks_fts.rowid
            WHERE chunks_fts MATCH ? AND c.material_id=?
            ORDER BY rank
            LIMIT ?
            ''',
            (match, material_id, limit),
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()

    context = []
    for row in rows:
        text = " ".join(str(row["text"] or "").split())
        if text:
            context.append(text[:650])
    if context:
        return context
    return [str(x) for x in (case.get("clues") or []) if str(x).strip()][:limit]


EDUCATION_CASES = _education_cases()
if EDUCATION_CASES:
    flow.CASE_LIBRARY["deepfake"] = EDUCATION_CASES
    flow.CASE_BY_ID.clear()
    flow.CASE_BY_ID.update(
        {
            case["id"]: (lesson_id, case)
            for lesson_id, lesson_cases in flow.CASE_LIBRARY.items()
            for case in lesson_cases
        }
    )

    base.LESSONS["deepfake"].update(
        {
            "title": "리터러시 교육 안내서",
            "short": "초·중·고 디지털윤리 교육 안내서의 개념과 활동을 읽고 직접 적용합니다.",
            "source_name": "디지털윤리 교육자료실",
            "source_url": ARCHIVE_URL,
            "source_role": "공식 디지털윤리 교육자료",
            "source_note": "초·중·고 대상 디지털윤리 교육 안내서와 활동 자료를 수집해 학습 자료로 사용합니다.",
            "criteria": [
                "자료에 적힌 개념과 활동 지시를 먼저 확인한다.",
                "사실·해석·의견을 구분해 자신의 말로 설명한다.",
                "정보의 출처와 근거를 확인하고 필요한 경우 교차검증한다.",
                "디지털 환경에서 안전하고 책임 있는 행동으로 연결한다.",
                "AI가 대신 결론 내리게 하기보다 학생이 직접 판단하고 답한다.",
            ],
            "skills": ["정보판별", "디지털 안전", "AI 윤리", "디지털 소통"],
            "safety_note": "",
        }
    )


_OLD_PUBLIC_CASE = flow._public_case


def _public_case_v15(case):
    data = dict(_OLD_PUBLIC_CASE(case))
    if str(case.get("id") or "").startswith("education_"):
        for key in (
            "source_url", "education_material_id", "education_target", "education_year",
            "education_material_type", "education_topics", "education_chunk_count",
            "education_embedded_chunk_count",
        ):
            data[key] = case.get(key, "")
    return data


flow._public_case = _public_case_v15

# v10 학습 프롬프트는 기존 KOBACO 주제에 그대로 두고,
# 교육자료 사례에서만 실제 교육자료 청크를 추가 근거로 넣습니다.
# 이 단계는 API를 쓰지 않는 FTS 검색이므로 임베딩이 일부만 완료돼도 동작합니다.
try:
    v10 = previous.previous.v11.previous
    _OLD_LEARNING_PROMPT = v10._learning_prompt

    def _learning_prompt_v15(session_id, user_message, lesson_id, case_id, case):
        prompt = _OLD_LEARNING_PROMPT(session_id, user_message, lesson_id, case_id, case)
        if str(case_id).startswith("education_"):
            prompt = prompt.replace("초등 고학년~중학생", "초·중·고 학생")
            evidence = _education_fts_context(case, user_message)
            evidence_block = "\n".join(f"- {item}" for item in evidence) or "- 검색된 근거 없음"
            prompt += f'''

[공식 교육자료 검색 근거]
대상: {case.get('education_target') or '-'}
자료명: {case.get('title') or '-'}
{evidence_block}

추가 규칙:
- 위 공식 교육자료 검색 근거에 없는 내용을 해당 안내서에 적혀 있다고 말하지 않는다.
- 학생의 답을 대신 완성하지 말고, 근거를 짚은 뒤 학생이 다시 판단하게 한다.
- 자료의 대상 학교급과 학생 수준을 고려해 표현 난이도를 조절한다.
'''
        return prompt

    v10._learning_prompt = _learning_prompt_v15
except Exception:
    pass


def _render_index_kobaco_v15():
    page = previous._render_index_kobaco_v14()
    page = page.replace("공익광고 효과 수치 제대로 읽기", "리터러시 교육 안내서")
    page = page.replace(
        "인지경로·신뢰성·기억요인처럼 서로 다른 조사 지표를 같은 ‘효과’ 숫자로 뭉뚱그리지 않는 법을 연습합니다.",
        "초·중·고 디지털윤리 교육 안내서의 개념과 활동을 읽고, 자료에 근거해 직접 생각하고 답합니다.",
    )
    page = page.replace("KOBACO 공익광고 효과평가 DB", "디지털윤리 교육자료 DB · 초·중·고")

    patch = r'''
<style>
.education-guide-preview{height:82px;margin:-10px -10px 9px;border-radius:7px;background:#eef3fb;border:1px solid #d6dfef;padding:10px;box-sizing:border-box;display:flex;flex-direction:column;justify-content:flex-end;gap:3px}
.education-guide-preview b{font-size:10px;color:#234b88}.education-guide-preview span{font-size:8px;color:#66758a}
.education-guide-card{border:1px solid #ddd5ca;border-radius:8px;background:#fff;overflow:hidden}.education-guide-head{padding:15px 16px;background:#f6f8fc;border-bottom:1px solid #e2e6ee}.education-guide-head small{display:block;font-size:8px;color:#6b778a;margin-bottom:4px}.education-guide-head b{font-size:14px}.education-guide-meta{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;padding:12px 14px}.education-guide-meta div{padding:9px;border:1px solid #ebe6df;border-radius:6px}.education-guide-meta small{display:block;font-size:8px;color:#847b72}.education-guide-meta b{display:block;margin-top:3px;font-size:10px}.education-guide-source{padding:0 14px 13px}.education-guide-source a{font-size:9px;color:#2d66ba;text-decoration:none}.education-guide-source a:hover{text-decoration:underline}
@media(max-width:700px){.education-guide-meta{grid-template-columns:1fr 1fr}}
</style>
<script>
(() => {
  const allEducationCases = Array.isArray(fixedTopicCases?.deepfake) ? [...fixedTopicCases.deepfake] : [];

  const previewBeforeEducation = window.fixedPreview;
  window.fixedPreview = function(c){
    const id=String(c?.id||'');
    if(id.startsWith('education_')){
      const target=c.education_target||'초·중·고';
      const year=c.education_year||'';
      return `<div class="education-guide-preview"><b>${esc(target)}</b><span>${esc([year,c.education_material_type].filter(Boolean).join(' · ')||'디지털윤리 교육자료')}</span></div>`;
    }
    return previewBeforeEducation(c);
  };

  const caseMediaBeforeEducation = window.caseMedia;
  window.caseMedia = function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return caseMediaBeforeEducation(c);
    const rows={};(c.data_rows||[]).forEach(r=>rows[String(r.label||'')]=String(r.value||''));
    const source=c.source_url?`<a href="${esc(c.source_url)}" target="_blank" rel="noopener">공식 자료 페이지 ↗</a>`:'';
    return `<div class="chat-case-media"><div class="education-guide-card"><div class="education-guide-head"><small>리터러시 교육 안내서</small><b>${esc(c.title||'디지털윤리 교육자료')}</b></div><div class="education-guide-meta"><div><small>대상</small><b>${esc(rows['대상']||'-')}</b></div><div><small>연도</small><b>${esc(rows['연도']||'-')}</b></div><div><small>자료유형</small><b>${esc(rows['자료유형']||'-')}</b></div><div><small>주제</small><b>${esc(rows['주제']||'-')}</b></div></div><div class="education-guide-source">${source}</div></div></div>`;
  };

  function rewriteEducationCard(){
    const card=document.querySelector('.lesson-card[data-lesson="deepfake"]');
    if(!card) return;
    const walker=document.createTreeWalker(card,NodeFilter.SHOW_TEXT);
    const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(node=>{
      const t=node.nodeValue||'';
      if(t.includes('공익광고 효과 수치 제대로 읽기')) node.nodeValue=t.replace('공익광고 효과 수치 제대로 읽기','리터러시 교육 안내서');
      else if(t.includes('인지경로')||t.includes('신뢰성')||t.includes('기억요인')) node.nodeValue='초·중·고 디지털윤리 교육 안내서의 개념과 활동을 읽고, 자료에 근거해 직접 생각하고 답합니다.';
      else if(t.includes('공익광고 효과평가')) node.nodeValue=t.replace(/KOBACO\s*공익광고\s*효과평가\s*DB/g,'디지털윤리 교육자료 DB · 초·중·고');
    });
  }

  async function currentAuth(){
    try{
      const r=await fetch('/api/auth/me',{credentials:'same-origin'});
      if(!r.ok) return null;
      const d=await r.json();
      return d.logged_in?d.user:null;
    }catch(e){return null;}
  }

  function schoolMatches(c,user){
    const target=String(c.education_target||'');
    if(!user?.school_level) return true;
    if(user.school_level==='초') return target.includes('초');
    if(user.school_level==='중') return target.includes('중');
    if(user.school_level==='고') return target.includes('고');
    return true;
  }

  function gradeScore(c,user){
    const text=`${c.education_target||''} ${c.title||''}`;
    const grade=Number(user?.grade||0);
    if(user?.school_level==='초'){
      if(grade>0 && grade<=3 && /(저학년|1.?3학년|1~3학년)/.test(text)) return 4;
      if(grade>=4 && /(고학년|4.?6학년|4~6학년)/.test(text)) return 4;
      if(/초등/.test(text)) return 2;
    }
    if(user?.school_level==='중' && /중등|중학생/.test(text)) return 2;
    if(user?.school_level==='고' && /고등|고등학생/.test(text)) return 2;
    return 1;
  }

  document.addEventListener('click',async e=>{
    const card=e.target.closest?.('.lesson-card');
    if(!card) return;
    e.preventDefault();e.stopImmediatePropagation();
    const user=await currentAuth();
    if(!user){
      const box=document.getElementById('aioff-login-required');
      if(box){box.classList.add('show');clearTimeout(box._t);box._t=setTimeout(()=>box.classList.remove('show'),3500);}
      return;
    }
    const lesson=card.dataset.lesson;
    if(lesson==='deepfake' && allEducationCases.length){
      const filtered=allEducationCases.filter(c=>schoolMatches(c,user));
      const usable=(filtered.length?filtered:allEducationCases)
        .map((c,i)=>({c,i,s:gradeScore(c,user)}))
        .sort((a,b)=>b.s-a.s||a.i-b.i)
        .map(x=>x.c);
      fixedTopicCases.deepfake=usable;
      delete fixedSamples.deepfake;
    }
    selectedLesson=lesson;
    document.querySelectorAll('.lesson-card').forEach(x=>x.classList.toggle('selected',x===card));
    showCaseChooser(lesson);
  },true);

  rewriteEducationCard();
  setTimeout(rewriteEducationCard,300);
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v15():
    return HTMLResponse(_render_index_kobaco_v15())
