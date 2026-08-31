# AI OFF

AI와 학습한 뒤, 학생이 AI에 맡긴 사고와 정보 판단을 다시 직접 수행해보는 디지털 리터러시 학습 서비스입니다.

## 현재 구현
- Gemini 실제 학습 채팅
- 학습 대화 기반 사고 기능 위임 분석
- 출처 신뢰도·사실/의견·근거 충분성·교차검증·불확실성 확인 분석
- 대화 맥락에 맞는 AI OFF 문제 3개 생성
- 이해·사고 수행 문제와 디지털 리터러시 판단 문제를 혼합 생성
- 학생 답변 평가 및 AI 위임/직접 확인 결과 비교
- 답변 수정 및 같은 문항 평가기준으로 재채점
- SQLite 세션·대화·평가 기록 저장
- FastAPI 백엔드 + 단일 HTML 프론트엔드
- systemd 자동 시작 서비스 파일 포함

## 현재 분석 항목
### 사고 위임
- 자료 탐색
- 개념 설명
- 비교·분석
- 주장 구성
- 근거 판단

### 정보 판단·검증
- 출처 신뢰도 판단
- 사실·의견 구분
- 근거 충분성 판단
- 교차검증
- 불확실성 확인

분석 결과는 이번 학습 대화에서 확인된 범위만 보여주며 학생의 장기적인 능력이나 성향을 단정하지 않습니다.

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
GEMINI_MODEL=gemini-3.5-flash-lite
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-20b
```

실제 `.env`, `aioff.db`, 가상환경 파일은 저장소에 커밋하지 않습니다.

## 실행
```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn literacy_app:app --host 0.0.0.0 --port 3000
```

`literacy_app.py`는 기존 `app.py`의 채팅·평가·DB 구조를 그대로 사용하면서, 화면 문구와 대화 분석/AI OFF 문제 생성 부분을 디지털 리터러시 방향으로 확장합니다.

## 배포 원칙
코드는 이 저장소를 기준으로 관리하고, NAVER VM에서는 `git pull` 후 `bash deploy.sh`로 서비스 파일 반영·재시작·헬스체크까지 수행합니다.
