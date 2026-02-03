"""
Session Checkpoint Manager

매 대화 후 Redis 세션을 Supabase session_checkpoints 테이블에 저장합니다.
20턴 또는 1시간마다 요약을 생성합니다.

주요 기능:
1. save_checkpoint_background(): 백그라운드로 대화 저장
2. generate_summary(): LLM으로 요약 생성
3. prune_summary_list(): 중요도 기반 가지치기
4. calculate_time_diff(): 마지막 대화 시간 차이 계산
5. load_checkpoints(): 로그인시 checkpoint 로드
"""

import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy import create_engine, text
from langchain.chat_models import init_chat_model
from enums.LLM import LLM
from db.config import CONNECTION_URL
from utils.langfuse_tracker import tracker


class SessionCheckpointManager:
    """세션 체크포인트 관리 클래스"""

    def __init__(self):
        """초기화"""
        self.engine = create_engine(CONNECTION_URL, pool_pre_ping=True)
        self.llm = init_chat_model(model=LLM.GPT5_MINI)

    def save_checkpoint_background(
        self,
        player_id: str,
        npc_id: int,
        user_message: str,
        npc_response: str,
        state: Dict[str, Any],
    ) -> None:
        """백그라운드로 체크포인트 저장

        매 대화마다 호출됩니다.
        conversation에 방금 한 대화만 저장합니다.

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            user_message: 유저 메시지
            npc_response: NPC 응답
            state: 현재 상태 (affection, sanity, memoryProgress, emotion)
        """
        try:
            conversation = {"user": user_message, "npc": npc_response}

            with self.engine.connect() as conn:
                summary_list_sql = text(
                    """
                    SELECT summary_list
                    FROM session_checkpoints
                    WHERE player_id = :player_id AND npc_id = :npc_id
                    ORDER BY created_at DESC
                    LIMIT 1
                """
                )
                result = conn.execute(
                    summary_list_sql,
                    {
                        "player_id": str(player_id),
                        "npc_id": npc_id,
                    },
                )
                row = (
                    result.fetchone()
                )  # 데이터베이스 조회 결과에서 한 줄씩 가져오는 함수
                # 결과가 있으면 → 그 한 줄을 반환
                # 결과가 없으면 → None 반환
                summary_list = row.summary_list if row and row.summary_list else []

                sql = text(
                    """
                    INSERT INTO session_checkpoints (player_id, npc_id, conversation, state, last_chat_at, summary_list)
                    VALUES (:player_id, :npc_id, :conversation, :state, NOW(), :summary_list)
                """
                )

                conn.execute(
                    sql,
                    {
                        "player_id": str(player_id),
                        "npc_id": npc_id,
                        "conversation": json.dumps(conversation, ensure_ascii=False),
                        "state": json.dumps(state, ensure_ascii=False),
                        "summary_list": json.dumps(summary_list, ensure_ascii=False),
                    },
                )
                conn.commit()

        except Exception as e:
            print(f"[ERROR] save_checkpoint_background 실패: {e}")

    async def generate_summary(
        self, player_id: str, npc_id: int, conversations: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """LLM으로 요약 생성

        20턴 또는 1시간 경과시 호출됩니다.

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            conversations: 대화 목록

        Returns:
            요약 딕셔너리 (summary, importance, created_at)
        """
        try:
            conversation_text = ""
            for conv in conversations:
                conversation_text += f"유저: {conv.get('user', '')}\n"
                conversation_text += f"NPC: {conv.get('npc', '')}\n\n"

            prompt = f"""다음 대화를 2-3문장으로 요약하고, 중요도를 1-5점으로 평가하세요.

[대화 내용]
{conversation_text}

[출력 형식]
요약: (2-3문장 요약)
중요도: (1-5 숫자만)"""

            # LangFuse 토큰 추적 (v3 API)
            config = tracker.get_langfuse_config(
                tags=["summary", "checkpoint", f"npc:{npc_id}"],
                user_id=player_id,
                metadata={
                    "npc_id": npc_id,
                    "conversation_count": len(conversations),
                }
            )
            
            response = await self.llm.ainvoke(prompt, **config)
            content = response.content

            lines = content.strip().split("\n")
            summary = ""
            importance = 3

            for line in lines:
                if line.startswith("요약:"):
                    summary = line.replace("요약:", "").strip()
                elif line.startswith("중요도:"):
                    importance_str = line.replace("중요도:", "").strip()
                    importance = int(importance_str)

            return {
                "summary": summary,
                "importance": importance,
                "created_at": datetime.now().isoformat(),
            }

        except Exception as e:
            print(f"[ERROR] generate_summary 실패: {e}")
            return {
                "summary": "요약 생성 실패",
                "importance": 1,
                "created_at": datetime.now().isoformat(),
            }

    def save_summary(
        self, player_id: str, npc_id: int, summary_list: List[Dict[str, Any]]
    ) -> None:
        """요약 리스트를 저장

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            summary_list: 가지치기된 전체 요약 리스트
        """
        try:
            sql = text(
                """
                UPDATE session_checkpoints
                SET summary_list = CAST(:summary_list AS jsonb)
                WHERE player_id = :player_id AND npc_id = :npc_id
                AND id = (
                    SELECT id FROM session_checkpoints
                    WHERE player_id = :player_id AND npc_id = :npc_id
                    ORDER BY created_at DESC
                    LIMIT 1
                )
            """
            )

            with self.engine.connect() as conn:
                conn.execute(
                    sql,
                    {
                        "player_id": str(player_id),
                        "npc_id": npc_id,
                        "summary_list": json.dumps(summary_list, ensure_ascii=False),
                    },
                )  # execute: 데이터베이스 쿼리를 실행하는 함수
                conn.commit()  # commit: 데이터베이스 변경 사항을 영구적으로 저장하는 함수

        except Exception as e:
            print(f"[ERROR] save_summary 실패: {e}")

    def prune_summary_list(
        self, summary_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """중요도 기반 가지치기

        규칙:
        1. 시간 기준: 현재 시간 - 요소 시간 > 3시간 -> 삭제 후보
        2. 개수 기준: 리스트 길이 > 5개 -> 삭제 후보
        3. 기본 로직: 가장 오래되고 중요도가 가장 낮은 항목 삭제
        4. 특이 케이스: 가장 오래된 항목이 동시에 가장 높은 중요도를 가지는 경우
           - 그 항목의 중요도를 1 감소시키고 유지
           - 그 다음으로 가장 오래되고 중요도가 가장 낮은 항목 삭제
        5. 최소 1개는 항상 유지

        Args:
            summary_list: 요약 목록

        Returns:
            가지치기된 요약 목록
        """
        if not summary_list:
            return []

        now = datetime.now()

        filtered_list = []
        for item in summary_list:
            created_at_str = item.get("created_at", "")
            if created_at_str:
                created_at = datetime.fromisoformat(created_at_str)
                time_diff = now - created_at
                if time_diff > timedelta(hours=3) and item.get("importance", 3) <= 2:
                    continue
            filtered_list.append(item)

        if len(filtered_list) <= 1:
            if len(filtered_list) == 0 and summary_list:
                latest_item = max(summary_list, key=lambda x: x.get("created_at", ""))
                return [latest_item]
            return filtered_list

        if len(filtered_list) <= 5:
            return filtered_list

        oldest_item = None
        oldest_time = None
        max_importance = 0

        for item in filtered_list:
            created_at_str = item.get("created_at", "")
            if created_at_str:
                created_at = datetime.fromisoformat(created_at_str)
                if (
                    oldest_time is None or created_at < oldest_time
                ):  # 현재 항목의 생성 시간이 지금까지 찾은 가장 오래된 시간보다 더 이전이면
                    # → 이 항목을 새로운 "가장 오래된 항목"으로 업데이트
                    oldest_time = created_at
                    oldest_item = item

            importance = item.get("importance", 3)
            if importance > max_importance:
                max_importance = importance

        if oldest_item and oldest_item.get("importance", 3) == max_importance:
            if oldest_item.get("importance", 3) > 1:
                oldest_item["importance"] = oldest_item.get("importance", 3) - 1

            remaining_items = [item for item in filtered_list if item != oldest_item]
            # remaining_items: 가장 오래된 항목을 제외한 나머지 항목들
            if not remaining_items:  # 나머지 항목이 없으면
                # → 가장 오래된 항목만 반환
                return [oldest_item]

            oldest_low_importance_item = None
            oldest_low_time = None  # 가장 오래된 낮은 중요도 항목의 생성 시간을 저장
            min_importance = 5

            for item in remaining_items:
                importance = item.get("importance", 3)
                if importance < min_importance:
                    min_importance = importance

            for item in remaining_items:
                if item.get("importance", 3) == min_importance:
                    created_at_str = item.get("created_at", "")
                    if created_at_str:
                        created_at = datetime.fromisoformat(created_at_str)
                        if oldest_low_time is None or created_at < oldest_low_time:
                            oldest_low_time = created_at
                            oldest_low_importance_item = item

            if oldest_low_importance_item:
                remaining_items.remove(oldest_low_importance_item)

            result = [oldest_item] + remaining_items
            return result[:5]

        oldest_low_importance_item = None
        oldest_low_time = None
        min_importance = 5

        for item in filtered_list:
            importance = item.get("importance", 3)
            if importance < min_importance:
                min_importance = importance

        for item in filtered_list:
            if item.get("importance", 3) == min_importance:
                created_at_str = item.get("created_at", "")
                if created_at_str:
                    created_at = datetime.fromisoformat(created_at_str)
                    if oldest_low_time is None or created_at < oldest_low_time:
                        oldest_low_time = created_at
                        oldest_low_importance_item = item

        if oldest_low_importance_item:
            result = [
                item for item in filtered_list if item != oldest_low_importance_item
            ]
            return result[:5]

        return filtered_list[:5]

    def calculate_time_diff(self, last_chat_at: Optional[str]) -> str:
        """마지막 대화와 현재 시간 차이 계산

        Args:
            last_chat_at: 마지막 대화 시간 (ISO 형식)

        Returns:
            한국어로 변환된 시간 차이 문자열
        """
        if not last_chat_at:
            return "처음 대화"

        try:
            if isinstance(last_chat_at, str):
                last_time = datetime.fromisoformat(last_chat_at.replace("Z", "+00:00"))
            else:
                last_time = last_chat_at

            now = datetime.now(last_time.tzinfo) if last_time.tzinfo else datetime.now()
            diff = now - last_time

            total_minutes = int(diff.total_seconds() / 60)

            if total_minutes < 1:
                return "방금 전"
            elif total_minutes < 60:
                return f"{total_minutes}분 전"
            elif total_minutes < 1440:
                hours = total_minutes // 60
                minutes = total_minutes % 60
                if minutes > 0:
                    return f"{hours}시간 {minutes}분 전"
                return f"{hours}시간 전"
            else:
                days = total_minutes // 1440
                return f"{days}일 전"

        except Exception as e:
            print(f"[ERROR] calculate_time_diff 실패: {e}")
            return "알 수 없음"

    def load_checkpoints(self, player_id: str, npc_id: int) -> Dict[str, Any]:
        """로그인시 checkpoint 로드

        최근 20개의 conversation과 summary_list를 로드합니다.

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID

        Returns:
            로드된 데이터 (conversations, summary_list, state, last_chat_at)
        """
        try:
            sql = text(
                """
                SELECT conversation, summary_list, state, last_chat_at
                FROM session_checkpoints
                 WHERE player_id = :player_id AND npc_id = :npc_id
                ORDER BY created_at DESC
                LIMIT 20
            """
            )

            with self.engine.connect() as conn:
                result = conn.execute(
                    sql, {"player_id": str(player_id), "npc_id": npc_id}
                )
                rows = result.fetchall()

            if not rows:
                return {
                    "conversations": [],
                    "summary_list": [],
                    "state": None,
                    "last_chat_at": None,
                }

            conversations = []
            for row in reversed(rows):
                if row.conversation:
                    conversations.append(row.conversation)

            latest_row = rows[0]
            summary_list = latest_row.summary_list if latest_row.summary_list else []
            state = latest_row.state if latest_row.state else None
            last_chat_at = (
                latest_row.last_chat_at.isoformat() if latest_row.last_chat_at else None
            )

            return {
                "conversations": conversations,
                "summary_list": summary_list,
                "state": state,
                "last_chat_at": last_chat_at,
            }

        except Exception as e:
            print(f"[ERROR] load_checkpoints 실패: {e}")
            return {
                "conversations": [],
                "summary_list": [],
                "state": None,
                "last_chat_at": None,
            }

    def get_last_chat_at(self, player_id: str, npc_id: int) -> Optional[str]:
        """마지막 대화 시간 조회

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID

        Returns:
            마지막 대화 시간 (ISO 형식) 또는 None
        """
        try:
            sql = text(
                """
                SELECT last_chat_at
                FROM session_checkpoints
                WHERE player_id = :player_id AND npc_id = :npc_id
                ORDER BY created_at DESC
                LIMIT 1
            """
            )

            with self.engine.connect() as conn:
                result = conn.execute(
                    sql, {"player_id": str(player_id), "npc_id": npc_id}
                )
                row = result.fetchone()

            if row and row.last_chat_at:
                return row.last_chat_at.isoformat()
            return None

        except Exception as e:
            print(f"[ERROR] get_last_chat_at 실패: {e}")
            return None


session_checkpoint_manager = SessionCheckpointManager()
