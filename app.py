from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List
from pathlib import Path
import sqlite3
import uuid
import os
import json
import time
import logging

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "aioff.db"
ENV_PATH = BASE_DIR / ".env"

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"

logger = logging.getLogger("aioff")


def load_env_file():
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env_file()
app = FastAPI(title="AI OFF")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect_db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        c.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        c.execute("CREATE TABLE IF NOT EXISTS analyses(session_id TEXT PRIMARY KEY, result_json TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        c.execute("CREATE TABLE IF NOT EXISTS off_questions(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, skill TEXT NOT NULL, question TEXT NOT NULL, why_this_question TEXT NOT NULL, criteria_json TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
        c.execute("CREATE TABLE IF NOT EXISTS off_results(id INTEGER PRIMARY KEY AUTOINCREMENT, question_id INTEGER NOT NULL, session_id TEXT NOT NULL, skill TEXT NOT NULL, answer TEXT NOT NULL, score INTEGER, level TEXT, feedback TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")


init_db()


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class SessionRequest(BaseModel):
    session_id: str


class DelegationSkill(BaseModel):
    skill: str
    delegation: int = Field(ge=0, le=100)
    evidence: List[str]
    rationale: str


class AnalysisResult(BaseModel):
    scores: List[DelegationSkill]
    top_skills: List[str]
    summary: str


class OffQuestion(BaseModel):
    skill: str
    question: str
    why_this_question: str
    evaluation_criteria: List[str]


class OffTestResult(BaseModel):
    questions: List[OffQuestion]


class AnswerItem(BaseModel):
    question_id: int
    answer: str = Field(min_length=1, max_length=5000)


class SubmitOffRequest(BaseModel):
    session_id: str
    answers: List[AnswerItem]


class EvaluationDraftItem(BaseModel):
    question_id: int
    score: float
    feedback: str = ""


class EvaluationDraft(BaseModel):
    results: List[EvaluationDraftItem]
    overall_summary: str = ""


def gemini_model():
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def groq_model():
    return os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL


def gemini_client():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "GEMINI_API_KEY가 설정되지 않았습니다.")
    try:
        from google import genai
        return genai.Client(api_key=key)
    except ImportError:
        raise HTTPException(503, "google-genai 패키지가 설치되지 않았습니다.")


def groq_client():
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=key)
    except ImportError:
        return None


def groq_configured():
    return bool(os.getenv("GROQ_API_KEY", "").strip())


def messages(session_id: str, limit: int = 40):
    with connect_db() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def transcript(session_id: str):
    return "\n".join(
        f"{'학생' if m['role'] == 'user' else 'AI'}: {m['content']}"
        for m in messages(session_id)
    )


def student_requests(session_id: str):
    return [m["content"] for m in messages(session_id) if m["role"] == "user"]


def chat_prompt(session_id: str, user_message: str):
    prior = messages(session_id, 8)
    history = "\n".join(
        f"{'학생' if m['role'] == 'user' else '튜터'}: {m['content']}"
        for m in prior
    )
    return f"""너는 중·고등학생의 수행평가와 학습을 돕는 AI 튜터다.
학생 대신 과제를 통째로 완성하기보다 학생이 스스로 판단할 수 있도록 설명, 질문, 예시를 제공한다.
학생이 요청한 초안·구조·근거는 필요한 범위에서 도울 수 있다.
확인되지 않은 사실·통계·출처는 만들지 말고 검증이 필요하면 명시한다.
답변은 한국어로 자연스럽고 간결하게 작성한다.

[이전 대화]
{history or '(없음)'}

[학생의 새 요청]
{user_message}"""


def save_chat_exchange(session_id: str, user_message: str, reply: str):
    with connect_db() as c:
        c.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)", (session_id,))
        c.execute("INSERT INTO messages(session_id, role, content) VALUES(?, 'user', ?)", (session_id, user_message))
        c.execute("INSERT INTO messages(session_id, role, content) VALUES(?, 'assistant', ?)", (session_id, reply))


