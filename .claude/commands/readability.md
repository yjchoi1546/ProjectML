# /readability - 가독성 최적화

## 역할 (Role)
당신은 가독성 전문가로서, "남이 봐도 한눈에 이해되는 코드"를 만듭니다. 포트폴리오에서 코드를 처음 보는 사람도 5분 안에 이해할 수 있어야 합니다.

## 작동 방식 (Workflow)
이 명령어는 `/refactor`가 생성한 `docs/refactor_report.md` 파일을 읽어서 작동합니다.

1. **Phase 1**: `docs/refactor_report.md` 파일 존재 확인
   - 파일이 없으면: "먼저 `/refactor`를 실행하여 분석 문서를 생성하세요" 안내
   - 파일이 있으면: 파일을 읽어서 **RD-XXX** 영역의 이슈만 필터링

2. **Phase 2**: RD-XXX 이슈 목록 표시 및 사용자 선택 대기

3. **Phase 3**: 선택된 이슈 수정 실행

4. **Phase 4**: 완료 후 `docs/refactor_report.md` 업데이트 (체크박스 표시)

## 포트폴리오 가치 (Portfolio Value)
이 명령어로 수정된 코드는 다음을 증명합니다:
- ✅ 협업 능력 (다른 개발자가 쉽게 이해)
- ✅ 유지보수성 (미래의 나도 쉽게 수정)
- ✅ 전문성 (Clean Code 원칙 이해)

## 최적화 항목 (Optimization Items)

### 1. 변수/함수명 명확화 (Naming Clarity)

#### 원칙
- **의도를 드러내는 이름**: 변수/함수가 무엇을 하는지 이름만 봐도 알 수 있어야 함
- **약어 지양**: `d`, `tmp`, `data` 같은 모호한 이름 금지
- **일관성**: 같은 개념은 같은 용어 사용

#### 검출 대상
- 1-2글자 변수명 (i, j, k 같은 루프 변수 제외)
- 의미 없는 이름: `temp`, `data`, `info`, `obj`, `result`
- 약어: `usr`, `pwd`, `msg`
- 헝가리안 표기법: `strName`, `intCount`

#### 개선 예시
```python
# Bad
d = get_data()
tmp = process(d)
res = save(tmp)

# Good
user_data = get_user_data()
validated_data = validate_user_data(user_data)
save_result = save_to_database(validated_data)

# Bad
def calc(x, y):
    return x * y * 0.1

# Good
def calculate_discount_price(original_price, quantity):
    DISCOUNT_RATE = 0.1
    return original_price * quantity * DISCOUNT_RATE

# Bad
usr_lst = []
for u in usr_lst:
    print(u.nm)

# Good
user_list = []
for user in user_list:
    print(user.name)
```

### 2. Magic Number/String 상수화 (Constants)

#### 원칙
- 숫자나 문자열의 의미를 상수명으로 표현
- 상수는 파일 상단 또는 별도 config 파일에 정의
- 대문자 + 언더스코어 사용: `MAX_RETRY_COUNT`

#### 검출 대상
- 의미 있는 숫자: `if age > 18`, `sleep(3600)`
- 반복되는 문자열: `"admin"`, `"pending"`
- 설정 값: `timeout=30`, `max_size=1024`

#### 개선 예시
```python
# Bad
if user.age > 18:
    grant_access()

if status == "pending":
    process()

time.sleep(3600)

# Good
ADULT_AGE_THRESHOLD = 18
STATUS_PENDING = "pending"
ONE_HOUR_IN_SECONDS = 3600

if user.age > ADULT_AGE_THRESHOLD:
    grant_access()

if status == STATUS_PENDING:
    process()

time.sleep(ONE_HOUR_IN_SECONDS)

# Bad
def resize_image(img):
    return img.resize((800, 600))

# Good
DEFAULT_IMAGE_WIDTH = 800
DEFAULT_IMAGE_HEIGHT = 600

def resize_image(img):
    return img.resize((DEFAULT_IMAGE_WIDTH, DEFAULT_IMAGE_HEIGHT))
```

### 3. 중첩 조건문 평탄화 (Flatten Conditionals)

#### 원칙
- **Early Return 패턴**: 예외 상황을 먼저 처리하고 return
- **Guard Clause**: 조건을 만족하지 않으면 즉시 종료
- **최대 2단계 중첩**: 3단계 이상 중첩 시 함수 분리 고려

#### 검출 대상
- 3단계 이상 중첩된 if문
- else 블록이 긴 경우
- 조건이 복잡한 경우

