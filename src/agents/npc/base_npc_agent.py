"""
NPC Agent 기본 클래스

모든 NPC Agent의 공통 기능을 정의합니다.
HeroineAgent와 SageAgent가 이 클래스를 상속받습니다.

주요 기능:
1. LLM 초기화 (일반/스트리밍)
2. 세션 관리 (로드/저장)
3. 장기 기억 관리 (User Memory - 4요소 하이브리드 검색)
4. 대화 버퍼 관리

상태 계산 유틸리티 함수:
- calculate_memory_progress(): 기억 진척도 계산
- calculate_affection_change(): 호감도 변화량 계산
- calculate_sanity_change(): 정신력 변화량 계산
"""

from abc import ABC, abstractmethod
from typing import Optional, AsyncIterator, List
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage

from db.redis_manager import redis_manager
from db.user_memory_manager import user_memory_manager
from db.session_checkpoint_manager import session_checkpoint_manager
from agents.npc.npc_state import NPCState
from enums.LLM import LLM


class BaseNPCAgent(ABC):
    """NPC Agent 기본 클래스 (추상 클래스)

    모든 NPC Agent가 상속받아야 하는 기본 클래스입니다.

    상속 클래스가 구현해야 하는 메서드:
    - _create_initial_session(): 초기 세션 생성
    - process_message(): 메시지 처리 (LangGraph 실행)
    - generate_response_stream(): 스트리밍 응답 생성

    사용 예시:
        class HeroineAgent(BaseNPCAgent):
            def _create_initial_session(self, player_id, npc_id):
                return {"player_id": player_id, ...}
    """

    def __init__(self, model_name: str = LLM.GPT5_MINI):
        """초기화

        Args:
            model_name: 사용할 LLM 모델명 (기본: gpt-4o-mini)
        """
        # 일반 LLM (전체 응답을 한번에 받음)
        self.llm = init_chat_model(model=model_name, temperature=1, max_tokens=150)

    # ============================================
    # 세션 관리 메서드
    # ============================================

    def load_session(self, player_id: int, npc_id: int) -> dict:
        """세션 로드

        Redis에서 세션을 불러옵니다. 없으면 새로 생성합니다.

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID

        Returns:
            세션 딕셔너리
        """
        session = redis_manager.load_session(player_id, npc_id)

        # Redis에 없으면 새 세션 생성
        if session is None:
            session = self._create_initial_session(player_id, npc_id)
            redis_manager.save_session(player_id, npc_id, session)

        return session

    def save_session(self, player_id: int, npc_id: int, session: dict) -> None:
        """세션 저장

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            session: 저장할 세션 데이터
        """
        redis_manager.save_session(player_id, npc_id, session)

    @abstractmethod
    def _create_initial_session(self, player_id: int, npc_id: int) -> dict:
        """초기 세션 생성 (서브클래스에서 구현)

        각 NPC 타입에 맞는 초기 세션을 생성합니다.

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID

        Returns:
            초기 세션 딕셔너리
        """
        pass

    # ============================================
    # 장기 기억 관리 메서드 (User Memory)
    # ============================================

    def add_to_memory(
        self, player_id: int, npc_id: int, content: str, metadata: dict = None
    ) -> None:
        """장기 기억에 추가

        대화 내용을 User Memory에 저장합니다.
        (실제 저장은 heroine_agent에서 save_conversation으로 수행)

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            content: 저장할 내용
            metadata: 추가 메타데이터 (선택)
        """
        # 직접 저장 대신 heroine_agent의 save_conversation 사용 권장
        pass

    def search_memory(
        self, player_id: int, npc_id: int, query: str, limit: int = 5
    ) -> list:
        """장기 기억 검색

        4요소 하이브리드 검색 (최신도, 중요도, 관련도, 키워드)

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            query: 검색어
            limit: 최대 결과 수

        Returns:
            검색된 기억 리스트
        """
        return user_memory_manager.search_memory_sync(player_id, npc_id, query, limit)

    # ============================================
    # 대화 버퍼 관리 메서드
    # ============================================

    def update_conversation_buffer(
        self, session: dict, role: str, content: str
    ) -> dict:
        """대화 버퍼 업데이트

        새 대화를 버퍼에 추가하고, 20턴 초과시 오래된 것을 제거합니다.

        Args:
            session: 세션 딕셔너리
            role: 역할 ("user" 또는 "assistant")
            content: 대화 내용

        Returns:
            업데이트된 세션
        """
        session["conversation_buffer"].append({"role": role, "content": content})

        # 20턴 초과시 오래된 것 제거
        if len(session["conversation_buffer"]) > 20:
            session["conversation_buffer"] = session["conversation_buffer"][-20:]

        return session

    def format_conversation_history(self, conversation_buffer: list) -> str:
        """대화 기록 포맷팅

        대화 기록을 LLM 프롬프트에 넣기 좋은 형태로 변환합니다.

        Args:
            conversation_buffer: 대화 버퍼 리스트

        Returns:
            포맷된 문자열
        """
        if not conversation_buffer:
            return "없음"

        formatted = []

        # 최근 10개만 사용 (프롬프트 길이 제한)
        for msg in conversation_buffer[-10:]:
            role = "플레이어" if msg["role"] == "user" else "NPC"
            formatted.append(f"{role}: {msg['content']}")

        return "\n".join(formatted)

    def get_time_since_last_chat(self, player_id: int, npc_id: int) -> str:
        """마지막 대화로부터 경과 시간 계산

        프롬프트에 삽입할 시간 정보를 반환합니다.

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID

        Returns:
            한국어로 변환된 시간 문자열 (예: "2시간 30분 전")
        """
        session = redis_manager.load_session(player_id, npc_id)

        if session:
            last_chat_at = session.get("last_chat_at")
            if last_chat_at:
                return session_checkpoint_manager.calculate_time_diff(last_chat_at)

        last_chat_at = session_checkpoint_manager.get_last_chat_at(player_id, npc_id)
        return session_checkpoint_manager.calculate_time_diff(last_chat_at)

    # ============================================
    # 추상 메서드 (서브클래스에서 구현 필수)
    # ============================================

    @abstractmethod
    async def process_message(self, state: NPCState) -> NPCState:
        """메시지 처리 (서브클래스에서 구현)

        LangGraph를 통해 메시지를 처리하고 응답을 생성합니다.

        Args:
            state: NPC 상태 딕셔너리

        Returns:
            처리 후 상태 딕셔너리
        """
        pass

    @abstractmethod
    async def generate_response_stream(self, state: NPCState) -> AsyncIterator[str]:
        """스트리밍 응답 생성 (서브클래스에서 구현)

        토큰 단위로 응답을 생성합니다.

        Args:
            state: NPC 상태 딕셔너리

        Yields:
            응답 토큰
        """
        pass