def error_code(exc):
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def extract_json_value(text: str):
    """Parse model JSON even when a fence or short preamble is present."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("model_json_empty")

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    starts = [i for i, ch in enumerate(stripped) if ch in "[{"]
    for start in starts:
        try:
            value, _ = decoder.raw_decode(stripped[start:])
            return value
        except json.JSONDecodeError:
            continue

    raise ValueError("model_json_invalid")


def validate_model_text(text: str, cls):
    value = extract_json_value(text)

    # Low-cost models sometimes return a bare list although the schema expects
    # a single wrapper object. Normalize only the two unambiguous list cases.
    if isinstance(value, list):
        if cls is OffTestResult:
            value = {"questions": value}
        elif cls is EvaluationDraft:
            value = {"results": value}

    return cls.model_validate(value)


def gemini_generate(prompt: str, config=None):
    client = gemini_client()
    last_error = None
    for attempt in range(2):
        try:
            kwargs = {"model": gemini_model(), "contents": prompt}
            if config is not None:
                kwargs["config"] = config
            return client.models.generate_content(**kwargs)
        except Exception as e:
            last_error = e
            code = error_code(e)
            if code == 429:
                raise
            if code not in {500, 502, 503, 504} or attempt == 1:
                raise
            time.sleep(0.6)
    raise last_error


def gemini_generate_text(prompt: str, config=None):
    response = gemini_generate(prompt, config=config)
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise ValueError("gemini_empty_response")
    return text


def gemini_generate_structured(prompt: str, cls):
    response = gemini_generate(
        prompt,
        config={"response_mime_type": "application/json", "response_schema": cls},
    )
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        try:
            return parsed if isinstance(parsed, cls) else cls.model_validate(parsed)
        except Exception:
            pass
    return validate_model_text((getattr(response, "text", None) or "").strip(), cls)


def groq_message_text(message):
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(getattr(item, "text", "") or getattr(item, "content", "") or ""))
        return "".join(parts).strip()
    return str(content or "").strip()


def groq_generate_text(prompt: str, max_output_tokens: int = 700):
    client = groq_client()
    if client is None:
        raise RuntimeError("GROQ_API_KEY_NOT_CONFIGURED")
    response = client.chat.completions.create(
        model=groq_model(),
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=max_output_tokens,
        temperature=0.3,
    )
    if not getattr(response, "choices", None):
        raise ValueError("groq_no_choices")
    text = groq_message_text(response.choices[0].message)
    if not text:
        raise ValueError("groq_empty_response")
    return text


def groq_generate_structured(prompt: str, cls, max_output_tokens: int = 900):
    client = groq_client()
    if client is None:
        raise RuntimeError("GROQ_API_KEY_NOT_CONFIGURED")
    response = client.chat.completions.create(
        model=groq_model(),
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=max_output_tokens,
        temperature=0.2,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": cls.__name__.lower(),
                "schema": cls.model_json_schema(),
                "strict": False,
            },
        },
    )
    if not getattr(response, "choices", None):
        raise ValueError("groq_no_choices")
    text = groq_message_text(response.choices[0].message)
    if not text:
        raise ValueError("groq_empty_response")
    return validate_model_text(text, cls)


def generate_text_with_fallback(prompt: str, gemini_config=None, max_output_tokens: int = 700):
    try:
        return gemini_generate_text(prompt, config=gemini_config), "gemini"
    except Exception as gemini_error:
        logger.warning(
            "Gemini text generation failed: %s code=%s",
            type(gemini_error).__name__,
            error_code(gemini_error),
        )
        if not groq_configured():
            raise gemini_error
        return groq_generate_text(prompt, max_output_tokens=max_output_tokens), "groq"


def generate_structured_with_fallback(prompt: str, cls, max_output_tokens: int = 900):
    """Success means API call, JSON parsing and schema validation all succeeded."""
    try:
        return gemini_generate_structured(prompt, cls), "gemini"
    except Exception as gemini_error:
        logger.warning(
            "Gemini structured generation failed: %s code=%s",
            type(gemini_error).__name__,
            error_code(gemini_error),
        )
        if not groq_configured():
            raise gemini_error
        return groq_generate_structured(
            prompt,
            cls,
            max_output_tokens=max_output_tokens,
        ), "groq"


def level_from_score(score: int):
    if score >= 75:
        return "확인됨"
    if score >= 45:
        return "부분 확인"
    return "추가 확인 필요"


def validate_evaluation(result: EvaluationDraft, expected_ids: set[int]):
    parsed = []
    seen = set()

    for item in result.results:
        question_id = int(item.question_id)
        if question_id not in expected_ids or question_id in seen:
            continue

        score = max(0, min(100, int(round(float(item.score)))))
        feedback = (item.feedback or "").strip()
        if not feedback:
            feedback = "답변의 핵심 내용을 평가기준과 다시 비교해 보세요."

        parsed.append({
            "question_id": question_id,
            "score": score,
            "level": level_from_score(score),
            "feedback": feedback,
        })
        seen.add(question_id)

    if seen != expected_ids:
        raise ValueError("evaluation_question_mismatch")

    overall_summary = (result.overall_summary or "").strip()
    if not overall_summary:
        overall_summary = "각 문항별 독립 수행 결과를 확인했습니다."

    return parsed, overall_summary


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "AI OFF",
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "model": gemini_model(),
        "fallback_configured": groq_configured(),
        "fallback_model": groq_model() if groq_configured() else None,
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    sid = req.session_id or str(uuid.uuid4())
    prompt = chat_prompt(sid, req.message)
    try:
        reply, provider = generate_text_with_fallback(prompt, max_output_tokens=700)
    except Exception as e:
        code = error_code(e)
        suffix = f" ({code})" if code else ""
        raise HTTPException(502, f"AI 응답 오류: {type(e).__name__}{suffix}")
    save_chat_exchange(sid, req.message, reply)
    return {"session_id": sid, "reply": reply, "provider": provider}


@app.post("/api/chat-stream")
def chat_stream(req: ChatRequest):
    sid = req.session_id or str(uuid.uuid4())
    prompt = chat_prompt(sid, req.message)

    def generate():
        reply_parts = []
        emitted = False
        gemini_error = None

        try:
            client = gemini_client()
            stream = client.models.generate_content_stream(
                model=gemini_model(),
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
            save_chat_exchange(sid, req.message, reply)
            return
        except Exception as e:
            gemini_error = e
            if emitted:
                yield "\n\n응답 전송이 중단되었습니다. 같은 질문을 다시 보내주세요."
                return

        if groq_configured():
            try:
                client = groq_client()
                stream = client.chat.completions.create(
                    model=groq_model(),
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=700,
                    temperature=0.3,
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
                save_chat_exchange(sid, req.message, reply)
                return
            except Exception as groq_error:
                logger.warning("Groq stream fallback failed: %s", type(groq_error).__name__)
                yield f"Gemini 오류 후 Groq 보조 응답도 실패했습니다: {type(groq_error).__name__}"
                return

        code = error_code(gemini_error)
        suffix = f" ({code})" if code else ""
        yield f"Gemini 응답 오류: {type(gemini_error).__name__}{suffix}"

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Session-Id": sid,
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/analyze")
def analyze(req: SessionRequest):
    tx = transcript(req.session_id)
    if not tx.strip():
        raise HTTPException(400, "분석할 학습 대화가 없습니다.")

    prompt = f"""다음은 학생과 AI 튜터의 실제 학습 대화다.

