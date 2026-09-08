from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

import requests

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "users" / "users.db"
COOKIE_NAME = "aioff_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
PBKDF2_ROUNDS = 240_000

REGION_CODES = {
    "서울": "B10",
    "부산": "C10",
    "대구": "D10",
    "인천": "E10",
    "광주": "F10",
    "대전": "G10",
    "울산": "H10",
    "세종": "I10",
    "경기": "J10",
    "강원": "K10",
    "충북": "M10",
    "충남": "N10",
    "전북": "P10",
    "전남": "Q10",
    "경북": "R10",
    "경남": "S10",
    "제주": "T10",
}
SCHOOL_LEVEL_NAMES = {"초": "초등학교", "중": "중학교", "고": "고등학교"}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                school_level TEXT NOT NULL,
                school_region TEXT NOT NULL,
                school_name TEXT NOT NULL,
                school_code TEXT NOT NULL DEFAULT '',
                grade INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires ON auth_sessions(expires_at);
            """
        )
        conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (int(time.time()),))
        conn.commit()


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _normalize_phone(value: str) -> str:
    return re.sub(r"[^0-9]", "", value or "")


def validate_registration(data: dict[str, Any]) -> dict[str, Any]:
    email = _normalize_email(str(data.get("email") or ""))
    password = str(data.get("password") or "")
    name = str(data.get("name") or "").strip()
    phone = _normalize_phone(str(data.get("phone") or ""))
    school_level = str(data.get("school_level") or "").strip()
    school_region = str(data.get("school_region") or "").strip()
    school_name = str(data.get("school_name") or "").strip()
    school_code = str(data.get("school_code") or "").strip()

    try:
        grade = int(data.get("grade"))
    except Exception:
        grade = 0

    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("이메일 형식을 확인해 주세요.")
    if len(password) < 6 or len(password) > 100:
        raise ValueError("비밀번호는 6자 이상으로 입력해 주세요.")
    if not (1 <= len(name) <= 30):
        raise ValueError("이름을 입력해 주세요.")
    if len(phone) < 9 or len(phone) > 11:
        raise ValueError("전화번호를 확인해 주세요.")
    if school_level not in SCHOOL_LEVEL_NAMES:
        raise ValueError("학교급을 선택해 주세요.")
    if school_region not in REGION_CODES:
        raise ValueError("지역을 선택해 주세요.")
    if not school_name:
        raise ValueError("학교를 선택하거나 학교명을 입력해 주세요.")

    max_grade = 6 if school_level == "초" else 3
    if grade < 1 or grade > max_grade:
        raise ValueError("학년을 확인해 주세요.")

    return {
        "email": email,
        "password": password,
        "name": name,
        "phone": phone,
        "school_level": school_level,
        "school_region": school_region,
        "school_name": school_name,
        "school_code": school_code,
        "grade": grade,
    }


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "email": str(row["email"]),
        "name": str(row["name"]),
        "school_level": str(row["school_level"]),
        "school_region": str(row["school_region"]),
        "school_name": str(row["school_name"]),
        "school_code": str(row["school_code"] or ""),
        "grade": int(row["grade"]),
    }


def create_user(data: dict[str, Any]) -> dict[str, Any]:
    clean = validate_registration(data)
    salt = secrets.token_bytes(16)
    digest = _hash_password(clean.pop("password"), salt)
    now = int(time.time())

    try:
        with _connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO users(
                    email,password_hash,password_salt,name,phone,
                    school_level,school_region,school_name,school_code,grade,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    clean["email"],
                    base64.b64encode(digest).decode("ascii"),
                    base64.b64encode(salt).decode("ascii"),
                    clean["name"],
                    clean["phone"],
                    clean["school_level"],
                    clean["school_region"],
                    clean["school_name"],
                    clean["school_code"],
                    clean["grade"],
                    now,
                ),
            )
            user_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError("이미 가입된 이메일입니다.")

    return _public_user(row)


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    email = _normalize_email(email)
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not row:
        return None

    try:
        salt = base64.b64decode(row["password_salt"])
        expected = base64.b64decode(row["password_hash"])
    except Exception:
        return None

    actual = _hash_password(password, salt)
    if not hmac.compare_digest(actual, expected):
        return None
    return _public_user(row)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    expires = now + SESSION_TTL_SECONDS
    with _connect() as conn:
        conn.execute(
            "INSERT INTO auth_sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
            (_token_hash(token), int(user_id), now, expires),
        )
        conn.commit()
    return token


def current_user(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT u.*
            FROM auth_sessions s
            JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>=?
            """,
            (_token_hash(token), now),
        ).fetchone()
        conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (now,))
        conn.commit()
    return _public_user(row) if row else None


def delete_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_token_hash(token),))
        conn.commit()


def search_schools(region: str, school_level: str, query: str) -> dict[str, Any]:
    """Search official NEIS schoolInfo when a key is configured; allow manual fallback otherwise."""
    region = (region or "").strip()
    school_level = (school_level or "").strip()
    query = (query or "").strip()
    if region not in REGION_CODES:
        raise ValueError("지역을 선택해 주세요.")
    if school_level not in SCHOOL_LEVEL_NAMES:
        raise ValueError("학교급을 선택해 주세요.")
    if len(query) < 2:
        raise ValueError("학교명은 2글자 이상 입력해 주세요.")

    key = os.getenv("NEIS_API_KEY", "").strip()
    if not key:
        return {
            "configured": False,
            "items": [],
            "message": "학교 검색 API 키가 아직 설정되지 않았습니다. 프로토타입에서는 학교명을 직접 입력할 수 있습니다.",
        }

    params = {
        "KEY": key,
        "Type": "json",
        "pIndex": 1,
        "pSize": 30,
        "ATPT_OFCDC_SC_CODE": REGION_CODES[region],
        "SCHUL_KND_SC_NM": SCHOOL_LEVEL_NAMES[school_level],
        "SCHUL_NM": query,
    }
    response = requests.get("https://open.neis.go.kr/hub/schoolInfo", params=params, timeout=10)
    response.raise_for_status()
    payload = response.json()

    blocks = payload.get("schoolInfo") or []
    rows: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("row"), list):
            rows.extend(block["row"])

    items = []
    seen: set[str] = set()
    for row in rows:
        code = str(row.get("SD_SCHUL_CODE") or "").strip()
        name = str(row.get("SCHUL_NM") or "").strip()
        address = str(row.get("ORG_RDNMA") or row.get("ORG_RDNDA") or "").strip()
        if not name:
            continue
        marker = code or f"{name}|{address}"
        if marker in seen:
            continue
        seen.add(marker)
        items.append({"code": code, "name": name, "address": address})

    return {"configured": True, "items": items[:20], "message": ""}


init_db()