# ============================================
# 상태 계산 유틸리티 함수들
# ============================================


def calculate_memory_progress(
    new_affection: int, current_progress: int, affection_delta: int
) -> int:
    """기억 진척도 계산

    호감도가 기억 진척도를 넘어서면, 넘어서는 만큼 기억 진척도도 증가합니다.
    기억 진척도는 절대 감소하지 않습니다.

    계산 규칙:
    - new_affection > current_progress 일 때만 증가
    - old_affection이 이미 current_progress 이상이면: progress += affection_delta
    - old_affection < current_progress < new_affection이면: progress += (new_affection - current_progress)

    예시:
    - old=40, progress=47, delta=10 -> new=50 -> progress = 47 + (50-47) = 50
    - old=50, progress=30, delta=2 -> new=52 -> progress = 30 + 2 = 32
    - old=30, progress=50, delta=10 -> new=40 -> progress = 50 (변화없음)

    Args:
        new_affection: 변화 후 호감도
        current_progress: 현재 기억 진척도
        affection_delta: 호감도 변화량

    Returns:
        새로운 기억 진척도
    """
    # 호감도가 감소했거나 변화 없으면 기억 진척도 유지
    if affection_delta <= 0:
        return current_progress

    # new_affection이 current_progress 이하면 변화 없음
    if new_affection <= current_progress:
        return current_progress

    # 이전 호감도 계산
    old_affection = new_affection - affection_delta

    # 이전 호감도가 이미 기억 진척도 이상이면 전체 delta 반영
    if old_affection >= current_progress:
        new_progress = current_progress + affection_delta
    else:
        # old_affection < current_progress < new_affection
        # 기억 진척도를 넘어서는 부분만 반영
        overflow = new_affection - current_progress
        new_progress = current_progress + overflow

    # 범위 제한: 0~100, 절대 감소 안함
    new_progress = min(100, new_progress)
    new_progress = max(current_progress, new_progress)

    return new_progress


