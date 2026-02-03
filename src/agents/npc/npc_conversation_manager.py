"""
NPCConversationManager - NPC 대화 관리 전문 클래스

HeroineAgent와 SageAgent가 공통으로 사용하는 대화 관리 로직을 통합합니다.

주요 기능:
1. User Memory 백그라운드 저장 + 플레이어 이름 추출
2. 대화 요약 생성 및 저장
3. 요약 생성 조건 판단 (20턴 또는 1시간 경과)

이 클래스가 없을 경우 발생할 문제:
- 대화 저장 로직 수정 시 HeroineAgent와 SageAgent 두 파일 모두 수정 필요
- 요약 생성 조건 로직 불일치 위험
- 플레이어 이름 추출 로직 중복
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from db.redis_manager import redis_manager
from db.user_memory_manager import user_memory_manager
from db.session_checkpoint_manager import session_checkpoint_manager
from db.user_memory_models import NPC_ID_TO_HEROINE


# 요약 생성 조건 상수
SUMMARY_TURN_THRESHOLD = 20  # N턴마다 요약 생성
SUMMARY_INITIAL_THRESHOLD = 10  # 첫 요약은 10턴 후
SUMMARY_TIME_THRESHOLD_HOURS = 1  # N시간 경과 후 요약 생성


class NPCConversationManager:
    """NPC 대화 관리 전문 클래스 (HeroineAgent + SageAgent 공통)

    대화 저장, 요약 생성 등 세션 관리 로직을 통합하여
    중복 코드를 제거하고 유지보수성을 높입니다.

    아키텍처 위치:
    - HeroineAgent/SageAgent의 대화 관리 책임을 위임받음
    - redis_manager, user_memory_manager, session_checkpoint_manager와 직접 통신

    사용 예시:
        manager = NPCConversationManager()

        # 백그라운드로 대화 저장
        await manager.save_to_user_memory_background(
            player_id=1, npc_id=1, user_msg="안녕", npc_response="안녕하세요"
        )

        # 요약 생성 조건 확인
        if manager.should_generate_summary(session):
            await manager.generate_and_save_summary(player_id, npc_id, conversations)
    """

    async def save_to_user_memory_background(
        self,
        player_id: int,
        npc_id: int,
        user_msg: str,
        npc_response: str,
        heroine_id: Optional[str] = None,
    ) -> Optional[str]:
        """백그라운드로 User Memory에 대화 저장

        LLM으로 fact를 추출하여 저장하고,
        이름이 추출되면 Redis 세션에도 저장합니다.

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            user_msg: 유저 메시지
            npc_response: NPC 응답
            heroine_id: 히로인 ID 문자열 (None이면 자동 결정)

        Returns:
            추출된 플레이어 이름 또는 None

        이 메서드가 없을 경우:
        - 대화가 장기 기억에 저장되지 않음
        - 플레이어 이름 추출 불가
        """
        try:
            # heroine_id 자동 결정
            if heroine_id is None:
                heroine_id = NPC_ID_TO_HEROINE.get(npc_id, "sage")

            result = await user_memory_manager.save_conversation(
                player_id=str(player_id),
                heroine_id=heroine_id,
                user_message=user_msg,
                npc_response=npc_response,
            )

            # 이름이 추출되었으면 Redis 세션에 저장
            extracted_name = result.get("extracted_player_name")
            if extracted_name:
                self._save_player_name_to_session(player_id, npc_id, extracted_name)
                print(f"[DEBUG] 플레이어 이름 저장: {extracted_name}")
                return extracted_name

            return None

        except Exception as e:
            print(f"[ERROR] User Memory 저장 실패: {e}")
            return None

    def _save_player_name_to_session(
        self, player_id: int, npc_id: int, player_name: str
    ) -> None:
        """플레이어 이름을 Redis 세션에 저장

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            player_name: 플레이어 이름
        """
        session = redis_manager.load_session(player_id, npc_id)
        if session:
            if "state" not in session:
                session["state"] = {}
            session["state"]["player_known_name"] = player_name
            redis_manager.save_session(player_id, npc_id, session)

    def should_generate_summary(self, session: Dict[str, Any]) -> bool:
        """요약 생성 조건 확인

        다음 조건 중 하나라도 만족하면 True:
        1. turn_count >= 20 (20턴 경과)
        2. last_summary_at이 1시간 이상 경과
        3. 첫 요약인 경우 turn_count >= 10

        Args:
            session: Redis 세션 딕셔너리

        Returns:
            요약 생성 필요 여부

        이 메서드가 없을 경우:
        - 요약 생성 조건이 Agent마다 불일치할 위험
        - 조건 변경 시 여러 파일 수정 필요
        """
        turn_count = session.get("turn_count", 0)
        last_summary_at = session.get("last_summary_at")

        # 조건 1: N턴 경과
        if turn_count >= SUMMARY_TURN_THRESHOLD:
            return True

        # 조건 2: 1시간 이상 경과
        if last_summary_at:
            last_summary_time = datetime.fromisoformat(last_summary_at)
            if datetime.now() - last_summary_time > timedelta(hours=SUMMARY_TIME_THRESHOLD_HOURS):
                return True

        # 조건 3: 첫 요약 (10턴 이상)
        if not last_summary_at and turn_count >= SUMMARY_INITIAL_THRESHOLD:
            return True

        return False

    async def generate_and_save_summary(
        self, player_id: int, npc_id: int, conversations: List[Dict[str, str]]
    ) -> None:
        """대화 요약 생성 및 저장

        대화 버퍼에서 요약을 생성하고 Redis와 DB에 저장합니다.

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            conversations: 대화 목록 [{"user": "...", "npc": "..."}, ...]

        이 메서드가 없을 경우:
        - 대화 컨텍스트가 누적되어 토큰 비용 증가
        - 장기 대화에서 맥락 유지 어려움
        """
        try:
            # 요약 생성
            summary_item = await session_checkpoint_manager.generate_summary(
                player_id, npc_id, conversations
            )

            # Redis 세션 업데이트
            session = redis_manager.load_session(player_id, npc_id)
            summary_list = []

            if session:
                summary_list = session.get("summary_list", [])
                summary_list.append(summary_item)

                # 오래된 요약 정리
                summary_list = session_checkpoint_manager.prune_summary_list(
                    summary_list
                )
                session["summary_list"] = summary_list

                redis_manager.save_session(player_id, npc_id, session)
            else:
                summary_list = [summary_item]
                summary_list = session_checkpoint_manager.prune_summary_list(
                    summary_list
                )

            # DB에 요약 저장
            session_checkpoint_manager.save_summary(player_id, npc_id, summary_list)

            print(f"[DEBUG] 요약 생성 완료: player={player_id}, npc={npc_id}")

        except Exception as e:
            print(f"[ERROR] _generate_and_save_summary 실패: {e}")

    def prepare_conversations_for_summary(
        self, conversation_buffer: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """요약을 위한 대화 형식 변환

        conversation_buffer를 요약 생성용 형식으로 변환합니다.

        Args:
            conversation_buffer: [{"role": "user/assistant", "content": "..."}, ...]

        Returns:
            변환된 대화 목록 [{"user": "...", "npc": "..."}, ...]
        """
        conversations = []
        for i in range(0, len(conversation_buffer), 2):
            if i + 1 < len(conversation_buffer):
                conversations.append({
                    "user": conversation_buffer[i].get("content", ""),
                    "npc": conversation_buffer[i + 1].get("content", ""),
                })
        return conversations

    def reset_summary_tracking(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """요약 생성 후 추적 변수 리셋

        Args:
            session: Redis 세션 딕셔너리

        Returns:
            업데이트된 세션
        """
        session["turn_count"] = 0
        session["last_summary_at"] = datetime.now().isoformat()
        return session


# 싱글톤 인스턴스 (필요시 사용)
npc_conversation_manager = NPCConversationManager()
