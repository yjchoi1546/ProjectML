"""
User-NPC 장기 기억 매니저

Mem0를 대체하는 직접 구현
PostgreSQL + pgvector + PGroonga 기반 4요소 하이브리드 검색

사용 예시:
    # 대화 후 기억 저장
    await user_memory_manager.save_conversation(
        player_id="10001",
        heroine_id="letia",
        user_message="나는 고양이 좋아해",
        npc_response="저도 고양이 좋아해요"
    )

    # 기억 검색
    memories = await user_memory_manager.search_memories(
        player_id="10001",
        heroine_id="letia",
        query="고양이"
    )
"""

import json
import uuid
import logging
from typing import List, Optional
from datetime import datetime
from sqlalchemy import create_engine, text
from langchain_openai import OpenAIEmbeddings
from langchain.chat_models import init_chat_model
from dotenv import load_dotenv
from enums.LLM import LLM

load_dotenv()

# 로거 설정
logger = logging.getLogger("user_memory")

from db.config import CONNECTION_URL
from utils.langfuse_tracker import tracker
from db.user_memory_models import (
    Speaker,
    Subject,
    ContentType,
    ExtractedFact,
    SearchWeights,
    UserMemory,
    NPC_ID_TO_HEROINE,
    HEROINE_TO_SPEAKER,
)


