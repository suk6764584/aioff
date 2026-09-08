from __future__ import annotations

import html
import re
from urllib.parse import urljoin

import requests
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response

import literacy_kobaco_app_21 as previous

app = previous.app
base = previous.base
flow = previous.flow


_AISAC_THUMB_CACHE: dict[str, tuple[bytes, str] | None] = {}
_AISAC_SEARCH_URL = "https://aisac.kobaco.co.kr/site/main/advideo/list_all_top"
_IMAGE_ATTR_RE = re.compile(r"(?:src|data-src|data-original)=[\"']([^\"']+)[\"']", re.I)
_IMAGE_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
_BG_IMAGE_RE = re.compile(r"url\([\"']?([^\"')]+)[\"']?\)", re.I)


def _aisac_image_score(url: str, distance: int) -> int:
    lower = url.lower()
    if any(x in lower for x in ("logo", "icon", "btn_", "button", "search", "close", "kakao", "common/", "loading", "blank")):
        return -10000
    score = max(0, 7000 - distance) // 100
    if any(x in lower for x in ("thumb", "thumbnail", "adv", "video", "upload", "file", "archive")):
        score += 35
    if re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", lower):
        score += 20
    return score


def _find_aisac_thumbnail(title: str) -> tuple[bytes, str] | None:
    title = str(title or "").strip()
    if not title:
        return None
    if title in _AISAC_THUMB_CACHE:
        return _AISAC_THUMB_CACHE[title]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
    }
    try:
        response = requests.get(
            _AISAC_SEARCH_URL,
            params={"kwdVal": title, "listType": "list", "pageSize": 12},
            headers=headers,
            timeout=8,
        )
        response.raise_for_status()
        text = response.text
        plain_title = html.unescape(title)
        pos = text.find(plain_title)
        if pos < 0:
            compact = re.sub(r"\s+", "", plain_title)
            compact_html = re.sub(r"\s+", "", html.unescape(text))
            compact_pos = compact_html.find(compact)
            pos = compact_pos if compact_pos >= 0 else len(text) // 2

        start = max(0, pos - 18000)
        end = min(len(text), pos + 18000)
        segment = text[start:end]
        local_title_pos = max(0, pos - start)
        candidates: list[tuple[int, str]] = []

        for match in _IMAGE_TAG_RE.finditer(segment):
            tag = match.group(0)
            attr = _IMAGE_ATTR_RE.search(tag)
            if not attr:
                continue
            raw_url = html.unescape(attr.group(1).strip())
            if not raw_url or raw_url.startswith("data:"):
                continue
            absolute = urljoin(response.url, raw_url)
            distance = abs(match.start() - local_title_pos)
            candidates.append((_aisac_image_score(absolute, distance), absolute))

        for match in _BG_IMAGE_RE.finditer(segment):
            raw_url = html.unescape(match.group(1).strip())
            if not raw_url or raw_url.startswith("data:"):
                continue
            absolute = urljoin(response.url, raw_url)
            distance = abs(match.start() - local_title_pos)
            candidates.append((_aisac_image_score(absolute, distance), absolute))

        candidates.sort(key=lambda x: x[0], reverse=True)
        seen: set[str] = set()
        for score, image_url in candidates:
            if score < 0 or image_url in seen:
                continue
            seen.add(image_url)
            try:
                image = requests.get(
                    image_url,
                    headers={**headers, "Referer": response.url},
                    timeout=8,
                )
                image.raise_for_status()
                media = str(image.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                data = image.content
                if media.startswith("image/") and len(data) >= 8000:
                    result = (data, media)
                    _AISAC_THUMB_CACHE[title] = result
                    return result
            except Exception:
                continue
    except Exception as exc:
        base.core.logger.warning("AiSAC thumbnail lookup failed: %s", type(exc).__name__)

    _AISAC_THUMB_CACHE[title] = None
    return None


def _aisac_fallback_svg(title: str) -> bytes:
    safe = html.escape(str(title or "AiSAC 광고"))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
      <rect width="1280" height="720" fill="#ece8e1"/>
      <rect x="48" y="48" width="1184" height="624" rx="28" fill="#fff" stroke="#d8d0c6"/>
      <text x="92" y="126" font-family="sans-serif" font-size="30" font-weight="800" fill="#356fe8">KOBACO AiSAC</text>
      <foreignObject x="92" y="190" width="1080" height="300"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:sans-serif;color:#292521;font-size:50px;font-weight:850;line-height:1.25">{safe}</div></foreignObject>
      <text x="92" y="606" font-family="sans-serif" font-size="24" fill="#7c746c">원본 광고 썸네일을 불러오지 못했습니다.</text>
    </svg>'''.encode("utf-8")


base._remove_route("/api/aioff-aisac-thumb/{case_id}", "GET")


@app.get("/api/aioff-aisac-thumb/{case_id}")
def aioff_aisac_thumb(case_id: str):
    found = flow.CASE_BY_ID.get(case_id)
    if not found or not str(case_id).startswith("kobaco_aisac_"):
        raise HTTPException(404, "AiSAC 광고 사례를 찾을 수 없습니다.")
    case = found[1]
    title = str(case.get("title") or "")
    result = _find_aisac_thumbnail(title)
    if result:
        data, media = result
        return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=3600"})
    return Response(
        _aisac_fallback_svg(title),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=600"},
    )


def _render_index_aioff_ui():
    page = previous._render_index_kobaco_v21()
    patch = r'''
<style>
/* 화면 폭을 넓게 쓰되 현재 기능/자료 구조는 그대로 유지한다. */
main{
  width:calc(100% - 24px)!important;
  max-width:1800px!important;
  margin:0 auto!important;
  padding-left:0!important;
  padding-right:0!important;
  padding-top:28px!important;
  padding-bottom:42px!important;
}
.workspace{width:100%!important;max-width:none!important}
.study-paper{width:100%!important;max-width:none!important}

/* 리터러시 사례 학습 제목 옆 AI ON만 제거. 상단 전역 상태표시는 건드리지 않는다. */
.study-paper>.paper-head .mode-label{display:none!important}

/* 사례 카드의 썸네일 영역을 카드 가로폭에 꽉 채운다. */
.chat-case-option{
  padding:0 0 13px!important;
  overflow:hidden!important;
}
.chat-case-option> b,
.chat-case-option> small{
  display:block!important;
  margin-left:14px!important;
  margin-right:14px!important;
  text-align:left!important;
}
.chat-case-option> b{margin-top:0!important}
.chat-case-option> small{margin-top:5px!important}
.education-guide-preview-v19,
.kobaco-picker-media,
.topic-preview{
  width:100%!important;
  height:230px!important;
  min-height:230px!important;
  margin:0 0 12px!important;
  border-radius:0!important;
}
.kobaco-picker-media img,
.aioff-aisac-preview img{
  display:block!important;
  width:100%!important;
  height:100%!important;
  object-fit:cover!important;
}
.education-guide-preview-v19{
  background:#eee9e1!important;
  overflow:hidden!important;
}
.education-guide-preview-v19 iframe{
  position:absolute!important;
  left:0!important;
  top:0!important;
  right:auto!important;
  bottom:auto!important;
  width:calc(100% + 18px)!important;
  height:calc(100% + 18px)!important;
  border:0!important;
  display:block!important;
  background:#fff!important;
  pointer-events:none!important;
}
.education-guide-preview-v19 .edu-chip{z-index:3!important}
.aioff-aisac-preview{position:relative;overflow:hidden;background:#eee9e1}
.aioff-aisac-preview:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,transparent 55%,rgba(0,0,0,.20));pointer-events:none}

