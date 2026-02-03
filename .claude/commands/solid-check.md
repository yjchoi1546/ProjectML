# /solid-check - SOLID 원칙 검증

## 역할 (Role)
당신은 객체지향 설계 전문가로서, SOLID 원칙 준수 여부를 검증하고 "유지보수 가능한 설계"를 만듭니다.

## 작동 방식 (Workflow)
이 명령어는 `/refactor`가 생성한 `docs/refactor_report.md` 파일을 읽어서 작동합니다.

1. **Phase 1**: `docs/refactor_report.md` 파일 존재 확인
   - 파일이 없으면: "먼저 `/refactor`를 실행하여 분석 문서를 생성하세요" 안내
   - 파일이 있으면: 파일을 읽어서 **SC-XXX** 영역의 이슈만 필터링

2. **Phase 2**: SC-XXX 이슈 목록 표시 및 사용자 선택 대기

3. **Phase 3**: 선택된 이슈 수정 실행

4. **Phase 4**: 완료 후 `docs/refactor_report.md` 업데이트 (체크박스 표시)

## 포트폴리오 가치 (Portfolio Value)
이 명령어로 수정된 코드는 다음을 증명합니다:
- ✅ 객체지향 설계 원칙 이해
- ✅ 확장 가능한 아키텍처 설계 능력
- ✅ 엔터프라이즈급 코드 작성 능력

## SOLID 원칙 (SOLID Principles)

### 1. SRP (Single Responsibility Principle) - 단일 책임 원칙

#### 정의
**"한 클래스는 하나의 책임만 가져야 한다"**
- 클래스를 변경하는 이유는 단 하나여야 함
- 하나의 클래스가 여러 역할을 하면 안 됨

#### 검출 대상
- 여러 책임을 가진 클래스 (God Class)
- 클래스명과 메서드가 일치하지 않음
- 클래스가 너무 많은 의존성을 가짐

#### 위반 예시와 수정
```python
# Bad - SRP 위반
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
    
    def save_to_database(self):
        """데이터베이스 저장 - DB 책임"""
        db.save(self)
    
    def send_welcome_email(self):
        """이메일 발송 - 이메일 책임"""
        email_service.send(self.email, "Welcome!")
    
    def generate_report(self):
        """보고서 생성 - 보고서 책임"""
        return f"User Report: {self.name}"
    
    def log_activity(self):
        """로그 기록 - 로깅 책임"""
        logger.info(f"User {self.name} activity")

# Good - SRP 준수
class User:
    """사용자 엔티티 - 사용자 데이터만 관리"""
    def __init__(self, name, email):
        self.name = name
        self.email = email

class UserRepository:
    """사용자 저장소 - DB 책임"""
    def save(self, user):
        db.save(user)
    
    def find_by_email(self, email):
        return db.query(User).filter_by(email=email).first()

class UserNotificationService:
    """사용자 알림 - 이메일 책임"""
    def send_welcome_email(self, user):
        email_service.send(user.email, "Welcome!")

class UserReportGenerator:
    """사용자 보고서 - 보고서 책임"""
    def generate(self, user):
        return f"User Report: {user.name}"

class UserActivityLogger:
    """사용자 활동 로깅 - 로깅 책임"""
    def log(self, user, action):
        logger.info(f"User {user.name}: {action}")
```

### 2. OCP (Open-Closed Principle) - 개방-폐쇄 원칙

#### 정의
**"확장에는 열려 있고, 수정에는 닫혀 있어야 한다"**
- 새로운 기능 추가 시 기존 코드를 수정하지 않아야 함
- 추상화와 다형성을 활용

#### 검출 대상
- if/elif/switch로 타입을 분기하는 코드
- 새로운 타입 추가 시 기존 코드 수정 필요
- 하드코딩된 타입 체크

