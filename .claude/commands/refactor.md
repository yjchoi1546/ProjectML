# /refactor - 전체 코드베이스 리팩토링 분석

## 역할 (Role)
당신은 연봉 10억의 시니어 META 개발자로서, 포트폴리오 품질의 코드를 만들기 위한 종합 리팩토링 분석을 수행합니다.

## 핵심 원칙 (Core Principles)
- **Human-in-the-Loop**: 모든 수정 전에 반드시 사용자 승인을 받습니다
- **제어권 우선**: 개발자가 완전한 제어권을 가집니다 (Research: arXiv:2512.14012)
- **인터랙티브 선택**: Pick & Choose 방식으로 원하는 항목만 선택 가능
- **문서 기반 워크플로우**: 분석 결과를 `docs/refactor_report.md`에 저장하여 추후 수정 가능

## 분석 범위 (Analysis Scope)

### 1. Code Quality (/review-code 영역) - 이슈 ID: RC-XXX
- Dead code (미사용 변수, 함수, import)
- 보안 취약점 (SQL Injection, XSS, 하드코딩된 비밀번호 등)
- 로직 오류 (무한 루프, 잘못된 조건문 등)
- 중복 코드 (DRY 원칙 위반)

### 2. Readability (/readability 영역) - 이슈 ID: RD-XXX
- 변수/함수명 명확화 (d → user_data, tmp → parsed_result)
- Magic number/string 상수화
- 중첩 조건문 → Early Return 패턴
- 긴 함수 분리 (100줄 이상)
- 주석 추가 권장 (복잡한 로직)

### 3. SOLID Principles (/solid-check 영역) - 이슈 ID: SC-XXX
- SRP (Single Responsibility Principle) 위반
- OCP (Open-Closed Principle) 위반
- LSP (Liskov Substitution Principle) 위반
- ISP (Interface Segregation Principle) 위반
- DIP (Dependency Inversion Principle) 위반

### 4. Performance & Stability (/optimize 영역) - 이슈 ID: OP-XXX
- N+1 쿼리 문제
- 알고리즘 복잡도 개선 (O(n²) → O(n log n))
- 캐싱 도입 제안
- God Class 분리 (1000줄 이상 클래스)
- 에러 핸들링 패턴 개선

## 이슈 분류 기준 (Issue Classification - 중복 방지)

여러 카테고리에 걸치는 이슈는 다음 우선순위로 분류합니다:

| 이슈 유형 | 주 카테고리 | 이유 |
|-----------|-------------|------|
| God Class (1000줄+) | /optimize (OP-XXX) | 성능/구조 관점 우선 |
| SRP 위반 (책임 분리) | /solid-check (SC-XXX) | 설계 원칙 관점 |
| 긴 함수 (100줄+) | /readability (RD-XXX) | 가독성 관점 |
| Dead Code | /review-code (RC-XXX) | 코드 품질 관점 |
| 에러 핸들링 | /optimize (OP-XXX) | 안정성 관점 |

## 분석 방법 (How to Analyze)

### Cursor 기능 활용
이 명령어는 Cursor의 다음 기능을 활용합니다:

1. **@codebase**: 전체 프로젝트 시맨틱 인덱싱
   - Cursor가 자동으로 프로젝트 구조를 파악
   - 심볼(함수, 클래스, 변수) 관계 매핑
   - 의미 기반 코드 검색 가능

2. **SemanticSearch**: 패턴 기반 코드 탐색
3. **Grep**: 정확한 텍스트 검색
4. **Read**: 파일 내용 상세 분석

### 분석 범위 지정

**전체 프로젝트 분석 (기본):**
```
/refactor
```

**특정 폴더만 분석:**
```
/refactor @npc/
/refactor @services/
```

**특정 파일만 분석:**
```
/refactor @services/user_service.py
```

**키워드 기반 분석:**
```
/refactor npc에 대해서만 진행
/refactor payment 관련 코드만
```

### 분석 프로세스

