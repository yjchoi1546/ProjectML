# /optimize - 성능 최적화 및 안정성 강화

## 역할 (Role)
당신은 성능 최적화 전문가로서, "효율적이고 안정적인 코드"를 만듭니다. 포트폴리오에서 성능과 안정성에 대한 이해도를 보여줍니다.

## 작동 방식 (Workflow)
이 명령어는 `/refactor`가 생성한 `docs/refactor_report.md` 파일을 읽어서 작동합니다.

1. **Phase 1**: `docs/refactor_report.md` 파일 존재 확인
   - 파일이 없으면: "먼저 `/refactor`를 실행하여 분석 문서를 생성하세요" 안내
   - 파일이 있으면: 파일을 읽어서 **OP-XXX** 영역의 이슈만 필터링

2. **Phase 2**: OP-XXX 이슈 목록 표시 및 사용자 선택 대기

3. **Phase 3**: 선택된 이슈 수정 실행

4. **Phase 4**: 완료 후 `docs/refactor_report.md` 업데이트 (체크박스 표시)

## 포트폴리오 가치 (Portfolio Value)
이 명령어로 수정된 코드는 다음을 증명합니다:
- ✅ 성능 최적화 능력 (알고리즘, DB 쿼리)
- ✅ 안정성 설계 (에러 핸들링)
- ✅ 확장 가능한 구조 (God Class 분리)

## 최적화 항목 (Optimization Items)

### 1. N+1 쿼리 문제 (N+1 Query Problem)

#### 정의
반복문 내에서 개별 쿼리를 실행하여 불필요한 DB 호출이 발생하는 문제

#### 검출 대상
- 반복문 내 DB 쿼리
- 관계형 데이터 로딩 시 개별 쿼리
- ORM의 Lazy Loading 남용

#### 성능 영향
- **Before**: N개 아이템 → N+1번 쿼리 (1 + N)
- **After**: 1-2번 쿼리 (JOIN 또는 Eager Loading)
- **개선**: 100배 이상 속도 향상 가능

#### 위반 예시와 수정
```python
# Bad - N+1 쿼리 문제
def get_users_with_orders():
    users = User.query.all()  # 1번 쿼리
    result = []
    for user in users:  # N번 반복
        orders = Order.query.filter_by(user_id=user.id).all()  # N번 쿼리!
        result.append({
            'user': user,
            'orders': orders
        })
    return result
# 총 쿼리 수: 1 + N번 (N = 사용자 수)

# Good - JOIN 사용
def get_users_with_orders():
    users = User.query.options(
        joinedload(User.orders)  # 1번 쿼리로 모두 로딩
    ).all()
    return users
# 총 쿼리 수: 1번

# Good - Eager Loading (SQLAlchemy)
users = db.session.query(User).options(
    selectinload(User.orders)
).all()

# Good - Raw SQL JOIN
SELECT users.*, orders.*
FROM users
LEFT JOIN orders ON users.id = orders.user_id
```

### 2. 알고리즘 복잡도 개선 (Algorithm Complexity)

#### 정의
시간 복잡도(Time Complexity)와 공간 복잡도(Space Complexity)를 개선하여 성능 향상

#### 검출 대상
- 중첩 반복문 (O(n²), O(n³))
- 불필요한 정렬
- 선형 탐색 (O(n)) → 해시 테이블 (O(1))

#### 개선 예시
```python
# Bad - O(n²) 중첩 반복문
def find_duplicates(items):
    duplicates = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i] == items[j]:
                duplicates.append(items[i])
    return duplicates
# 시간 복잡도: O(n²)

# Good - O(n) 해시 테이블
def find_duplicates(items):
    seen = set()
    duplicates = set()
    for item in items:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    return list(duplicates)
# 시간 복잡도: O(n)

# Bad - O(n) 선형 탐색
def find_user_by_id(users, target_id):
    for user in users:
        if user.id == target_id:
            return user
    return None
# 시간 복잡도: O(n)

# Good - O(1) 해시 테이블
user_dict = {user.id: user for user in users}  # O(n) 한 번만
user = user_dict.get(target_id)  # O(1)
# 시간 복잡도: O(1) (조회 시)

# Bad - 불필요한 정렬
def get_top_5_scores(scores):
    sorted_scores = sorted(scores, reverse=True)  # O(n log n)
    return sorted_scores[:5]

# Good - heapq 사용
import heapq
def get_top_5_scores(scores):
    return heapq.nlargest(5, scores)  # O(n log k), k=5
```