#### 위반 예시와 수정
```python
# Bad - OCP 위반
class PaymentProcessor:
    def process(self, payment_type, amount):
        if payment_type == "credit_card":
            # 신용카드 처리
            return self._process_credit_card(amount)
        elif payment_type == "paypal":
            # PayPal 처리
            return self._process_paypal(amount)
        elif payment_type == "bank_transfer":
            # 계좌이체 처리
            return self._process_bank_transfer(amount)
        # 새로운 결제 수단 추가 시 이 코드를 수정해야 함!

# Good - OCP 준수 (Strategy 패턴)
from abc import ABC, abstractmethod

class PaymentStrategy(ABC):
    """결제 전략 인터페이스"""
    @abstractmethod
    def process(self, amount):
        pass

class CreditCardPayment(PaymentStrategy):
    """신용카드 결제"""
    def process(self, amount):
        # 신용카드 처리 로직
        return f"Credit card payment: ${amount}"

class PayPalPayment(PaymentStrategy):
    """PayPal 결제"""
    def process(self, amount):
        # PayPal 처리 로직
        return f"PayPal payment: ${amount}"

class BankTransferPayment(PaymentStrategy):
    """계좌이체 결제"""
    def process(self, amount):
        # 계좌이체 처리 로직
        return f"Bank transfer: ${amount}"

class PaymentProcessor:
    """결제 처리기 - 기존 코드 수정 없이 확장 가능"""
    def __init__(self, strategy: PaymentStrategy):
        self.strategy = strategy
    
    def process(self, amount):
        return self.strategy.process(amount)

# 사용
processor = PaymentProcessor(CreditCardPayment())
processor.process(100)

# 새로운 결제 수단 추가 시 기존 코드 수정 불필요!
class CryptoPayment(PaymentStrategy):
    def process(self, amount):
        return f"Crypto payment: ${amount}"
```

### 3. LSP (Liskov Substitution Principle) - 리스코프 치환 원칙

#### 정의
**"자식 클래스는 부모 클래스를 대체할 수 있어야 한다"**
- 부모 클래스의 인스턴스를 자식 클래스로 바꿔도 동작해야 함
- 자식 클래스가 부모의 계약을 위반하면 안 됨

#### 검출 대상
- 자식 클래스가 부모 메서드를 빈 구현으로 오버라이드
- 자식 클래스가 부모보다 약한 전제조건 또는 강한 후속조건
- 예외를 던지는 오버라이드

#### 위반 예시와 수정
```python
# Bad - LSP 위반
class Bird:
    def fly(self):
        return "Flying"

class Sparrow(Bird):
    def fly(self):
        return "Sparrow flying"

class Penguin(Bird):
    def fly(self):
        # 펭귄은 날 수 없음!
        raise NotImplementedError("Penguins can't fly")

# 문제: Bird를 기대하는 코드에 Penguin을 넣으면 예외 발생
def make_bird_fly(bird: Bird):
    return bird.fly()

make_bird_fly(Sparrow())  # OK
make_bird_fly(Penguin())  # Error!

# Good - LSP 준수
class Bird:
    """새 기본 클래스"""
    def move(self):
        pass

class FlyingBird(Bird):
    """날 수 있는 새"""
    def fly(self):
        return "Flying"
    
    def move(self):
        return self.fly()

class Sparrow(FlyingBird):
    def fly(self):
        return "Sparrow flying"

class Penguin(Bird):
    """날 수 없는 새"""
    def swim(self):
        return "Swimming"
    
    def move(self):
        return self.swim()

# 사용
def make_bird_move(bird: Bird):
    return bird.move()

make_bird_move(Sparrow())  # "Sparrow flying"
make_bird_move(Penguin())  # "Swimming"
```

### 4. ISP (Interface Segregation Principle) - 인터페이스 분리 원칙

#### 정의
**"클라이언트는 사용하지 않는 인터페이스에 의존하지 않아야 한다"**
- 큰 인터페이스를 작은 인터페이스로 분리
- 필요한 메서드만 구현

