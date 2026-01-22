from langchain.chat_models import init_chat_model
from enums.LLM import LLM
from agents.dungeon.dungeon_state import DungeonEventParser
import random
from agents.dungeon.event.main_event_scenarios import MAIN_EVENT_SCENARIOS
from agents.dungeon.event.heroine_scenarios import HEROINE_SCENARIOS
from agents.dungeon.event import event_rewards_penalties as rewards_module
from pydantic import BaseModel
from agents.dungeon.event.event_rewards_penalties import (
    get_reward_dict,
    get_penalty_dict)
from prompts.promptmanager import PromptManager
from prompts.prompt_type.dungeon.DungeonPromptType import DungeonPromptType
from agents.dungeon.dungeon_state import DungeonEventState
from langchain_core.messages import HumanMessage
from langgraph.graph import START, END, StateGraph

llm = init_chat_model(model=LLM.GROK_4_FAST_NON_REASONING, temperature=0.5)

def heroine_memories_node(state: DungeonEventState) -> DungeonEventState:

    heroine_id = state["heroine_data"].get("heroine_id")
    memory_progress = state["heroine_data"].get("memory_progress")
    player_id = state.get("player_id") if "player_id" in state else None

    try:
        heroine_id = int(heroine_id) if isinstance(heroine_id, str) else heroine_id
    except Exception:
        pass

    # player_id는 int 변환이 가능할 때만 변환, 아니면 str 그대로 사용
    if player_id is not None and isinstance(player_id, str):
        try:
            player_id_int = int(player_id)
            player_id = player_id_int
        except ValueError:
            # player_id가 숫자가 아니면(str) 그대로 둠
            pass

    # 해당 히로인의 해금된 기억들을 필터링 (memory_progress 이하)
    heroine_memories = [
        scenario
        for scenario in HEROINE_SCENARIOS
        if scenario["heroine_id"] == heroine_id
        and scenario["memory_progress"] <= memory_progress
    ]

    print(f"[heroine_memories_node] 플레이어 ID: {player_id} | 히로인 ID: {heroine_id}")
    print(f"[heroine_memories_node] 기억 진척도: {memory_progress}")
    print(f"[heroine_memories_node] 해금된 기억 개수: {len(heroine_memories)}")
    return {"heroine_memories": heroine_memories}


def selected_main_event_node(state: DungeonEventState) -> DungeonEventState:
    used_events = state.get("used_events", [])
    used_event_codes = [
        evt.get("event_code") for evt in used_events if "event_code" in evt
    ]

    # 사용 가능한 이벤트 필터링 (중복 제외)
    available_events = []
    for event in MAIN_EVENT_SCENARIOS:
        # 이미 사용한 이벤트 제외
        if event["event_code"] in used_event_codes:
            continue

        available_events.append(event)

    # 사용 가능한 이벤트가 없으면 모든 이벤트 풀에서 선택 (중복 허용)
    if not available_events:
        available_events = MAIN_EVENT_SCENARIOS

    # 랜덤 선택
    selected_event = random.choice(available_events)

    # 시나리오 텍스트 치환 (히로인 이름 등)
    scenario_text = selected_event["scenario_text"]
    heroine_name = state["heroine_data"].get("name", "그녀")
    if "{heroine_name}" in scenario_text:
        scenario_text = scenario_text.format(heroine_name=heroine_name)

    # 선택된 이벤트를 구조화된 dict로 반환
    event_data = {
        "event_id": selected_event.get("event_id", 0),
        "title": selected_event["title"],
        "event_code": selected_event["event_code"],
        "is_personal": selected_event["is_personal"],
        "scenario_text": scenario_text,
    }

    print(f"[selected_main_event_node] 선택된 이벤트: {selected_event['title']}")
    print(
        f"[selected_main_event_node] 개별 이벤트 여부: {selected_event['is_personal']}"
    )

    return {"selected_main_event": event_data}