/* 자료 영역 + 세로 입력 패널 */
.aioff-learning-columns{
  display:grid;
  grid-template-columns:minmax(0,1fr) clamp(320px,24vw,430px);
  min-height:calc(100vh - 150px);
  border-top:0;
}
.aioff-learning-columns>.chat-area{
  min-width:0;
  padding:18px 20px 18px 24px!important;
  border-right:1px solid var(--line);
}
.aioff-learning-columns .chat{
  height:calc(100vh - 205px)!important;
  min-height:760px!important;
  max-height:none!important;
  padding-bottom:18px!important;
}

.aioff-composer-side{
  min-width:0;
  display:flex;
  flex-direction:column;
  background:#fffdf9;
}
.aioff-composer-side-head{
  padding:18px 18px 14px;
  border-bottom:1px solid var(--line);
}
.aioff-composer-side-head strong{
  display:block;
  margin-bottom:4px;
  font-size:15px;
  color:var(--ink);
}
.aioff-composer-side-head span{
  display:block;
  font-size:11px;
  line-height:1.5;
  color:var(--muted);
}
.aioff-side-question{
  margin-top:12px;
  padding:12px 13px;
  border:1px solid #eadbc8;
  border-radius:10px;
  background:#fff8ee;
}
.aioff-side-question small{
  display:block;
  margin-bottom:5px;
  font-size:10px;
  font-weight:850;
  color:#9a5b30;
}
.aioff-side-question b{
  display:block;
  font-size:13px;
  line-height:1.55;
  color:#332b25;
}
.aioff-composer-side .composer-wrap{
  flex:1;
  min-height:0;
  display:flex;
  flex-direction:column;
  padding:16px 18px 18px!important;
}
.aioff-composer-side .composer{
  flex:1;
  min-height:0;
  display:flex!important;
  flex-direction:column!important;
  align-items:stretch!important;
  gap:12px!important;
  border-top:0!important;
  padding-top:0!important;
}
.aioff-composer-side .composer textarea{
  flex:1;
  width:100%!important;
  min-height:560px!important;
  max-height:none!important;
  resize:none!important;
  padding:16px!important;
  border-radius:12px!important;
  line-height:1.65!important;
  background:#fff!important;
}
.aioff-composer-side .send-btn{
  align-self:flex-end;
  min-width:96px;
  height:46px!important;
}
.aioff-composer-side .chat-status{
  margin-top:8px!important;
}

