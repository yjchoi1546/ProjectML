"""
User-NPC 장기 기억 모델 정의

NEW_LONGMEMORY_SYSTEM.MD 명세에 따른 Pydantic 모델
"""

from enum import Enum
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass
from pydantic import BaseModel, Field


# ============================================
# Enum 정의
# ============================================


class Speaker(str, Enum):
    """발화자 - 누가 말했는가?"""

    USER = "user"
    LETIA = "letia"
    LUPAMES = "lupames"
    ROCO = "roco"
    SAGE = "sage"


class Subject(str, Enum):
    """대상 - 무엇에 대한 사실인가?"""

    USER = "user"
    LETIA = "letia"
    LUPAMES = "lupames"
    ROCO = "roco"
    SAGE = "sage"
    WORLD = "world"


class ContentType(str, Enum):
    """내용 타입"""

    PREFERENCE = "preference"  # 선호도 (좋아하는 것, 싫어하는 것)
    TRAIT = "trait"  # 특성 (성격, 외모 등)
    EVENT = "event"  # 이벤트 (함께한 경험)
    OPINION = "opinion"  # 평가 (누군가에 대한 의견)
    PERSONAL = "personal"  # 개인정보 (이름, 직업 등)


# ============================================
# Fact 추출용 모델
# ============================================


class ExtractedFact(BaseModel):
    """LLM이 대화에서 추출한 사실

    예시:
        대화: "플레이어: 나는 고양이 좋아해"
        추출: ExtractedFact(
            speaker=Speaker.USER,
            subject=Subject.USER,
            content_type=ContentType.PREFERENCE,
            content="고양이를 좋아함",
            importance=6
        )
    """

    speaker: Speaker  # 누가 말했나
    subject: Subject  # 무엇에 대한 사실인가
    content_type: ContentType  # 내용 타입
    content: str  # 추출된 사실 내용
    importance: int = Field(default=5, ge=1, le=10)  # 중요도 1~10
    keywords: List[str] = Field(default_factory=list)  # 검색용 키워드/상위 개념
    player_name: Optional[str] = None  # 플레이어가 이름을 밝힌 경우 추출


class FactExtractionResult(BaseModel):
    """Fact 추출 결과 (LLM 응답 파싱용)"""

    facts: List[ExtractedFact] = []


# ============================================
# 검색 설정
# ============================================


@dataclass
class SearchWeights:
    """검색 가중치 설정

    기본값은 NEW_LONGMEMORY_SYSTEM.MD 권장값 사용
    합이 1.0일 필요 없음 (실험으로 튜닝)
    """

    recency: float = 0.15  # 최신도 가중치
    importance: float = 0.15  # 중요도 가중치
    relevance: float = 0.50  # 관련도 가중치 (dense retriever)
    keyword: float = 0.20  # 키워드 가중치 (sparse retriever)


# ============================================
# DB 조회 결과 컨테이너
# ============================================


@dataclass
class UserMemory:
    """DB에서 조회한 메모리 정보

    Attributes:
        id: 메모리 고유 ID (UUID)
        player_id: 플레이어 ID
        heroine_id: 히로인 ID
        speaker: 발화자
        subject: 대상
        content: 사실 내용
        content_type: 내용 타입
        importance: 중요도 (1-10)
        created_at: 생성 시간
        recency_score: 최신도 점수 (검색시)
        importance_score: 정규화된 중요도 (검색시)
        relevance_score: 관련도 점수 (검색시)
        keyword_score: 키워드 점수 (검색시)
        final_score: 최종 점수 (검색시)
    """

    id: str
    player_id: str
    heroine_id: str
    speaker: str
    subject: str
    content: str
    content_type: str
    importance: int
    created_at: datetime
    recency_score: float = 0.0
    importance_score: float = 0.0
    relevance_score: float = 0.0
    keyword_score: float = 0.0
    final_score: float = 0.0


# ============================================
# 히로인 ID 매핑
# ============================================

# NPC ID (숫자) -> npc_id (문자열) 변환
NPC_ID_TO_HEROINE = {0: "sage", 1: "letia", 2: "lupames", 3: "roco"}

# heroine_id -> Speaker Enum 변환
HEROINE_TO_SPEAKER = {
    "sage": Speaker.SAGE,
    "letia": Speaker.LETIA,
    "lupames": Speaker.LUPAMES,
    "roco": Speaker.ROCO,
}