def create_sub_event_node(state: DungeonEventState) -> DungeonEventState:
    heroine_info = state.get("heroine_data", {}) if isinstance(state, dict) else {}
    heroine_name = heroine_info.get("name") or heroine_info.get("heroine_name") or None
    memory_progress = (
        heroine_info.get("memory_progress") or heroine_info.get("memoryProgress") or 0
    )
    selected_main_event = state.get("selected_main_event", {})
    is_personal = bool(selected_main_event.get("is_personal", False))
    player_id = state.get("player_id")

    available_rewards = [
        r.get("id")
        for r in (
            getattr(rewards_module, "SPAWN_MONSTER_REWARDS", [])
            + getattr(rewards_module, "DROP_ITEM_REWARDS", [])
            + getattr(rewards_module, "CHANGE_STAT_REWARDS", [])
        )
    ]
    available_penalties = [
        p.get("id")
        for p in (
            getattr(rewards_module, "SPAWN_MONSTER_PENALTIES", [])
            + getattr(rewards_module, "DROP_ITEM_PENALTIES", [])
            + getattr(rewards_module, "CHANGE_STAT_PENALTIES", [])
        )
    ]

    prompts = PromptManager(DungeonPromptType.DUNGEON_SUB_EVENT).get_prompt(
        heroine_data=state.get("heroine_data"),
        heroine_memories=state.get("heroine_memories"),
        selected_main_event=selected_main_event,
        event_room=state.get("event_room"),
        next_floor=state.get("next_floor"),
        heroine_name=heroine_name,
        memory_progress=memory_progress,
        is_personal=is_personal,
        available_rewards=available_rewards,
        available_penalties=available_penalties,
        player_id=player_id,
    )

    parser_llm = llm.with_structured_output(DungeonEventParser)
    try:
        response = parser_llm.invoke(prompts)
    except Exception as e:
        print(f"[create_sub_event_node] LLM invoke failed: {e}")
        fallback_narrative = (
            (selected_main_event.get("scenario_text")[:200] + "...")
            if isinstance(selected_main_event, dict)
            else "짧은 이상한 기척이 느껴진다."
        )

        class _Resp:
            pass

        response = _Resp()
        response.sub_event_narrative = fallback_narrative

        class _Choice(BaseModel):
            action: str
            reward_id: str | None = None
            penalty_id: str | None = None

        response.event_choices = [
            _Choice(action="조용히 관찰한다"),
            _Choice(action="상호작용을 시도한다"),
        ]
        response.expected_outcome = "선택에 따라 간단한 반응이 발생합니다."

    choices = []
    for choice in response.event_choices:
        reward = get_reward_dict(choice.reward_id) if choice.reward_id else None
        penalty = get_penalty_dict(choice.penalty_id) if choice.penalty_id else None
        choices.append({"action": choice.action, "reward": reward, "penalty": penalty})

    sub_event_data = {
        "narrative": response.sub_event_narrative,
        "choices": choices,
        "expected_outcome": response.expected_outcome,
    }
    print(f"[create_sub_event_node] 서브 이벤트 생성 완료")
    print(response)

    # 하위 호환성을 위한 문자열 버전도 생성
    sub_event_text = f"""
=== 서브 이벤트 내러티브 ===
{response.sub_event_narrative}

=== 선택지 ===
{chr(10).join([f"{i+1}. action='{choice.action}' reward_id='{choice.reward_id}' penalty_id='{choice.penalty_id}'" for i, choice in enumerate(response.event_choices)])}

=== 예상 결과 ===
{response.expected_outcome}
"""

    return {
        "messages": [HumanMessage(sub_event_text)],
        "sub_event": sub_event_data,
        "final_answer": sub_event_data,
    }


# langgraph stategraph
graph_builder = StateGraph(DungeonEventState)
graph_builder.add_node("heroine_memories_node", heroine_memories_node)
graph_builder.add_node("selected_main_event_node", selected_main_event_node)
graph_builder.add_node("create_sub_event_node", create_sub_event_node)

graph_builder.add_edge(START, "heroine_memories_node")
graph_builder.add_edge("heroine_memories_node", "selected_main_event_node")

graph_builder.add_edge("selected_main_event_node", "create_sub_event_node")
graph_builder.add_edge("create_sub_event_node", END)
graph_builder