#### 검출 대상
- 빈 메서드 구현 (pass, NotImplementedError)
- 모든 메서드를 사용하지 않는 클래스
- Fat Interface (너무 많은 메서드)

#### 위반 예시와 수정
```python
# Bad - ISP 위반
class Worker(ABC):
    @abstractmethod
    def work(self):
        pass
    
    @abstractmethod
    def eat(self):
        pass
    
    @abstractmethod
    def sleep(self):
        pass

class HumanWorker(Worker):
    def work(self):
        return "Working"
    
    def eat(self):
        return "Eating"
    
    def sleep(self):
        return "Sleeping"

class RobotWorker(Worker):
    def work(self):
        return "Working"
    
    def eat(self):
        # 로봇은 먹지 않음!
        pass
    
    def sleep(self):
        # 로봇은 자지 않음!
        pass

# Good - ISP 준수
class Workable(ABC):
    @abstractmethod
    def work(self):
        pass

class Eatable(ABC):
    @abstractmethod
    def eat(self):
        pass

class Sleepable(ABC):
    @abstractmethod
    def sleep(self):
        pass

class HumanWorker(Workable, Eatable, Sleepable):
    def work(self):
        return "Working"
    
    def eat(self):
        return "Eating"
    
    def sleep(self):
        return "Sleeping"

class RobotWorker(Workable):
    """로봇은 일만 함 - 필요한 인터페이스만 구현"""
    def work(self):
        return "Working"
```

### 5. DIP (Dependency Inversion Principle) - 의존성 역전 원칙

#### 정의
**"고수준 모듈은 저수준 모듈에 의존하지 않아야 한다. 둘 다 추상화에 의존해야 한다"**
- 구체 클래스가 아닌 인터페이스에 의존
- 의존성 주입(Dependency Injection) 사용

#### 검출 대상
- 클래스 내부에서 직접 객체 생성 (new, 생성자 호출)
- 구체 클래스에 직접 의존
- 하드코딩된 의존성

#### 위반 예시와 수정
```python
# Bad - DIP 위반
class MySQLDatabase:
    def save(self, data):
        print(f"Saving to MySQL: {data}")

class UserService:
    def __init__(self):
        # 구체 클래스에 직접 의존!
        self.database = MySQLDatabase()
    
    def create_user(self, user):
        self.database.save(user)

# 문제: MySQL에서 PostgreSQL로 변경하려면 UserService 수정 필요

# Good - DIP 준수
from abc import ABC, abstractmethod

class Database(ABC):
    """데이터베이스 인터페이스 (추상화)"""
    @abstractmethod
    def save(self, data):
        pass

class MySQLDatabase(Database):
    def save(self, data):
        print(f"Saving to MySQL: {data}")

class PostgreSQLDatabase(Database):
    def save(self, data):
        print(f"Saving to PostgreSQL: {data}")

class UserService:
    def __init__(self, database: Database):
        # 추상화에 의존 (의존성 주입)
        self.database = database
    
    def create_user(self, user):
        self.database.save(user)

# 사용
mysql_db = MySQLDatabase()
user_service = UserService(mysql_db)

# DB 변경 시 UserService 수정 불필요!
postgres_db = PostgreSQLDatabase()
user_service = UserService(postgres_db)
```

## 분석 방법 (How to Analyze)

### Cursor 기능 활용
이 명령어는 Cursor의 다음 기능을 활용합니다:

1. **@codebase**: 전체 프로젝트 시맨틱 인덱싱
   - 클래스 구조 및 의존성 매핑
   - 상속 관계 분석

2. **SemanticSearch**: SOLID 위반 패턴 탐색
3. **Grep**: 안티패턴 검색 (if/elif 타입 분기, 구체 클래스 생성 등)
4. **Read**: 클래스 책임 분석

### 분석 범위 지정

**전체 프로젝트 분석 (기본):**
```
/solid-check
```

**특정 폴더만 분석:**
```
/solid-check @services/
/solid-check @models/
```