class UserMemoryManager:
    """User-NPC 장기 기억 매니저

    Mem0를 대체하여 직접 PostgreSQL에 기억을 저장하고 검색합니다.

    주요 기능:
    1. LLM으로 대화에서 fact 추출
    2. 중복/충돌 검사 후 저장
    3. 4요소 하이브리드 검색 (최신도, 중요도, 관련도, 키워드)
    """

    def __init__(self, embedding_model: str = "text-embedding-3-small"):
        """초기화

        Args:
            embedding_model: OpenAI 임베딩 모델명
        """
        # DB 연결
        self.engine = create_engine(CONNECTION_URL, pool_pre_ping=True)

        # 임베딩 모델
        self.embeddings = OpenAIEmbeddings(model=embedding_model)

        # Fact 추출용 LLM (temperature=0으로 일관된 추출)
        self.extract_llm = init_chat_model(model=LLM.GPT5_MINI)

        # 기본 검색 가중치
        self.default_weights = SearchWeights()

        # 중복 판정 임계값 (90% 유사도 이상이면 중복)
        self.duplicate_threshold = 0.9

    # ============================================
    # Fact 추출
    # ============================================

    async def extract_facts(
        self, conversation: str, heroine_id: str
    ) -> List[ExtractedFact]:
        """대화에서 장기 기억할 fact 추출

        LLM을 사용하여 대화에서 중요한 사실을 추출합니다.

        Args:
            conversation: 대화 내용 (예: "플레이어: 고양이 좋아해\n레티아: 저도요")
            heroine_id: 히로인 ID (letia, lupames, roco)

        Returns:
            추출된 ExtractedFact 리스트
        """
        prompt = f"""You are an expert Memory Manager for an AI heroine.
Your goal is to extract key facts from the conversation to be stored in the long-term memory database.

[Conversation]
{conversation}

[Heroine ID]
{heroine_id}

[Extraction Rules]
1. **Analyze**: Identify important facts based on the [Criteria] below.
2. **Content Generation**: Convert the fact into a clear, standalone natural language sentence (Subject + Predicate + Object).
3. **Keyword Extraction (CRITICAL)**:
   - Extract **5 to 8** essential keywords for search optimization.
   - **Broader Category**: You MUST infer the broader category for objects or concepts.
     - Concrete: "Grape" -> Add "Fruit", "Food"
     - Abstract: "Warm-hearted" -> Add "Personality", "Evaluation"
   - **Optimization**: Exclude common stopwords (is, the) and vague words (thing, stuff). Focus on nouns and core adjectives.
4. **Player Name Extraction (IMPORTANT)**:
   - If the player reveals their name, extract it into the `player_name` field.
   - Examples: "I'm Minsu", "Call me Minsu", "My name is Kim Minsu", "나 민수야", "민수라고 불러"
   - Extract ONLY the name itself, not the full sentence.

[Extraction Criteria & Content Types - ONLY THESE 5 TYPES]
- "preference": Likes/Dislikes (e.g., Food, Color, Hobbies).
- "trait": Personality, Appearance, Habits.
- "event": Shared experiences or specific actions taken.
- "opinion": Evaluation of others/situations (e.g., "Thinks user is kind").
- "personal": Biographical info (Name, Job, Age).

[DO NOT EXTRACT - EXCLUDED TYPE]
- "world": World-building, lore, scenario information about the heroine's world. This is pre-defined content, NOT user memory.

[Importance Scale - BE STRICTLY OBJECTIVE]
- 1-4: Trivial/Low value (DO NOT SAVE - greetings, small talk, filler, vague statements).
- 5-6: General but meaningful information (worth saving).
- 7-8: Important information.
- 9-10: Critical (Trauma, Secrets, Core relationship changes).

IMPORTANT: Do NOT inflate importance scores just to save something.
If nothing meaningful is said, return an empty array.
Most casual conversations should result in [].

[CRITICAL - When NOT to Save]
Return an EMPTY array [] in these cases:
- Simple greetings: "Hi", "Hello", "Good morning", "안녕", "반가워"
- Small talk with no substance: "How are you?", "What are you doing?"
- Filler responses: "Okay", "I see", "Hmm", "알겠어", "그렇구나"
- Repeated information already known
- Vague statements with no concrete facts
- Any world/lore/scenario information (heroine's backstory, world setting, etc.)
- Conversations that reveal NO new personal facts about the user

[Output Format - JSON Array]
Return a JSON array of **0 to 2** objects.
- Only extract facts with importance >= 5.
- Only use types: preference, trait, event, opinion, personal.
- Do NOT force extraction. Quality over quantity.
- It is NORMAL and EXPECTED to return [] for most casual conversations.

Example 1 (Concrete - Preference):
Input: "I've been really into grapes lately."
Output:
[
  {{
    "speaker": "user",
    "subject": "user",
    "content_type": "preference",
    "content": "멘토는 요즘 포도를 매우 좋아한다.",
    "importance": 6,
    "keywords": ["나", "멘토", "포도", "좋아함", "선호", "과일", "음식", "식성"],
    "player_name": null
  }}
]

Example 2 (Abstract - Opinion):
Input: (Heroine) "You have such a warm heart."
Output:
[
  {{
    "speaker": "{heroine_id}",
    "subject": "user",
    "content_type": "opinion",
    "content": "히로인은 멘토가 따뜻한 마음을 가졌다고 생각한다.",
    "importance": 7,
    "keywords": ["히로인", "멘토", "따뜻함", "다정함", "성격", "평가", "인성"],
    "player_name": null
  }}
]

Example 3 (Player Name):
Input: "My name is Minsu" or "나 민수야" or "민수라고 불러"
Output:
[
  {{
    "speaker": "user",
    "subject": "user",
    "content_type": "personal",
    "content": "멘토의 이름은 민수이다.",
    "importance": 8,
    "keywords": ["이름", "멘토", "민수", "개인정보"],
    "player_name": "민수"
  }}
]
"""

        # LangFuse 토큰 추적 (v3 API)
        config = tracker.get_langfuse_config(
            tags=["memory", "fact_extraction", f"heroine:{heroine_id}"],
            metadata={
                "heroine_id": heroine_id,
                "conversation_length": len(conversation)
            }
        )
        
        response = await self.extract_llm.ainvoke(prompt, **config)

        # JSON 파싱
        try:
            content = response.content.strip()
            # 코드 블록 제거
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            facts_data = json.loads(content.strip())
            
            # 로그: LLM 응답 결과 요약
            logger.info(f"[MEMORY] ===== Fact Extraction Result =====")
            logger.info(f"[MEMORY] Conversation: {conversation[:100]}...")
            logger.info(f"[MEMORY] LLM returned {len(facts_data)} fact(s)")
            
            # 빈 배열인 경우 명시적 로그
            if not facts_data:
                logger.info(f"[MEMORY] EMPTY ARRAY returned - No meaningful facts to save")
                logger.info(f"[MEMORY] Reason: Conversation likely contains only greetings/small talk/trivial content")
                return []

            # ExtractedFact 객체로 변환 (2차 안전장치 필터링 포함)
            facts = []
            filtered_count = 0
            
            for idx, item in enumerate(facts_data):
                importance = item.get("importance", 5)
                content_type = item.get("content_type", "")
                fact_content = item.get("content", "")[:80]
                
                logger.debug(f"[MEMORY] Processing fact #{idx+1}: type={content_type}, importance={importance}")
                logger.debug(f"[MEMORY]   Content: {fact_content}")
                
                # 2차 안전장치: importance < 5 필터링
                if importance < 5:
                    logger.info(f"[MEMORY] FILTERED (importance={importance} < 5): {fact_content}")
                    filtered_count += 1
                    continue
                
                # 2차 안전장치: world 타입 필터링 (히로인 세계관/시나리오 정보 제외)
                if content_type == "world":
                    logger.info(f"[MEMORY] FILTERED (type=world, not user memory): {fact_content}")
                    filtered_count += 1
                    continue
                
                # 저장 대상 fact 로그
                logger.info(f"[MEMORY] ACCEPTED: type={content_type}, importance={importance}, content={fact_content}")
                
                keywords = item.get("keywords", []) or []
                player_name = item.get("player_name")
                fact = ExtractedFact(
                    speaker=Speaker(item["speaker"]),
                    subject=Subject(item["subject"]),
                    content_type=ContentType(content_type),
                    content=item["content"],
                    importance=importance,
                    keywords=keywords,
                    player_name=player_name,
                )
                facts.append(fact)

            # 최종 결과 로그
            logger.info(f"[MEMORY] ===== Extraction Summary =====")
            logger.info(f"[MEMORY] Total from LLM: {len(facts_data)}, Filtered: {filtered_count}, To Save: {len(facts)}")
            if not facts:
                logger.info(f"[MEMORY] RESULT: Nothing to save after filtering")
            else:
                logger.info(f"[MEMORY] RESULT: {len(facts)} fact(s) will be saved")
            
            return facts

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"[MEMORY] Fact extraction parsing failed: {e}")
            logger.error(f"[MEMORY] Raw response: {response.content[:200] if response.content else 'None'}")
            return []

    # ============================================
    # 기억 저장
    # ============================================

    async def add_memory(
        self, player_id: str, heroine_id: str, fact: ExtractedFact
    ) -> dict:
        """단일 fact 저장 (중복/충돌 처리 포함)

        하이브리드 충돌 감지:
        1. 90% 유사도: 완전 중복으로 바로 무효화
        2. 65% 유사도 + 같은 content_type: LLM으로 충돌 판단

        Args:
            player_id: 플레이어 ID
            heroine_id: 히로인 ID
            fact: 저장할 fact

        Returns:
            dict: {
                "memory_id": 생성된 메모리 ID,
                "invalidated": 무효화된 기억 리스트 [{"content": ..., "created_at": ...}]
            }
        """
        # 1. 임베딩 생성 (content + keywords)
        text_to_embed = self._combine_content_with_keywords(fact.content, fact.keywords)
        embedding = self.embeddings.embed_query(text_to_embed)
        print(
            "[MemorySave]",
            f"player={player_id}",
            f"heroine={heroine_id}",
            f"speaker={fact.speaker.value}",
            f"subject={fact.subject.value}",
            f"content={fact.content}",
            f"keywords={fact.keywords}",
            f"embed_input={text_to_embed}",
        )

        # 무효화된 기억 정보 수집
        invalidated = []

        # 2. 완전 중복 검사 (90% 유사도)
        similar = await self._find_similar_memory(player_id, heroine_id, embedding)

        if similar:
            await self._invalidate_memory(similar["id"])
            invalidated.append({"content": similar["content"]})
            print(f"[INFO] 완전 중복 무효화: {similar['content'][:50]}...")
        else:
            # 3. 충돌 후보 검색 (65% 유사도 + 같은 content_type)
            candidates = await self._find_conflict_candidates(
                player_id, heroine_id, embedding, fact.content_type.value
            )

            # 4. LLM으로 충돌 판단
            for candidate in candidates:
                is_conflict = await self._check_conflict_with_llm(
                    fact.content, candidate["content"]
                )
                if is_conflict:
                    await self._invalidate_memory(candidate["id"])
                    invalidated.append({"content": candidate["content"]})
                    print(
                        f"[INFO] 취향 변경 감지, 기존 무효화: {candidate['content'][:50]}..."
                    )

        # 5. 새 기억 저장
        memory_id = str(uuid.uuid4())

        sql = text(
            """
            INSERT INTO user_memories 
            (id, player_id, heroine_id, speaker, subject, content, keywords, content_type, embedding, importance)
            VALUES (:id, :player_id, :heroine_id, :speaker, :subject, :content, :keywords, :content_type, 
                    CAST(:embedding AS vector), :importance)
            RETURNING id
        """
        )

        with self.engine.connect() as conn:
            conn.execute(
                sql,
                {
                    "id": memory_id,
                    "player_id": player_id,
                    "heroine_id": heroine_id,
                    "speaker": fact.speaker.value,
                    "subject": fact.subject.value,
                    "content": fact.content,
                    "keywords": fact.keywords,
                    "content_type": fact.content_type.value,
                    "embedding": str(embedding),
                    "importance": fact.importance,
                },
            )
            conn.commit()

        return {"memory_id": memory_id, "invalidated": invalidated}

    def _extract_player_name(self, fact: ExtractedFact) -> Optional[str]:
        """ExtractedFact에서 플레이어 이름 추출

        LLM이 fact 추출 시 player_name 필드에 직접 이름을 추출합니다.

        Args:
            fact: ExtractedFact 객체

        Returns:
            추출된 이름 또는 None
        """
        return fact.player_name

    async def save_conversation(
        self, player_id: str, heroine_id: str, user_message: str, npc_response: str
    ) -> dict:
        """대화를 분석하여 fact 추출 후 저장

        Mem0의 add_memory를 대체하는 메인 메서드

        Args:
            player_id: 플레이어 ID
            heroine_id: 히로인 ID
            user_message: 플레이어 메시지
            npc_response: NPC 응답

        Returns:
            dict: {
                "memory_ids": 저장된 메모리 ID 리스트,
                "preference_changes": 취향 변화 리스트 [{"old": ..., "new": ...}],
                "extracted_player_name": 추출된 플레이어 이름 또는 None
            }
        """
        logger.info(f"[MEMORY] ========== SAVE CONVERSATION START ==========")
        logger.info(f"[MEMORY] Player: {player_id}, Heroine: {heroine_id}")
        logger.info(f"[MEMORY] User: {user_message[:100]}{'...' if len(user_message) > 100 else ''}")
        logger.info(f"[MEMORY] NPC: {npc_response[:100]}{'...' if len(npc_response) > 100 else ''}")
        
        # 대화 포맷
        conversation = f"플레이어: {user_message}\n{heroine_id}: {npc_response}"

        # Fact 추출
        facts = await self.extract_facts(conversation, heroine_id)
        facts = facts[:2]

        if not facts:
            logger.info(f"[MEMORY] FINAL RESULT: No facts to save - skipping DB insert")
            logger.info(f"[MEMORY] ========== SAVE CONVERSATION END (0 saved) ==========")
            return {"memory_ids": [], "preference_changes": [], "extracted_player_name": None}

        # 각 fact 저장
        memory_ids = []
        preference_changes = []
        extracted_player_name = None

        for idx, fact in enumerate(facts):
            logger.info(f"[MEMORY] Saving fact #{idx+1} to DB...")
            result = await self.add_memory(player_id, heroine_id, fact)
            if result["memory_id"]:
                memory_ids.append(result["memory_id"])
                logger.info(f"[MEMORY] Saved with ID: {result['memory_id']}")

            # 무효화된 기억이 있으면 취향 변화로 기록
            for inv in result["invalidated"]:
                preference_changes.append({"old": inv["content"], "new": fact.content})
                logger.info(f"[MEMORY] Preference changed: '{inv['content'][:50]}' -> '{fact.content[:50]}'")

            # 이름 추출 시도
            if extracted_player_name is None:
                name = self._extract_player_name(fact)
                if name:
                    extracted_player_name = name
                    logger.info(f"[MEMORY] Player name extracted: {name}")

        logger.info(f"[MEMORY] FINAL RESULT: {len(memory_ids)} fact(s) saved to user_memories")
        logger.info(f"[MEMORY] ========== SAVE CONVERSATION END ({len(memory_ids)} saved) ==========")
        
        return {
            "memory_ids": memory_ids,
            "preference_changes": preference_changes,
            "extracted_player_name": extracted_player_name,
        }

    # ============================================
    # 기억 검색
    # ============================================

    async def search_memories(
        self,
        player_id: str,
        heroine_id: str,
        query: str,
        limit: int = 5,
        weights: SearchWeights = None,
    ) -> List[UserMemory]:
        """4요소 하이브리드 검색

        Mem0의 search_memory를 대체하는 메인 검색 메서드

        Args:
            player_id: 플레이어 ID
            heroine_id: 히로인 ID
            query: 검색어
            limit: 최대 결과 수
            weights: 검색 가중치 (None이면 기본값)

        Returns:
            UserMemory 리스트 (점수 높은 순)
        """
        weights = weights or self.default_weights

        # 검색어 임베딩
        query_embedding = self.embeddings.embed_query(query)

        # DB 검색 함수 호출
        sql = text(
            """
            SELECT * FROM search_user_memories_hybrid(
                :player_id,
                :heroine_id,
                :query_text,
                CAST(:query_embedding AS vector),
                :top_k,
                :w_recency,
                :w_importance,
                :w_relevance,
                :w_keyword
            )
        """
        )

        memories = []

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "player_id": player_id,
                    "heroine_id": heroine_id,
                    "query_text": query,
                    "query_embedding": str(query_embedding),
                    "top_k": limit,
                    "w_recency": weights.recency,
                    "w_importance": weights.importance,
                    "w_relevance": weights.relevance,
                    "w_keyword": weights.keyword,
                },
            )

            for row in result:
                memory = UserMemory(
                    id=str(row.id),
                    player_id=row.player_id,
                    heroine_id=row.heroine_id,
                    speaker=row.speaker,
                    subject=row.subject,
                    content=row.content,
                    content_type=row.content_type,
                    importance=row.importance,
                    created_at=row.created_at,
                    recency_score=row.recency_score,
                    importance_score=row.importance_score,
                    relevance_score=row.relevance_score,
                    keyword_score=row.keyword_score,
                    final_score=row.final_score,
                )
                memories.append(memory)

        return memories

    def search_memory_sync(
        self, player_id: str, npc_id: int, query: str, limit: int = 5
    ) -> List[dict]:
        """동기 검색 (기존 Mem0 인터페이스 호환용)

        heroine_agent.py의 기존 코드와 호환되도록 dict 리스트 반환

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID (숫자)
            query: 검색어
            limit: 최대 결과 수

        Returns:
            기억 dict 리스트 (Mem0 형식 호환)
        """
        heroine_id = NPC_ID_TO_HEROINE.get(npc_id, "letia")

        # 검색어 임베딩
        query_embedding = self.embeddings.embed_query(query)

        sql = text(
            """
            SELECT * FROM search_user_memories_hybrid(
                :player_id,
                :heroine_id,
                :query_text,
                CAST(:query_embedding AS vector),
                :top_k,
                :w_recency,
                :w_importance,
                :w_relevance,
                :w_keyword
            )
        """
        )

        results = []

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "player_id": player_id,
                    "heroine_id": heroine_id,
                    "query_text": query,
                    "query_embedding": str(query_embedding),
                    "top_k": limit,
                    "w_recency": self.default_weights.recency,
                    "w_importance": self.default_weights.importance,
                    "w_relevance": self.default_weights.relevance,
                    "w_keyword": self.default_weights.keyword,
                },
            )

            for row in result:
                # Mem0 형식과 유사하게 반환
                results.append(
                    {
                        "memory": row.content,
                        "text": row.content,
                        "score": row.final_score,
                        "metadata": {
                            "speaker": row.speaker,
                            "subject": row.subject,
                            "content_type": row.content_type,
                        },
                    }
                )

        return results

    # ============================================
    # 내부 메서드
    # ============================================

    def _combine_content_with_keywords(self, content: str, keywords: List[str]) -> str:
        """임베딩 입력을 content와 키워드로 단순 결합"""
        if keywords:
            return f"{content} (Keywords: {', '.join(keywords)})"
        return content

    async def _find_similar_memory(
        self, player_id: str, heroine_id: str, embedding: list
    ) -> Optional[dict]:
        """유사 기억 검색 (중복 검사용)"""
        sql = text(
            """
            SELECT * FROM find_similar_memory(
                :player_id,
                :heroine_id,
                CAST(:embedding AS vector),
                :threshold
            )
        """
        )

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "player_id": player_id,
                    "heroine_id": heroine_id,
                    "embedding": str(embedding),
                    "threshold": self.duplicate_threshold,
                },
            )

            row = result.fetchone()
            # fetchone(): 1개 행 → Optional[Row] 반환
            # for문: 여러 행 순회 → 각 행을 처리
            if row:
                return {
                    "id": str(row.id),
                    "content": row.content,
                    "similarity": row.similarity,
                }

        return None

    async def _invalidate_memory(self, memory_id: str) -> None:
        """기억 무효화 (soft delete)"""
        sql = text("SELECT invalidate_memory(:memory_id)")

        with self.engine.connect() as conn:
            conn.execute(sql, {"memory_id": memory_id})
            conn.commit()

    async def _find_conflict_candidates(
        self, player_id: str, heroine_id: str, embedding: list, content_type: str
    ) -> List[dict]:
        """충돌 후보 검색 (하이브리드 취향 변경 감지용)

        임베딩 유사도 0.65 이상 + 같은 content_type인 기억들을 반환

        Args:
            player_id: 플레이어 ID
            heroine_id: 히로인 ID
            embedding: 새 fact의 임베딩
            content_type: 콘텐츠 타입 (preference, trait 등)

        Returns:
            충돌 후보 dict 리스트
        """
        sql = text(
            """
            SELECT * FROM find_conflict_candidates(
                :player_id,
                :heroine_id,
                CAST(:embedding AS vector),
                :content_type,
                :threshold
            )
        """
        )

        candidates = []

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "player_id": player_id,
                    "heroine_id": heroine_id,
                    "embedding": str(embedding),
                    "content_type": content_type,
                    "threshold": 0.55,
                },
            )

            for row in result:
                candidates.append(
                    {
                        "id": str(row.id),
                        "content": row.content,
                        "content_type": row.content_type,
                        "similarity": row.similarity,
                    }
                )

        return candidates

    async def _check_conflict_with_llm(
        self, new_content: str, existing_content: str
    ) -> bool:
        """LLM으로 두 기억이 충돌하는지 판단

        Args:
            new_content: 새로 저장하려는 기억
            existing_content: 기존에 저장된 기억

        Returns:
            True면 충돌 (기존 기억 무효화 필요)
        """
        prompt = f"""다음 두 기억이 충돌하거나 대체 관계인지 판단하세요.

[기존 기억]
{existing_content}

[새 기억]
{new_content}

[판단 기준]
- 같은 주제에 대해 취향/선호도가 바뀌었으면 충돌
- 새 기억이 기존 기억을 부정하거나 수정하면 충돌
- 서로 다른 주제면 충돌 아님
- 추가 정보면 충돌 아님

충돌이면 "yes", 아니면 "no"만 응답하세요."""

        # LangFuse 토큰 추적 (v3 API)
        config = tracker.get_langfuse_config(
            tags=["memory", "conflict_check"],
            metadata={"action": "conflict_detection"}
        )
        
        response = await self.extract_llm.ainvoke(prompt, **config)
        answer = response.content.strip().lower()

        return answer == "yes"

    async def detect_preference_change(
        self, player_id: str, heroine_id: str, user_message: str
    ) -> List[dict]:
        """응답 생성 전 취향 변화 선제 감지

        유저 메시지에서 preference fact를 추출하고,
        기존 기억과 충돌하는지 미리 검사합니다.

        Args:
            player_id: 플레이어 ID
            heroine_id: 히로인 ID
            user_message: 유저 메시지

        Returns:
            취향 변화 리스트 [{"old": 기존 취향, "new": 새 취향}]
        """
        # 1. 유저 메시지만으로 preference fact 추출
        conversation = f"플레이어: {user_message}"
        facts = await self.extract_facts(conversation, heroine_id)
        print(
            f"[DEBUG] 추출된 facts: {[(f.content, f.content_type.value) for f in facts]}"
        )

        # preference 타입만 필터링
        preference_facts = [f for f in facts if f.content_type.value == "preference"]
        print(f"[DEBUG] preference facts: {[f.content for f in preference_facts]}")

        if not preference_facts:
            return []

        preference_changes = []

        # 2. 각 fact에 대해 충돌 검사
        for fact in preference_facts:
            text_to_embed = self._combine_content_with_keywords(
                fact.content, fact.keywords
            )
            embedding = self.embeddings.embed_query(text_to_embed)

            # 충돌 후보 검색
            candidates = await self._find_conflict_candidates(
                player_id, heroine_id, embedding, "preference"
            )
            print(
                f"[DEBUG] 충돌 후보 {len(candidates)}개: {[c['content'] for c in candidates]}"
            )

            # LLM으로 충돌 판단
            for candidate in candidates:
                is_conflict = await self._check_conflict_with_llm(
                    fact.content, candidate["content"]
                )
                print(
                    f"[DEBUG] LLM 충돌 판단: {fact.content} vs {candidate['content']} -> {is_conflict}"
                )
                if is_conflict:
                    preference_changes.append(
                        {"old": candidate["content"], "new": fact.content}
                    )

        return preference_changes

    # ============================================
    # 유틸리티 메서드
    # ============================================

    def format_memories_for_prompt(self, memories: List[UserMemory]) -> str:
        """프롬프트용 문자열 포맷
        각 요소에 가중치를 곱해서 합산한 최종 점수
        단순 벡터 유사도가 아니라, 시간/중요도/의미/키워드를 모두 고려한 종합 점수

        Args:
            memories: UserMemory 리스트

        Returns:
            포맷된 문자열
        """
        if not memories:
            return "관련 기억 없음"

        lines = []
        for i, mem in enumerate(memories, 1):
            score_info = f"[점수: {mem.final_score:.2f}]" if mem.final_score > 0 else ""
            lines.append(f"{i}. {mem.content} {score_info}")

        return "\n".join(lines)

    def get_all_memories(self, player_id: str, npc_id: int) -> List[dict]:
        """모든 유효한 기억 조회 (Mem0 호환용)
        player_id와 npc_id를 받아서 DB에서 해당 세션의 모든 기억을 가져옴
        Mem0 라이브러리 호환을 위해 memory, text, metadata 형식으로 반환"""
        heroine_id = NPC_ID_TO_HEROINE.get(npc_id, "letia")

        sql = text(
            """
            SELECT id, content, speaker, subject, content_type, importance, created_at
            FROM user_memories
            WHERE player_id = :player_id
              AND heroine_id = :heroine_id
              AND invalid_at IS NULL
            ORDER BY created_at DESC
        """
        )

        results = []

        with self.engine.connect() as conn:
            result = conn.execute(
                sql, {"player_id": player_id, "heroine_id": heroine_id}
            )

            for row in result:
                results.append(
                    {
                        "id": str(row.id),
                        "memory": row.content,
                        "text": row.content,
                        "metadata": {
                            "speaker": row.speaker,
                            "subject": row.subject,
                            "content_type": row.content_type,
                            "importance": row.importance,
                        },
                    }
                )

        return results

    # ============================================
    # 시간 기반 기억 조회 메서드
    # ============================================

    def get_valid_memories_sync(
        self, player_id: str, npc_id: int, limit: int = 50
    ) -> List[dict]:
        """현재 유효한 기억만 조회

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID (숫자)
            limit: 최대 결과 수

        Returns:
            기억 dict 리스트
        """
        heroine_id = NPC_ID_TO_HEROINE.get(npc_id, "letia")

        sql = text(
            """
            SELECT * FROM get_valid_memories(:player_id, :heroine_id, :limit)
        """
        )

        results = []

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {"player_id": player_id, "heroine_id": heroine_id, "limit": limit},
            )

            for row in result:
                results.append(
                    {
                        "memory": row.content,
                        "text": row.content,
                        "metadata": {
                            "speaker": row.speaker,
                            "subject": row.subject,
                            "content_type": row.content_type,
                        },
                    }
                )

        return results

    def get_memories_at_point_sync(
        self, player_id: str, npc_id: int, point_in_time: datetime, limit: int = 50
    ) -> List[dict]:
        """특정 시점에 유효했던 기억 조회

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID (숫자)
            point_in_time: 조회 시점
            limit: 최대 결과 수

        Returns:
            기억 dict 리스트
        """
        heroine_id = NPC_ID_TO_HEROINE.get(npc_id, "letia")

        sql = text(
            """
            SELECT * FROM get_memories_at_point(:player_id, :heroine_id, :point_in_time, :limit)
        """
        )

        results = []

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "player_id": player_id,
                    "heroine_id": heroine_id,
                    "point_in_time": point_in_time,
                    "limit": limit,
                },
            )

            for row in result:
                results.append(
                    {
                        "memory": row.content,
                        "text": row.content,
                        "metadata": {
                            "speaker": row.speaker,
                            "subject": row.subject,
                            "content_type": row.content_type,
                        },
                    }
                )

        return results

    def get_recent_memories_sync(
        self, player_id: str, npc_id: int, days: int, limit: int = 50
    ) -> List[dict]:
        """최근 N일 동안 생성된 기억 조회

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID (숫자)
            days: 최근 N일
            limit: 최대 결과 수

        Returns:
            기억 dict 리스트
        """
        heroine_id = NPC_ID_TO_HEROINE.get(npc_id, "letia")

        sql = text(
            """
            SELECT * FROM get_recent_memories(:player_id, :heroine_id, :days, :limit)
        """
        )

        results = []

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "player_id": player_id,
                    "heroine_id": heroine_id,
                    "days": days,
                    "limit": limit,
                },
            )

            for row in result:
                results.append(
                    {
                        "memory": row.content,
                        "text": row.content,
                        "created_at": row.created_at,
                        "metadata": {
                            "speaker": row.speaker,
                            "subject": row.subject,
                            "content_type": row.content_type,
                        },
                    }
                )

        return results

    def get_memories_days_ago_sync(
        self, player_id: str, npc_id: int, days_ago: int, limit: int = 50
    ) -> List[dict]:
        """N일 전에 했던 이야기 조회

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID (숫자)
            days_ago: N일 전 (1=어제, 2=그제)
            limit: 최대 결과 수

        Returns:
            기억 dict 리스트
        """
        heroine_id = NPC_ID_TO_HEROINE.get(npc_id, "letia")

        sql = text(
            """
            SELECT * FROM get_memories_days_ago(:player_id, :heroine_id, :days_ago, :limit)
        """
        )

        results = []

        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "player_id": player_id,
                    "heroine_id": heroine_id,
                    "days_ago": days_ago,
                    "limit": limit,
                },
            )

            for row in result:
                results.append(
                    {
                        "memory": row.content,
                        "text": row.content,
                        "created_at": row.created_at,
                        "metadata": {
                            "speaker": row.speaker,
                            "subject": row.subject,
                            "content_type": row.content_type,
                        },
                    }
                )

        return results


# 싱글톤 인스턴스
user_memory_manager = UserMemoryManager()