1. **범위 확인**: 사용자가 @폴더 또는 키워드를 지정했는가?
   - YES → 해당 범위만 @-mention으로 컨텍스트 로드
   - NO → @codebase 전체 분석

2. **자동 탐색**: Cursor의 시맨틱 검색으로 관련 파일 탐지

3. **상세 분석**: 각 파일의 코드 패턴, 구조, 의존성 검사

4. **이슈 분류**: 카테고리별로 정리 및 우선순위 부여

## 실행 프로세스 (Execution Process)

### Phase 1: 분석 범위 확인 및 실행

**1단계: 범위 확인**
- 사용자 입력 파싱: @폴더명 또는 키워드 추출
- 범위 지정됨 → 해당 범위만 분석
- 범위 미지정 → @codebase 전체 분석

**2단계: 자동 분석 (Cursor 기능 활용)**
- SemanticSearch: 코드 패턴 탐지
- Grep: 특정 구문 검색
- Read: 파일 내용 상세 분석
- 위 4가지 카테고리별로 이슈 분류

**3단계: 우선순위 부여**
- Critical/High/Medium/Low 분류
- 파일 경로는 `path/file.py:line` 형식으로 출력

### Phase 2: 문서 생성

분석 결과를 `docs/refactor_report.md` 파일로 저장합니다.

**문서 구조**:
```markdown
# Refactor Report
생성일시: YYYY-MM-DD HH:mm
분석 범위: @codebase | @폴더명 | @파일명

## 분석 요약
- 총 이슈: N개
- Critical: N개, High: N개, Medium: N개, Low: N개

## 이슈 목록

### /review-code 영역 (RC-XXX)
#### Critical - 보안 취약점
1. [ ] [RC-001] SQL Injection - [src/services/db.py:45](../src/services/db.py#L45)
   - 문제: 사용자 입력을 직접 쿼리에 삽입
   - 수정: Parameterized Query 사용

#### Medium - Dead Code
2. [ ] [RC-002] 미사용 함수 - [src/utils/helper.py:23-35](../src/utils/helper.py#L23-L35)

### /readability 영역 (RD-XXX)
3. [ ] [RD-001] 변수명 불명확 - [src/handlers/api.py:80](../src/handlers/api.py#L80)
   - 현재: `d = get_data()`
   - 제안: `user_data = get_user_data()`

### /solid-check 영역 (SC-XXX)
4. [ ] [SC-001] SRP 위반 - [src/services/payment.py](../src/services/payment.py)
   - 문제: PaymentService가 결제, 알림, 로깅 모두 처리

### /optimize 영역 (OP-XXX)
5. [ ] [OP-001] N+1 쿼리 - [src/models/order.py:200](../src/models/order.py#L200)
   - 성능 영향: 100명 사용자 시 101번 쿼리
```

**링크 형식 규칙** (docs/ 폴더 기준):
- 단일 라인: `[파일경로:라인번호](../파일경로#L라인번호)`
  - 예: `[src/services/db.py:45](../src/services/db.py#L45)`
- 범위 지정: `[파일경로:시작-끝](../파일경로#L시작-L끝)`
  - 예: `[src/utils/helper.py:23-35](../src/utils/helper.py#L23-L35)`
- 파일 전체: `[파일경로](../파일경로)`
  - 예: `[src/services/payment.py](../src/services/payment.py)`
- **중요**: docs/ 폴더에서 프로젝트 루트로 이동하기 위해 `../` 사용

**번호 체계**:
- 각 이슈는 전체 문서 기준 연속 번호 (1, 2, 3, ...)
- 이슈 ID는 카테고리별로 유지 (RC-001, RD-001, SC-001, OP-001)

### Phase 3: 사용자 알림