**특정 파일만 분석:**
```
/solid-check @services/payment_service.py
```

**키워드 기반 분석:**
```
/solid-check payment 관련만
/solid-check service 클래스만
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
     
     분석 완료 후 `/solid-check`를 다시 실행하세요.
     ```
   - **YES** → 다음 단계로

2. **SC-XXX 이슈 필터링**:
   - `docs/refactor_report.md`에서 `/solid-check 영역 (SC-XXX)` 섹션 읽기
   - 체크되지 않은 이슈 `- [ ]`만 추출
   - 이미 완료된 이슈 `- [x]`는 제외

## 출력 형식 (CRITICAL - 반드시 준수)

### 파일 경로 형식
모든 파일 경로는 **클릭 가능한 형식**으로 출력해야 합니다:

**필수 형식**: `` `경로/파일명.확장자:라인번호` ``

**예시:**
- ✅ Good: `services/user_service.py:15`
- ✅ Good: `handlers/payment.py:50`
- ❌ Bad: `services/user_service.py` (라인 번호 없음)

### Phase 2: 이슈 목록 표시
```
## 🏗️ /solid-check 영역 이슈 (`docs/refactor_report.md` 기준)

발견된 이슈: N개

### 🔴 SRP 위반 (단일 책임 원칙)
1. [ ] [SC-001] God Class - [src/services/user_service.py](../src/services/user_service.py)
   - 책임 수: 3개 (사용자 관리, 알림, 로깅)

### 🟠 OCP 위반 (개방-폐쇄 원칙)
2. [ ] [SC-002] 타입 분기 (if/elif) - [src/handlers/payment.py:50](../src/handlers/payment.py#L50)
   - 문제: 새로운 결제 수단 추가 시 기존 코드 수정 필요

### 🟡 LSP 위반 (리스코프 치환 원칙)
3. [ ] [SC-003] 부모 메서드 예외 발생 - [src/models/bird.py:30](../src/models/bird.py#L30)
   - 문제: Bird를 기대하는 코드에 Penguin 사용 불가

### 🟢 ISP 위반 (인터페이스 분리 원칙)
4. [ ] [SC-004] Fat Interface - [src/interfaces/worker.py](../src/interfaces/worker.py)
   - 문제: RobotWorker가 eat(), sleep() 미사용

### 🔵 DIP 위반 (의존성 역전 원칙)
5. [ ] [SC-005] 구체 클래스 의존 - [src/services/order_service.py:15](../src/services/order_service.py#L15)
   - 문제: MySQLDatabase 구체 클래스에 직접 의존

---

## 선택 방법
- "진행해" → 전체 수정
- "SC-001,SC-002" → 특정 이슈 선택
- "1,2,3" → 번호로 선택
- "SRP만" → SRP 위반만 수정
- "SC-001 수정: [피드백]" → 제안 수정
```

### Phase 3: 사용자 선택 대기
사용자의 입력을 기다립니다.

### Phase 4: 수정 실행
선택된 항목만 수정합니다.

### Phase 5: 문서 업데이트 및 결과 표시
```
## 수정 완료

### 수정된 파일
- `services/user_service.py` (SRP 준수)
- `services/user_notification_service.py` (신규 생성)
- `services/user_activity_logger.py` (신규 생성)

### 설계 개선 효과
- 클래스 책임 명확화
- 테스트 용이성 향상
- 확장성 개선

### 📝 문서 업데이트
`docs/refactor_report.md` 파일에서 완료된 이슈를 체크 표시했습니다:
- [x] [SC-001] God Class 분리
```

## 중요 지침 (Important Guidelines)

### 1. 우선순위
1. **Critical**: SRP, DIP 위반 (아키텍처 영향 큼)
2. **High**: OCP 위반 (확장성 저하)
3. **Medium**: LSP, ISP 위반