### 3. 캐싱 도입 (Caching)

#### 정의
반복적으로 계산되는 값을 저장하여 재사용

#### 검출 대상
- 동일한 계산이 반복됨
- 변경되지 않는 데이터를 매번 조회
- 무거운 연산 (API 호출, DB 쿼리, 파일 I/O)

#### 캐싱 전략
- **Memoization**: 함수 결과 캐싱
- **LRU Cache**: 최근 사용 항목 캐싱
- **Redis/Memcached**: 분산 캐싱

#### 개선 예시
```python
# Bad - 반복 계산
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
# 시간 복잡도: O(2^n) - 매우 느림!

# Good - Memoization
from functools import lru_cache

@lru_cache(maxsize=None)
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
# 시간 복잡도: O(n)

# Bad - 매번 DB 조회
def get_user_profile(user_id):
    return db.query(User).get(user_id)

# Good - 캐싱
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_user_profile(user_id):
    return db.query(User).get(user_id)

# Good - Redis 캐싱
import redis
cache = redis.Redis()

def get_user_profile(user_id):
    # 캐시 확인
    cached = cache.get(f"user:{user_id}")
    if cached:
        return json.loads(cached)
    
    # DB 조회
    user = db.query(User).get(user_id)
    
    # 캐시 저장 (1시간)
    cache.setex(f"user:{user_id}", 3600, json.dumps(user))
    return user
```

### 4. God Class 분리 (God Class Decomposition)

#### 정의
너무 많은 책임을 가진 클래스를 작은 클래스로 분리

#### 검출 대상
- 1000줄 이상 클래스
- 10개 이상 메서드
- 여러 책임을 가진 클래스

#### 개선 예시
```python
# Bad - God Class (500줄)
class OrderManager:
    def create_order(self, data):
        # 주문 생성 로직 (50줄)
        pass
    
    def validate_order(self, order):
        # 검증 로직 (30줄)
        pass
    
    def calculate_total(self, order):
        # 금액 계산 (40줄)
        pass
    
    def apply_discount(self, order):
        # 할인 적용 (50줄)
        pass
    
    def process_payment(self, order):
        # 결제 처리 (60줄)
        pass
    
    def send_confirmation_email(self, order):
        # 이메일 발송 (40줄)
        pass
    
    def update_inventory(self, order):
        # 재고 업데이트 (50줄)
        pass
    
    def generate_invoice(self, order):
        # 송장 생성 (60줄)
        pass
    
    def log_order(self, order):
        # 로그 기록 (30줄)
        pass

# Good - 책임 분리
class OrderValidator:
    """주문 검증"""
    def validate(self, order):
        pass

class OrderCalculator:
    """금액 계산"""
    def calculate_total(self, order):
        pass
    
    def apply_discount(self, order):
        pass

class PaymentProcessor:
    """결제 처리"""
    def process(self, order):
        pass

class OrderNotifier:
    """알림 발송"""
    def send_confirmation_email(self, order):
        pass

class InventoryManager:
    """재고 관리"""
    def update(self, order):
        pass

class InvoiceGenerator:
    """송장 생성"""
    def generate(self, order):
        pass

class OrderService:
    """주문 서비스 (조율자)"""
    def __init__(self, validator, calculator, payment_processor, 
                 notifier, inventory_manager, invoice_generator):
        self.validator = validator
        self.calculator = calculator
        self.payment_processor = payment_processor
        self.notifier = notifier
        self.inventory_manager = inventory_manager
        self.invoice_generator = invoice_generator
    
    def create_order(self, data):
        # 각 컴포넌트 조율
        order = Order(data)
        self.validator.validate(order)
        self.calculator.calculate_total(order)
        self.payment_processor.process(order)
        self.notifier.send_confirmation_email(order)
        self.inventory_manager.update(order)
        self.invoice_generator.generate(order)
        return order
```

