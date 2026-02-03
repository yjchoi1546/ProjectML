from agents.npc.npc_state import NPCState, HeroineState, SageState, IntentType, EmotionType
from agents.npc.base_npc_agent import (
    BaseNPCAgent,
    WEEKDAY_MAP,
    get_last_weekday,
    MAX_CONVERSATION_BUFFER_SIZE,
    MAX_RECENT_MESSAGES,
    MAX_RECENT_KEYWORDS,
    MEMORY_UNLOCK_TTL_TURNS,
    NO_DATA,
)
from agents.npc.heroine_agent import HeroineAgent, heroine_agent
from agents.npc.sage_agent import SageAgent, sage_agent
from agents.npc.heroine_heroine_agent import HeroineHeroineAgent, heroine_heroine_agent
from agents.npc.npc_utils import parse_llm_json_response, load_persona_yaml
from agents.npc.npc_constants import (
    NPC_ID_TO_NAME_EN,
    NPC_ID_TO_NAME_KR,
    NPC_NAME_KR_TO_ID,
    is_sage,
    is_heroine,
)

# SC-001: 리팩토링된 공통 컴포넌트
from agents.npc.memory_retriever import MemoryRetriever, memory_retriever
from agents.npc.npc_conversation_manager import NPCConversationManager, npc_conversation_manager

# SC-001: 히로인 전용 컴포넌트
from agents.npc.heroine_intent_classifier import HeroineIntentClassifier
from agents.npc.heroine_scenario_retriever import HeroineScenarioRetriever, heroine_scenario_retriever
from agents.npc.heroine_prompt_builder import HeroinePromptBuilder

# SC-001: 대현자 전용 컴포넌트
from agents.npc.sage_intent_classifier import SageIntentClassifier
from agents.npc.sage_scenario_retriever import SageScenarioRetriever, sage_scenario_retriever
from agents.npc.sage_prompt_builder import SagePromptBuilder

__all__ = [
    # State
    "NPCState",
    "HeroineState",
    "SageState",
    "IntentType",
    "EmotionType",
    # Base
    "BaseNPCAgent",
    "WEEKDAY_MAP",
    "get_last_weekday",
    "MAX_CONVERSATION_BUFFER_SIZE",
    "MAX_RECENT_MESSAGES",
    "MAX_RECENT_KEYWORDS",
    "MEMORY_UNLOCK_TTL_TURNS",
    "NO_DATA",
    # Agents
    "HeroineAgent",
    "heroine_agent",
    "SageAgent",
    "sage_agent",
    "HeroineHeroineAgent",
    "heroine_heroine_agent",
    # Utils
    "parse_llm_json_response",
    "load_persona_yaml",
    # Constants
    "NPC_ID_TO_NAME_EN",
    "NPC_ID_TO_NAME_KR",
    "NPC_NAME_KR_TO_ID",
    "is_sage",
    "is_heroine",
    # SC-001: 공통 컴포넌트
    "MemoryRetriever",
    "memory_retriever",
    "NPCConversationManager",
    "npc_conversation_manager",
    # SC-001: 히로인 컴포넌트
    "HeroineIntentClassifier",
    "HeroineScenarioRetriever",
    "heroine_scenario_retriever",
    "HeroinePromptBuilder",
    # SC-001: 대현자 컴포넌트
    "SageIntentClassifier",
    "SageScenarioRetriever",
    "sage_scenario_retriever",
    "SagePromptBuilder",
]
