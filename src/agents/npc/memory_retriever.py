"""
MemoryRetriever - User Memory 검색 전문 클래스

HeroineAgent와 SageAgent가 공통으로 사용하는 기억 검색 로직을 통합합니다.

주요 기능:
1. 시간 키워드 기반 User Memory 검색 (어제, N일 전, 최근, N월 N일, 지난주 X요일)
2. 4요소 하이브리드 검색 (기본) - search_memories 사용
3. NPC-NPC 대화 기억 검색 (npc_npc_memories 테이블)
4. 다른 NPC와의 최근 대화 검색 (npc_npc_checkpoints 테이블)

이 클래스가 없을 경우 발생할 문제:
- 시간 키워드 분석 로직 수정 시 HeroineAgent와 SageAgent 두 파일 모두 수정 필요
- 버그 수정이 한쪽에만 적용될 위험
- 테스트 코드 중복
"""

import re
from datetime import datetime
from typing import Optional, List, Dict, Any

from agents.npc.base_npc_agent import WEEKDAY_MAP, get_last_weekday
from agents.npc.npc_constants import NPC_ID_TO_NAME_KR
from db.user_memory_manager import user_memory_manager
from db.user_memory_models import NPC_ID_TO_HEROINE, SearchWeights
from db.npc_npc_memory_manager import npc_npc_memory_manager


# NPC 이름 -> ID 매핑 (대현자 포함)
NPC_NAME_TO_ID: Dict[str, int] = {
    "사트라": 0,
    "대현자": 0,
    "레티아": 1,
    "루파메스": 2,
    "로코": 3,
}