### 5. 에러 핸들링 패턴 개선 (Error Handling)

#### 정의
일관되고 안정적인 에러 처리로 시스템 안정성 향상

#### 검출 대상
- 빈 except 블록 (except: pass)
- 광범위한 예외 처리 (except Exception)
- 에러 로깅 누락
- 리소스 정리 누락 (파일, DB 연결)

#### 개선 예시
```python
# Bad - 광범위한 예외 처리
def process_data(file_path):
    try:
        data = read_file(file_path)
        result = process(data)
        return result
    except:  # 모든 예외를 잡음!
        return None

# Good - 구체적인 예외 처리
def process_data(file_path):
    try:
        data = read_file(file_path)
        result = process(data)
        return result
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        raise
    except PermissionError:
        logger.error(f"Permission denied: {file_path}")
        raise
    except ValueError as e:
        logger.error(f"Invalid data format: {e}")
        raise

# Bad - 리소스 정리 누락
def read_file(path):
    file = open(path, 'r')
    data = file.read()
    file.close()  # 에러 발생 시 실행 안 됨!
    return data

# Good - Context Manager 사용
def read_file(path):
    with open(path, 'r') as file:
        data = file.read()
    return data  # 자동으로 파일 닫힘

# Good - Custom Exception
class OrderValidationError(Exception):
    """주문 검증 실패"""
    pass

class PaymentFailedError(Exception):
    """결제 실패"""
    pass

def create_order(data):
    if not validate_order(data):
        raise OrderValidationError("Invalid order data")
    
    if not process_payment(data):
        raise PaymentFailedError("Payment failed")

# Bad - 에러 무시
def save_to_cache(key, value):
    try:
        cache.set(key, value)
    except:
        pass  # 에러 무시!

# Good - 에러 로깅
def save_to_cache(key, value):
    try:
        cache.set(key, value)
    except redis.ConnectionError:
        logger.warning(f"Cache unavailable, key: {key}")
        # 캐시 실패는 치명적이지 않으므로 계속 진행
    except Exception as e:
        logger.error(f"Unexpected cache error: {e}")
        # 예상치 못한 에러는 로깅하고 계속 진행

# Good - Retry 패턴
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
def call_external_api(url):
    response = requests.get(url, timeout=5)
    response.raise_for_status()
    return response.json()
```

## 분석 방법 (How to Analyze)

### Cursor 기능 활용
이 명령어는 Cursor의 다음 기능을 활용합니다:

1. **@codebase**: 전체 프로젝트 시맨틱 인덱싱
   - 코드 흐름 및 성능 병목 분석
   - DB 쿼리 패턴 탐지

2. **SemanticSearch**: 성능 안티패턴 검색
3. **Grep**: N+1 쿼리, 중첩 반복문, 예외 처리 검색
4. **Read**: 알고리즘 복잡도 분석

### 분석 범위 지정

**전체 프로젝트 분석 (기본):**
```
/optimize
```

**특정 폴더만 분석:**
```
/optimize @services/
/optimize @models/
```

**특정 파일만 분석:**
```
/optimize @services/payment_processor.py
```

**키워드 기반 분석:**
```
/optimize database 관련만
/optimize 성능 문제만
```

## 실행 프로세스 (Execution Process)

### Phase 1: 문서 읽기 및 이슈 필터링

1. **문서 확인**:
   ```
   `docs/refactor_report.md` 파일이 존재하는가?
   ```
   - **NO** → 사용자에게 알림:
     ```
     ⚠️ 먼저 `/refactor`를 실행하여 분석 문서를 생성하세요.
     
     사용법:
     1. `/refactor` - 전체 프로젝트 분석
     2. `/refactor @폴더명` - 특정 폴더만 분석
     
     분석 완료 후 `/optimize`를 다시 실행하세요.
     ```
   - **YES** → 다음 단계로