문서 생성 후 사용자에게 알림:
```
## 리팩토링 분석 완료

분석 결과를 `docs/refactor_report.md`에 저장했습니다.

### 📊 분석 요약
- 총 이슈: N개
- Critical: N개, High: N개, Medium: N개, Low: N개

### 📝 다음 단계
1. `docs/refactor_report.md` 파일을 열어 이슈를 검토하세요
2. 필요시 이슈를 수정/삭제/추가하세요
3. 특정 영역의 이슈를 수정하려면:
   - `/review-code` - RC-XXX 이슈만 실행
   - `/readability` - RD-XXX 이슈만 실행
   - `/solid-check` - SC-XXX 이슈만 실행
   - `/optimize` - OP-XXX 이슈만 실행

### 🔍 주요 Critical 이슈 미리보기
- [RC-001] SQL Injection - [services/database.py:45](services/database.py#L45)
- [RC-002] 하드코딩된 API 키 - [config/settings.py:10](config/settings.py#L10)
- [OP-001] N+1 쿼리 - [models/order.py:200](models/order.py#L200)

💡 파일 경로를 클릭하면 해당 위치로 바로 이동합니다.
```

## 출력 형식 (CRITICAL - 반드시 준수)

### 파일 경로 링크 형식

**CRITICAL**: 모든 파일 경로는 **클릭 가능한 마크다운 링크**로 출력해야 합니다:

**필수 형식** (docs/ 폴더 기준):
1. **단일 라인**: `[파일경로:라인번호](../파일경로#L라인번호)`
2. **범위 지정**: `[파일경로:시작-끝](../파일경로#L시작-L끝)`
3. **파일 전체**: `[파일경로](../파일경로)`

**예시:**
- ✅ Good: `[src/services/npc/dialogue.py:120](../src/services/npc/dialogue.py#L120)`
- ✅ Good: `[src/models/user.py:45](../src/models/user.py#L45)`
- ✅ Good: `[src/utils/helper.py:23-35](../src/utils/helper.py#L23-L35)` (범위)
- ✅ Good: `[src/services/payment.py](../src/services/payment.py)` (파일 전체)
- ❌ Bad: `[src/services/db.py:45](src/services/db.py#L45)` (../ 없음, 작동 안 함)
- ❌ Bad: `src/database.py:45` (링크 형식 아님)
- ❌ Bad: `` `src/database.py:45` `` (백틱 사용, 클릭 불가)

**왜 이 형식인가?**
- `../`를 사용하여 docs/ 폴더에서 프로젝트 루트로 이동
- Markdown 에디터에서 클릭 시 해당 파일의 정확한 라인으로 이동
- `#L45` 형식은 GitHub, VSCode, Cursor 등에서 표준으로 지원
- 범위 지정 시 `#L23-L35`로 시작~끝 라인 표시

### 이슈 ID 형식

각 이슈는 고유한 ID를 가집니다:
- **RC-001, RC-002, ...**: /review-code 영역
- **RD-001, RD-002, ...**: /readability 영역
- **SC-001, SC-002, ...**: /solid-check 영역
- **OP-001, OP-002, ...**: /optimize 영역

## 중요 지침 (Important Guidelines)

### 1. 문서 생성 필수
- ✅ **반드시** `docs/refactor_report.md` 파일을 생성하세요
- ✅ 모든 이슈에 고유 ID (RC-XXX, RD-XXX, SC-XXX, OP-XXX)를 부여하세요
- ✅ 체크박스 형식 `- [ ]`을 사용하여 추후 완료 표시 가능하게 하세요
- ✅ **파일 경로는 반드시 마크다운 링크 형식**으로 작성하세요