/* 큰 자료가 답답하지 않게 학습 카드 폭/높이를 확장한다. */
.education-study-v21{max-width:none!important;width:100%!important}
.education-study-v21-visual iframe{
  height:clamp(620px,72vh,920px)!important;
}
.education-study-v21-visual img{
  width:100%!important;
  max-height:900px!important;
  object-fit:contain!important;
}

/* 생각해보기는 한 문제씩만 보여준다. */
.education-study-v21-questions ol{padding-left:0!important;list-style:none!important}
.education-study-v21-questions li{display:none!important}
.education-study-v21-questions li.aioff-current-question{display:block!important;margin:0!important}
.education-study-v21-questions h4{display:flex!important;align-items:center!important;justify-content:space-between!important;gap:10px!important}
.aioff-question-progress{font-size:10px;font-weight:800;color:#9b6d4d}

@media(max-width:1180px){
  main{width:calc(100% - 20px)!important}
  .aioff-learning-columns{grid-template-columns:minmax(0,1fr) 320px}
  .aioff-composer-side .composer textarea{min-height:500px!important}
  .education-guide-preview-v19,.kobaco-picker-media,.topic-preview{height:205px!important;min-height:205px!important}
}
@media(max-width:900px){
  main{width:100%!important;padding-left:12px!important;padding-right:12px!important}
  .aioff-learning-columns{display:block;min-height:0}
  .aioff-learning-columns>.chat-area{border-right:0;padding:16px!important}
  .aioff-learning-columns .chat{height:680px!important;min-height:680px!important}
  .aioff-composer-side{border-top:1px solid var(--line)}
  .aioff-composer-side .composer textarea{min-height:220px!important}
  .education-study-v21-visual iframe{height:520px!important}
  .education-guide-preview-v19,.kobaco-picker-media,.topic-preview{height:170px!important;min-height:170px!important}
}
</style>
<script>
(() => {
  let activeEducationCard=null;
  let activeQuestions=[];
  let activeQuestionIndex=0;
  let lastUserMessageCount=0;

  function installWideLearningLayout(){
    const paper=document.querySelector('.study-paper');
    if(!paper || paper.querySelector('.aioff-learning-columns')) return;

    paper.querySelector(':scope > .paper-head .mode-label')?.remove();

    const chatArea=paper.querySelector(':scope > .chat-area');
    const composerWrap=paper.querySelector(':scope > .composer-wrap');
    if(!chatArea || !composerWrap) return;

    const columns=document.createElement('div');
    columns.className='aioff-learning-columns';
    paper.insertBefore(columns,chatArea);
    columns.appendChild(chatArea);

    const side=document.createElement('aside');
    side.className='aioff-composer-side';
    side.innerHTML='<div class="aioff-composer-side-head"><strong>생각 적기</strong><span>자료를 보면서 현재 질문 하나에 답해보세요.</span><div class="aioff-side-question" data-aioff-side-question style="display:none"><small data-aioff-side-progress></small><b data-aioff-side-text></b></div></div>';
    side.appendChild(composerWrap);
    columns.appendChild(side);

    const textarea=composerWrap.querySelector('textarea');
    if(textarea){
      textarea.placeholder='현재 질문에 대한 생각을 적어보세요.';
      textarea.setAttribute('aria-label','현재 질문에 대한 답변 입력');
    }
  }

  /* 교육자료 선택카드는 가짜 표지 대신 실제 PDF 첫 페이지를 그대로 썸네일로 사용한다. */
  const previewBeforeAioff=window.fixedPreview;
  if(typeof previewBeforeAioff==='function'){
    window.fixedPreview=function(c){
      const id=String(c?.id||'');
      if(id.startsWith('education_')){
        const target=c.education_target||'';
        const year=c.education_year||'';
        return `<div class="education-guide-preview-v19"><iframe src="/api/education-file/${encodeURIComponent(id)}#page=1&toolbar=0&navpanes=0&scrollbar=0&view=Fit" title="${esc(c.title||'교육자료')} 표지" loading="lazy"></iframe><span class="edu-chip">${esc([target,year].filter(Boolean).join(' · '))}</span></div>`;
      }
      if(id.startsWith('kobaco_aisac_')){
        return `<div class="kobaco-picker-media aioff-aisac-preview"><img src="/api/aioff-aisac-thumb/${encodeURIComponent(id)}" alt="${esc(c.title||'AiSAC 광고')} 썸네일" loading="lazy"></div>`;
      }
      return previewBeforeAioff(c);
    };
  }

  function updateQuestionUI(){
    if(!activeEducationCard || !activeQuestions.length) return;
    const items=[...activeEducationCard.querySelectorAll('.education-study-v21-questions li')];
    items.forEach((li,i)=>li.classList.toggle('aioff-current-question',i===activeQuestionIndex));

    const section=activeEducationCard.querySelector('.education-study-v21-questions');
    const heading=section?.querySelector('h4');
    if(heading){
      let progress=heading.querySelector('.aioff-question-progress');
      if(!progress){
        progress=document.createElement('span');
        progress.className='aioff-question-progress';
        heading.appendChild(progress);
      }
      progress.textContent=`${Math.min(activeQuestionIndex+1,activeQuestions.length)} / ${activeQuestions.length}`;
    }

    const side=document.querySelector('[data-aioff-side-question]');
    const sideProgress=document.querySelector('[data-aioff-side-progress]');
    const sideText=document.querySelector('[data-aioff-side-text]');
    if(side&&sideProgress&&sideText){
      side.style.display='block';
      sideProgress.textContent=`질문 ${Math.min(activeQuestionIndex+1,activeQuestions.length)} / ${activeQuestions.length}`;
      sideText.textContent=activeQuestions[activeQuestionIndex]||'';
    }

    const textarea=document.getElementById('input');
    if(textarea) textarea.placeholder=`질문 ${Math.min(activeQuestionIndex+1,activeQuestions.length)}에 대한 생각을 적어보세요.`;
  }

  function installSequentialQuestions(){
    const cards=[...document.querySelectorAll('.education-study-v21[data-loaded="1"]')];
    if(!cards.length) return;
    const card=cards[cards.length-1];
    if(card===activeEducationCard && card.dataset.aioffSeq==='1') return;

    const questions=[...card.querySelectorAll('.education-study-v21-questions li')]
      .map(li=>(li.textContent||'').trim()).filter(Boolean);
    if(!questions.length) return;

    activeEducationCard=card;
    activeQuestions=questions;
    activeQuestionIndex=0;
    card.dataset.aioffSeq='1';
    lastUserMessageCount=document.querySelectorAll('#chat .msg-row.user-row, #chat .msg.user').length;
    updateQuestionUI();
  }

  function advanceAfterAnswer(){
    if(!activeEducationCard || !activeQuestions.length) return;
    const count=document.querySelectorAll('#chat .msg-row.user-row, #chat .msg.user').length;
    if(count<=lastUserMessageCount) return;
    lastUserMessageCount=count;
    if(activeQuestionIndex < activeQuestions.length-1){
      activeQuestionIndex+=1;
      updateQuestionUI();
    }else{
      const sideProgress=document.querySelector('[data-aioff-side-progress]');
      if(sideProgress) sideProgress.textContent=`질문 ${activeQuestions.length} / ${activeQuestions.length} · 답변 완료`;
    }
  }

  function scan(){
    installWideLearningLayout();
    installSequentialQuestions();
    advanceAfterAnswer();
  }

  installWideLearningLayout();
  scan();
  new MutationObserver(scan).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['data-loaded']});
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def aioff_ui_index():
    return HTMLResponse(_render_index_aioff_ui())
