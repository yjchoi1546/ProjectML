"""NPC-NPC 장기기억 + 체크포인트 매니저

목표:
- npc_npc_checkpoints: NPC-NPC 대화 전체 기록
- npc_npc_memories: NPC-NPC 장기기억(핵심)

주의:
- (npcA, npcB) 쌍은 항상 (min,max)로 저장합니다.
- interrupted_turn 이후의 장기기억은 invalid_at으로 무효화합니다.
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from langchain_openai import OpenAIEmbeddings
from langchain.chat_models import init_chat_model

from db.config import CONNECTION_URL
from enums.LLM import LLM
from agents.npc.npc_constants import NPC_ID_TO_NAME_KR
from utils.langfuse_tracker import tracker


def _normalize_pair(npc_id_1: int, npc_id_2: int) -> Tuple[int, int]:
    """NPC ID 쌍을 정규화합니다 (작은 값, 큰 값 순서로 정렬).
    
    Args:
        npc_id_1: 첫 번째 NPC ID
        npc_id_2: 두 번째 NPC ID
    
    Returns:
        정규화된 (min_id, max_id) 튜플
    """
    if npc_id_1 < npc_id_2:
        return npc_id_1, npc_id_2
    return npc_id_2, npc_id_1


class NpcNpcMemoryManager:
    """NPC-NPC 저장/조회 담당 클래스"""

    def __init__(self, embedding_model: str = "text-embedding-3-small"):
        if not CONNECTION_URL:
            raise RuntimeError("DATABASE_URL이 비어있습니다 (.env 확인)")

        self.engine = create_engine(CONNECTION_URL, pool_pre_ping=True)
        self.embeddings = OpenAIEmbeddings(model=embedding_model)

        # 아주 단순한 fact 추출용 (필요 최소)
        self.extract_llm = init_chat_model(model=LLM.GPT5_MINI)

    # ============================================
    # 체크포인트 저장/조회
    # ============================================

    def save_checkpoint(
        self,
        player_id: str,
        npc1_id: int,
        npc2_id: int,
        situation: Optional[str],
        conversation: List[Dict[str, Any]],
    ) -> str:
        heroine_id_1, heroine_id_2 = _normalize_pair(npc1_id, npc2_id)
        checkpoint_id = str(uuid.uuid4())

        sql = text(
            """
            INSERT INTO npc_npc_checkpoints (
                id, player_id, heroine_id_1, heroine_id_2,
                situation, conversation, turn_count, interrupted_turn,
                created_at, updated_at, last_turn_at
            )
            VALUES (
                :id, :player_id, :heroine_id_1, :heroine_id_2,
                :situation, CAST(:conversation AS jsonb), :turn_count, NULL,
                NOW(), NOW(), NOW()
            )
            """
        )

        with self.engine.connect() as conn:
            conn.execute(
                sql,
                {
                    "id": checkpoint_id,
                    "player_id": str(player_id),
                    "heroine_id_1": heroine_id_1,
                    "heroine_id_2": heroine_id_2,
                    "situation": situation,
                    "conversation": json.dumps(conversation, ensure_ascii=False),
                    "turn_count": len(conversation),
                },
            )
            conn.commit()

        return checkpoint_id

    def get_checkpoints(
        self,
        player_id: str,
        npc1_id: Optional[int] = None,
        npc2_id: Optional[int] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        where_pair = ""
        params: Dict[str, Any] = {"player_id": str(player_id), "limit": int(limit)}

        if npc1_id is not None and npc2_id is not None:
            heroine_id_1, heroine_id_2 = _normalize_pair(npc1_id, npc2_id)
            where_pair = (
                "AND heroine_id_1 = :heroine_id_1 AND heroine_id_2 = :heroine_id_2"
            )
            params["heroine_id_1"] = heroine_id_1
            params["heroine_id_2"] = heroine_id_2

        sql = text(
            f"""
            SELECT id, player_id, heroine_id_1, heroine_id_2, situation,
                   conversation, turn_count, interrupted_turn, created_at
            FROM npc_npc_checkpoints
            WHERE player_id = :player_id
            {where_pair}
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )

        results: List[Dict[str, Any]] = []
        with self.engine.connect() as conn:
            for row in conn.execute(sql, params):
                results.append(
                    {
                        "id": str(row.id),
                        "player_id": row.player_id,
                        "heroine_id_1": row.heroine_id_1,
                        "heroine_id_2": row.heroine_id_2,
                        "situation": row.situation,
                        "conversation": row.conversation,
                        "turn_count": row.turn_count,
                        "interrupted_turn": row.interrupted_turn,
                        "created_at": (
                            row.created_at.isoformat() if row.created_at else None
                        ),
                    }
                )

        return results

    def truncate_checkpoint(
        self, checkpoint_id: str, interrupted_turn: int
    ) -> Optional[Dict[str, Any]]:
        # 1) 조회
        sql_select = text(
            """
            SELECT conversation
            FROM npc_npc_checkpoints
            WHERE id = :id
            """
        )

        with self.engine.connect() as conn:
            row = conn.execute(sql_select, {"id": checkpoint_id}).fetchone()
            if not row:
                return None

            conversation = row.conversation or []
            truncated = conversation[:interrupted_turn]

            sql_update = text(
                """
                UPDATE npc_npc_checkpoints
                SET conversation = CAST(:conversation AS jsonb),
                    turn_count = :turn_count,
                    interrupted_turn = :interrupted_turn,
                    last_turn_at = NOW()
                WHERE id = :id
                """
            )

            conn.execute(
                sql_update,
                {
                    "id": checkpoint_id,
                    "conversation": json.dumps(truncated, ensure_ascii=False),
                    "turn_count": len(truncated),
                    "interrupted_turn": int(interrupted_turn),
                },
            )
            conn.commit()

        return {
            "id": checkpoint_id,
            "conversation": truncated,
            "turn_count": len(truncated),
        }

    # ============================================
    # 장기기억 저장/조회
    # ============================================

    async def extract_facts(
        self,
        conversation: List[Dict[str, Any]],
        npc1_id: int,
        npc2_id: int,
    ) -> List[Dict[str, Any]]:
        """NPC-NPC 대화에서 장기기억으로 남길 fact를 추출합니다.

        Args:
            conversation: 대화 리스트 [{speaker_id, text}, ...]
            npc1_id: 첫 번째 NPC ID
            npc2_id: 두 번째 NPC ID

        Returns:
            추출된 fact 리스트
        """
        # 대화 텍스트로 변환
        name1 = NPC_ID_TO_NAME_KR.get(npc1_id, f"NPC_{npc1_id}")
        name2 = NPC_ID_TO_NAME_KR.get(npc2_id, f"NPC_{npc2_id}")

        conversation_text = ""
        for msg in conversation:
            speaker_id = msg.get("speaker_id")
            text = msg.get("text", "")
            speaker_name = NPC_ID_TO_NAME_KR.get(speaker_id, f"NPC_{speaker_id}")
            conversation_text += f"{speaker_name}: {text}\n"

        prompt = f"""다음은 NPC 두 명의 대화입니다.

[대화]
{conversation_text}

[NPC 정보]
- NPC_A: {name1} (ID: {npc1_id})
- NPC_B: {name2} (ID: {npc2_id})

[추출 기준]
- NPC간 관계 변화 (친해짐, 갈등 등)
- 중요한 정보 공유 (비밀, 과거 이야기)
- 세계관에 대한 새로운 정보
- 다른 NPC나 플레이어에 대한 평가
- 사소한 잡담은 제외

[speaker_id 값]
- {npc1_id}: {name1}가 말한 내용
- {npc2_id}: {name2}가 말한 내용

[subject_id 값]
- {npc1_id}: {name1}에 대한 사실
- {npc2_id}: {name2}에 대한 사실
- 0: 세계관에 대한 사실

[content_type 값]
- "preference": 선호도
- "trait": 특성
- "event": 이벤트/경험
- "opinion": 평가/의견
- "personal": 개인정보

[중요도 기준]
- 1-3: 사소한 정보
- 4-6: 일반적인 정보
- 7-8: 중요한 정보
- 9-10: 매우 중요한 정보

JSON 배열로 응답하세요. 저장할 사실이 없으면 빈 배열 []을 반환하세요.
예시:
[
    {{"speaker_id": {npc1_id}, "subject_id": {npc2_id}, "content_type": "opinion", "content": "{name2}를 믿을 수 있다고 생각함", "importance": 7}},
    {{"speaker_id": {npc2_id}, "subject_id": 0, "content_type": "event", "content": "과거 전쟁에 대해 이야기함", "importance": 6}}
]"""

        # LangFuse 토큰 추적 (v3 API)
        config = tracker.get_langfuse_config(
            tags=["memory", "npc_npc_fact_extraction"],
            metadata={
                "npc1_id": npc1_id,
                "npc2_id": npc2_id,
                "conversation_length": len(conversation)
            }
        )
        
        resp = await self.extract_llm.ainvoke(prompt, **config)
        content = resp.content

        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            data = json.loads(content.strip())
        except Exception:
            print("[WARN] extract_facts JSON 파싱 실패")
            data = []

        facts: List[Dict[str, Any]] = []
        for item in data:
            fact_content = item.get("content")
            if not fact_content:
                continue
            speaker_id = item.get("speaker_id")
            subject_id = item.get("subject_id")
            content_type = item.get("content_type", "event")
            importance = item.get("importance", 5)
            if not isinstance(importance, int):
                importance = 5
            facts.append(
                {
                    "speaker_id": speaker_id,
                    "subject_id": subject_id,
                    "content_type": content_type,
                    "content": fact_content,
                    "importance": importance,
                }
            )

        return facts

    async def save_conversation(
        self,
        player_id: str,
        npc1_id: int,
        npc2_id: int,
        checkpoint_id: str,
        situation: Optional[str],
        conversation: List[Dict[str, Any]],
    ) -> int:
        """대화를 분석하여 중요 fact만 추출 후 저장

        Args:
            player_id: 플레이어 ID
            npc1_id: 첫 번째 NPC ID
            npc2_id: 두 번째 NPC ID
            checkpoint_id: 체크포인트 ID
            situation: 대화 상황
            conversation: 대화 리스트

        Returns:
            저장된 fact 개수
        """
        heroine_id_1, heroine_id_2 = _normalize_pair(npc1_id, npc2_id)

        # 1. LLM으로 중요 fact 추출
        facts = await self.extract_facts(conversation, npc1_id, npc2_id)

        if not facts:
            return 0

        # 2. 각 fact를 DB에 저장
        inserted = 0
        with self.engine.connect() as conn:
            for idx, fact in enumerate(facts):
                speaker_id = fact.get("speaker_id")
                subject_id = fact.get("subject_id")
                content = fact.get("content")
                content_type = fact.get("content_type", "event")
                importance = fact.get("importance", 5)

                if speaker_id is None or content is None:
                    continue

                embed = self.embeddings.embed_query(str(content))

                sql_insert = text(
                    """
                    INSERT INTO npc_npc_memories (
                        conversation_id, turn_index,
                        player_id, heroine_id_1, heroine_id_2,
                        speaker_id, subject_id,
                        content, content_type,
                        embedding, importance,
                        created_at,
                        metadata
                    )
                    VALUES (
                        :conversation_id, :turn_index,
                        :player_id, :heroine_id_1, :heroine_id_2,
                        :speaker_id, :subject_id,
                        :content, :content_type,
                        CAST(:embedding AS vector), :importance,
                        NOW(),
                        CAST(:metadata AS jsonb)
                    )
                    """
                )

                conn.execute(
                    sql_insert,
                    {
                        "conversation_id": checkpoint_id,
                        "turn_index": idx + 1,
                        "player_id": str(player_id),
                        "heroine_id_1": heroine_id_1,
                        "heroine_id_2": heroine_id_2,
                        "speaker_id": int(speaker_id),
                        "subject_id": int(subject_id) if subject_id else 0,
                        "content": str(content),
                        "content_type": content_type,
                        "embedding": str(embed),
                        "importance": importance,
                        "metadata": json.dumps(
                            {"situation": situation}, ensure_ascii=False
                        ),
                    },
                )
                inserted += 1

            conn.commit()

        return inserted

    def save_turn_memories(
        self,
        player_id: str,
        npc1_id: int,
        npc2_id: int,
        checkpoint_id: str,
        situation: Optional[str],
        conversation: List[Dict[str, Any]],
    ) -> int:
        """턴 단위로 장기기억을 저장합니다(가장 단순한 형태).

        성능 최적화:
        - 배치 임베딩 API 사용 (N번 호출 → 1번 호출)

        Args:
            player_id: 플레이어 ID
            npc1_id: 첫 번째 NPC ID
            npc2_id: 두 번째 NPC ID
            checkpoint_id: 체크포인트 ID
            situation: 대화 상황
            conversation: 대화 리스트

        Returns:
            저장된 기억 개수
        """
        heroine_id_1, heroine_id_2 = _normalize_pair(npc1_id, npc2_id)

        # 1. 유효한 메시지만 필터링 및 전처리
        valid_messages = []
        for idx, msg in enumerate(conversation):
            speaker_id = msg.get("speaker_id")
            text_content = msg.get("text")
            
            if speaker_id is None or not text_content:
                continue
            
            try:
                speaker_int = int(speaker_id)
            except (TypeError, ValueError):
                print(
                    f"[WARN] npc_npc_memories 저장 스킵: speaker_id 변환 실패 "
                    f"(speaker_id={speaker_id}, pair=({heroine_id_1},{heroine_id_2}), turn={idx + 1})"
                )
                continue

            # subject_id 계산
            if speaker_int == int(heroine_id_1):
                subject_id = int(heroine_id_2)
            elif speaker_int == int(heroine_id_2):
                subject_id = int(heroine_id_1)
            else:
                print(
                    f"[WARN] npc_npc_memories 저장 스킵: speaker_id가 pair에 없음 "
                    f"(speaker_id={speaker_int}, pair=({heroine_id_1},{heroine_id_2}), turn={idx + 1})"
                )
                continue

            valid_messages.append({
                "idx": idx,
                "speaker_id": speaker_int,
                "subject_id": subject_id,
                "text": str(text_content),
            })

        if not valid_messages:
            return 0

        # 2. 배치 임베딩 생성 (한 번의 API 호출)
        texts = [msg["text"] for msg in valid_messages]
        embeddings = self.embeddings.embed_documents(texts)

        # 3. DB에 일괄 저장
        inserted = 0
        with self.engine.connect() as conn:
            for msg, embed in zip(valid_messages, embeddings):
                sql_insert = text(
                    """
                    INSERT INTO npc_npc_memories (
                        conversation_id, turn_index,
                        player_id, heroine_id_1, heroine_id_2,
                        speaker_id, subject_id,
                        content, content_type,
                        embedding, importance,
                        created_at,
                        metadata
                    )
                    VALUES (
                        :conversation_id, :turn_index,
                        :player_id, :heroine_id_1, :heroine_id_2,
                        :speaker_id, :subject_id,
                        :content, :content_type,
                        CAST(:embedding AS vector), :importance,
                        NOW(),
                        CAST(:metadata AS jsonb)
                    )
                    """
                )

                conn.execute(
                    sql_insert,
                    {
                        "conversation_id": checkpoint_id,
                        "turn_index": msg["idx"] + 1,
                        "player_id": str(player_id),
                        "heroine_id_1": heroine_id_1,
                        "heroine_id_2": heroine_id_2,
                        "speaker_id": msg["speaker_id"],
                        "subject_id": msg["subject_id"],
                        "content": msg["text"],
                        "content_type": "turn",
                        "embedding": str(embed),
                        "importance": 5,
                        "metadata": json.dumps(
                            {"situation": situation}, ensure_ascii=False
                        ),
                    },
                )
                inserted += 1

            conn.commit()

        return inserted

    def invalidate_memories_after_turn(
        self, checkpoint_id: str, interrupted_turn: int
    ) -> int:
        sql = text(
            """
            UPDATE npc_npc_memories
            SET invalid_at = NOW(), updated_at = NOW()
            WHERE conversation_id = :conversation_id
              AND turn_index > :interrupted_turn
              AND invalid_at IS NULL
            """
        )

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "conversation_id": checkpoint_id,
                    "interrupted_turn": int(interrupted_turn),
                },
            )
            conn.commit()

        return result.rowcount

    def get_latest_checkpoint_conversation(
        self,
        player_id: str,
        npc1_id: int,
        npc2_id: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """가장 최신 NPC-NPC 대화(conversation)를 가져옵니다.

        Args:
            player_id: 플레이어 ID
            npc1_id: 첫 번째 NPC ID
            npc2_id: 두 번째 NPC ID

        Returns:
            대화 리스트 또는 None
        """
        heroine_id_1, heroine_id_2 = _normalize_pair(npc1_id, npc2_id)

        sql = text(
            """
            SELECT conversation
            FROM npc_npc_checkpoints
            WHERE player_id = :player_id
              AND heroine_id_1 = :heroine_id_1
              AND heroine_id_2 = :heroine_id_2
            ORDER BY created_at DESC
            LIMIT 1
            """
        )

        with self.engine.connect() as conn:
            row = conn.execute(
                sql,
                {
                    "player_id": str(player_id),
                    "heroine_id_1": heroine_id_1,
                    "heroine_id_2": heroine_id_2,
                },
            ).fetchone()

            if row and row.conversation:
                return row.conversation

        return None

    def search_memories(
        self,
        player_id: str,
        npc1_id: int,
        npc2_id: int,
        query: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        heroine_id_1, heroine_id_2 = _normalize_pair(npc1_id, npc2_id)
        query_embedding = self.embeddings.embed_query(query)

        sql = text(
            """
            SELECT * FROM search_npc_npc_memories_hybrid(
                :player_id,
                :heroine_id_1,
                :heroine_id_2,
                :query_text,
                CAST(:query_embedding AS vector),
                :top_k
            )
            """
        )

        results: List[Dict[str, Any]] = []
        with self.engine.connect() as conn:
            for row in conn.execute(
                sql,
                {
                    "player_id": str(player_id),
                    "heroine_id_1": heroine_id_1,
                    "heroine_id_2": heroine_id_2,
                    "query_text": query,
                    "query_embedding": str(query_embedding),
                    "top_k": int(limit),
                },
            ):
                results.append(
                    {
                        "id": str(row.id),
                        "content": row.content,
                        "score": float(row.final_score),
                        "speaker_id": row.speaker_id,
                        "subject_id": row.subject_id,
                        "turn_index": row.turn_index,
                    }
                )

        return results


npc_npc_memory_manager = NpcNpcMemoryManager()