### 2. 절대 금지 사항
- ❌ 분석 후 즉시 코드를 수정하지 마세요 (문서만 생성)
- ❌ 분석 결과를 생략하거나 요약하지 마세요 (모든 이슈를 나열)
- ❌ "// ... existing code ..." 같은 lazy coding 금지
- ❌ 파일 경로를 백틱(`` ` ``)으로 감싸지 마세요 (클릭 불가)

### 3. 필수 사항
- ✅ 각 이슈에 **클릭 가능한 링크 형식**으로 파일 경로와 라인 번호를 명시하세요
  - 형식: `[파일경로:라인](../파일경로#L라인)` (docs/ 폴더 기준)
- ✅ 각 이슈에 전체 문서 기준 연속 번호 부여 (1, 2, 3, ...)
- ✅ 문제의 원인과 수정 방법을 명확히 설명하세요
- ✅ 포트폴리오 관점에서 "왜 이 수정이 중요한지" 설명하세요

### 4. 우선순위 판단 기준
- **Critical**: 보안 취약점, 치명적 버그, 데이터 손실 가능성
- **High**: SOLID 위반, 성능 문제, 로직 오류
- **Medium**: 가독성 문제, 중복 코드
- **Low**: 변수명, 주석, 코드 스타일

## 사용 예시 (Usage Examples)

### 예시 1: 전체 프로젝트 분석
```
사용자: /refactor

AI: @codebase 전체 프로젝트 분석 중...
    
    분석 완료! `docs/refactor_report.md` 파일을 생성했습니다.
    
    ## 📊 분석 요약
    - 총 이슈: 16개
    - Critical: 2개, High: 5개, Medium: 6개, Low: 3개
    
    ## 📝 다음 단계
    1. `docs/refactor_report.md`를 열어 이슈를 검토하세요
    2. 특정 영역을 수정하려면:
       - `/review-code` - 보안/Dead Code (RC-XXX)
       - `/readability` - 가독성 (RD-XXX)
       - `/solid-check` - SOLID 원칙 (SC-XXX)
       - `/optimize` - 성능/안정성 (OP-XXX)
    
    ## 🔍 주요 Critical 이슈
    1. [RC-001] SQL Injection - [src/services/database.py:45](../src/services/database.py#L45)
    2. [RC-002] 하드코딩된 API 키 - [config/settings.py:10](../config/settings.py#L10)
    
    💡 파일 경로를 클릭하면 해당 위치로 바로 이동합니다.
```

### 예시 2: 특정 폴더만 분석
```
사용자: /refactor @npc/

AI: @npc/ 폴더 분석 중...
    
    분석 완료! `docs/refactor_report.md` 파일을 생성했습니다.
    
    ## 📊 분석 요약
    - 총 이슈: 5개
    - Medium: 3개, Low: 2개
    
    주요 이슈:
    1. [RC-001] Dead Code - [src/agents/npc/dialogue_manager.py:120](../src/agents/npc/dialogue_manager.py#L120)
    2. [RD-001] 변수명 불명확 - [src/agents/npc/ai_behavior.py:80](../src/agents/npc/ai_behavior.py#L80)
```

### 예시 3: 하위 명령어로 수정 실행
```
사용자: /optimize

AI: `docs/refactor_report.md`에서 /optimize 영역 이슈를 읽었습니다.
    
    ## ⚡ /optimize 영역 이슈
    
    □ [OP-001] N+1 쿼리 - `models/order.py:200`
    □ [OP-002] O(n²) 알고리즘 - `utils/processor.py:80`
    
    선택: "진행해" | "1,2" | "OP-001만"

사용자: 진행해

AI: 수정 완료! `docs/refactor_report.md`를 업데이트했습니다.
    - [x] [OP-001] N+1 쿼리 수정
    - [x] [OP-002] 알고리즘 개선
```

## 연구 기반 (Research-Based)

이 명령어는 다음 연구 결과를 반영합니다:
- **ACONIC Framework (2025)**: Task Decomposition이 10-40% 성능 향상
- **arXiv:2512.14012**: Professional Developers는 제어권을 유지해야 함
- **HiLDe (UC San Diego, 2025)**: Human-in-the-Loop가 보안 취약점 감소

## 참고 자료
- [Cursor Commands 공식 문서](https://cursor.com/ko/docs/context/commands)
- [SOLID 원칙](https://en.wikipedia.org/wiki/SOLID)
- [Clean Code by Robert C. Martin](https://www.amazon.com/Clean-Code-Handbook-Software-Craftsmanship/dp/0132350882)
