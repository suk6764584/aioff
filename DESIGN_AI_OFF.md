# AI OFF · Product Design Direction

이 문서는 AI OFF 프로토타입의 화면 설계 기준이다. 특정 브랜드를 복제하지 않고, Oh My Design의 실제 서비스 DESIGN.md에서 AI OFF에 맞는 원칙만 추려 재구성한다.

## 1. Product character

AI OFF는 대시보드가 아니라 **학습 흐름**이다.

사용자는 다음 네 단계만 이해하면 된다.

1. AI와 공부한다.
2. 대화를 마치고 문제를 만든다.
3. AI 없이 직접 푼다.
4. AI에 맡긴 정도와 혼자 수행한 결과를 비교한다.

화면은 점수 관리 도구나 관리자 콘솔처럼 보이지 않아야 한다. 학생에게는 차분한 학습지와 대화 공간의 중간 정도로 느껴져야 한다.

## 2. Selected Oh My Design references

### LikeLion — education context

Use:
- 한국어 교육 서비스에 어울리는 직접적인 다음 행동 안내
- `#222222` 계열 본문과 얇은 hairline 중심의 차분한 구조
- 따뜻한 면을 한두 곳에만 사용해 학습 구간을 구분
- 학습을 실제 문제 해결과 반복 수행의 흐름으로 표현

Do not copy:
- LikeLion 브랜드 오렌지 자체를 그대로 브랜드색으로 사용
- 교육 마케팅 카드/프로모션 구조

Reference: https://oh-my-design.kr/design-systems/likelion

### Headspace — warm, low-pressure surface

Use:
- 차가운 SaaS 흰/회색 대시보드 대신 따뜻한 cream canvas
- 그림자 대신 면 색과 여백으로 깊이 구분
- 강한 행동색은 한 단계에 하나만 사용
- 학생에게 친근하지만 유치하지 않은 둥근 모서리

Do not copy:
- Headspace 캐릭터/감정 일러스트레이션
- 브랜드 전용 폰트나 고유 orange/blue 조합을 그대로 복제

Reference: https://oh-my-design.kr/design-systems/headspace

### Toss — action hierarchy and Korean copy

Use:
- 한 화면/한 단계에서 가장 중요한 행동을 하나만 강하게 보이게 함
- 기술 용어보다 학생이 바로 이해하는 한국어
- 숫자나 상태는 설명과 함께 보여 줌
- 불필요한 장식 대신 타이포와 여백으로 위계 형성

Do not copy:
- 금융 서비스 컴포넌트
- Toss Product Sans 등 브랜드 전용 자산

Reference: https://oh-my-design.kr/design-systems/toss

## 3. AI OFF visual system

### Colors

- Canvas: `#F6F1E8` — 따뜻한 종이/노트 배경
- Paper: `#FFFDFC` — 대화와 문제 본문
- Ink: `#24211D` — 주요 제목
- Body: `#5B5650` — 설명
- Muted: `#8A837A` — 보조 정보
- Hairline: `#E3DDD3` — 구획
- AI ON blue: `#356FE8` — AI와 함께하는 단계의 행동색
- AI OFF orange: `#F06A3C` — 직접 수행으로 넘어가는 전환색
- Success green: `#2E8A66` — 잘했어요 상태
- Practice amber: `#B77722` — 조금 더 연습 상태

색은 모드와 행동을 설명하는 역할에만 사용한다. 카드마다 다른 색을 주지 않는다.

### Typography

시스템 한글 폰트를 사용한다. 별도 브랜드 폰트 파일을 포함하지 않는다.

- Hero: 40–44px / 700–800 / line-height 1.16
- Section title: 24–28px / 700
- Panel title: 18px / 700
- Body: 15px / 400–500 / line-height 1.65
- Helper: 12–13px / 400–600

긴 설명은 박스 안에 넣기보다 본문 흐름 안에서 짧게 쓴다.

### Geometry

- 기본 radius: 10–12px
- 작은 label: 6–8px
- 주요 CTA만 pill 또는 12px radius
- 모든 영역을 카드로 감싸지 않는다.
- drop shadow 금지. 구분은 `1px` hairline, 여백, canvas/paper 차이로 만든다.

## 4. Layout rules

### Global

- 헤더 → 짧은 서비스 설명 → 진행 단계 → 현재 작업 순서
- 진행 단계는 카드 4개가 아니라 하나의 연결된 progress rail로 표시
- 데스크톱에서는 대화 본문 + 학습 메모 2열, 모바일은 1열

### AI ON

- AI 응답은 흰 말풍선 카드가 아니라 본문 텍스트처럼 표시
- 학생 질문만 작은 색 면으로 구분
- 입력창 바로 아래에 다음 행동 `대화 마치고 문제 만들기`를 명확히 배치
- 버튼 문구만 보고도 다음에 문제 3개가 나온다는 사실을 알 수 있어야 함

### AI OFF

- 문제는 카드 3장이 아니라 한 장의 학습지 안에서 번호와 구분선으로 이어짐
- 각 문제의 `이 문제를 내는 이유`는 작은 메모 형식
- 답변 입력란은 넓고 여백이 충분해야 함

### Result

- 내부 판정 문자열 `확인됨 / 부분 확인 / 추가 확인 필요`는 학생에게 노출하지 않는다.
- 화면 문구:
  - `잘했어요!`
  - `조금만 더 연습해봐요`
  - `한 번 더 공부해볼까요?`
- `AI에 맡긴 정도`와 `혼자 수행한 결과`를 먼저 설명한 뒤 숫자를 보여 준다.
- 결과 마지막에 `새 학습 시작`을 제공한다.

## 5. Voice

학생에게 직접 말한다.

Prefer:
- `AI와 공부를 마쳤다면, 이제 직접 풀어볼 문제를 만들어 보세요.`
- `이 문제는 방금 AI에 맡겼던 사고를 직접 해보는 문제예요.`
- `잘했어요!`
- `조금만 더 연습해봐요.`

Avoid:
- `독립 수행 검증을 시작합니다.`
- `위임 지표를 분석합니다.`
- `세션 상태`
- `평가 게이트`
- `AI 기반 분석 결과`
- 홍보성 문구나 생성형 AI 특유의 과장된 카피

## 6. Anti-AI-slop gate

화면을 제출하기 전에 아래를 확인한다.

- 둥근 카드가 연속으로 3개 이상 반복되지 않는가?
- 모든 정보가 박스 안에 들어가 있지 않은가?
- 그림자나 그라데이션이 불필요하게 들어가 있지 않은가?
- 한 화면에 강한 CTA가 두 개 이상 경쟁하지 않는가?
- 내부 용어를 학생이 해석해야 하는 부분이 없는가?
- 버튼을 눌렀을 때 다음에 무엇이 일어나는지 문구만 보고 알 수 있는가?
- AI ON과 AI OFF가 색과 카피 양쪽에서 구분되는가?
- 결과 점수의 의미가 숫자보다 먼저 설명되는가?
