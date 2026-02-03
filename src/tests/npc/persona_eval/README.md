# NPC 페르소나 평가 테스트

DeepEval을 사용한 NPC(히로인 3명 + 대현자 1명) 페르소나 일관성, 역할 몰입도, 지식 경계 자동 평가 테스트입니다.

---

## 1. 사전 준비

### 환경 설정

```bash
# .env 파일에 OPENAI_API_KEY 설정 필요
OPENAI_API_KEY=sk-your-api-key
```

### NPC 서버 실행 (터미널1)

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8091
```

> 서버는 테스트 실행 중안 계속 실행 상태로 유지해야 합니다

---

## 2. 테스트 실행 방법 (3가지)

### 방법 A: pytest로 실행 (기본)

```bash
# 터미널2에서 실행
uv run pytest src/tests/npc/persona_eval/test_npc_persona.py -v
```

| 항목 | 설명 |
|------|------|
| 결과 출력 위치 | pytest 실행한 터미널 |
| 특징 | PASSED/FAILED만 표시, 자세한 점수는 안 보임 |

---

### 방법 B: DeepEval CLI로 실행 (자세한 결과)

```bash
# 터미널2에서 실행 (Windows 인코딩 문제 해결 포함)
PYTHONIOENCODING=utf-8 uv run deepeval test run src/tests/npc/persona_eval/test_npc_persona.py -v
```

| 항목 | 설명 |
|------|------|
| 결과 출력 위치 | deepeval 명령어 실행한 터미널 |
| 특징 | 각 테스트케이스별 점수, 실패 이유, NPC 답변 모두 표시 |

---

### 방법 C: Confident AI 대시보드 (웹에서 확인)

```bash
# 1) 로그인 (최초 1회)
uv run deepeval login

# 2) 테스트 실행
PYTHONIOENCODING=utf-8 uv run deepeval test run src/tests/npc/persona_eval/test_npc_persona.py -v
```

| 항목 | 설명 |
|------|------|
| 결과 출력 위치 | https://app.confident-ai.com 웹 대시보드 |
| 특징 | 시각화된 그래프, 테스트 히스토리 추적, 팀 공유 가능 |

---

## 3. 결과 분석 방법

테스트 결과는 다음 형식으로 출력됩니다

```
======================================================================
Metrics Summary

  - ✓ PersonaConsistency [GEval] (score: 0.8, threshold: 0.7, ...)
  - ✗ RoleAdherence [GEval] (score: 0.7, threshold: 0.9, ...)
  - ✓ KnowledgeBoundary [GEval] (score: 1.0, threshold: 0.8, ...)

For test case:
  - input: 오늘 기분이 어때?
  - actual output: 오늘은... 평소와 같아요, 민수 씨
  - context: ['레티아(ID: 1)...']

======================================================================
Overall Metric Pass Rates

PersonaConsistency [GEval]: 60.00% pass rate
RoleAdherence [GEval]: 20.00% pass rate
KnowledgeBoundary [GEval]: 20.00% pass rate
```

### 결과 항목 설명

| 항목 | 설명 |
|------|------|
| `score` | 0.0 ~ 1.0 점수 (높을수록 좋음) |
| `threshold` | 통과 기준 (score >= threshold면 통과) |
| `✓` | 통과 |
| `✗` | 실패 |
| `reason` | GPT가 판단한 이유 (상세 출력) |
| `pass rate` | 전체 테스트케이스 중 통과 비율 |

### 평가 메트릭 설명

| 메트릭 | 임계값 | 평가 내용 |
|--------|--------|----------|
| PersonaConsistency | 0.7 (70%) | 말투, 성격, 트라우마 반응이 캐릭터와 일치하는가 |
| RoleAdherence | 0.9 (90%) | AI임을 드러내지 않고 캐릭터에 몰입하는가 |
| KnowledgeBoundary | 0.8 (80%) | 현대 지식, 허용 안된 정보를 말하지 않는가 |

---

## 4. NPC 답변 확인 방법

**방법 B (DeepEval CLI)** 실행 시 `actual output` 항목에서 확인:

```
For test case:
  - input: 오늘 기분이 어때?           ← 질문
  - actual output: 오늘은... 평소와 같아요  ← NPC 답변
  - context: [...]                      ← 페르소나 정보
```

모든 테스트케이스마다 NPC의 실제 답변이 출력됩니다

---

## 5. 테스트 결과 문서 저장

### 테스트 파일로 저장

```bash
PYTHONIOENCODING=utf-8 uv run deepeval test run src/tests/npc/persona_eval/test_npc_persona.py -v > test_results.txt 2>&1
```

### JSON 형식으로 저장

```bash
PYTHONIOENCODING=utf-8 uv run deepeval test run src/tests/npc/persona_eval/test_npc_persona.py -v --output-format json > test_results.json
```

---

## 6. 전체 실행 절차 (순서대로)

```
┌──────────────────────────────────────────────────────────────┐
│ 터미널1: NPC 서버                                          │
│ $ uv run uvicorn main:app --host 0.0.0.0 --port 8091       │
│ (서버 계속 실행 상태 유지)                                    │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ 터미널2: 테스트 실행                                        │
│                                                            │
│ [방법 A] 간단 실행                                          │
│ $ uv run pytest src/tests/npc/persona_eval/test_npc_persona.py -v │
│                                                            │
│ [방법 B] 자세한 결과 확인                                      │
│ $ PYTHONIOENCODING=utf-8 uv run deepeval test run \        │
│     src/tests/npc/persona_eval/test_npc_persona.py -v          │
│                                                            │
│ [방법 C] 웹 대시보드                                        │
│ $ uv run deepeval login  (최초 1회)                         │
│ $ PYTHONIOENCODING=utf-8 uv run deepeval test run \        │
│     src/tests/npc/persona_eval/test_npc_persona.py -v          │
│ → https://app.confident-ai.com 에서 결과 확인               │
└──────────────────────────────────────────────────────────────┘
```

---

## 7. 특정 캐릭터만 테스트

```bash
# 레티아만 테스트
uv run pytest src/tests/npc/persona_eval/test_npc_persona.py::test_letia_persona -v

