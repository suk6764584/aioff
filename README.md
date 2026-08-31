# AI OFF

AI와 학습한 뒤, 학생이 AI에 맡긴 사고 기능을 다시 직접 수행할 수 있는지 확인하는 학습 서비스입니다.

## 현재 구현
- Gemini 실제 학습 채팅
- 학습 대화 기반 사고 기능 위임 분석
- 위임 정도가 큰 상위 3개 기능에 대한 맞춤 AI OFF 문제 생성
- 학생 답변 평가 및 AI 위임/독립 수행 비교
- SQLite 세션·대화·평가 기록 저장
- FastAPI 백엔드 + 단일 HTML 프론트엔드
- systemd 자동 시작 서비스 파일 포함

## 서버 환경
- Python 3.11
- FastAPI
- Uvicorn
- google-genai
- SQLite

## 환경변수
`.env.example`을 참고해 서버의 `/opt/aioff/.env`에만 실제 값을 저장합니다.

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.7-flash
```

실제 `.env`, `aioff.db`, 가상환경 파일은 저장소에 커밋하지 않습니다.

## 실행
```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 3000
```

## 배포 원칙
앞으로 코드는 이 저장소를 기준으로 관리하고, NAVER VM에서는 `git pull` 후 서비스를 재시작하는 방식으로 업데이트합니다.
