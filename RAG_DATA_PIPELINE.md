# AI OFF 교육자료 DB + 최신 뉴스 DB

## 목적

기존 KOBACO DB는 그대로 유지한다. 새 DB는 별도로 구성한다.

- `data/education/education.db`: 디지털윤리.kr 초등·중등·고등 교육자료 메타데이터, 첨부파일, PDF 텍스트 chunk, embedding
- `data/news/news.db`: 최신 뉴스 메타데이터, topic tags, embedding, 연령별 교육자료 연결 결과
- 두 DB는 `link_news_education.py`에서 embedding similarity로 연결한다.

## 교육자료 수집 원칙

`https://xn--2z1b40gs9nlqcf0n.kr/front/archive/archiveMainList.do` 전체 페이지를 순회한 뒤 `대상`에 `초등`, `중등`, `고등`이 포함된 자료만 선택한다. 숫자 131/133을 코드에 고정하지 않는다. 사이트 실제 결과를 매 실행 시 기록한다.

원문 파일은 `data/education/files/`에 저장하고 Git에는 올리지 않는다. PDF/TXT와 ZIP 안의 PDF/TXT는 텍스트 chunk를 만든다. HWP/PPT 등 미지원 형식은 메타데이터/원본 파일은 보존하되 `unsupported`로 기록한다.

## Vector/RAG

기본 embedding model은 `gemini-embedding-001`, 768차원이다. 교육자료와 뉴스 모두 같은 모델·차원으로 임베딩해야 cosine similarity가 유효하다. `GEMINI_EMBED_MODEL`로 변경할 수 있지만 모델을 변경하면 두 DB를 함께 재임베딩해야 한다.

## 실행

먼저 파서 검증:

```bash
cd /opt/aioff
git pull --ff-only origin main
.venv/bin/pip install -r requirements.txt
bash build_rag_data.sh validate
```

검증 결과의 전체 자료 수와 초·중·고 선택 자료 수가 정상일 때 전체 구축:

```bash
bash build_rag_data.sh build
```

뉴스만 갱신:

```bash
bash build_rag_data.sh refresh-news
```

## 하드 게이트

`build_education_db.py`는 전체 파싱이 250건 미만 또는 초·중·고 자료가 80건 미만이면 DB/다운로드 전에 중단한다. 사이트 구조가 바뀌었는데 잘못된 DB를 만드는 것을 막기 위한 장치다.