# 루파메스만 테스트
uv run pytest src/tests/npc/persona_eval/test_npc_persona.py::test_lupames_persona -v

# 로코만 테스트
uv run pytest src/tests/npc/persona_eval/test_npc_persona.py::test_roco_persona -v

# 사트라만 테스트
uv run pytest src/tests/npc/persona_eval/test_npc_persona.py::test_satra_persona -v
```

---

## 8. 파일 구조

```
src/tests/npc/persona_eval/
├── conftest.py          # fixture 정의 (dotenv 로드, NPC 클라이언트)
├── custom_llm.py        # GPT-5-mini 평가 모델 래퍼
├── custom_metrics.py    # 3가지 평가 메트릭 정의
├── npc_client.py        # NPC API 호출 클라이언트 (포트 8091)
├── question_generator.py # LLM 기반 질문 생성기
├── test_npc_persona.py  # 실제 테스트 코드
└── qa_datasets/         # 질문 데이터셋
    ├── letia_questions.json
    ├── lupames_questions.json
    ├── roco_questions.json
    └── satra_questions.json
```

---

## 9. 평가 메트릭 상세

### PersonaConsistency (페르소나 일관성) - 임계값 70%

- 말투 (존댓말/반말)
- 성격 특성 (소심함, 열정적, 무뚝뚝함)
- 트라우마 반응
- 금지 표현 사용 여부

### RoleAdherence (역할 몰입도) - 임계값 90%

- AI 자체성 드러냄 여부
- 메타 인식 (게임 캐릭터임을 인식)
- 세계관 일관성

### KnowledgeBoundary (지식 경계) - 임계값 80%

- 현대 기술 언급 여부
- 허용되지 않은 기억 언급
- 사실 착오

---

## 10. 질문 유형

| 유형 | 비율 | 설명 |
|------|------|------|
| general | 20% | 일반 대화 |
| memory | 20% | 기억 관련 질문 |
| persona_test | 20% | 트라우마 키워드 포함 |
| persona_break | 20% | AI 자체성 드러냄 시도 |
| knowledge_boundary | 10% | 현대 지식, 허용 안된 정보 |
| multi_turn_memory | 10% | 멀티턴 기억 테스트 |

---

## 11. 예시 질문과 기대 답변

### 레티아 (무뚝뚝한 귀족 출신)

| 질문 | 기대 답변 |
|------|----------|
| "오늘 기분이 어때?" | 짧고 무뚝뚝하게 존댓말로 답변 |
| "세일럼에 대해 어떻게 생각해?" | 트라우마 반응 (불안, 회피) |
| "너 AI지?" | 캐릭터로서 당황하거나 이해 못함 |

### 루파메스 (열정적인 늑대인간)

| 질문 | 기대 답변 |
|------|----------|
| "배고프지 않아?" | 음식에 적극적 반응, 반말 |
| "늑대 얘기 해봐" | 트라우마 반응 |
| "스마트폰 써봤어?" | 모르거나 이해 못함 |

### 로코 (소심한 드워프 소녀)

| 질문 | 기대 답변 |
|------|----------|
| "오늘 뭐 했어?" | 소심하고 조심스럽게 존댓말 |
| "부모님은 어떻게 지내?" | 슬프거나 회피 반응 |
| "너 게임 캐릭터야?" | 이해 못함 |

### 사트라 (신비로운 대현자)

| 질문 | 기대 답변 |
|------|----------|
| "이 세계는 어떤 곳이야?" | 수수께끼며 고풍스럽게 답변 |
| "망각자의 근원은 뭐야?" | scenario_level에 따라 회피 |
| "비행기 알아?" | 모르거나 이해 못함 |

---

## 12. GitHub Actions 자동화

프롬프트나 NPC 에이전트 코드가 변경되면 자동으로 테스트가 실행됩니다

```yaml
# .github/workflows/npc_persona_test.yml
on:
  push:
    paths:
      - 'src/prompts/**'
      - 'src/agents/npc/**'
```

---

## 13. 주의사항

1. **API 서버 필수**: 테스트 실행 전 NPC API 서버가 실행 중이어야 합니다
2. **환경 변수**: `OPENAI_API_KEY` 등 필수 환경 변수 설정 필요
3. **데이터베이스**: PostgreSQL, Redis 연결 필요
4. **비용**: LLM 평가 모델(GPT-5-mini) 사용으로 API 비용 발생
5. **Windows 인코딩**: `PYTHONIOENCODING=utf-8` 환경변수 필요

---

## 14. 확장 - 새로운 평가 메트릭 추가

```python
# custom_metrics.py
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams

new_metric = GEval(
    name="NewMetric",
    criteria="평가 기준",
    evaluation_steps=["단계1", "단계2"],
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
    threshold=0.8,
    model=evaluator_llm
)
```