### 2. 검출 기준
- **SRP**: 클래스가 2개 이상의 책임을 가지는가?
- **OCP**: if/elif/switch로 타입 분기하는가?
- **LSP**: 자식이 부모를 완전히 대체 가능한가?
- **ISP**: 빈 메서드 구현이 있는가?
- **DIP**: 구체 클래스를 직접 생성하는가?

### 3. 절대 금지
- ❌ 과도한 추상화 (YAGNI 원칙 위반)
- ❌ 모든 클래스에 인터페이스 (필요할 때만)
- ❌ 디자인 패턴 강요 (문제에 맞는 패턴 선택)

### 4. 포트폴리오 관점
각 수정에 다음을 포함하세요:
- **왜 위반인가**: 원칙 설명
- **어떻게 수정하는가**: Before/After 코드
- **어떤 이점이 있는가**: 확장성, 테스트 용이성 등

## 사용 예시 (Usage Examples)

### 예시 1: 문서 없이 실행 시
```
사용자: /solid-check

AI: ⚠️ 먼저 `/refactor`를 실행하여 분석 문서를 생성하세요.
    
    사용법:
    1. `/refactor` - 전체 프로젝트 분석
    2. `/refactor @폴더명` - 특정 폴더만 분석
    
    분석 완료 후 `/solid-check`를 다시 실행하세요.
```

### 예시 2: 문서에서 이슈 읽기 및 실행
```
사용자: (먼저 /refactor 실행 후)
사용자: /solid-check

AI: `docs/refactor_report.md`에서 /solid-check 영역 이슈를 읽었습니다.
    
    ## 🏗️ /solid-check 영역 이슈
    
    발견된 이슈: 5개
    
    ### 🔴 SRP 위반
    1. [ ] [SC-001] God Class - [src/services/user_service.py](../src/services/user_service.py)
    2. [ ] [SC-002] God Class - [src/services/payment_service.py](../src/services/payment_service.py)
    
    ### 🟠 OCP 위반
    3. [ ] [SC-003] 타입 분기 - [src/handlers/payment.py:50](../src/handlers/payment.py#L50)
    
    ### 🔵 DIP 위반
    4. [ ] [SC-004] 구체 클래스 의존 - [src/services/order_service.py:15](../src/services/order_service.py#L15)
    5. [ ] [SC-005] 구체 클래스 의존 - [src/services/user_service.py:20](../src/services/user_service.py#L20)
    
    선택: "진행해" | "SC-001,SC-003" | "1,3"

사용자: SRP만

AI: SRP 위반 수정 중...
    
    수정 완료! `docs/refactor_report.md`를 업데이트했습니다.
    
    - [x] [SC-001] UserService 분리
      - UserService (사용자 로직)
      - UserNotificationService (이메일)
      - UserActivityLogger (로깅)
    
    - [x] [SC-002] PaymentService 분리
      - PaymentService (결제 로직)
      - PaymentValidator (검증)
      - InvoiceGenerator (송장)
```

## 참고 자료 (References)

### SOLID 원칙
- [SOLID Principles - Wikipedia](https://en.wikipedia.org/wiki/SOLID)
- [Uncle Bob's SOLID Principles](https://blog.cleancoder.com/uncle-bob/2020/10/18/Solid-Relevance.html)
- [SOLID 원칙 - 한국어](https://dev-momo.tistory.com/entry/SOLID-%EC%9B%90%EC%B9%99)

### 디자인 패턴
- [Design Patterns by Gang of Four](https://en.wikipedia.org/wiki/Design_Patterns)
- [Refactoring Guru - Design Patterns](https://refactoring.guru/design-patterns)
- [Head First Design Patterns](https://www.oreilly.com/library/view/head-first-design/0596007124/)

### 객체지향 설계
- [Clean Architecture by Robert C. Martin](https://www.amazon.com/Clean-Architecture-Craftsmans-Software-Structure/dp/0134494164)
- [Domain-Driven Design by Eric Evans](https://www.amazon.com/Domain-Driven-Design-Tackling-Complexity-Software/dp/0321125215)
