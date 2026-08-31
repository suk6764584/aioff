from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List, Literal
from pathlib import Path
import sqlite3, uuid, os, json

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "aioff.db"
ENV_PATH = BASE_DIR / ".env"
DEFAULT_MODEL = "gemini-3.7-flash"


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


class EvaluationItem(BaseModel):
    question_id: int
    skill: str
    score: int = Field(ge=0, le=100)
    level: Literal["확인됨", "부분 확인", "추가 확인 필요"]
    feedback: str


class EvaluationResult(BaseModel):
    results: List[EvaluationItem]
    overall_summary: str


def gemini_client():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "GEMINI_API_KEY가 설정되지 않았습니다.")
    try:
        from google import genai
        return genai.Client(api_key=key)
    except ImportError:
        raise HTTPException(503, "google-genai 패키지가 설치되지 않았습니다.")


def model_name():
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def messages(session_id: str, limit: int = 40):
    with connect_db() as c:
        rows = c.execute("SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?", (session_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def transcript(session_id: str):
    return "\n".join(f"{'학생' if m['role']=='user' else 'AI'}: {m['content']}" for m in messages(session_id))


def structured(response, cls):
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        return parsed if isinstance(parsed, cls) else cls.model_validate(parsed)
    return cls.model_validate_json(response.text)


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "service": "AI OFF", "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()), "model": model_name()}


@app.post("/api/chat")
def chat(req: ChatRequest):
    client = gemini_client()
    sid = req.session_id or str(uuid.uuid4())
    with connect_db() as c:
        c.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)", (sid,))
        c.execute("INSERT INTO messages(session_id, role, content) VALUES(?, 'user', ?)", (sid, req.message))

    prior = messages(sid, 18)[:-1]
    history = "\n".join(f"{'학생' if m['role']=='user' else '튜터'}: {m['content']}" for m in prior)
    prompt = f"""너는 중·고등학생의 수행평가와 학습을 돕는 AI 튜터다.
학생 대신 과제를 통째로 완성하기보다 학생이 스스로 판단할 수 있도록 설명, 질문, 예시를 제공한다.
학생이 요청한 초안·구조·근거는 필요한 범위에서 도울 수 있다.
확인되지 않은 사실·통계·출처는 만들지 말고 검증이 필요하면 명시한다.
답변은 한국어로 자연스럽고 간결하게 작성한다.

[이전 대화]
{history or '(없음)'}

[학생의 새 요청]
{req.message}"""
    try:
        r = client.models.generate_content(model=model_name(), contents=prompt)
        reply = (r.text or "").strip()
        if not reply:
            raise ValueError("empty")
    except Exception as e:
        raise HTTPException(502, f"Gemini 응답 오류: {type(e).__name__}")

    with connect_db() as c:
        c.execute("INSERT INTO messages(session_id, role, content) VALUES(?, 'assistant', ?)", (sid, reply))
    return {"session_id": sid, "reply": reply}


@app.post("/api/analyze")
def analyze(req: SessionRequest):
    client = gemini_client()
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
top_skills는 위임 정도가 큰 기능 3개를 순서대로 넣는다.
학생의 성향이나 장기 능력을 단정하지 않는다."""
    try:
        r = client.models.generate_content(model=model_name(), contents=prompt, config={"response_mime_type":"application/json", "response_schema":AnalysisResult})
        result = structured(r, AnalysisResult)
    except Exception as e:
        raise HTTPException(502, f"Gemini 분석 오류: {type(e).__name__}")
    data = result.model_dump()
    with connect_db() as c:
        c.execute("INSERT INTO analyses(session_id,result_json) VALUES(?,?) ON CONFLICT(session_id) DO UPDATE SET result_json=excluded.result_json, created_at=CURRENT_TIMESTAMP", (req.session_id, json.dumps(data, ensure_ascii=False)))
    return data


@app.post("/api/off-test")
def off_test(req: SessionRequest):
    client = gemini_client()
    tx = transcript(req.session_id)
    with connect_db() as c:
        row = c.execute("SELECT result_json FROM analyses WHERE session_id=?", (req.session_id,)).fetchone()
    analysis = json.loads(row["result_json"]) if row else analyze(req)
    top = analysis["top_skills"][:3]
    prompt = f"""학생의 학습 대화:
{tx}

AI 위임이 큰 기능: {', '.join(top)}

각 기능에 대해 학생이 AI 없이 직접 수행할 수 있는지 확인하는 짧은 문제를 정확히 3개 생성하라.
방금 대화의 실제 주제와 내용을 활용한다.
단순 암기가 아니라 해당 사고 기능을 직접 수행해야 풀 수 있게 한다.
각 문제는 2~5분 안에 답할 수 있어야 한다.
정답이나 모범답안을 질문에 포함하지 않는다.
skill은 제시된 상위 기능 중 하나를 사용한다.
evaluation_criteria는 채점 핵심 기준 2~4개를 적는다."""
    try:
        r = client.models.generate_content(model=model_name(), contents=prompt, config={"response_mime_type":"application/json", "response_schema":OffTestResult})
        result = structured(r, OffTestResult)
    except Exception as e:
        raise HTTPException(502, f"AI OFF 문제 생성 오류: {type(e).__name__}")

    out = []
    with connect_db() as c:
        c.execute("DELETE FROM off_questions WHERE session_id=?", (req.session_id,))
        c.execute("DELETE FROM off_results WHERE session_id=?", (req.session_id,))
        for q in result.questions[:3]:
            cur = c.execute("INSERT INTO off_questions(session_id,skill,question,why_this_question,criteria_json) VALUES(?,?,?,?,?)", (req.session_id, q.skill, q.question, q.why_this_question, json.dumps(q.evaluation_criteria, ensure_ascii=False)))
            out.append({"question_id":cur.lastrowid, **q.model_dump()})
    return {"questions": out}


@app.post("/api/off-submit")
def off_submit(req: SubmitOffRequest):
    client = gemini_client()
    if not req.answers:
        raise HTTPException(400, "제출된 답변이 없습니다.")
    ids = [a.question_id for a in req.answers]
    marks = ",".join("?" for _ in ids)
    with connect_db() as c:
        rows = c.execute(f"SELECT id,skill,question,criteria_json FROM off_questions WHERE session_id=? AND id IN ({marks})", [req.session_id] + ids).fetchall()
    qmap = {r["id"]:r for r in rows}
    items = []
    for a in req.answers:
        q = qmap.get(a.question_id)
        if q:
            items.append({"question_id":a.question_id, "skill":q["skill"], "question":q["question"], "criteria":json.loads(q["criteria_json"]), "answer":a.answer})
    prompt = f"""다음은 AI OFF 단계에서 학생이 AI 도움 없이 작성한 답변이다.

{json.dumps(items, ensure_ascii=False, indent=2)}

각 답변을 기준에 따라 평가하라.
목표는 성적이 아니라 AI에 위임했던 사고 기능을 독립적으로 수행했는지 확인하는 것이다.
score는 독립 수행 확인 정도 0~100이다.
75 이상은 확인됨, 45~74는 부분 확인, 0~44는 추가 확인 필요로 분류한다.
표현보다 사고 수행 여부를 우선한다.
학생의 인격·지능·장기 능력을 판단하지 않는다.
feedback에는 잘한 점과 다음에 직접 해볼 한 가지를 짧게 적는다.
question_id와 skill은 입력값을 그대로 유지한다."""
    try:
        r = client.models.generate_content(model=model_name(), contents=prompt, config={"response_mime_type":"application/json", "response_schema":EvaluationResult})
        result = structured(r, EvaluationResult)
    except Exception as e:
        raise HTTPException(502, f"AI OFF 답변 평가 오류: {type(e).__name__}")

    answer_map = {a.question_id:a.answer for a in req.answers}
    with connect_db() as c:
        c.execute("DELETE FROM off_results WHERE session_id=?", (req.session_id,))
        for x in result.results:
            c.execute("INSERT INTO off_results(question_id,session_id,skill,answer,score,level,feedback) VALUES(?,?,?,?,?,?,?)", (x.question_id, req.session_id, x.skill, answer_map.get(x.question_id, ""), x.score, x.level, x.feedback))
    return result.model_dump()
