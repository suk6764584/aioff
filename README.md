# AI OFF

AI와 학습한 뒤 학생이 AI에 맡긴 사고와 정보 판단을 다시 직접 수행하는 디지털 리터러시 학습 서비스입니다.

## 현재 서비스

현재 배포 엔트리포인트는 `aioff_entry:app`입니다.

주요 기능:
- KOBACO AiSAC 실제 광고 데이터 기반 미디어 리터러시 학습
- 공식 리터러시 교육 안내서 기반 학교급·학년 맞춤 학습
- 최신 뉴스 기반 사실·해석 구분 학습
- 로그인/회원가입 및 NEIS 학교 검색·학교급·학년 프로필
- Gemini 학습 채팅 + Groq fallback
- AI OFF 대화 분석, 문제 생성, 답변 평가·재도전
- SQLite 세션·회원·교육자료 데이터, DuckDB/Parquet KOBACO 데이터

현재 실행 체인은 `aioff_entry.py → news_learning.py → aioff_runtime.py → aioff_ui.py → literacy_app.py → app.py`로 정리되어 있으며, 과거 번호형 `literacy_kobaco_app_*`, `literacy_media_app_*`, `literacy_cases_*` 모듈은 사용하지 않습니다.

## 서버 환경

- Python 3.11
- FastAPI / Uvicorn
- google-genai / Groq
- SQLite / DuckDB

실제 `.env`, DB, 다운로드 교육자료, 가상환경은 Git에 올리지 않습니다.

## 로컬 실행

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn aioff_entry:app --host 0.0.0.0 --port 3000
```

## 서버 배포

NAVER VM의 `/opt/aioff`에서:

```bash
bash deploy.sh
```

`deploy.sh`가 최신 코드 pull, 의존성 확인, 통합 엔트리포인트/라우트/레이아웃 검증, systemd 재시작, health check까지 수행합니다.

## 교육자료 데이터

교육자료 원본 재구축은 일반 배포와 분리합니다. 자세한 순서는 `RAG_DATA_PIPELINE.md`를 따릅니다.