2. **OP-XXX 이슈 필터링**:
   - `docs/refactor_report.md`에서 `/optimize 영역 (OP-XXX)` 섹션 읽기
   - 체크되지 않은 이슈 `- [ ]`만 추출
   - 이미 완료된 이슈 `- [x]`는 제외

## 출력 형식 (CRITICAL - 반드시 준수)

### 파일 경로 형식
모든 파일 경로는 **클릭 가능한 형식**으로 출력해야 합니다:

**필수 형식**: `` `경로/파일명.확장자:라인번호` ``

**예시:**
- ✅ Good: `services/user_service.py:45`
- ✅ Good: `utils/processor.py:80`
- ✅ Good: `services/order_manager.py:50-200` (범위)
- ❌ Bad: `services/user_service.py` (라인 번호 없음)

### Phase 2: 이슈 목록 표시
```
## ⚡ /optimize 영역 이슈 (`docs/refactor_report.md` 기준)

발견된 이슈: N개

### 🚀 Performance - N+1 쿼리
1. [ ] [OP-001] N+1 쿼리 문제 - [src/services/user_service.py:45](../src/services/user_service.py#L45)
   - 성능 영향: 100명 사용자 → 101번 쿼리
   - 예상 개선: 100배 속도 향상

### ⚡ Performance - 알고리즘 복잡도
2. [ ] [OP-002] O(n²) 중첩 반복문 - [src/utils/processor.py:80](../src/utils/processor.py#L80)
   - 예상 개선: 1000배 속도 향상

### 💾 Performance - 캐싱 누락
3. [ ] [OP-003] 반복 계산 - [src/services/report.py:120](../src/services/report.py#L120)
   - 예상 개선: 10배 속도 향상

### 🏗️ Structure - God Class
4. [ ] [OP-004] 1200줄 클래스 - [src/services/order_manager.py](../src/services/order_manager.py)
   - 15개 메서드, 5개 책임

### 🛡️ Stability - 에러 핸들링
5. [ ] [OP-005] 광범위한 예외 처리 - [src/handlers/api.py:200](../src/handlers/api.py#L200)
6. [ ] [OP-006] 리소스 정리 누락 - [src/utils/file_handler.py:50](../src/utils/file_handler.py#L50)

---

## 선택 방법
- "진행해" → 전체 수정
- "OP-001,OP-003" → 특정 이슈 선택
- "1,2,3" → 번호로 선택
- "Performance만" → 성능 이슈만 수정
- "OP-001 수정: [피드백]" → 제안 수정
```

### Phase 3: 사용자 선택 대기
사용자의 입력을 기다립니다.

### Phase 4: 수정 실행
선택된 항목만 수정합니다.

### Phase 5: 문서 업데이트 및 결과 표시
```
## 수정 완료

### 수정된 파일
- `services/user_service.py` (N+1 쿼리 수정)
- `utils/processor.py` (알고리즘 개선)

### 성능 개선 효과
1. [OP-001] N+1 쿼리 수정
   - Before: 101번 쿼리 (1 + 100)
   - After: 1번 쿼리
   - 개선: 100배 속도 향상
   - 응답 시간: 5초 → 50ms

2. [OP-002] 알고리즘 개선
   - Before: O(n²) = 1,000,000번 연산
   - After: O(n) = 1,000번 연산
   - 개선: 1000배 속도 향상

### 📝 문서 업데이트
`docs/refactor_report.md` 파일에서 완료된 이슈를 체크 표시했습니다:
- [x] [OP-001] N+1 쿼리 문제
- [x] [OP-002] O(n²) 중첩 반복문

### 권장 사항
- 프로파일링 도구로 성능 측정하세요
- 부하 테스트를 실행하세요
```

## 중요 지침 (Important Guidelines)

### 1. 우선순위
1. **Critical**: N+1 쿼리, O(n²) 이상 알고리즘
2. **High**: 에러 핸들링 누락, 리소스 정리 누락
3. **Medium**: 캐싱 누락, God Class
4. **Low**: 미세 최적화

