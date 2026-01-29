# NPC API 프로토콜 문서

언리얼 엔진과 NPC 시스템 간의 통신 프로토콜입니다.

**Base URL**: `http://localhost:8090`

---

## 목차

1. [로그인/세션](#1-로그인세션)
2. [히로인 대화](#2-히로인-대화)
3. [대현자 대화](#3-대현자-대화)
4. [히로인간 대화](#4-히로인간-대화)
5. [길드 시스템](#5-길드-시스템)
6. [TTS 음성 엔드포인트](#6-tts-음성-엔드포인트)
7. [호출 흐름도](#7-호출-흐름도)
8. [세션/디버그 API](#8-세션디버그-api)
9. [에러 응답](#9-에러-응답)
10. [프로토콜 요약표](#10-프로토콜-요약표)

---

## 1. 로그인/세션

### POST /api/npc/login

게임 접속시 **1번만** 호출합니다. 플레이어의 모든 NPC 세션을 초기화합니다.

> **플레이어 이름 기억 기능**: 플레이어가 대화 중 자신의 이름을 밝히면 (예: "나는 민수야", "민수라고 불러"), NPC가 이름을 기억하고 이후 대화에서 사용합니다. 이름은 서버 재시작 후에도 유지됩니다.

#### Request

```json
{
    "playerId": "10001",
    "scenarioLevel": 3,
    "heroines": [
        {
            "heroineId": 1,
            "affection": 45,
            "memoryProgress": 30,
            "sanity": 80
        },
        {
            "heroineId": 2,
            "affection": 60,
            "memoryProgress": 50,
            "sanity": 100
        },
        {
            "heroineId": 3,
            "affection": 25,
            "memoryProgress": 20,
            "sanity": 90
        }
    ]
}
```

**Request 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| playerId | string | 플레이어 고유 ID |
| scenarioLevel | int | 현재 시나리오 레벨 (1-10) |
| heroines | array | 히로인들의 상태 배열 |
| heroines[].heroineId | int | 히로인 ID (1=레티아, 2=루파메스, 3=로코) |
| heroines[].affection | int | 호감도 (0-100) |
| heroines[].memoryProgress | int | 기억 진척도 (0-100) |
| heroines[].sanity | int | 정신력 (0-100) |

#### Response

```json
{
    "success": true,
    "message": "세션 초기화 완료"
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| success | bool | 성공 여부 |
| message | string | 결과 메시지 |

---

## 2. 히로인 대화

### POST /api/npc/heroine/chat/sync

히로인과 대화합니다. **전체 응답을 한번에** 반환합니다.

> 메모리 저장 시 LLM이 content+keywords(JSON)를 추출해 keywords 배열(상위 카테고리 포함)과 함께 DB에 기록하고, 임베딩은 "content (Keywords: ...)"로 생성합니다. 검색은 PGroonga로 content+keywords를 함께 봅니다.

#### Request

```json
{
    "playerId": "10001",
    "heroineId": 1,
    "text": "안녕, 오늘 기분이 어때?"
}
```

**Request 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| playerId | string | 플레이어 ID |
| heroineId | int | 대화할 히로인 ID |
| text | string | 플레이어 메시지 |

#### Response

```json
{
    "text": "...별로야.",
    "emotion": 0,
    "affection": 50,
    "sanity": 85,
    "memoryProgress": 35
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| text | string | NPC 응답 텍스트 |
| emotion | int | 감정 상태 (0-6) |
| affection | int | 변경된 호감도 |
| sanity | int | 변경된 정신력 |
| memoryProgress | int | 변경된 기억 진척도 |

---

### 히로인별 ID

| ID | 이름 | 성격 |
|----|------|------|
| 1 | 레티아 | 차갑고 무뚝뚝, 반말 |
| 2 | 루파메스 | 활발하고 호탕, 반말 |
| 3 | 로코 | 순수하고 어린아이 같음, 존댓말 |

---

### 감정 종류 (emotion)

| 정수값 | 문자열 | 설명 |
|--------|--------|------|
| 0 | neutral | 평온 |
| 1 | joy | 기쁨 |
| 2 | fun | 재미 |
| 3 | sorrow | 슬픔 |
| 4 | angry | 분노 |
| 5 | surprise | 놀람 |
| 6 | mysterious | 신비로움 |

> **참고**: API 응답에서 emotion은 **정수(int)**로 전달됩니다.

---

## 3. 대현자 대화

### POST /api/npc/sage/chat/sync

대현자 사트라와 대화합니다. 전체 응답을 한번에 반환합니다.

#### Request

```json
{
    "playerId": "10001",
    "text": "이 세계에 대해 알려줘"
}
```

**Request 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| playerId | string | 플레이어 ID |
| text | string | 플레이어 메시지 |

#### Response

```json
{
    "text": "이 세계는 디멘시움이라는 물질로 인해...",
    "emotion": 6,
    "scenarioLevel": 3,
    "infoRevealed": true
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| text | string | NPC 응답 텍스트 |
| emotion | int | 감정 상태 (0-6) |
| scenarioLevel | int | 현재 시나리오 레벨 |
| infoRevealed | bool | 정보 공개 여부 |

---

### 대현자 감정 종류

> **참고**: 대현자도 히로인과 동일한 통합 감정 매핑을 사용합니다.

| 정수값 | 문자열 | 설명 |
|--------|--------|------|
| 0 | neutral | 평온 |
| 1 | joy | 기쁨 |
| 2 | fun | 재미 |
| 3 | sorrow | 슬픔 |
| 4 | angry | 분노 |
| 5 | surprise | 놀람 |
| 6 | mysterious | 신비로움 |

---

## 4. 히로인간 대화

### POST /api/npc/heroine-conversation/generate

두 히로인 사이의 대화를 생성합니다.

#### Request

```json
{
    "playerId": "player_10001",
    "heroine1Id": 1,
    "heroine2Id": 2,
    "situation": "길드 휴게실에서 쉬는 중",
    "turnCount": 10
}
```

**Request 필드:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| playerId | string | O | 플레이어 ID |
| heroine1Id | int | O | 첫 번째 히로인 ID |
| heroine2Id | int | O | 두 번째 히로인 ID |
| situation | string | X | 상황 설명 (없으면 자동 생성) |
| turnCount | int | X | 대화 턴 수 (기본값 10) |

#### Response

```json
{
    "id": "uuid-string",
    "heroine1_id": 1,
    "heroine2_id": 2,
    "content": "레티아: ...뭐해.\n루파메스: 아 심심해서...",
    "conversation": [
        {
            "speaker_id": 1,
            "speaker_name": "레티아",
            "text": "...뭐해.",
            "emotion": 0
        },
        {
            "speaker_id": 2,
            "speaker_name": "루파메스",
            "text": "아 심심해서 왔지~",
            "emotion": 1
        }
    ],
    "importance_score": 5,
    "timestamp": "2025-01-15T10:30:00.000Z"
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | 대화 고유 ID (UUID) |
| heroine1_id | int | 첫 번째 히로인 ID |
| heroine2_id | int | 두 번째 히로인 ID |
| content | string | 대화 전체 텍스트 |
| conversation | array | 대화 배열 |
| conversation[].speaker_id | int | 발화자 히로인 ID |
| conversation[].speaker_name | string | 발화자 이름 |
| conversation[].text | string | 대사 내용 |
| conversation[].emotion | int | 감정 (0-6) |
| importance_score | int | 중요도 (1-10) |
| timestamp | string | 생성 시각 (ISO 8601) |

---

### GET /api/npc/heroine-conversation

저장된 히로인간 대화 기록을 조회합니다.

#### Request (Query Parameters)

**Request 필드:**

| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| player_id | string | O | 플레이어 ID |
| heroine1_id | int | X | 첫 번째 히로인 ID |
| heroine2_id | int | X | 두 번째 히로인 ID |
| limit | int | X | 최대 조회 수 (기본값 10) |

#### Response

```json
{
    "conversations": [
        {
            "id": "uuid-string",
            "agent_id": "conv_1_2",
            "content": "레티아: ...뭐해.\n루파메스: 아 심심해서...",
            "importance_score": 5,
            "metadata": {...},
            "created_at": "2025-01-15T10:30:00.000Z"
        }
    ]
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| conversations | array | 대화 기록 배열 |
| conversations[].id | string | 대화 고유 ID (UUID) |
| conversations[].agent_id | string | 에이전트 ID (conv_{작은ID}_{큰ID}) |
| conversations[].content | string | 대화 전체 텍스트 |
| conversations[].importance_score | int | 중요도 (1-10) |
| conversations[].metadata | object | 메타데이터 (상황, 감정 등) |
| conversations[].created_at | string | 생성 시각 (ISO 8601) |

---

### POST /api/npc/heroine-conversation/interrupt

NPC-NPC 대화 인터럽트 처리. **유저가 NPC 대화 중간에 끊고 들어왔을 때** 호출합니다.

`interruptedTurn` 이후의 대화는 NPC가 모르는 것으로 처리됩니다.

#### Request

```json
{
    "playerId": "player_10001",
    "conversationId": "uuid-string",
    "interruptedTurn": 3,
    "heroine1Id": 1,
    "heroine2Id": 2
}
```

**Request 필드:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| playerId | string | O | 플레이어 ID |
| conversationId | string | O | 대화 ID (UUID) |
| interruptedTurn | int | O | 유저가 끊은 턴 (이 턴까지만 유효) |
| heroine1Id | int | O | 첫 번째 히로인 ID |
| heroine2Id | int | O | 두 번째 히로인 ID |

#### Response (성공)

```json
{
    "success": true,
    "message": "3턴까지의 대화만 유지됩니다",
    "conversation_id": "uuid-string",
    "interrupted_turn": 3,
    "updated_memories": 2
}
```

**Response 필드 (성공):**

| 필드 | 타입 | 설명 |
|------|------|------|
| success | bool | 성공 여부 (true) |
| message | string | 결과 메시지 |
| conversation_id | string | 대화 ID |
| interrupted_turn | int | 끊긴 턴 번호 |
| updated_memories | int | 업데이트된 양방향 NPC 기억 수 |

#### Response (실패)

```json
{
    "success": false,
    "message": "대화를 찾을 수 없습니다",
    "conversation_id": "uuid-string"
}
```

**Response 필드 (실패):**

| 필드 | 타입 | 설명 |
|------|------|------|
| success | bool | 성공 여부 (false) |
| message | string | 에러 메시지 |
| conversation_id | string | 대화 ID |

#### 사용 예시

```
10턴 대화 중 3턴에서 유저가 끊고 들어온 경우:
- interruptedTurn = 3
- 1, 2, 3턴 대화만 유지
- 4턴 이후는 DB에서 삭제
- NPC는 4턴 이후 대화 내용을 모름
```

---

## 5. 길드 시스템

User가 길드에 있는 동안 NPC들이 자동으로 대화합니다.

### POST /api/npc/guild/enter

길드에 진입합니다. **NPC간 백그라운드 대화가 시작**됩니다.

#### Request

```json
{
    "playerId": "10001"
}
```

**Request 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| playerId | string | 플레이어 ID |

#### Response

```json
{
    "success": true,
    "message": "길드에 진입했습니다. NPC 대화가 시작됩니다.",
    "activeConversation": null
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| success | bool | 성공 여부 |
| message | string | 결과 메시지 |
| activeConversation | object/null | 현재 진행 중인 NPC 대화 (없으면 null) |

---

### POST /api/npc/guild/leave

길드에서 퇴장합니다. **NPC간 대화가 중단**됩니다.

#### Request

```json
{
    "playerId": "10001"
}
```

**Request 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| playerId | string | 플레이어 ID |

#### Response

```json
{
    "success": true,
    "message": "길드에서 퇴장했습니다. NPC 대화가 중단됩니다.",
    "activeConversation": {
        "active": true,
        "npc1_id": 1,
        "npc2_id": 2,
        "started_at": "2025-01-15T10:30:00.000Z"
    }
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| success | bool | 성공 여부 |
| message | string | 결과 메시지 |
| activeConversation | object/null | 퇴장 시 진행 중이던 NPC 대화 정보 |
| activeConversation.active | bool | 대화 활성화 여부 |
| activeConversation.npc1_id | int | 첫 번째 NPC ID |
| activeConversation.npc2_id | int | 두 번째 NPC ID |
| activeConversation.started_at | string | 대화 시작 시각 (ISO 8601) |

---

### GET /api/npc/guild/status/{player_id}

길드 상태를 조회합니다.

#### Request (Path Parameter)

**Request 필드:**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| player_id | string | 플레이어 ID |

#### Response

```json
{
    "in_guild": true,
    "active_conversation": {
        "active": true,
        "npc1_id": 1,
        "npc2_id": 2,
        "started_at": "2025-01-15T10:30:00.000Z"
    },
    "has_background_task": true
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| in_guild | bool | 길드 내 존재 여부 |
| active_conversation | object/null | 현재 진행 중인 NPC 대화 정보 |
| active_conversation.active | bool | 대화 활성화 여부 |
| active_conversation.npc1_id | int | 첫 번째 NPC ID |
| active_conversation.npc2_id | int | 두 번째 NPC ID |
| active_conversation.started_at | string | 대화 시작 시각 (ISO 8601) |
| has_background_task | bool | 백그라운드 태스크 실행 여부 |

---

## 6. TTS 음성 엔드포인트

기존 대화 엔드포인트에 **TTS 음성(audio_base64)**이 포함된 버전입니다.

### 왜 WAV 파일이 아닌 Base64인가?

| 이유 | 설명 |
|------|------|
| **JSON 호환성** | HTTP JSON 응답에 바이너리 파일을 직접 포함할 수 없음 |
| **단일 응답** | 텍스트 + 상태 + 음성을 하나의 JSON으로 전달 가능 |
| **언리얼 호환** | 언리얼 엔진에서 Base64 디코딩 후 바로 재생 가능 |
| **전송 안정성** | 텍스트 기반이므로 인코딩 문제 없음 |

### Base64 -> WAV 변환 방법

**언리얼 엔진 (C++):**

```cpp
// Base64 디코딩
TArray<uint8> WavData;
FBase64::Decode(AudioBase64String, WavData);

// USoundWave로 변환 후 재생
USoundWave* SoundWave = NewObject<USoundWave>();
// ... WavData를 SoundWave에 로드
```

**Python (유틸리티 스크립트):**

```python
from src.tools.audio.base64_to_wav import save_base64_as_wav

# Base64 문자열을 WAV 파일로 저장
save_base64_as_wav(audio_base64_string, "output.wav")
```

---

### 음성 매핑 (NPC별 Typecast Voice)

| NPC ID | 이름 | Typecast Voice |
|--------|------|----------------|
| 0 | 사트라 (대현자) | Yubin (유빈) |
| 1 | 레티아 | Mio (미오) |
| 2 | 루파메스 | Sora (소라) |
| 3 | 로코 | Saeron (새론) |

---

### POST /api/npc/heroine/chat/sync/voice

히로인과 대화합니다. **텍스트 응답 + TTS 음성**이 포함됩니다.

#### Request

```json
{
    "playerId": "10001",
    "heroineId": 1,
    "text": "안녕, 오늘 기분이 어때?"
}
```

**Request 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| playerId | string | 플레이어 ID |
| heroineId | int | 대화할 히로인 ID |
| text | string | 플레이어 메시지 |

#### Response

```json
{
    "text": "...별로야.",
    "emotion": 0,
    "emotion_intensity": 1.0,
    "affection": 50,
    "sanity": 85,
    "memoryProgress": 35,
    "audio_base64": "UklGRv..."
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| text | string | NPC 응답 텍스트 |
| emotion | int | 감정 상태 (0-6) |
| emotion_intensity | float | 감정 강도 (0.5-2.0, 1.0=보통) |
| affection | int | 변경된 호감도 |
| sanity | int | 변경된 정신력 |
| memoryProgress | int | 변경된 기억 진척도 |
| audio_base64 | string | WAV 오디오 (Base64 인코딩) |

---

### POST /api/npc/sage/chat/sync/voice

대현자 사트라와 대화합니다. **텍스트 응답 + TTS 음성**이 포함됩니다.

#### Request

```json
{
    "playerId": "10001",
    "text": "이 세계에 대해 알려줘"
}
```

**Request 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| playerId | string | 플레이어 ID |
| text | string | 플레이어 메시지 |

#### Response

```json
{
    "text": "이 세계는 디멘시움이라는 물질로 인해...",
    "emotion": 6,
    "emotion_intensity": 1.2,
    "scenarioLevel": 3,
    "infoRevealed": true,
    "audio_base64": "UklGRv..."
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| text | string | NPC 응답 텍스트 |
| emotion | int | 감정 상태 (0-6) |
| emotion_intensity | float | 감정 강도 (0.5-2.0, 1.0=보통) |
| scenarioLevel | int | 현재 시나리오 레벨 |
| infoRevealed | bool | 정보 공개 여부 |
| audio_base64 | string | WAV 오디오 (Base64 인코딩) |

---

### POST /api/npc/heroine-conversation/generate/voice

두 히로인 사이의 대화를 생성합니다. **각 턴마다 개별 TTS 음성**이 포함됩니다.

#### Request

```json
{
    "playerId": "player_10001",
    "heroine1Id": 1,
    "heroine2Id": 2,
    "situation": "길드 휴게실에서 쉬는 중",
    "turnCount": 10
}
```

**Request 필드:**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| playerId | string | O | 플레이어 ID |
| heroine1Id | int | O | 첫 번째 히로인 ID |
| heroine2Id | int | O | 두 번째 히로인 ID |
| situation | string | X | 상황 설명 (없으면 자동 생성) |
| turnCount | int | X | 대화 턴 수 (기본값 10) |

#### Response

```json
{
    "id": "uuid-string",
    "heroine1_id": 1,
    "heroine2_id": 2,
    "situation": "길드 휴게실에서 쉬는 중",
    "conversation": [
        {
            "speaker_id": 1,
            "speaker_name": "레티아",
            "text": "...뭐해.",
            "emotion": 0,
            "emotion_intensity": 1.0,
            "audio_base64": "UklGRv..."
        },
        {
            "speaker_id": 2,
            "speaker_name": "루파메스",
            "text": "아 심심해서 왔지~",
            "emotion": 1,
            "emotion_intensity": 1.5,
            "audio_base64": "UklGRv..."
        }
    ],
    "importance_score": 5,
    "timestamp": "2025-01-15T10:30:00.000Z"
}
```

**Response 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | 대화 고유 ID (UUID) |
| heroine1_id | int | 첫 번째 히로인 ID |
| heroine2_id | int | 두 번째 히로인 ID |
| situation | string | 대화 상황 |
| conversation | array | 대화 배열 (각 턴에 음성 포함) |
| conversation[].speaker_id | int | 발화자 히로인 ID |
| conversation[].speaker_name | string | 발화자 이름 |
| conversation[].text | string | 대사 내용 |
| conversation[].emotion | int | 감정 (0-6) |
| conversation[].emotion_intensity | float | 감정 강도 (0.5-2.0) |
| conversation[].audio_base64 | string | WAV 오디오 (Base64 인코딩) |
| importance_score | int | 중요도 (1-10) |
| timestamp | string | 생성 시각 (ISO 8601) |

---

### 감정 강도 (emotion_intensity)

TTS 음성의 감정 표현 강도를 조절합니다. Typecast API의 `emotion_intensity` 파라미터에 매핑됩니다.

| 값 | 의미 | 예시 |
|----|------|------|
| 0.5 | 약한 감정 | 살짝 기쁜 |
| 1.0 | 보통 (기본값) | 일반적인 감정 표현 |
| 1.5 | 강한 감정 | 매우 기쁜 |
| 2.0 | 극도로 강한 감정 | 환호하며 기뻐하는 |

> **참고**: LLM이 대화 컨텍스트를 분석하여 `emotion_intensity`를 자동으로 결정합니다.

---

## 7. 호출 흐름도

### 7-1. 기본 흐름

```
[게임 시작]
    |
    v
POST /api/npc/login  (1회)
    |
    v
[길드 진입]
    |
    v
POST /api/npc/guild/enter
    |
    +---> [백그라운드] NPC간 자동 대화 (30-60초 간격)
    |
    v
[히로인과 대화]
    |
    v
POST /api/npc/heroine/chat/sync
    |
    +---> 해당 히로인이 NPC 대화 중이면 자동 인터럽트
    |
    v
[대현자와 대화]
    |
    v
POST /api/npc/sage/chat/sync
    |
    v
[길드 퇴장]
    |
    v
POST /api/npc/guild/leave
    |
    +---> 백그라운드 NPC 대화 중단
```

### 7-2. NPC-NPC 대화 인터럽트 흐름

유저가 NPC-NPC 대화 중간에 끊고 들어왔을 때의 흐름입니다.

```
[언리얼] NPC 대화 요청
    |
    v
POST /api/npc/heroine-conversation/generate
    |
    v
[서버] 10턴 대화 생성 + DB 저장
    |
    v
Response: { "id": "uuid-xxx", "conversation": [...] }
    |
    v
[언리얼] id(uuid) 저장, 대화를 유저에게 순차 출력
    |
    v
[유저] 3턴째에서 NPC 대화 끊고 히로인에게 말 검
    |
    v
[언리얼] 끊긴 턴(3) 확인
    |
    v
POST /api/npc/heroine-conversation/interrupt
    {
        "conversationId": "uuid-xxx",  // 저장해둔 id
        "interruptedTurn": 3,          // 끊긴 턴
        "heroine1Id": 1,
        "heroine2Id": 2
    }
    |
    v
[서버] 3단계 무효화 처리
    1. npc_npc_checkpoints에서 4턴 이후 대화 삭제
    2. npc_npc_memories에서 4턴 이후 기억 invalid_at 설정
    3. Redis 세션에서 4턴 이후 대화 버퍼 삭제
    |
    v
[결과] NPC는 1,2,3턴 대화만 기억함
       유저가 "뭐 얘기했어?" 물어도 4턴 이후는 모름
```

---

## 8. 세션/디버그 API

### GET /api/npc/session/{player_id}/{npc_id}

NPC별 세션 정보를 조회합니다. (디버그용)

#### Request (Path Parameters)

**Request 필드:**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| player_id | string | 플레이어 ID |
| npc_id | int | NPC ID (0=대현자, 1=레티아, 2=루파메스, 3=로코) |

#### Response (히로인 세션)

```json
{
    "player_id": 10001,
    "npc_id": 1,
    "npc_type": "heroine",
    "conversation_buffer": [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "...뭐야."}
    ],
    "short_term_summary": "",
    "summary_list": [],
    "turn_count": 5,
    "last_summary_at": null,
    "recent_used_keywords": ["음식"],
    "state": {
        "affection": 50,
        "sanity": 100,
        "memoryProgress": 30,
        "emotion": 0,
        "player_known_name": "민수"
    },
    "last_chat_at": "2025-01-15T10:30:00.000Z"
}
```

**Response 필드 (히로인):**

| 필드 | 타입 | 설명 |
|------|------|------|
| player_id | string | 플레이어 ID |
| npc_id | int | NPC ID |
| npc_type | string | NPC 타입 ("heroine") |
| conversation_buffer | array | 최근 대화 기록 (최대 20개) |
| conversation_buffer[].role | string | 역할 ("user" 또는 "assistant") |
| conversation_buffer[].content | string | 대화 내용 |
| short_term_summary | string | 단기 요약 |
| summary_list | array | 요약 목록 |
| turn_count | int | 현재 대화 턴 수 |
| last_summary_at | string/null | 마지막 요약 생성 시각 |
| recent_used_keywords | array | 최근 5턴 내 사용된 좋아하는 키워드 |
| state | object | 히로인 상태 |
| state.affection | int | 호감도 (0-100) |
| state.sanity | int | 정신력 (0-100) |
| state.memoryProgress | int | 기억 진척도 (0-100) |
| state.emotion | int | 현재 감정 (0-6) |
| state.player_known_name | string/null | NPC가 기억하는 플레이어 이름 (없으면 null) |
| last_chat_at | string/null | 마지막 대화 시각 (ISO 8601) |

#### Response (대현자 세션)

```json
{
    "player_id": 10001,
    "npc_id": 0,
    "npc_type": "sage",
    "conversation_buffer": [
        {"role": "user", "content": "이 세계는 뭐야?"},
        {"role": "assistant", "content": "흐음, 궁금한가..."}
    ],
    "short_term_summary": "",
    "summary_list": [],
    "turn_count": 3,
    "last_summary_at": null,
    "state": {
        "scenarioLevel": 3,
        "emotion": 0,
        "player_known_name": "민수"
    },
    "last_chat_at": "2025-01-15T10:30:00.000Z"
}
```

**Response 필드 (대현자):**

| 필드 | 타입 | 설명 |
|------|------|------|
| player_id | string | 플레이어 ID |
| npc_id | int | NPC ID (대현자는 0) |
| npc_type | string | NPC 타입 ("sage") |
| conversation_buffer | array | 최근 대화 기록 (최대 20개) |
| short_term_summary | string | 단기 요약 |
| summary_list | array | 요약 목록 |
| turn_count | int | 현재 대화 턴 수 |
| last_summary_at | string/null | 마지막 요약 생성 시각 |
| state | object | 대현자 상태 |
| state.scenarioLevel | int | 시나리오 레벨 (1-10) |
| state.emotion | int | 현재 감정 (0-6) |
| state.player_known_name | string/null | NPC가 기억하는 플레이어 이름 (없으면 null) |
| last_chat_at | string/null | 마지막 대화 시각 (ISO 8601) |

---

### GET /api/npc/npc-conversation/active/{player_id}

현재 진행 중인 NPC간 대화를 조회합니다.

#### Request (Path Parameter)

**Request 필드:**

| 파라미터 | 타입 | 설명 |
|----------|------|------|
| player_id | string | 플레이어 ID |

#### Response (대화 진행 중)

```json
{
    "active": true,
    "conversation": {
        "active": true,
        "npc1_id": 1,
        "npc2_id": 2,
        "started_at": "2025-01-15T10:30:00.000Z"
    }
}
```

**Response 필드 (대화 진행 중):**

| 필드 | 타입 | 설명 |
|------|------|------|
| active | bool | 대화 활성화 여부 (true) |
| conversation | object | 대화 정보 |
| conversation.active | bool | 대화 활성화 여부 |
| conversation.npc1_id | int | 첫 번째 NPC ID |
| conversation.npc2_id | int | 두 번째 NPC ID |
| conversation.started_at | string | 대화 시작 시각 (ISO 8601) |

#### Response (대화 없음)

```json
{
    "active": false,
    "conversation": null
}
```

**Response 필드 (대화 없음):**

| 필드 | 타입 | 설명 |
|------|------|------|
| active | bool | 대화 활성화 여부 (false) |
| conversation | null | 대화 정보 없음 |

---

## 9. 에러 응답

### 404 Not Found

```json
{
    "detail": "세션을 찾을 수 없습니다"
}
```

### 500 Internal Server Error

```json
{
    "detail": "서버 내부 오류가 발생했습니다"
}
```

---

## 10. 프로토콜 요약표

| 기능 | Method | Endpoint | Request Body | Response |
|------|--------|----------|--------------|----------|
| 로그인 | POST | /api/npc/login | playerId, scenarioLevel, heroines[] | success, message |
| 히로인 대화 | POST | /api/npc/heroine/chat/sync | playerId, heroineId, text | text, emotion(int), affection, sanity, memoryProgress |
| **히로인 대화 + 음성** | POST | /api/npc/heroine/chat/sync/voice | playerId, heroineId, text | text, emotion, emotion_intensity, audio_base64, ... |
| 대현자 대화 | POST | /api/npc/sage/chat/sync | playerId, text | text, emotion(int), scenarioLevel, infoRevealed |
| **대현자 대화 + 음성** | POST | /api/npc/sage/chat/sync/voice | playerId, text | text, emotion, emotion_intensity, audio_base64, ... |
| 히로인간 대화 생성 | POST | /api/npc/heroine-conversation/generate | playerId, heroine1Id, heroine2Id, situation?, turnCount? | id, content, conversation[] |
| **히로인간 대화 + 음성** | POST | /api/npc/heroine-conversation/generate/voice | playerId, heroine1Id, heroine2Id, situation?, turnCount? | conversation[] (각 턴에 audio_base64 포함) |
| 히로인간 대화 조회 | GET | /api/npc/heroine-conversation | player_id, heroine1_id?, heroine2_id?, limit? | conversations[] |
| 히로인간 대화 인터럽트 | POST | /api/npc/heroine-conversation/interrupt | playerId, conversationId, interruptedTurn, heroine1Id, heroine2Id | success, message, interrupted_turn |
| 길드 진입 | POST | /api/npc/guild/enter | playerId | success, message |
| 길드 퇴장 | POST | /api/npc/guild/leave | playerId | success, message, activeConversation |
| 길드 상태 조회 | GET | /api/npc/guild/status/{player_id} | - | in_guild, active_conversation |
| 세션 조회 | GET | /api/npc/session/{player_id}/{npc_id} | - | 세션 정보 (상태, 대화 버퍼 등) |
| NPC 대화 활성화 조회 | GET | /api/npc/npc-conversation/active/{player_id} | - | active, conversation |