{tx}

학생이 AI에 어떤 사고 기능을 얼마나 위임했는지 분석하라.
반드시 자료 탐색, 주장 구성, 근거 판단, 반론 구성, 정보 검증의 5개 기능을 모두 평가한다.
delegation은 이번 세션에서 AI가 해당 핵심 사고를 대신 수행한 정도를 0~100으로 나타낸다.
단순히 질문했다는 이유만으로 높은 점수를 주지 않는다.
evidence는 실제 대화에서 확인되는 짧은 근거를 최대 2개 적는다.
top_skills에는 위임 정도가 0보다 큰 기능만 최대 3개를 높은 순서대로 넣는다.
0보다 큰 기능이 없으면 top_skills는 빈 배열로 둔다.
학생의 성향이나 장기 능력을 단정하지 않는다."""

    try:
        result, _ = generate_structured_with_fallback(
            prompt,
            AnalysisResult,
            max_output_tokens=900,
        )
    except Exception as e:
        logger.exception("Conversation analysis failed")
        raise HTTPException(502, f"대화 분석 오류: {type(e).__name__}")

    data = result.model_dump()
    ranked = sorted(data["scores"], key=lambda x: x["delegation"], reverse=True)
    data["top_skills"] = [x["skill"] for x in ranked if x["delegation"] > 0][:3]

    with connect_db() as c:
        c.execute(
            "INSERT INTO analyses(session_id,result_json) VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET result_json=excluded.result_json, created_at=CURRENT_TIMESTAMP",
            (req.session_id, json.dumps(data, ensure_ascii=False)),
        )
    return data


@app.post("/api/off-test")
def off_test(req: SessionRequest):
    tx = transcript(req.session_id)
    requests = student_requests(req.session_id)

    with connect_db() as c:
        row = c.execute(
            "SELECT result_json FROM analyses WHERE session_id=?",
            (req.session_id,),
        ).fetchone()

    analysis = json.loads(row["result_json"]) if row else analyze(req)
    ranked = sorted(analysis["scores"], key=lambda x: x["delegation"], reverse=True)
    top = [x["skill"] for x in ranked if x["delegation"] > 0][:3]

    if not top:
        raise HTTPException(
            400,
            "이번 세션에서는 AI에 의미 있게 위임한 사고 기능이 확인되지 않아 AI OFF 문제를 만들지 않았습니다.",
        )

    request_list = "\n".join(f"- {text}" for text in requests)

    prompt = f"""다음은 학생의 전체 학습 세션이다.

