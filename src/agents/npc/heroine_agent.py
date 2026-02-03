"""
히로인 NPC Agent (리팩토링 버전)

기억을 잃은 3명의 히로인(레티아, 루파메스, 로코)과의 대화를 처리합니다.

주요 기능:
1. 호감도(affection), 정신력(sanity), 기억진척도(memoryProgress) 관리
2. 키워드 기반 호감도 변화 계산 (좋아하는것 +10, 트라우마 -10)
3. 의도 분류에 따른 컨텍스트 검색 (기억/시나리오)
4. 캐릭터 페르소나 기반 응답 생성

리팩토링:
- MemoryRetriever: 시간 키워드 기반 기억 검색, NPC-NPC 대화 검색
- NPCConversationManager: 대화 저장, 요약 생성
- HeroineIntentClassifier: 의도 분류
- HeroineScenarioRetriever: 시나리오 검색
- HeroinePromptBuilder: 프롬프트 생성

저장 위치:
- Redis: 세션 상태 (affection, sanity, memoryProgress, conversation_buffer)
- PostgreSQL (user_memories): User-NPC 장기 기억 (4요소 하이브리드 검색)
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from langchain.chat_models import init_chat_model
from langgraph.graph import START, END, StateGraph

from agents.npc.npc_state import HeroineState
from agents.npc.base_npc_agent import (
    BaseNPCAgent,
    calculate_memory_progress,
    calculate_affection_change,
    detect_memory_unlock,
    MAX_RECENT_KEYWORDS,
    MEMORY_UNLOCK_TTL_TURNS,
    NO_DATA,
)
from agents.npc.emotion_mapper import heroine_emotion_to_int
from agents.npc.npc_utils import parse_llm_json_response, load_persona_yaml

# 리팩토링된 컴포넌트들
from agents.npc.memory_retriever import MemoryRetriever
from agents.npc.npc_conversation_manager import NPCConversationManager
from agents.npc.heroine_intent_classifier import HeroineIntentClassifier
from agents.npc.heroine_scenario_retriever import HeroineScenarioRetriever
from agents.npc.heroine_prompt_builder import HeroinePromptBuilder

from db.redis_manager import redis_manager
from services.heroine_scenario_service import heroine_scenario_service
from enums.LLM import LLM
from utils.langfuse_tracker import tracker


# ============================================
# 페르소나 데이터 로드
# ============================================

def _get_default_heroine_persona() -> Dict[str, Any]:
    """기본 히로인 페르소나 데이터 (파일 없을 때 사용)"""
    return {
        "letia": {
            "name": "레티아",
            "personality": {"base": "차갑고 무뚝뚝하지만 속정이 깊음"},
            "speech_style": {"honorific": False},
            "affection_responses": {
                "low": {"description": "경계", "examples": ["...뭐야."]},
                "mid": {"description": "중립", "examples": ["흠..."]},
                "high": {"description": "친근", "examples": ["...고마워."]},
                "max": {"description": "애정", "examples": ["...바보."]},
            },
            "sanity_responses": {"zero": {"description": "우울", "examples": ["..."]}},
            "liked_keywords": ["검", "훈련", "강해지기"],
            "trauma_keywords": ["화재", "불", "가족"],
        }
    }


# 페르소나 데이터 로드 (모듈 로드시 1회)
PERSONA_DATA = load_persona_yaml("heroine_persona.yaml", _get_default_heroine_persona)
HEROINE_KEY_MAP = {1: "letia", 2: "lupames", 3: "roco"}


class HeroineAgent(BaseNPCAgent):
    """히로인 NPC Agent (리팩토링 버전)

    기억을 잃은 히로인과의 대화를 처리합니다.
    각 책임을 전문 컴포넌트에 위임하여 SRP를 준수합니다.

    사용 예시:
        agent = HeroineAgent()
        result = await agent.process_message(state)
    """

    def __init__(self, model_name: str = LLM.GROK_4_1_FAST_NON_REASONING):
        """초기화"""
        super().__init__(model_name)
        self.llm = init_chat_model(model=model_name, temperature=1, max_tokens=200)
        self.intent_llm = init_chat_model(model=model_name, temperature=0, max_tokens=20)

        # 공통 컴포넌트
        self.memory_retriever = MemoryRetriever()
        self.conversation_manager = NPCConversationManager()

        # 히로인 전용 컴포넌트
        self.intent_classifier = HeroineIntentClassifier(self.intent_llm)
        self.scenario_retriever = HeroineScenarioRetriever()
        self.prompt_builder = HeroinePromptBuilder(
            persona_data=PERSONA_DATA,
            world_context=PERSONA_DATA.get("world_context", {}),
        )

        # LangGraph 빌드
        self.graph = self._build_graph()

    # ============================================
    # 세션 관련 메서드
    # ============================================

    def _create_initial_session(self, player_id: int, npc_id: int) -> dict:
        """히로인 초기 세션 생성"""
        return {
            "player_id": player_id,
            "npc_id": npc_id,
            "npc_type": "heroine",
            "conversation_buffer": [],
            "short_term_summary": "",
            "recent_used_keywords": [],
            "recently_unlocked_memory": None,
            "state": {
                "affection": 0,
                "sanity": 100,
                "memoryProgress": 0,
                "emotion": "neutral",
            },
        }

    def _get_persona(self, heroine_id: int) -> Dict[str, Any]:
        """히로인 페르소나 가져오기"""
        key = HEROINE_KEY_MAP.get(heroine_id, "letia")
        return PERSONA_DATA.get(key, PERSONA_DATA.get("letia", {}))

    # ============================================
    # 키워드 분석
    # ============================================

    async def _analyze_keywords(self, state: HeroineState) -> Tuple[int, Optional[str]]:
        """키워드 분석 - 호감도 변화량 사전 계산"""
        user_message = state["messages"][-1].content
        npc_id = state["npc_id"]
        persona = self._get_persona(npc_id)

        affection = state.get("affection", 0)
        recent_used_keywords = state.get("recent_used_keywords", [])

        liked_keywords = persona.get("liked_keywords", [])
        trauma_keywords = persona.get("trauma_keywords", [])

        affection_delta, used_keyword = calculate_affection_change(
            current_affection=affection,
            liked_keywords=liked_keywords,
            trauma_keywords=trauma_keywords,
            user_message=user_message,
            recent_used_keywords=recent_used_keywords,
        )

        return affection_delta, used_keyword

    # ============================================
    # 검색 메서드 (컴포넌트 위임)
    # ============================================

    async def _retrieve_memory(self, state: HeroineState) -> str:
        """기억 검색 - MemoryRetriever 사용"""
        user_message = state["messages"][-1].content
        player_id = state["player_id"]
        npc_id = state["npc_id"]

        facts_parts = []

        # 1. 시간 키워드 기반 User Memory 검색 (비동기 4요소 하이브리드)
        user_memories = await self.memory_retriever.search_by_time_keyword(
            user_message, player_id, npc_id
        )

        if user_memories:
            facts_parts.append("[플레이어와의 기억]")
            for memory in user_memories:
                memory_text = memory.get("memory", memory.get("text", ""))
                # 개별 점수도 로그로 출력 (디버깅용)
                if "scores" in memory:
                    scores = memory["scores"]
                    print(f"[MEMORY_SCORE] {memory_text[:30]}... | "
                          f"rec={scores.get('recency', 0):.2f} "
                          f"imp={scores.get('importance', 0):.2f} "
                          f"rel={scores.get('relevance', 0):.2f} "
                          f"kw={scores.get('keyword', 0):.2f} "
                          f"final={scores.get('final', 0):.2f}")
                facts_parts.append(f"- {memory_text}")

        # 2. NPC-NPC 장기기억 검색
        npc_memories = self.memory_retriever.search_npc_npc_memories(
            user_message, player_id, npc_id
        )

        if npc_memories:
            facts_parts.append("\n[다른 히로인과의 대화 기억]")
            for memory in npc_memories:
                facts_parts.append(f"- {memory.get('content', '')}")

        return "\n".join(facts_parts) if facts_parts else "관련 기억 없음"

    async def _retrieve_scenario(self, state: HeroineState) -> str:
        """시나리오 검색 - HeroineScenarioRetriever 사용"""
        user_message = state["messages"][-1].content
        npc_id = state["npc_id"]
        memory_progress = state.get("memoryProgress", 0)
        recently_unlocked = state.get("recently_unlocked_memory")

        return await self.scenario_retriever.retrieve(
            user_message=user_message,
            npc_id=npc_id,
            memory_progress=memory_progress,
            recently_unlocked=recently_unlocked,
        )

    async def _retrieve_heroine_conversation(self, state: HeroineState) -> str:
        """다른 히로인과의 최근 대화 검색"""
        user_message = state["messages"][-1].content
        player_id = state["player_id"]
        npc_id = state["npc_id"]

        other_id = self.memory_retriever.detect_other_npc_id(user_message, npc_id)
        if other_id is None:
            return "관련 대화 없음"

        conversation = self.memory_retriever.get_latest_npc_conversation(
            player_id, npc_id, other_id
        )

        return self.memory_retriever.format_npc_conversation(conversation)

    # ============================================
    # 상태 업데이트
    # ============================================

    async def _update_state_after_response(
        self, state: HeroineState, context: Dict[str, Any],
        response_text: str, emotion_int: int = 0,
    ) -> Dict[str, Any]:
        """응답 후 상태 업데이트"""
        player_id = state["player_id"]
        npc_id = state["npc_id"]

        affection = state.get("affection", 0)
        sanity = state.get("sanity", 100)
        memory_progress = state.get("memoryProgress", 0)
        affection_delta = context.get("affection_delta", 0)
        sanity_delta = affection_delta

        # 새 값 계산
        new_affection = max(0, min(100, affection + affection_delta))
        new_sanity = max(0, min(100, sanity + sanity_delta))
        new_memory_progress = calculate_memory_progress(
            new_affection, memory_progress, affection_delta
        )

        # Redis 세션 업데이트
        session = redis_manager.load_session(player_id, npc_id)
        player_known_name = None

        if session:
            session["state"]["affection"] = new_affection
            session["state"]["sanity"] = new_sanity
            session["state"]["memoryProgress"] = new_memory_progress
            session["state"]["emotion"] = emotion_int

            if "player_known_name" in session.get("state", {}):
                player_known_name = session["state"]["player_known_name"]

            # 대화 버퍼 추가
            session["conversation_buffer"].append(
                {"role": "user", "content": state["messages"][-1].content}
            )
            session["conversation_buffer"].append(
                {"role": "assistant", "content": response_text}
            )

            # 키워드 업데이트
            used_keyword = context.get("used_liked_keyword")
            recent_keywords = session.get("recent_used_keywords", [])
            if used_keyword:
                recent_keywords.append(used_keyword)
            session["recent_used_keywords"] = recent_keywords[-MAX_RECENT_KEYWORDS:]

            # recently_unlocked_memory 관리
            recently_unlocked = context.get("recently_unlocked_memory")
            if recently_unlocked:
                session["recently_unlocked_memory"] = recently_unlocked
            elif "recently_unlocked_memory" in session:
                del session["recently_unlocked_memory"]

            # turn_count, last_chat_at 업데이트
            turn_count = session.get("turn_count", 0) + 1
            session["turn_count"] = turn_count
            session["last_chat_at"] = datetime.now().isoformat()

            # 요약 생성 조건 확인 (NPCConversationManager 사용)
            if self.conversation_manager.should_generate_summary(session):
                session = self.conversation_manager.reset_summary_tracking(session)
                conversations = self.conversation_manager.prepare_conversations_for_summary(
                    session["conversation_buffer"]
                )
                asyncio.create_task(
                    self.conversation_manager.generate_and_save_summary(
                        player_id, npc_id, conversations
                    )
                )

            redis_manager.save_session(player_id, npc_id, session)

        # User Memory 저장 (백그라운드)
        user_msg = state["messages"][-1].content
        asyncio.create_task(
            self.conversation_manager.save_to_user_memory_background(
                player_id, npc_id, user_msg, response_text
            )
        )

        return {
            "affection": new_affection,
            "sanity": new_sanity,
            "memoryProgress": new_memory_progress,
            "emotion": emotion_int,
            "response_text": response_text,
            "player_known_name": player_known_name,
        }

    # ============================================
    # LangGraph 빌드
    # ============================================

    def _build_graph(self) -> StateGraph:
        """LangGraph 빌드"""
        graph = StateGraph(HeroineState)

        graph.add_node("keyword_analyze", self._keyword_analyze_node)
        graph.add_node("router", self._router_node)
        graph.add_node("memory_retrieve", self._memory_retrieve_node)
        graph.add_node("scenario_retrieve", self._scenario_retrieve_node)
        graph.add_node("heroine_retrieve", self._heroine_retrieve_node)
        graph.add_node("generate", self._generate_node)
        graph.add_node("post_process", self._post_process_node)

        graph.add_edge(START, "keyword_analyze")
        graph.add_edge("keyword_analyze", "router")

        graph.add_conditional_edges(
            "router",
            self._route_by_intent,
            {
                "general": "generate",
                "memory_recall": "memory_retrieve",
                "scenario_inquiry": "scenario_retrieve",
                "heroine_recall": "heroine_retrieve",
            },
        )

        graph.add_edge("memory_retrieve", "generate")
        graph.add_edge("scenario_retrieve", "generate")
        graph.add_edge("heroine_retrieve", "generate")
        graph.add_edge("generate", "post_process")
        graph.add_edge("post_process", END)

        return graph.compile()

    # ============================================
    # LangGraph 노드
    # ============================================

    async def _keyword_analyze_node(self, state: HeroineState) -> dict:
        """키워드 분석 노드"""
        t = time.time()
        affection_delta, used_keyword = await self._analyze_keywords(state)
        print(f"[TIMING] 키워드 분석: {time.time() - t:.3f}s")

        # 기억 해금 감지
        newly_unlocked_scenario = None
        recently_unlocked_memory = None
        current_affection = state.get("affection", 0)
        current_memory_progress = state.get("memoryProgress", 0)
        npc_id = state["npc_id"]

        expected_new_affection = max(0, min(100, current_affection + affection_delta))
        expected_new_progress = calculate_memory_progress(
            expected_new_affection, current_memory_progress, affection_delta
        )

        unlocked_threshold = detect_memory_unlock(
            current_memory_progress, expected_new_progress
        )

        if unlocked_threshold is not None:
            scenario = heroine_scenario_service.get_scenario_by_exact_progress(
                heroine_id=npc_id, memory_progress=unlocked_threshold
            )
            if scenario:
                newly_unlocked_scenario = scenario.get("content", "")
                recently_unlocked_memory = {
                    "memory_progress": unlocked_threshold,
                    "title": scenario.get("title", ""),
                    "keywords": scenario.get("metadata", {}).get("keywords", []),
                    "unlocked_at": datetime.now().isoformat(),
                    "ttl_turns": MEMORY_UNLOCK_TTL_TURNS,
                }
        else:
            existing_memory = state.get("recently_unlocked_memory")
            if existing_memory:
                ttl = existing_memory.get("ttl_turns", 0) - 1
                if ttl > 0:
                    recently_unlocked_memory = {
                        **existing_memory,
                        "ttl_turns": ttl,
                    }

        return {
            "affection_delta": affection_delta,
            "used_liked_keyword": used_keyword,
            "newly_unlocked_scenario": newly_unlocked_scenario,
            "recently_unlocked_memory": recently_unlocked_memory,
        }

    async def _router_node(self, state: HeroineState) -> dict:
        """의도 분류 노드 - HeroineIntentClassifier 사용"""
        t = time.time()
        intent = await self.intent_classifier.classify(
            user_message=state["messages"][-1].content,
            conversation_buffer=state.get("conversation_buffer", []),
            recently_unlocked=state.get("recently_unlocked_memory"),
            heroine_name=state.get("heroine_name"),
            session_id=state.get("session_id"),
            user_id=state.get("user_id"),
        )
        print(f"[TIMING] 의도 분류: {time.time() - t:.3f}s")
        return {"intent": intent}

    def _route_by_intent(self, state: HeroineState) -> str:
        """의도에 따라 라우팅"""
        return state.get("intent", "general")

    async def _memory_retrieve_node(self, state: HeroineState) -> dict:
        """기억 검색 노드"""
        t = time.time()
        facts = await self._retrieve_memory(state)
        print(f"[TIMING] 기억 검색: {time.time() - t:.3f}s")
        return {"retrieved_facts": facts}

    async def _scenario_retrieve_node(self, state: HeroineState) -> dict:
        """시나리오 검색 노드"""
        t = time.time()
        scenarios = await self._retrieve_scenario(state)
        print(f"[TIMING] 시나리오 검색: {time.time() - t:.3f}s")
        return {"unlocked_scenarios": scenarios}

    async def _heroine_retrieve_node(self, state: HeroineState) -> dict:
        """히로인 대화 검색 노드"""
        t = time.time()
        conversation = await self._retrieve_heroine_conversation(state)
        print(f"[TIMING] 히로인 대화 검색: {time.time() - t:.3f}s")
        return {"heroine_conversation": conversation}

    async def _generate_node(self, state: HeroineState) -> dict:
        """응답 생성 노드 - HeroinePromptBuilder 사용"""
        t = time.time()

        context = {
            "affection_delta": state.get("affection_delta", 0),
            "retrieved_facts": state.get("retrieved_facts", NO_DATA),
            "unlocked_scenarios": state.get("unlocked_scenarios", NO_DATA),
            "heroine_conversation": state.get("heroine_conversation", NO_DATA),
            "preference_changes": state.get("preference_changes", []),
            "newly_unlocked_scenario": state.get("newly_unlocked_scenario"),
        }

        npc_id = state["npc_id"]
        time_since_last_chat = self.get_time_since_last_chat(state["player_id"], npc_id)

        prompt = self.prompt_builder.build(
            state=state,
            context=context,
            time_since_last_chat=time_since_last_chat,
            format_conversation_history_func=self.format_conversation_history,
            format_summary_list_func=self.format_summary_list,
        )

        print(f"[PROMPT]\n{prompt}\n{'='*50}")

        config = tracker.get_langfuse_config(
            tags=["npc", "heroine", "response", state.get("heroine_name", "unknown")],
            session_id=state.get("session_id"),
            user_id=state.get("user_id"),
            metadata={
                "heroine_name": state.get("heroine_name"),
                "intent": state.get("intent", "unknown"),
                "affection": state.get("affection", 0),
            }
        )

        response = await self.llm.ainvoke(prompt, **config)
        print(f"[TIMING] LLM 호출: {time.time() - t:.3f}s")

        result = parse_llm_json_response(
            response.content,
            default={
                "thought": "",
                "text": response.content,
                "emotion": "neutral",
                "emotion_intensity": 1.0,
            }
        )

        return {
            "response_text": result.get("text", ""),
            "emotion": heroine_emotion_to_int(result.get("emotion", "neutral")),
            "emotion_str": result.get("emotion", "neutral"),
            "emotion_intensity": result.get("emotion_intensity", 1.0),
        }

    async def _post_process_node(self, state: HeroineState) -> dict:
        """후처리 노드 - 상태 업데이트"""
        t = time.time()

        context = {
            "affection_delta": state.get("affection_delta", 0),
            "used_liked_keyword": state.get("used_liked_keyword"),
            "recently_unlocked_memory": state.get("recently_unlocked_memory"),
        }

        result = await self._update_state_after_response(
            state, context, state.get("response_text", ""), state.get("emotion", 0)
        )

        print(f"[TIMING] 상태 업데이트: {time.time() - t:.3f}s")
        return {
            "affection": result["affection"],
            "sanity": result["sanity"],
            "memoryProgress": result["memoryProgress"],
        }

    # ============================================
    # 공개 메서드
    # ============================================

    async def process_message(self, state: HeroineState) -> HeroineState:
        """메시지 처리 (비스트리밍)"""
        t = time.time()
        result = await self.graph.ainvoke(state)
        print(f"[TIMING] graph.ainvoke 내부: {time.time() - t:.3f}s")
        return result


# 싱글톤 인스턴스
heroine_agent = HeroineAgent()