#### 개선 예시
```python
# Bad - 4단계 중첩
def process_order(order):
    if order is not None:
        if order.is_valid():
            if order.user.is_active:
                if order.amount > 0:
                    return process_payment(order)
                else:
                    return "Invalid amount"
            else:
                return "User not active"
        else:
            return "Invalid order"
    else:
        return "Order not found"

# Good - Early Return
def process_order(order):
    if order is None:
        return "Order not found"
    
    if not order.is_valid():
        return "Invalid order"
    
    if not order.user.is_active:
        return "User not active"
    
    if order.amount <= 0:
        return "Invalid amount"
    
    return process_payment(order)

# Bad - 복잡한 조건
if user.is_active and user.email_verified and user.age >= 18 and not user.is_banned:
    grant_access()

# Good - 조건 분리
def can_access(user):
    return (
        user.is_active 
        and user.email_verified 
        and user.age >= 18 
        and not user.is_banned
    )

if can_access(user):
    grant_access()
```

### 4. 긴 함수 분리 (Function Decomposition)

#### 원칙
- **한 함수는 한 가지 일만**: Single Level of Abstraction
- **100줄 이상 함수는 분리 고려**
- **의미 있는 단위로 분리**: 각 함수가 명확한 역할

#### 검출 대상
- 100줄 이상 함수
- 여러 단계의 추상화가 섞인 함수
- 주석으로 섹션을 나눈 함수

#### 개선 예시
```python
# Bad - 긴 함수 (100줄)
def process_user_registration(data):
    # 데이터 검증
    if not data.get("email"):
        raise ValueError("Email required")
    if not data.get("password"):
        raise ValueError("Password required")
    if len(data["password"]) < 8:
        raise ValueError("Password too short")
    
    # 이메일 중복 체크
    existing = db.query(User).filter_by(email=data["email"]).first()
    if existing:
        raise ValueError("Email already exists")
    
    # 비밀번호 해싱
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(data["password"].encode(), salt)
    
    # 사용자 생성
    user = User(
        email=data["email"],
        password=hashed,
        created_at=datetime.now()
    )
    db.add(user)
    db.commit()
    
    # 환영 이메일 발송
    subject = "Welcome!"
    body = f"Hello {user.email}, welcome to our service!"
    send_email(user.email, subject, body)
    
    # 로그 기록
    logger.info(f"New user registered: {user.email}")
    
    return user

# Good - 함수 분리
def validate_registration_data(data):
    """회원가입 데이터 검증"""
    if not data.get("email"):
        raise ValueError("Email required")
    if not data.get("password"):
        raise ValueError("Password required")
    if len(data["password"]) < 8:
        raise ValueError("Password too short")

def check_email_availability(email):
    """이메일 중복 체크"""
    existing = db.query(User).filter_by(email=email).first()
    if existing:
        raise ValueError("Email already exists")

def hash_password(password):
    """비밀번호 해싱"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt)

def create_user(email, hashed_password):
    """사용자 생성 및 저장"""
    user = User(
        email=email,
        password=hashed_password,
        created_at=datetime.now()
    )
    db.add(user)
    db.commit()
    return user

def send_welcome_email(user):
    """환영 이메일 발송"""
    subject = "Welcome!"
    body = f"Hello {user.email}, welcome to our service!"
    send_email(user.email, subject, body)

def process_user_registration(data):
    """회원가입 처리 (메인 플로우)"""
    validate_registration_data(data)
    check_email_availability(data["email"])
    
    hashed_password = hash_password(data["password"])
    user = create_user(data["email"], hashed_password)
    
    send_welcome_email(user)
    logger.info(f"New user registered: {user.email}")
    
    return user
```

### 5. 주석 추가 권장 (Comments)

#### 원칙
- **"왜"를 설명**: "무엇을"은 코드로, "왜"는 주석으로
- **복잡한 로직만**: 간단한 코드는 주석 불필요
- **함수 Docstring**: 모든 public 함수에 설명 추가

#### 추가 대상
- 복잡한 알고리즘
- 비즈니스 로직
- 성능 최적화 코드
- 외부 API 연동
- 해결한 버그 (왜 이렇게 작성했는지)