### 2. 성능 측정
- 수정 전후 벤치마크 제공
- Big-O 표기법으로 복잡도 표시
- 예상 개선 효과 명시

### 3. 절대 금지
- ❌ 측정 없는 최적화 (Premature Optimization)
- ❌ 가독성을 해치는 최적화
- ❌ 에러를 무시하는 코드

### 4. 포트폴리오 관점
각 수정에 다음을 포함하세요:
- **성능 영향**: 수치로 표현 (100배 향상)
- **복잡도**: Big-O 표기법
- **트레이드오프**: 메모리 vs 속도

## 도구 및 기법 (Tools & Techniques)

### 프로파일링
```python
# Python - cProfile
import cProfile
cProfile.run('my_function()')

# Python - line_profiler
@profile
def my_function():
    pass

# Python - memory_profiler
from memory_profiler import profile
@profile
def my_function():
    pass
```

### 벤치마킹
```python
import timeit

# 실행 시간 측정
time = timeit.timeit('my_function()', number=1000)
print(f"Average time: {time/1000:.6f}s")
```

## 사용 예시 (Usage Examples)

### 예시 1: 문서 없이 실행 시
```
사용자: /optimize

AI: ⚠️ 먼저 `/refactor`를 실행하여 분석 문서를 생성하세요.
    
    사용법:
    1. `/refactor` - 전체 프로젝트 분석
    2. `/refactor @폴더명` - 특정 폴더만 분석
    
    분석 완료 후 `/optimize`를 다시 실행하세요.
```

### 예시 2: 문서에서 이슈 읽기 및 실행
```
사용자: (먼저 /refactor 실행 후)
사용자: /optimize

AI: `docs/refactor_report.md`에서 /optimize 영역 이슈를 읽었습니다.
    
    ## ⚡ /optimize 영역 이슈
    
    발견된 이슈: 4개
    
    1. [ ] [OP-001] N+1 쿼리 - [src/services/user_service.py:45](../src/services/user_service.py#L45)
    2. [ ] [OP-002] O(n²) 알고리즘 - [src/utils/processor.py:80](../src/utils/processor.py#L80)
    3. [ ] [OP-003] 캐싱 누락 - [src/services/report.py:120](../src/services/report.py#L120)
    4. [ ] [OP-004] God Class - [src/services/order_manager.py](../src/services/order_manager.py)
    
    선택: "진행해" | "OP-001,OP-002" | "1,2"

사용자: OP-001,OP-002

AI: 수정 완료! `docs/refactor_report.md`를 업데이트했습니다.
    
    - [x] [OP-001] N+1 쿼리 수정 (100배 속도 향상)
    - [x] [OP-002] 알고리즘 개선 (1000배 속도 향상)
```

### 예시 3: 성능 이슈만 선택
```
사용자: Performance만 수정해줘

AI: Performance 관련 이슈만 수정 중...
    
    수정 완료:
    - [x] [OP-001] N+1 쿼리 수정
      - Before: 101번 쿼리
      - After: 1번 쿼리 (JOIN 사용)
      - 개선: 100배 속도 향상, 5초 → 50ms
    
    - [x] [OP-002] 알고리즘 개선
      - Before: O(n²) = 1,000,000번 연산
      - After: O(n) = 1,000번 연산
      - 개선: 1000배 속도 향상
```

## 참고 자료 (References)

### 성능 최적화
- [High Performance Python](https://www.oreilly.com/library/view/high-performance-python/9781492055013/)
- [Database Performance Tuning](https://use-the-index-luke.com/)
- [Big-O Cheat Sheet](https://www.bigocheatsheet.com/)

### 에러 핸들링
- [Python Exception Handling Best Practices](https://docs.python.org/3/tutorial/errors.html)
- [Effective Error Handling](https://www.joelonsoftware.com/2003/10/13/13/)

### 알고리즘
- [Introduction to Algorithms (CLRS)](https://mitpress.mit.edu/books/introduction-algorithms-third-edition)
- [LeetCode](https://leetcode.com/)
- [Algorithm Visualizer](https://algorithm-visualizer.org/)
