"""
대현자 NPC Agent (리팩토링 버전)

대현자 사트라(Satra)와의 대화를 처리합니다.
세계관과 시나리오 정보를 제공하는 역할입니다.

주요 기능:
1. 시나리오 레벨(scenarioLevel) 기반 정보 공개 관리
2. 레벨에 따른 태도 변화 (거리감 -> 친근함)
3. 허용된 정보만 제공, 금지된 정보는 회피

리팩토링:
- MemoryRetriever: 시간 키워드 기반 기억 검색
- NPCConversationManager: 대화 저장, 요약 생성
- SageIntentClassifier: 의도 분류
- SageScenarioRetriever: 시나리오 검색
- SagePromptBuilder: 프롬프트 생성

저장 위치:
- Redis: 세션 상태 (scenarioLevel, emotion, conversation_buffer)
- PostgreSQL (user_memories): User-NPC 장기 기억 (대화 내용)
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, Any

from langchain.chat_models import init_chat_model
from langgraph.graph import START, END, StateGraph

from agents.npc.npc_state import SageState
from agents.npc.base_npc_agent import BaseNPCAgent, NO_DATA
from agents.npc.emotion_mapper import sage_emotion_to_int
from agents.npc.npc_utils import parse_llm_json_response, load_persona_yaml

# 리팩토링된 컴포넌트들
from agents.npc.memory_retriever import MemoryRetriever
from agents.npc.npc_conversation_manager import NPCConversationManager
from agents.npc.sage_intent_classifier import SageIntentClassifier
from agents.npc.sage_scenario_retriever import SageScenarioRetriever
from agents.npc.sage_prompt_builder import SagePromptBuilder

from db.redis_manager import redis_manager
from enums.LLM import LLM
from utils.langfuse_tracker import tracker


# ============================================
# 페르소나 데이터 로드
# ============================================

def _get_default_sage_persona() -> Dict[str, Any]:
    """기본 대현자 페르소나 데이터 (파일 없을 때 사용)"""
    return {
        "satra": {
            "name": "사트라",
            "basic_info": {
                "apparent_age": "20대 중반 외모",
                "appearance": "은발, 붉은 눈, 하얀 피부",
                "role": "셀레파이스의 대현자",
            },
            "speech_style": {"tone": "기품 있는 하대", "mentor_address": "멘토"},
            "level_attitudes": {
                "low": {
                    "description": "거리감 있음, 수수께끼처럼 말함",
                    "examples": ["흠, 그건 아직 알 필요 없어."],
                },
                "mid": {
                    "description": "조금 친밀해짐",
                    "examples": ["그건... 때가 되면 알려줄게."],
                },
                "high": {
                    "description": "친근함, 솔직해짐",
                    "examples": ["좋아, 솔직히 말해볼게."],
                },
            },
            "personality": {"surface": ["알 수 없는 미소", "기품 있음", "지혜로움"]},
            "info_rules": {
                "level_1": {
                    "allowed": ["기초 세계관", "길드 정보"],
                    "forbidden": ["플레이어 과거", "히로인 비밀"],
                    "evasion": "아직 때가 아니야.",
                }
            },
        }
    }


# 페르소나 데이터 로드 (모듈 로드시 1회)
PERSONA_DATA = load_persona_yaml("sage_persona.yaml", _get_default_sage_persona)


class SageAgent(BaseNPCAgent):
    """대현자 NPC Agent (리팩토링 버전)

    대현자 사트라와의 대화를 처리합니다.
    각 책임을 전문 컴포넌트에 위임하여 SRP를 준수합니다.

    사용 예시:
        agent = SageAgent()
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

        # 대현자 전용 컴포넌트
        self.intent_classifier = SageIntentClassifier(self.intent_llm)
        self.scenario_retriever = SageScenarioRetriever()
        self.prompt_builder = SagePromptBuilder(
            persona_data=PERSONA_DATA,
            world_context=PERSONA_DATA.get("world_context", {}),
        )

        # LangGraph 빌드
        self.graph = self._build_graph()

    # ============================================
    # 세션 관련 메서드
    # ============================================

    def _create_initial_session(self, player_id: int, npc_id: int) -> dict:
        """대현자 초기 세션 생성"""
        return {
            "player_id": player_id,
            "npc_id": npc_id,
            "npc_type": "sage",
            "conversation_buffer": [],
            "short_term_summary": "",
            "state": {
                "scenarioLevel": 1,
                "emotion": "neutral",
            },
        }

    # ============================================
    # 검색 메서드 (컴포넌트 위임)
    # ============================================

    async def _retrieve_memory(self, state: SageState) -> str:
        """기억 검색 - MemoryRetriever 사용"""
        user_message = state["messages"][-1].content
        player_id = state["player_id"]
        npc_id = 0  # sage

        facts_parts = []

        # 시간 키워드 기반 User Memory 검색 (비동기 4요소 하이브리드)
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

        return "\n".join(facts_parts) if facts_parts else "관련 기억 없음"

    async def _retrieve_scenario(self, state: SageState) -> str:
        """시나리오 검색 - SageScenarioRetriever 사용"""
        user_message = state["messages"][-1].content
        scenario_level = state.get("scenarioLevel", 1)

        return await self.scenario_retriever.retrieve(
            user_message=user_message,
            scenario_level=scenario_level,
        )

    # ============================================
    # 상태 업데이트
    # ============================================

    async def _update_state_after_response(
        self, state: SageState, context: Dict[str, Any],
        response_text: str, emotion_int: int = 0, info_revealed: bool = False,
    ) -> Dict[str, Any]:
        """응답 후 상태 업데이트"""
        player_id = state["player_id"]
        npc_id = state["npc_id"]

        # Redis 세션 업데이트
        session = redis_manager.load_session(player_id, npc_id)
        player_known_name = None

        if session:
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
                player_id, npc_id, user_msg, response_text, heroine_id="sage"
            )
        )

        return {
            "response_text": response_text,
            "emotion": emotion_int,
            "info_revealed": info_revealed,
            "player_known_name": player_known_name,
        }

    # ============================================
    # LangGraph 빌드
    # ============================================

    def _build_graph(self) -> StateGraph:
        """LangGraph 빌드"""
        graph = StateGraph(SageState)

        graph.add_node("router", self._router_node)
        graph.add_node("memory_retrieve", self._memory_retrieve_node)
        graph.add_node("scenario_retrieve", self._scenario_retrieve_node)
        graph.add_node("generate", self._generate_node)
        graph.add_node("post_process", self._post_process_node)

        graph.add_edge(START, "router")

        graph.add_conditional_edges(
            "router",
            self._route_by_intent,
            {
                "general": "generate",
                "memory_recall": "memory_retrieve",
                "worldview_inquiry": "scenario_retrieve",
            },
        )

        graph.add_edge("memory_retrieve", "generate")
        graph.add_edge("scenario_retrieve", "generate")
        graph.add_edge("generate", "post_process")
        graph.add_edge("post_process", END)

        return graph.compile()

    # ============================================
    # LangGraph 노드
    # ============================================

    async def _router_node(self, state: SageState) -> dict:
        """의도 분류 노드 - SageIntentClassifier 사용"""
        t = time.time()
        intent = await self.intent_classifier.classify(
            user_message=state["messages"][-1].content,
            conversation_context=state.get("short_term_summary", ""),
            session_id=state.get("session_id"),
            user_id=state.get("user_id"),
        )
        print(f"[TIMING] 의도 분류: {time.time() - t:.3f}s")
        return {"intent": intent}

    def _route_by_intent(self, state: SageState) -> str:
        """의도에 따라 라우팅"""
        return state.get("intent", "general")

    async def _memory_retrieve_node(self, state: SageState) -> dict:
        """기억 검색 노드"""
        t = time.time()
        facts = await self._retrieve_memory(state)
        print(f"[TIMING] 기억 검색: {time.time() - t:.3f}s")
        return {"retrieved_facts": facts}

    async def _scenario_retrieve_node(self, state: SageState) -> dict:
        """시나리오 검색 노드"""
        t = time.time()
        scenarios = await self._retrieve_scenario(state)
        print(f"[TIMING] 시나리오 검색: {time.time() - t:.3f}s")
        return {"unlocked_scenarios": scenarios}

    async def _generate_node(self, state: SageState) -> dict:
        """응답 생성 노드 - SagePromptBuilder 사용"""
        t = time.time()

        context = {
            "unlocked_scenarios": state.get("unlocked_scenarios", NO_DATA),
            "retrieved_facts": state.get("retrieved_facts", NO_DATA),
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
            tags=["npc", "sage", "response"],
            session_id=state.get("session_id"),
            user_id=state.get("user_id"),
            metadata={
                "npc_name": "sage_satra",
                "intent": state.get("intent", "unknown"),
                "scenario_level": state.get("scenarioLevel", 0),
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
                "info_revealed": False,
            }
        )

        return {
            "response_text": result.get("text", ""),
            "emotion": sage_emotion_to_int(result.get("emotion", "neutral")),
            "emotion_intensity": result.get("emotion_intensity", 1.0),
            "info_revealed": result.get("info_revealed", False),
        }

    async def _post_process_node(self, state: SageState) -> dict:
        """후처리 노드 - 상태 업데이트"""
        t = time.time()

        context = {}
        emotion_int = state.get("emotion", 0)

        await self._update_state_after_response(
            state, context, state.get("response_text", ""),
            emotion_int, state.get("info_revealed", False)
        )

        print(f"[TIMING] 상태 업데이트: {time.time() - t:.3f}s")
        return {"info_revealed": state.get("info_revealed", False)}

    # ============================================
    # 공개 메서드
    # ============================================

    async def process_message(self, state: SageState) -> SageState:
        """메시지 처리 (비스트리밍)"""
        result = await self.graph.ainvoke(state)
        return result


# 싱글톤 인스턴스
sage_agent = SageAgent()