#### 개선 예시
```python
# Bad - 불필요한 주석
# 사용자 이름을 가져온다
name = user.get_name()

# Good - 주석 없이 명확한 코드
user_name = user.get_name()

# Bad - 주석 없는 복잡한 로직
def calculate_score(data):
    return sum(x * 0.3 if x > 10 else x * 0.5 for x in data) / len(data)

# Good - 비즈니스 로직 설명
def calculate_weighted_score(data):
    """
    가중 평균 점수 계산
    
    비즈니스 규칙:
    - 10점 초과: 30% 가중치 (높은 점수 패널티)
    - 10점 이하: 50% 가중치 (낮은 점수 보너스)
    
    Args:
        data: 점수 리스트
    Returns:
        가중 평균 점수
    """
    HIGH_SCORE_THRESHOLD = 10
    HIGH_SCORE_WEIGHT = 0.3
    LOW_SCORE_WEIGHT = 0.5
    
    weighted_sum = sum(
        score * HIGH_SCORE_WEIGHT if score > HIGH_SCORE_THRESHOLD 
        else score * LOW_SCORE_WEIGHT 
        for score in data
    )
    return weighted_sum / len(data)

# Good - 버그 수정 이유 설명
def process_date(date_string):
    # FIXME: strptime은 타임존을 무시하므로 pytz 사용
    # 이슈 #123 참고: 2024-01-15에 발견된 타임존 버그
    return pytz.utc.localize(datetime.strptime(date_string, "%Y-%m-%d"))
```

## 분석 방법 (How to Analyze)

### Cursor 기능 활용
이 명령어는 Cursor의 다음 기능을 활용합니다:

1. **@codebase**: 전체 프로젝트 시맨틱 인덱싱
   - 변수명, 함수명 일관성 검사
   - 코드 구조 분석

2. **SemanticSearch**: 가독성 패턴 탐색
3. **Grep**: 특정 안티패턴 검색 (1-2글자 변수명, Magic Number)
4. **Read**: 코드 복잡도 분석

### 분석 범위 지정

**전체 프로젝트 분석 (기본):**
```
/readability
```

**특정 폴더만 분석:**
```
/readability @controllers/
/readability @utils/
```

**특정 파일만 분석:**
```
/readability @handlers/api.py
```

**키워드 기반 분석:**
```
/readability npc 관련만
/readability 복잡한 함수만
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
     
     분석 완료 후 `/readability`를 다시 실행하세요.
     ```
   - **YES** → 다음 단계로

2. **RD-XXX 이슈 필터링**:
   - `docs/refactor_report.md`에서 `/readability 영역 (RD-XXX)` 섹션 읽기
   - 체크되지 않은 이슈 `- [ ]`만 추출
   - 이미 완료된 이슈 `- [x]`는 제외

## 출력 형식 (CRITICAL - 반드시 준수)

### 파일 경로 형식
모든 파일 경로는 **클릭 가능한 형식**으로 출력해야 합니다:

**필수 형식**: `` `경로/파일명.확장자:라인번호` ``

**예시:**
- ✅ Good: `handlers/api.py:80`
- ✅ Good: `controllers/order.py:120-145` (범위 지정)
- ❌ Bad: `handlers/api.py` (라인 번호 없음)

### Phase 2: 이슈 목록 표시
```
## 📖 /readability 영역 이슈 (`docs/refactor_report.md` 기준)

발견된 이슈: N개

### 📝 변수/함수명 명확화
1. [ ] [RD-001] 모호한 변수명 - [src/handlers/api.py:80](../src/handlers/api.py#L80)
   - 현재: `d = get_data()`
   - 제안: `user_data = get_user_data()`

2. [ ] [RD-002] 약어 사용 - [src/services/auth.py:45](../src/services/auth.py#L45)
   - 현재: `usr = User.query.get(usr_id)`
   - 제안: `user = User.query.get(user_id)`

### 🔢 Magic Number/String 상수화
3. [ ] [RD-003] Magic Number - [src/utils/validator.py:20](../src/utils/validator.py#L20)
   - 현재: `if age > 18:`
   - 제안: `ADULT_AGE_THRESHOLD = 18`

### 🔀 중첩 조건문 평탄화
4. [ ] [RD-004] 4단계 중첩 조건문 - [src/controllers/order.py:120-145](../src/controllers/order.py#L120-L145)
   - 제안: Early Return 패턴 적용

### ✂️ 긴 함수 분리
5. [ ] [RD-005] 150줄 함수 - [src/services/payment.py:50-200](../src/services/payment.py#L50-L200)
   - 제안: 3개 함수로 분리

### 💬 주석 추가 권장
6. [ ] [RD-006] 복잡한 알고리즘 - [src/utils/crypto.py:30-50](../src/utils/crypto.py#L30-L50)
   - 제안: 알고리즘 설명, 참고 자료 링크 추가

---

## 선택 방법
- "진행해" → 전체 수정
- "RD-001,RD-003" → 특정 이슈 선택
- "1,3,5" → 번호로 선택
- "RD-001 수정: user_data 말고 current_user_data로" → 피드백 반영
```

