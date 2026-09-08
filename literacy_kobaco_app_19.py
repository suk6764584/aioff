from __future__ import annotations

import mimetypes
import sqlite3
import zipfile
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pypdf import PdfReader

import literacy_kobaco_app_18 as previous

app = previous.app
base = previous.base
flow = previous.flow

BASE_DIR = Path(__file__).resolve().parent
EDU_DB = BASE_DIR / "data" / "education" / "education.db"
EDU_FILES = (BASE_DIR / "data" / "education" / "files").resolve()
_EDU_THUMB_CACHE: dict[int, tuple[bytes, str]] = {}


def _education_case(case_id: str) -> dict:
    found = flow.CASE_BY_ID.get(case_id)
    if not found or not str(case_id).startswith("education_"):
        raise HTTPException(404, "교육자료를 찾을 수 없습니다.")
    return found[1]


def _safe_local_path(raw: str) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        resolved = path.resolve()
    except Exception:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    if EDU_FILES != resolved and EDU_FILES not in resolved.parents:
        return None
    return resolved


def _material_attachments(material_id: int) -> list[dict]:
    if not EDU_DB.exists():
        return []
    conn = sqlite3.connect(EDU_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, filename, local_path, mime_type
            FROM attachments
            WHERE material_id=? AND local_path<>''
            ORDER BY
              CASE
                WHEN LOWER(filename) LIKE '%.pdf' THEN 0
                WHEN LOWER(filename) LIKE '%.zip' THEN 1
                ELSE 2
              END,
              id
            """,
            (int(material_id),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _pdf_document(material_id: int) -> Path | None:
    attachments = _material_attachments(material_id)
    for item in attachments:
        path = _safe_local_path(str(item.get("local_path") or ""))
        if path and path.suffix.lower() == ".pdf":
            return path

    cache_dir = BASE_DIR / "data" / "education" / "preview_cache" / f"{material_id:04d}"
    cached = cache_dir / "document.pdf"
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    for item in attachments:
        path = _safe_local_path(str(item.get("local_path") or ""))
        if not path or path.suffix.lower() != ".zip":
            continue
        try:
            with zipfile.ZipFile(path) as zf:
                pdfs = [
                    info for info in zf.infolist()
                    if not info.is_dir()
                    and info.filename.lower().endswith(".pdf")
                    and "__macosx/" not in info.filename.lower()
                ]
                if not pdfs:
                    continue
                pdfs.sort(key=lambda x: (x.filename.count("/"), len(x.filename), x.filename))
                data = zf.read(pdfs[0])
                if not data.startswith(b"%PDF"):
                    continue
                cache_dir.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(data)
                return cached
        except Exception:
            continue
    return None


def _image_media(data: bytes, name: str = "") -> str | None:
    lower = name.lower()
    if data.startswith(b"\x89PNG\r\n\x1a\n") or lower.endswith(".png"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff") or lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if data.startswith(b"GIF8") or lower.endswith(".gif"):
        return "image/gif"
    if data[:4] in (b"RIFF",) and b"WEBP" in data[:16] or lower.endswith(".webp"):
        return "image/webp"
    guessed = mimetypes.guess_type(name)[0] if name else None
    return guessed if guessed and guessed.startswith("image/") else None


def _thumbnail_from_zip(path: Path) -> tuple[bytes, str] | None:
    try:
        with zipfile.ZipFile(path) as zf:
            candidates = [
                info for info in zf.infolist()
                if not info.is_dir()
                and Path(info.filename).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
                and 12_000 <= info.file_size <= 12_000_000
                and "__macosx/" not in info.filename.lower()
            ]
            if not candidates:
                return None
            candidates.sort(
                key=lambda info: (
                    0 if any(x in info.filename.lower() for x in ("표지", "cover", "01", "001")) else 1,
                    -info.file_size,
                    len(info.filename),
                )
            )
            for info in candidates[:20]:
                data = zf.read(info)
                media = _image_media(data, info.filename)
                if media:
                    return data, media
    except Exception:
        return None
    return None


def _thumbnail_from_pdf(path: Path) -> tuple[bytes, str] | None:
    try:
        reader = PdfReader(str(path))
    except Exception:
        return None

    best: tuple[bytes, str] | None = None
    best_size = 0
    for page in reader.pages[:8]:
        try:
            images = list(page.images)
        except Exception:
            continue
        for image in images:
            try:
                data = bytes(image.data)
                name = str(getattr(image, "name", "") or "")
            except Exception:
                continue
            if len(data) < 12_000:
                continue
            media = _image_media(data, name)
            if not media:
                continue
            if len(data) > best_size:
                best = (data, media)
                best_size = len(data)
    return best


def _fallback_thumb(case: dict) -> tuple[bytes, str]:
    title = str(case.get("title") or "리터러시 교육자료")
    target = str(case.get("education_target") or "")
    safe_title = (
        title.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    safe_target = (
        target.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
    <rect width="960" height="540" fill="#eef3fb"/>
    <rect x="42" y="42" width="876" height="456" rx="28" fill="#fff" stroke="#cfd9e8"/>
    <text x="78" y="110" fill="#2864b7" font-family="sans-serif" font-size="24" font-weight="700">리터러시 교육 안내서</text>
    <foreignObject x="78" y="160" width="805" height="230"><div xmlns="http://www.w3.org/1999/xhtml" style="font-family:sans-serif;color:#24313f;font-size:34px;font-weight:800;line-height:1.35">{safe_title}</div></foreignObject>
    <text x="78" y="448" fill="#68778a" font-family="sans-serif" font-size="22">{safe_target}</text>
    </svg>'''
    return svg.encode("utf-8"), "image/svg+xml"


for path in ("/api/education-file/{case_id}", "/api/education-thumb/{case_id}"):
    base._remove_route(path, "GET")


@app.get("/api/education-file/{case_id}")
def education_file_v19(case_id: str):
    case = _education_case(case_id)
    material_id = int(case.get("education_material_id") or 0)
    path = _pdf_document(material_id)
    if not path:
        raise HTTPException(404, "브라우저에서 바로 볼 수 있는 PDF 원문이 없습니다.")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


@app.get("/api/education-thumb/{case_id}")
def education_thumb_v19(case_id: str):
    case = _education_case(case_id)
    material_id = int(case.get("education_material_id") or 0)
    if material_id in _EDU_THUMB_CACHE:
        data, media = _EDU_THUMB_CACHE[material_id]
        return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=3600"})

    result: tuple[bytes, str] | None = None
    attachments = _material_attachments(material_id)

    # ZIP 안에 실제 JPG/PNG 학습 이미지가 있으면 우선 사용합니다.
    for item in attachments:
        path = _safe_local_path(str(item.get("local_path") or ""))
        if path and path.suffix.lower() == ".zip":
            result = _thumbnail_from_zip(path)
            if result:
                break

    if not result:
        pdf = _pdf_document(material_id)
        if pdf:
            result = _thumbnail_from_pdf(pdf)

    if not result:
        result = _fallback_thumb(case)

    _EDU_THUMB_CACHE[material_id] = result
    data, media = result
    return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=3600"})


def _render_index_kobaco_v19():
    page = previous._render_index_kobaco_v18()
    patch = r'''
<style>
/* LOGIN 상태: OFF는 회색 점, ON은 파란 점 하나. 로그아웃은 상태 아래쪽으로 내린다. */
.aioff-auth-state:before{display:none!important}
.aioff-login-indicator{
  display:inline-block;width:7px;height:7px;border-radius:50%;
  flex:0 0 7px;background:#aaa39a;margin-right:6px;vertical-align:1px;
}
.aioff-auth-dock.is-on .aioff-login-indicator{background:#2f75e8}
.aioff-auth-state{display:inline-flex!important;align-items:center!important}
.aioff-auth-dock.is-on .aioff-auth-links{
  position:absolute!important;top:28px!important;right:0!important;
  width:auto!important;height:auto!important;padding:0!important;margin:0!important;
  display:flex!important;background:transparent!important;border:0!important;box-shadow:none!important;
}
.aioff-auth-dock.is-on .aioff-auth-links button,
.aioff-auth-dock.is-on .aioff-auth-links button:first-of-type{
  min-width:78px!important;height:34px!important;padding:0 13px!important;
  border:1px solid #cfc7bc!important;border-radius:8px!important;
  background:#f7f3ed!important;color:#514b45!important;font-size:11px!important;font-weight:800!important;
}

/* 학교 autocomplete는 select와 같은 높이/정렬을 사용 */
.aioff-school-search.aioff-school-combobox{position:relative!important;display:block!important;width:100%!important}
.aioff-school-search.aioff-school-combobox:after{
  content:"";position:absolute;right:16px;top:20px;width:7px;height:7px;
  border-right:1.5px solid #302c28;border-bottom:1.5px solid #302c28;
  transform:rotate(45deg);pointer-events:none;z-index:3;
}
.aioff-school-search.aioff-school-combobox.is-open:after{transform:translateY(4px) rotate(225deg)}
#aioff-school-name{
  width:100%!important;height:42px!important;min-height:42px!important;box-sizing:border-box!important;
  padding:0 42px 0 12px!important;margin:0!important;line-height:40px!important;border-radius:8px!important;background:#fff!important;
}
.aioff-school-search.aioff-school-combobox.is-open #aioff-school-name{
  border-bottom-left-radius:0!important;border-bottom-right-radius:0!important;border-color:#bdb4a9!important;
}
#aioff-school-results{
  left:0!important;right:0!important;top:41px!important;width:100%!important;box-sizing:border-box!important;
  margin:0!important;max-height:250px!important;padding:0!important;overflow-y:auto!important;
  border:1px solid #bdb4a9!important;border-top:0!important;border-radius:0 0 8px 8px!important;
  background:#fff!important;box-shadow:0 9px 22px rgba(35,29,23,.14)!important;
}
#aioff-school-results:not(.open){display:none!important}#aioff-school-results.open{display:block!important}
#aioff-school-results.open:before{display:none!important}
#aioff-school-results .aioff-school-result{
  display:block!important;width:100%!important;min-height:48px!important;box-sizing:border-box!important;
  margin:0!important;padding:8px 12px!important;border:0!important;border-bottom:1px solid #ece5dc!important;
  border-radius:0!important;background:#fff!important;text-align:left!important;color:#2f2b27!important;line-height:1.25!important;
}
#aioff-school-results .aioff-school-result:hover,#aioff-school-results .aioff-school-result.is-active{background:#f2f5fa!important}
#aioff-school-results .aioff-school-result b{display:block!important;margin:0 0 3px!important;font-size:12px!important}
#aioff-school-results .aioff-school-result small{display:block!important;margin:0!important;font-size:10px!important;color:#756e67!important}

/* 교육자료 선택 카드: 실제 원문 이미지 썸네일 */
.education-guide-preview-v19{
  height:142px;margin:-10px -10px 9px;position:relative;overflow:hidden;border-radius:7px;background:#e8edf5;border:1px solid #d3dbe7;
}
.education-guide-preview-v19 img{width:100%;height:100%;display:block;object-fit:cover;background:#eef3fb}
.education-guide-preview-v19 .edu-chip{
  position:absolute;left:8px;bottom:8px;max-width:calc(100% - 16px);padding:4px 7px;border-radius:6px;
  background:rgba(22,31,43,.78);color:#fff;font-size:8px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}

/* 교육자료 학습 화면: 메타정보보다 실제 자료를 먼저 보여준다. */
.education-learning-card{border:1px solid #d9d2c9;border-radius:9px;background:#fff;overflow:hidden}
.education-learning-head{padding:13px 15px;background:#f7f9fc;border-bottom:1px solid #dfe5ee}
.education-learning-head small{display:block;font-size:8px;color:#66758a;margin-bottom:4px}.education-learning-head b{font-size:14px;line-height:1.4}
.education-document-shell{height:clamp(430px,63vh,720px);background:#3b3b3b;border-bottom:1px solid #ded8d0}
.education-document-shell iframe{display:block;width:100%;height:100%;border:0;background:#3b3b3b}
.education-learning-task{padding:14px 16px;background:#fff8ef;border-bottom:1px solid #eadfce}
.education-learning-task small{display:block;font-size:9px;color:#8a6b4f;font-weight:900;margin-bottom:5px}
.education-learning-task b{display:block;font-size:12px;line-height:1.55;color:#332b25}
.education-learning-meta{display:flex;gap:6px;flex-wrap:wrap;padding:10px 14px;background:#faf8f4;border-bottom:1px solid #e7e0d7}
.education-learning-meta span{padding:5px 8px;border:1px solid #ded6cb;border-radius:999px;background:#fff;font-size:9px;color:#645c54}
.education-learning-actions{display:flex;gap:8px;padding:10px 14px 13px;flex-wrap:wrap}
.education-learning-actions a{display:inline-flex;padding:7px 10px;border-radius:7px;text-decoration:none;font-size:9px;font-weight:850;background:#26221f;color:#fff!important}
.education-learning-actions a.alt{background:#fff;color:#2d2925!important;border:1px solid #cfc6ba}
@media(max-width:700px){.education-document-shell{height:56vh;min-height:380px}}
</style>
<script>
(() => {
  const dock=document.querySelector('.aioff-auth-dock');
  const state=dock?.querySelector('.aioff-auth-state');
  if(dock&&state){
    const prev=dock.previousElementSibling;
    if(prev && !(prev.textContent||'').trim()){
      const r=prev.getBoundingClientRect();
      if(r.width<=16 && r.height<=16) prev.style.display='none';
    }
    if(!state.querySelector('.aioff-login-indicator')){
      const dot=document.createElement('span');
      dot.className='aioff-login-indicator';
      dot.setAttribute('aria-hidden','true');
      state.prepend(dot);
    }
  }

  const schoolInput=document.getElementById('aioff-school-name');
  const schoolWrap=schoolInput?.closest('.aioff-school-search');
  const schoolBox=document.getElementById('aioff-school-results');
  if(schoolInput&&schoolWrap&&schoolBox){
    schoolWrap.classList.add('aioff-school-combobox');
    schoolInput.setAttribute('autocomplete','off');
    schoolInput.setAttribute('role','combobox');
    schoolInput.setAttribute('aria-autocomplete','list');
    schoolInput.setAttribute('aria-controls','aioff-school-results');
    schoolInput.setAttribute('spellcheck','false');
    function syncOpen(){
      const open=schoolBox.classList.contains('open');
      schoolWrap.classList.toggle('is-open',open);
      schoolInput.setAttribute('aria-expanded',open?'true':'false');
    }
    syncOpen();
    new MutationObserver(syncOpen).observe(schoolBox,{attributes:true,attributeFilter:['class']});
  }

  const educationPool19=Array.isArray(fixedTopicCases?.deepfake)?[...fixedTopicCases.deepfake]:[];

  function strictLevelMatch(c,user){
    const target=String(c?.education_target||'').replace(/\s+/g,'');
    const level=user?.school_level||'';
    const hasElementary=/(초등|초등학생|초등학교|초)/.test(target);
    const hasMiddle=/(중등|중학생|중학교|중)/.test(target);
    const hasHigh=/(고등|고등학생|고등학교|고)/.test(target);
    const hasParent=/(학부모|보호자|교사|교직원)/.test(target);
    if(level==='초') return hasElementary && !hasMiddle && !hasHigh && !hasParent;
    if(level==='중') return hasMiddle && !hasElementary && !hasHigh && !hasParent;
    if(level==='고') return hasHigh && !hasElementary && !hasMiddle && !hasParent;
    return false;
  }

  function gradePriority(c,user){
    const text=`${c?.education_target||''} ${c?.title||''}`;
    const grade=Number(user?.grade||0);
    if(user?.school_level==='초'){
      if(grade<=3 && /(저학년|1.?3학년|1~3학년)/.test(text)) return 6;
      if(grade>=4 && /(고학년|4.?6학년|4~6학년)/.test(text)) return 6;
      if(/초등/.test(text)) return 3;
    }
    if(user?.school_level==='중' && /(중등|중학생|중학교)/.test(text)) return 3;
    if(user?.school_level==='고' && /(고등|고등학생|고등학교)/.test(text)) return 3;
    return 1;
  }

  const chooserBeforeV19=window.showCaseChooser;
  window.showCaseChooser=async function(lessonId){
    if(lessonId!=='deepfake') return chooserBeforeV19(lessonId);
    try{
      const r=await fetch('/api/auth/me',{credentials:'same-origin'});
      const data=r.ok?await r.json():{};
      const user=data.logged_in?data.user:null;
      if(user){
        const strict=educationPool19
          .filter(c=>strictLevelMatch(c,user))
          .map((c,i)=>({c,i,s:gradePriority(c,user)}))
          .sort((a,b)=>b.s-a.s||a.i-b.i)
          .map(x=>x.c);
        fixedTopicCases.deepfake=strict;
        delete fixedSamples.deepfake;
      }
    }catch(e){}
    return chooserBeforeV19(lessonId);
  };

  const previewBeforeV19=window.fixedPreview;
  window.fixedPreview=function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return previewBeforeV19(c);
    const target=c.education_target||'';
    const year=c.education_year||'';
    return `<div class="education-guide-preview-v19"><img src="/api/education-thumb/${encodeURIComponent(id)}" alt="${esc(c.title||'교육자료')} 썸네일" loading="lazy"><span class="edu-chip">${esc([target,year].filter(Boolean).join(' · '))}</span></div>`;
  };

  const mediaBeforeV19=window.caseMedia;
  window.caseMedia=function(c){
    const id=String(c?.id||'');
    if(!id.startsWith('education_')) return mediaBeforeV19(c);
    const rows={};(c.data_rows||[]).forEach(r=>rows[String(r.label||'')]=String(r.value||''));
    const question=c.opening_question||(Array.isArray(c.opening_questions)?c.opening_questions[0]:'')||'자료를 직접 보고, 가장 먼저 확인되는 사실과 자신의 생각을 구분해 적어보세요.';
    const source=c.source_url?`<a class="alt" href="${esc(c.source_url)}" target="_blank" rel="noopener">공식 자료 페이지 ↗</a>`:'';
    return `<div class="chat-case-media"><div class="education-learning-card">
      <div class="education-learning-head"><small>리터러시 교육 안내서 · 실제 원문 학습</small><b>${esc(c.title||'디지털윤리 교육자료')}</b></div>
      <div class="education-document-shell"><iframe src="/api/education-file/${encodeURIComponent(id)}#view=FitH" title="${esc(c.title||'교육자료')} 원문"></iframe></div>
      <div class="education-learning-task"><small>자료를 보면서 생각해보세요</small><b>${esc(question)}</b></div>
      <div class="education-learning-meta"><span>대상 ${esc(rows['대상']||'-')}</span><span>${esc(rows['연도']||'연도 -')}</span><span>${esc(rows['자료유형']||'자료유형 -')}</span></div>
      <div class="education-learning-actions"><a href="/api/education-file/${encodeURIComponent(id)}" target="_blank" rel="noopener">원문 크게 보기 ↗</a>${source}</div>
    </div></div>`;
  };
})();
</script>
'''
    return page.replace("</body>", patch + "\n</body>")


base._remove_route("/", "GET")


@app.get("/", response_class=HTMLResponse)
def kobaco_literacy_index_v19():
    return HTMLResponse(_render_index_kobaco_v19())