def calculate_affection_change(
    current_affection: int,
    liked_keywords: List[str],
    trauma_keywords: List[str],
    user_message: str,
    recent_used_keywords: List[str] = None,
    is_positive_romance: bool = False,
    is_negative_romance: bool = False,
) -> tuple:
    """호감도 변화량 계산

    사용자 메시지에서 키워드를 분석하여 호감도 변화량을 계산합니다.

    가중치:
    - 좋아하는 키워드: +10
    - 트라우마 키워드: -10
    - 긍정적 연애: +5 (호감도가 감소하지 않을 때만)
    - 부정적 연애: -5 (호감도가 증가하지 않을 때만)

    반복 방지:
    - 최근 5턴 내 사용된 좋아하는 키워드는 효과 없음
    - 다른 좋아하는 키워드로는 여전히 호감도 상승 가능

    Args:
        current_affection: 현재 호감도
        liked_keywords: 좋아하는 키워드 목록
        trauma_keywords: 트라우마 키워드 목록
        user_message: 사용자 메시지
        recent_used_keywords: 최근 5턴 내 사용된 좋아하는 키워드 목록
        is_positive_romance: 긍정적 연애 관련 여부
        is_negative_romance: 부정적 연애 관련 여부

    Returns:
        (호감도 변화량, 이번에 사용된 좋아하는 키워드 또는 None)
    """
    if recent_used_keywords is None:
        recent_used_keywords = []

    delta = 0
    used_liked_keyword = None
    message_lower = user_message.lower()

    # 좋아하는 것 체크 (+10)
    for keyword in liked_keywords:
        if keyword.lower() in message_lower:
            # 최근 5턴 내 같은 키워드 사용 여부 확인 (대소문자 무시)
            recent_lower = [k.lower() for k in recent_used_keywords]

            if keyword.lower() not in recent_lower:
                delta += 100
                used_liked_keyword = keyword
            # 같은 키워드 반복시 호감도 상승 없음, 하지만 루프 종료
            break

    # 트라우마 체크 (-10)
    for keyword in trauma_keywords:
        if keyword.lower() in message_lower:
            delta -= 100
            break

    # 연애 관련 (+5 / -5)
    if is_positive_romance and delta >= 0:
        delta += 5
    if is_negative_romance and delta <= 0:
        delta -= 5

    # 범위 제한 (0-100)
    new_affection = current_affection + delta
    new_affection = max(0, min(100, new_affection))

    # 실제 변화량 반환 (범위 제한 적용 후)
    actual_delta = new_affection - current_affection

    return (actual_delta, used_liked_keyword)


def calculate_sanity_change(
    current_sanity: int, affection_delta: int, died_in_dungeon: bool = False
) -> int:
    """정신력 변화량 계산

    정신력 변화 규칙:
    - 던전 사망시: -20
    - 호감도 증가시: 호감도 증가량과 동일하게 회복

    Args:
        current_sanity: 현재 정신력
        affection_delta: 호감도 변화량
        died_in_dungeon: 던전 사망 여부

    Returns:
        정신력 변화량
    """
    delta = 0

    if died_in_dungeon:
        delta = -20  # 던전 사망시 -20
    elif affection_delta > 0:
        delta = affection_delta  # 호감도 증가와 동일 비율로 회복

    # 범위 제한 (0-100)
    new_sanity = current_sanity + delta
    new_sanity = max(0, min(100, new_sanity))

    return new_sanity - current_sanity


# ============================================
# 기억 해금 관련 상수 및 함수
# ============================================

# 기억 해금 임계값 목록 (DB 시나리오 memory_progress 값과 일치해야 함)
MEMORY_THRESHOLDS = [10, 50, 60, 70, 80, 100]


def detect_memory_unlock(old_progress: int, new_progress: int) -> Optional[int]:
    """기억 해금 감지

    old_progress와 new_progress 사이에 새로 넘어간 임계값이 있는지 확인합니다.
    여러 임계값을 넘었을 경우 가장 높은 값만 반환합니다.

    Args:
        old_progress: 이전 기억 진척도
        new_progress: 새로운 기억 진척도

    Returns:
        새로 해금된 임계값 (없으면 None)
    """
    unlocked_threshold = None

    for threshold in MEMORY_THRESHOLDS:
        if old_progress < threshold <= new_progress:
            unlocked_threshold = threshold

    return unlocked_threshold