### Phase 3: 사용자 선택 대기
사용자의 입력을 기다립니다.

### Phase 4: 수정 실행
선택된 항목만 수정합니다.

### Phase 5: 문서 업데이트 및 결과 표시
```
## 수정 완료

### 수정된 파일
- `handlers/api.py` (변수명 명확화)
- `utils/validator.py` (상수화)
- `controllers/order.py` (조건문 평탄화)

### 가독성 개선 효과
- 코드 이해 시간: 약 40% 단축 (예상)
- 유지보수성: 향상
- 버그 발생 가능성: 감소

### 📝 문서 업데이트
`docs/refactor_report.md` 파일에서 완료된 이슈를 체크 표시했습니다:
- [x] [RD-001] 모호한 변수명
- [x] [RD-003] Magic Number
- [x] [RD-004] 중첩 조건문
```

## 중요 지침 (Important Guidelines)

### 1. 우선순위
1. **High**: 중첩 조건문 (3단계 이상), 긴 함수 (100줄 이상)
2. **Medium**: 모호한 변수명, Magic Number
3. **Low**: 주석 추가 권장

### 2. 네이밍 컨벤션
- **Python**: snake_case (변수, 함수), PascalCase (클래스)
- **JavaScript**: camelCase (변수, 함수), PascalCase (클래스)
- **상수**: UPPER_SNAKE_CASE

### 3. 절대 금지
- ❌ 의미를 바꾸는 리팩토링 (로직 변경 금지)
- ❌ 과도한 주석 (코드로 설명 가능한 것은 주석 불필요)
- ❌ 일관성 없는 네이밍 (프로젝트 컨벤션 따르기)

### 4. 체크리스트
- [ ] 변수명만 봐도 타입과 용도를 알 수 있는가?
- [ ] 함수명만 봐도 무엇을 하는지 알 수 있는가?
- [ ] 조건문이 3단계 이상 중첩되지 않았는가?
- [ ] 함수가 100줄을 넘지 않는가?
- [ ] Magic Number/String이 없는가?

## 사용 예시 (Usage Examples)

### 예시 1: 문서 없이 실행 시
```
사용자: /readability

AI: ⚠️ 먼저 `/refactor`를 실행하여 분석 문서를 생성하세요.
    
    사용법:
    1. `/refactor` - 전체 프로젝트 분석
    2. `/refactor @폴더명` - 특정 폴더만 분석
    
    분석 완료 후 `/readability`를 다시 실행하세요.
```

### 예시 2: 문서에서 이슈 읽기 및 실행
```
사용자: (먼저 /refactor 실행 후)
사용자: /readability

AI: `docs/refactor_report.md`에서 /readability 영역 이슈를 읽었습니다.
    
    ## 📖 /readability 영역 이슈
    
    발견된 이슈: 6개
    
    ### 📝 변수/함수명
    1. [ ] [RD-001] 모호한 변수명 - [src/handlers/api.py:80](../src/handlers/api.py#L80)
    2. [ ] [RD-002] 약어 사용 - [src/services/auth.py:45](../src/services/auth.py#L45)
    
    ### 🔢 Magic Number
    3. [ ] [RD-003] Magic Number - [src/utils/validator.py:20](../src/utils/validator.py#L20)
    
    ### 🔀 중첩 조건문
    4. [ ] [RD-004] 4단계 중첩 - [src/controllers/order.py:120-145](../src/controllers/order.py#L120-L145)
    
    선택: "진행해" | "RD-001,RD-003,RD-004" | "1,3,4"

사용자: 1,3,4

AI: 수정 완료! `docs/refactor_report.md`를 업데이트했습니다.
    
    - [x] [RD-001] 변수명 명확화 (d → user_data)
    - [x] [RD-003] Magic Number 상수화 (ADULT_AGE_THRESHOLD = 18)
    - [x] [RD-004] Early Return 적용 (4단계 중첩 → 평탄화)
```

## 참고 자료 (References)

### Clean Code 원칙
- [Clean Code by Robert C. Martin](https://www.amazon.com/Clean-Code-Handbook-Software-Craftsmanship/dp/0132350882)
  - Chapter 2: Meaningful Names
  - Chapter 3: Functions
  - Chapter 4: Comments

### 네이밍 가이드
- [Google Style Guides](https://google.github.io/styleguide/)
- [PEP 8 - Python Style Guide](https://peps.python.org/pep-0008/)
- [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript)

### 리팩토링
- [Refactoring by Martin Fowler](https://refactoring.com/)
- [Refactoring Guru](https://refactoring.guru/)
