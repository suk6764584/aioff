# AI OFF 교육자료 DB + 뉴스 DB

## 현재 기준

기존 KOBACO DB는 그대로 유지하고 교육자료/뉴스 DB는 분리한다.

- `data/education/education.db`: 공식 디지털 리터러시 교육자료 메타데이터, 첨부파일, chunk, embedding
- `data/news/news.db`: 뉴스 메타데이터/embedding/교육자료 연결용 DB
- 교육자료와 뉴스의 실제 연결은 같은 embedding 모델·차원을 사용한다.

## 교육자료 canonical pipeline

교육자료 원본을 다시 구축해야 할 때만 아래 순서로 명시적으로 실행한다.

```bash
cd /opt/aioff
.venv/bin/python download_education_sources.py --rebuild-db
.venv/bin/python extract_education_sources.py
.venv/bin/python embed_education_db.py
```

일상적인 배포에서는 위 재구축 명령을 실행하지 않는다. 특히 embedding이 진행 중일 때 `education.db`를 다시 만들거나 chunk를 초기화하지 않는다.

현재 DB 상태만 확인:

```bash
bash build_rag_data.sh validate
```

기존 chunk의 미완료 embedding만 이어서 수행:

```bash
bash build_rag_data.sh education-embed
```

`embed_education_db.py`는 이미 저장된 embedding을 건너뛰어 재개한다.

## 수집/추출 구성

- `education_archive_parser.py`: 공식 자료실 목록/첨부 링크 파싱 전용 helper
- `download_education_sources.py`: 대상 자료와 첨부 원본 수집
- `extract_education_sources.py`: 원본에서 text chunk 생성
- `embed_education_db.py`: `gemini-embedding-001`, 768차원 embedding 저장
- `education_db.py`: SQLite schema/search/vector 저장

## 뉴스

현재 운영용 뉴스 파이프라인은 2026년 수집본의 사건 단위 정제/교육자료 매칭 단계가 진행 중이다. 예전 14일 probe 방식은 폐기했다. `build_rag_data.sh`에서 뉴스 DB를 자동 재구축하지 않는다.