[학생이 실제로 요청한 내용]
{request_list}

[전체 대화]
{tx}

[이번 세션에서 의미 있게 AI에 위임한 사고 기능]
{', '.join(top)}

학생이 AI 없이 직접 수행할 수 있는지 확인하는 짧은 AI OFF 문제를 정확히 3개 생성하라.

중요한 주제 분배 규칙:
- 문제를 만들기 전에 학생 요청에서 서로 다른 학습 주제를 구분한다.
- 예: 이차함수와 상관계수는 서로 다른 학습 주제다.
- 서로 다른 주제가 2개이면 두 주제를 모두 반드시 포함하고 3문제를 2+1로 배분한다.
- 서로 다른 주제가 3개 이상이면 학습 비중이 큰 주요 주제 3개에서 각각 1문제씩 만든다.
- 한 주제만 있었다면 그 주제에서 3문제를 만든다.
- 이전에 다룬 독립적인 주제가 있는데 최신 주제 하나에 3문제를 모두 몰아서는 안 된다.
- 단순 인사나 같은 주제의 후속 질문은 별도 주제로 세지 않는다.

사고 기능 규칙:
- skill은 반드시 위에 제시된 의미 있는 위임 기능 중 하나만 사용한다.
- 위임 기능이 1개뿐이면 그 기능을 여러 문제에서 반복해서 사용해도 된다.
- 위임 점수가 0인 기능을 억지로 검증하지 않는다.