class MemoryRetriever:
    """User Memory 검색 전문 클래스 (HeroineAgent + SageAgent 공통)

    시간 키워드 분석과 NPC-NPC 대화 검색 로직을 통합하여
    중복 코드를 제거하고 유지보수성을 높입니다.

    아키텍처 위치:
    - HeroineAgent/SageAgent의 기억 검색 책임을 위임받음
    - user_memory_manager, npc_npc_memory_manager와 직접 통신

    사용 예시:
        retriever = MemoryRetriever()

        # 시간 키워드 기반 검색 (비동기)
        memories = await retriever.search_by_time_keyword("어제 뭐 했어?", player_id=1, npc_id=1)

        # NPC-NPC 대화 기억 검색
        npc_memories = retriever.search_npc_npc_memories("루파메스 어때?", player_id=1, current_npc_id=1)
    """

    def __init__(self, weights: SearchWeights = None):
        """초기화

        Args:
            weights: 4요소 하이브리드 검색 가중치 (None이면 기본값 사용)
        """
        self.weights = weights or SearchWeights()

    def _convert_user_memory_to_dict(self, memory) -> Dict[str, Any]:
        """UserMemory 객체를 dict로 변환 (호환성 유지)

        Args:
            memory: UserMemory 객체

        Returns:
            Mem0 호환 형식의 dict
        """
        return {
            "memory": memory.content,
            "text": memory.content,
            "score": memory.final_score,
            "metadata": {
                "speaker": memory.speaker,
                "subject": memory.subject,
                "content_type": memory.content_type,
            },
            # 개별 점수도 포함 (디버깅/분석용)
            "scores": {
                "recency": memory.recency_score,
                "importance": memory.importance_score,
                "relevance": memory.relevance_score,
                "keyword": memory.keyword_score,
                "final": memory.final_score,
            },
        }

    async def search_by_time_keyword(
        self, user_message: str, player_id: int, npc_id: int
    ) -> List[Dict[str, Any]]:
        """시간 키워드 기반 User Memory 검색

        사용자 메시지에서 시간 표현을 분석하여 해당 시점의 기억을 검색합니다.

        지원하는 시간 표현:
        - "어제" -> 1일 전
        - "그제", "그저께" -> 2일 전
        - "N일 전" -> N일 전
        - "최근", "요즘", "며칠" -> 최근 7일
        - "전부", "다", "모든", "기억하는 거" -> 전체 유효 기억
        - "N월 N일" -> 특정 날짜
        - "지난주 X요일" -> 지난주 특정 요일
        - "지지난주 X요일" -> 지지난주 특정 요일
        - "바뀌", "변하", "전에는" -> 취향 변화 히스토리 (SageAgent용)
        - 기본 -> 4요소 하이브리드 검색 (search_memories 사용)

        Args:
            user_message: 사용자 메시지
            player_id: 플레이어 ID
            npc_id: NPC ID

        Returns:
            검색된 기억 리스트 (각 항목은 dict)
        """
        # 정규식 패턴 미리 컴파일
        days_ago_match = re.search(r"(\d+)\s*일\s*전", user_message)

        # 1. "어제"
        if "어제" in user_message:
            print("[MEMORY_FUNC] get_memories_days_ago_sync(1)")
            return user_memory_manager.get_memories_days_ago_sync(
                player_id, npc_id, days_ago=1, limit=5
            )

        # 2. "그제", "그저께"
        if "그제" in user_message or "그저께" in user_message:
            print("[MEMORY_FUNC] get_memories_days_ago_sync(2)")
            return user_memory_manager.get_memories_days_ago_sync(
                player_id, npc_id, days_ago=2, limit=5
            )

        # 3. "N일 전"
        if days_ago_match:
            days = int(days_ago_match.group(1))
            print(f"[MEMORY_FUNC] get_memories_days_ago_sync({days})")
            return user_memory_manager.get_memories_days_ago_sync(
                player_id, npc_id, days_ago=days, limit=5
            )

        # 4. "최근", "요즘", "며칠"
        if re.search(r"(최근|요즘|며칠)", user_message):
            print("[MEMORY_FUNC] get_recent_memories_sync(7)")
            return user_memory_manager.get_recent_memories_sync(
                player_id, npc_id, days=7, limit=5
            )

        # 5. 취향 변화 히스토리 (SageAgent에서 사용)
        if re.search(r"(바뀌|변하|전에는|바꼈|바뀐|변했)", user_message):
            print("[MEMORY_FUNC] get_preference_history_sync")
            return user_memory_manager.get_preference_history_sync(
                player_id, npc_id, user_message
            )

        # 6. "전부", "다", "모든", "기억하는 거"
        if re.search(r"(전부|다\s|모든|기억하는\s*거)", user_message):
            print("[MEMORY_FUNC] get_valid_memories_sync")
            return user_memory_manager.get_valid_memories_sync(
                player_id, npc_id, limit=10
            )

        # 7. "N월 N일" 특정 날짜
        date_match = re.search(r"(\d{1,2})월\s*(\d{1,2})일", user_message)
        if date_match:
            month = int(date_match.group(1))
            day = int(date_match.group(2))
            year = datetime.now().year
            point_in_time = datetime(year, month, day)
            print(f"[MEMORY_FUNC] get_memories_at_point_sync({month}/{day})")
            return user_memory_manager.get_memories_at_point_sync(
                player_id, npc_id, point_in_time, limit=5
            )

        # 8. "지지난주 X요일"
        week_match_2 = re.search(r"지지난주\s*(월|화|수|목|금|토|일)요일", user_message)
        if week_match_2:
            weekday = WEEKDAY_MAP[week_match_2.group(1) + "요일"]
            point_in_time = get_last_weekday(weekday, weeks_ago=2)
            print(
                f"[MEMORY_FUNC] get_memories_at_point_sync(지지난주 {week_match_2.group(1)}요일)"
            )
            return user_memory_manager.get_memories_at_point_sync(
                player_id, npc_id, point_in_time, limit=5
            )

        # 9. "지난주 X요일"
        week_match_1 = re.search(r"지난주\s*(월|화|수|목|금|토|일)요일", user_message)
        if week_match_1:
            weekday = WEEKDAY_MAP[week_match_1.group(1) + "요일"]
            point_in_time = get_last_weekday(weekday, weeks_ago=1)
            print(
                f"[MEMORY_FUNC] get_memories_at_point_sync(지난주 {week_match_1.group(1)}요일)"
            )
            return user_memory_manager.get_memories_at_point_sync(
                player_id, npc_id, point_in_time, limit=5
            )

        # 10. 기본: 4요소 하이브리드 검색 (search_memories 사용)
        heroine_id = NPC_ID_TO_HEROINE.get(npc_id, "letia")
        print(f"[MEMORY_FUNC] search_memories (hybrid, weights={self.weights})")
        
        memories = await user_memory_manager.search_memories(
            player_id=str(player_id),
            heroine_id=heroine_id,
            query=user_message,
            limit=3,
            weights=self.weights,
        )
        
        # UserMemory 객체를 dict로 변환
        return [self._convert_user_memory_to_dict(m) for m in memories]

    def detect_other_npc_id(
        self, user_message: str, current_npc_id: int
    ) -> Optional[int]:
        """사용자 메시지에서 다른 NPC ID 감지

        메시지에서 NPC 이름을 찾아 해당 NPC의 ID를 반환합니다.
        현재 대화 중인 NPC와 동일한 경우 None을 반환합니다.

        Args:
            user_message: 사용자 메시지
            current_npc_id: 현재 대화 중인 NPC ID

        Returns:
            다른 NPC ID 또는 None (현재 NPC와 동일하거나 NPC 언급 없음)

        예시:
            detect_other_npc_id("루파메스 어때?", current_npc_id=1)  # -> 2
            detect_other_npc_id("레티아 어때?", current_npc_id=1)  # -> None (현재 NPC)
            detect_other_npc_id("오늘 뭐해?", current_npc_id=1)  # -> None (NPC 언급 없음)
        """
        other_id = None

        for npc_name, npc_id in NPC_NAME_TO_ID.items():
            if npc_name in user_message:
                other_id = npc_id
                break

        # 현재 NPC와 다른 경우만 반환
        if other_id is not None and int(other_id) != int(current_npc_id):
            return other_id

        return None

    def search_npc_npc_memories(
        self, user_message: str, player_id: int, current_npc_id: int
    ) -> List[Dict[str, Any]]:
        """다른 NPC와의 장기 기억 검색 (npc_npc_memories 테이블)

        사용자가 다른 NPC에 대해 물어볼 때 (예: "루파메스 어때?")
        현재 NPC가 해당 NPC와 나눈 과거 대화 기억을 검색합니다.

        Args:
            user_message: 사용자 메시지
            player_id: 플레이어 ID
            current_npc_id: 현재 대화 중인 NPC ID

        Returns:
            검색된 NPC-NPC 기억 리스트

        이 메서드가 없을 경우:
        - NPC 간 관계 정보를 활용할 수 없음
        - "루파메스를 어떻게 생각해?" 같은 질문에 답변 불가
        """
        other_id = self.detect_other_npc_id(user_message, current_npc_id)

        if other_id is None:
            return []

        print(f"[NPC_NPC_MEMORY] search_memories: current={current_npc_id}, other={other_id}")
        return npc_npc_memory_manager.search_memories(
            player_id=str(player_id),
            npc1_id=int(current_npc_id),
            npc2_id=int(other_id),
            query=user_message,
            limit=3,
        )

    def get_latest_npc_conversation(
        self, player_id: int, npc1_id: int, npc2_id: int
    ) -> List[Dict[str, Any]]:
        """다른 NPC와의 최근 대화 검색 (npc_npc_checkpoints 테이블)

        특정 두 NPC 사이의 가장 최근 대화 내용을 가져옵니다.
        "루파메스랑 뭐 얘기했어?" 같은 질문에 사용됩니다.

        Args:
            player_id: 플레이어 ID
            npc1_id: 첫 번째 NPC ID (현재 대화 중인 NPC)
            npc2_id: 두 번째 NPC ID (질문 대상 NPC)

        Returns:
            최근 대화 리스트 (각 항목: {speaker_id, text})

        이 메서드가 없을 경우:
        - NPC 간 최근 대화 내용을 조회할 수 없음
        - "다른 히로인과 뭐 얘기했어?" 질문에 구체적 답변 불가
        """
        print(f"[NPC_NPC_CHECKPOINT] get_latest: npc1={npc1_id}, npc2={npc2_id}")
        return npc_npc_memory_manager.get_latest_checkpoint_conversation(
            player_id=str(player_id),
            npc1_id=int(npc1_id),
            npc2_id=int(npc2_id),
        )

    def format_npc_conversation(
        self, conversation: List[Dict[str, Any]]
    ) -> str:
        """NPC 대화를 프롬프트용 문자열로 포맷

        Args:
            conversation: 대화 리스트 (각 항목: {speaker_id, text})

        Returns:
            포맷된 문자열 (예: "레티아: 안녕\n루파메스: 반가워")
        """
        if not conversation:
            return "관련 대화 없음"

        lines = ["[다른 NPC와의 최근 대화]"]
        for msg in conversation:
            speaker_id = msg.get("speaker_id")
            text = msg.get("text", "")
            speaker_name = NPC_ID_TO_NAME_KR.get(speaker_id, f"NPC_{speaker_id}")
            lines.append(f"{speaker_name}: {text}")

        return "\n".join(lines)


# 싱글톤 인스턴스 (필요시 사용)
memory_retriever = MemoryRetriever()
