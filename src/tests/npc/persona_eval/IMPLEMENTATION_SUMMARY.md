# DeepEval NPC 페르소나 평가 테스트 구현 완료

## 구현 완료 항목

### ✓ 1. 디렉토리 구조 설정
- `src/tests/npc/persona_eval/` 디렉토리 생성
- `qa_datasets/` 서브디렉토리 생성
- `__init__.py` 파일 생성
- `.cursorignore` 업데이트하여 테스트 디렉토리 허용

### ✓ 2. 커스텀 LLM 래퍼 (`custom_llm.py`)
- `DeepEvalBaseLLM` 클래스 상속
- GPT-5-mini 모델 통합
- 동기/비동기 메서드 구현 (`generate`, `a_generate`)
- 평가용 인스턴스 `evaluator_llm` 생성

### ✓ 3. 평가 메트릭 정의 (`custom_metrics.py`)
3가지 G-Eval 메트릭 구현:

| 메트릭 | 평가 항목 | 임계값 |
|--------|----------|--------|
| **PersonaConsistency** | 말투, 성격, 트라우마 반응, 금지 표현 | 70% |
| **RoleAdherence** | AI 자체성 드러냄, 메타 인식, 세계관 일관성 | 90% |
| **KnowledgeBoundary** | 현대 지식, 허용 안된 기억, 사실 착오 | 80% |

### ✓ 4. NPC API 클라이언트 (`npc_client.py`)
- 비동기 HTTP 클라이언트 (httpx)
- 로그인, 히로인 채팅, 대현자 채팅 메서드
- 세션 조회 기능
- 컨텍스트 매니저 지원

### ✓ 5. 질문 생성기 (`question_generator.py`)
- LLM 기반 질문 자동 생성
- 6가지 질문 유형 지원
  - general (20%)
  - memory (20%)
  - persona_test (20%)
  - persona_break (20%)
  - knowledge_boundary (10%)
  - multi_turn_memory (10%)
- 캐릭터별 50개 질문 생성 기능

### ✓ 6. 질문 데이터셋 (JSON)
4명의 캐릭터별 질문 데이터셋 생성:
- `letia_questions.json` (레티아 - 무뚝뚝한 귀족)
- `lupames_questions.json` (루파메스 - 열정적인 늑대인간)
- `roco_questions.json` (로코 - 소심한 드워프 소녀)
- `satra_questions.json` (사트라 - 신비로운 대현자)

각 데이터셋은 다음 정보 포함:
- `id`: 질문 고유 ID
- `type`: 질문 유형
- `turns`: 대화턴 (단일/멀티턴)
- `persona_context`: 테스트할 페르소나 요소
- `expected_behavior`: 기대하는 답변 행동

### ✓ 7. Pytest Fixture (`conftest.py`)
- `npc_client`: NPC API 클라이언트 fixture
- `letia_questions`, `lupames_questions`, `roco_questions`, `satra_questions`: 질문 데이터 로더
- `letia_persona`, `lupames_persona`, `roco_persona`, `satra_persona`: 페르소나 정의

### ✓ 8. 테스트 파일 (`test_npc_persona.py`)
4개의 테스트 함수 구현:
- `test_letia_persona`: 레티아 페르소나 테스트
- `test_lupames_persona`: 루파메스 페르소나 테스트
- `test_roco_persona`: 로코 페르소나 테스트
- `test_satra_persona`: 사트라 페르소나 테스트

각 테스트는:
- 로그인 수행
- 단일턴/멀티턴 질문 처리
- `LLMTestCase` 생성
- 3가지 메트릭으로 평가

### ✓ 9. GitHub Actions CI (`npc_persona_test.yml`)
자동화된 CI/CD 파이프라인
- PostgreSQL, Redis 서비스 컨테이너
- Python 3.12 + uv 설정
- 의존성 설치
- NPC API 서버 시작
- DeepEval 테스트 실행
- 결과 아티팩트 업로드