문제 작성 규칙:
- 방금 대화의 실제 주제와 내용을 활용한다.
- 단순 암기보다 해당 사고 기능을 직접 수행해야 풀 수 있게 한다.
- 각 문제는 2~5분 안에 답할 수 있어야 한다.
- 정답이나 모범답안을 질문에 포함하지 않는다.
- evaluation_criteria는 채점 핵심 기준 2~4개를 적는다."""

    try:
        result, _ = generate_structured_with_fallback(
            prompt,
            OffTestResult,
            max_output_tokens=1200,
        )
        if len(result.questions) < 3:
            raise ValueError("off_test_question_count")
    except Exception as e:
        logger.exception("AI OFF question generation failed")
        raise HTTPException(502, f"AI OFF 문제 생성 오류: {type(e).__name__}")

    out = []
    with connect_db() as c:
        c.execute("DELETE FROM off_questions WHERE session_id=?", (req.session_id,))
        c.execute("DELETE FROM off_results WHERE session_id=?", (req.session_id,))
        for q in result.questions[:3]:
            cur = c.execute(
                "INSERT INTO off_questions(session_id,skill,question,why_this_question,criteria_json) VALUES(?,?,?,?,?)",
                (
                    req.session_id,
                    q.skill,
                    q.question,
                    q.why_this_question,
                    json.dumps(q.evaluation_criteria, ensure_ascii=False),
                ),
            )
            out.append({"question_id": cur.lastrowid, **q.model_dump()})
    return {"questions": out}


@app.post("/api/off-submit")
def off_submit(req: SubmitOffRequest):
    if not req.answers:
        raise HTTPException(400, "제출된 답변이 없습니다.")

    ids = [a.question_id for a in req.answers]
    marks = ",".join("?" for _ in ids)
    with connect_db() as c:
        rows = c.execute(
            f"SELECT id,skill,question,criteria_json FROM off_questions WHERE session_id=? AND id IN ({marks})",
            [req.session_id] + ids,
        ).fetchall()

    qmap = {r["id"]: r for r in rows}
    answer_map = {a.question_id: a.answer for a in req.answers}
    items = []

    for a in req.answers:
        q = qmap.get(a.question_id)
        if q:
            items.append({
                "question_id": a.question_id,
                "skill": q["skill"],
                "question": q["question"],
                "criteria": json.loads(q["criteria_json"]),
                "answer": a.answer,
            })

    if len(items) != len(req.answers):
        raise HTTPException(400, "현재 세션의 AI OFF 문항과 제출 답변이 일치하지 않습니다.")

    prompt_blocks = []
    for i, item in enumerate(items, 1):
        criteria_text = "\n".join(f"- {x}" for x in item["criteria"])
        prompt_blocks.append(f"""[문항 {i}]
question_id: {item['question_id']}
사고 기능: {item['skill']}
질문: {item['question']}
학생 답변: {item['answer']}
평가기준:
{criteria_text}""")

    prompt = f"""다음은 학생이 AI OFF 단계에서 AI 도움 없이 직접 작성한 답변입니다.
질문, 학생 답변, 출제 시 저장된 평가기준만 사용하여 각 답변을 평가하세요.

{chr(10).join(prompt_blocks)}

평가 원칙:
- 각 문항의 score만 0~100 범위의 숫자로 판단하세요.
- 문장 표현의 화려함보다 평가기준에 해당하는 사고를 실제로 수행했는지 우선합니다.
- 확인되지 않은 내용을 학생이 맞게 썼다고 가정하지 마세요.
- feedback은 잘한 점과 부족한 점 또는 다음에 직접 확인할 점을 2~3문장으로 작성하세요.
- 학생의 지능, 성격, 장기 능력을 판단하지 마세요.
- question_id는 위에 제시된 값을 그대로 사용하세요.
- 등급(level)은 작성하지 마세요. 서버가 score로 계산합니다.
- 모든 question_id를 정확히 한 번씩 평가하세요.

반환 형식:
{{
  "results": [
    {{"question_id": 1, "score": 80, "feedback": "..."}}
  ],
  "overall_summary": "이번 AI OFF 수행에 대한 1~2문장 요약"
}}"""

    try:
        draft, _ = generate_structured_with_fallback(
            prompt,
            EvaluationDraft,
            max_output_tokens=900,
        )
        parsed_results, overall_summary = validate_evaluation(draft, set(ids))
    except Exception as e:
        logger.exception("AI OFF evaluation failed")
        raise HTTPException(502, f"AI OFF 답변 평가 오류: {type(e).__name__}")

    results = []
    with connect_db() as c:
        c.execute("DELETE FROM off_results WHERE session_id=?", (req.session_id,))
        for x in parsed_results:
            q = qmap[x["question_id"]]
            result_item = {
                "question_id": x["question_id"],
                "skill": q["skill"],
                "score": x["score"],
                "level": x["level"],
                "feedback": x["feedback"],
            }
            results.append(result_item)
            c.execute(
                "INSERT INTO off_results(question_id,session_id,skill,answer,score,level,feedback) VALUES(?,?,?,?,?,?,?)",
                (
                    x["question_id"],
                    req.session_id,
                    q["skill"],
                    answer_map.get(x["question_id"], ""),
                    x["score"],
                    x["level"],
                    x["feedback"],
                ),
            )

    return {"results": results, "overall_summary": overall_summary}