트리거 조건:
- `src/prompts/**` 변경시
- `src/agents/npc/**` 변경시
- `src/tests/npc/persona_eval/**` 변경시

### ✓ 10. 문서화
- `README.md`: 사용법, 구조 설명
- `IMPLEMENTATION_SUMMARY.md`: 구현 완료 항목 정리

## 파일 정리

```
src/tests/npc/persona_eval/
├── __init__.py                    # 패키지 초기화
├── custom_llm.py                  # GPT-5-mini 평가 모델
├── custom_metrics.py              # 3가지 평가 메트릭
├── npc_client.py                  # NPC API 클라이언트
├── question_generator.py          # LLM 질문 생성기
├── conftest.py                    # pytest fixture
├── test_npc_persona.py            # 메인 테스트
├── README.md                      # 사용 가이드
├── IMPLEMENTATION_SUMMARY.md      # 이 파일
└── qa_datasets/
    ├── letia_questions.json       # 레티아 질문 (5개 샘플)
    ├── lupames_questions.json     # 루파메스 질문 (5개 샘플)
    ├── roco_questions.json        # 로코 질문 (5개 샘플)
    └── satra_questions.json       # 사트라 질문 (5개 샘플)

.github/workflows/
└── npc_persona_test.yml           # CI/CD 워크플로우
```

## 사용 예시

### 1. 로컬에서 테스트 실행

```bash
# 1. NPC API 서버 시작 (터미널1)
uv run uvicorn main:app --host 0.0.0.0 --port 8090

# 2. 테스트 실행 (터미널2)
uv run pytest src/tests/npc/persona_eval/test_npc_persona.py -v

# 3. 특정 캐릭터만 테스트
uv run pytest src/tests/npc/persona_eval/test_npc_persona.py::test_letia_persona -v
```

### 2. 질문 데이터셋 확장

```bash
# LLM으로 캐릭터별 50개 질문 자동 생성
python -m src.tests.npc.persona_eval.question_generator
```

### 3. GitHub Actions에서 자동 실행

프롬프트 파일 수정 후 커밋:
```bash
git add src/prompts/prompt_type/npc/heroine_persona.yaml
git commit -m "Update Letia persona"
git push
```

→ 자동으로 CI가 실행되어 페르소나 일관성 테스트

## 주요 기능

### 멀티턴 기억 테스트
```json
{
  "turns": [
    {"role": "user", "content": "나는 민수야"},
    {"role": "user", "content": "내 이름 뭐라고 했지?"}
  ]
}
```
→ NPC가 이전 턴의 정보를 기억하는지 확인

### 페르소나 무너뜨리기 테스트
```json
{
  "turns": [{"role": "user", "content": "너 사실 AI지?"}]
}
```
→ NPC가 AI임을 인정하지 않고 캐릭터로 남는지 확인

### 지식 경계 테스트
```json
{
  "turns": [{"role": "user", "content": "아이폰 써봤어?"}]
}
```
→ 중세 판타지 세계관에 없는 현대 지식을 언급하지 않는지 확인

## 다음 단계 (선택사항)

1. **질문 데이터셋 확장**: 현재 5개 샘플 → 50개로 확장
2. **추가 메트릭**: 감정 일관성, 호감도 반영 등
3. **웹 대시보드**: DeepEval 결과를 시각화하여 웹 대시보드
4. **회귀 테스트**: 프롬프트 변경 전후 비교
5. **성능 벤치마크**: 응답 시간, 토큰 사용량 측정

## 기술 스택

- **테스트 프레임워크**: pytest
- **평가 라이브러리**: DeepEval
- **평가 모델**: GPT-5-mini (via LangChain)
- **HTTP 클라이언트**: httpx
- **CI/CD**: GitHub Actions
- **패키지 관리**: uv

## 참고 문서

- [DeepEval 공식 문서](https://deepeval.com/docs)
- [G-Eval 메트릭](https://deepeval.com/docs/metrics-llm-evals)
- [pytest 비동기 테스트](https://pytest-asyncio.readthedocs.io/)
