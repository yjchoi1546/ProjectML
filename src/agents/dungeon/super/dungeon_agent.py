"""
Super Dungeon Agent
Event Agent와 Monster Agent를 병렬로 실행하고 결과를 병합하는 최상위 Agent
"""

from typing import Dict, Any
from datetime import datetime
import copy
from langgraph.graph import START, END, StateGraph
from agents.dungeon.dungeon_state import SuperDungeonState
from agents.dungeon.monster.dungeon_monster_agent import monster_graph
from agents.dungeon.event.dungeon_event_agent import (
        graph_builder as event_graph_builder
    )


# ===== Node 1: Event Processing =====
def event_node(state: SuperDungeonState) -> Dict[str, Any]:
    print("\n[Event Node] 이벤트 생성 시작...")

    event_graph = event_graph_builder.compile()
    player_id = None
    
    # 다양한 위치에서 player_id를 추출 시도
    if "player_id" in state:
        player_id = state["player_id"]
    elif "player_ids" in state and state["player_ids"]:
        player_id = state["player_ids"][0]
    elif "dungeon_base_data" in state and state["dungeon_base_data"].get("player_ids"):
        player_id = state["dungeon_base_data"]["player_ids"][0]

    event_state = {
        "heroine_data": state.get("heroine_data"),
        "heroine_memories": state.get("heroine_memories"),
        "event_room": state.get("heroine_data", {}).get("event_room", 3),
        "next_floor": state.get("dungeon_base_data", {}).get("floor_count", 1),
        "used_events": state.get("used_events", []),
        "player_id": player_id,
    }

    event_result = event_graph.invoke(event_state)

    print(f"[Event Node] 완료:")
    main_event = event_result.get('selected_main_event', {})
    main_event_title = main_event.get('title', 'N/A') if isinstance(main_event, dict) else 'N/A'
    print(f"  - Main Event: {main_event_title}")
    sub_event = event_result.get('sub_event', {})
    sub_event_preview = str(sub_event.get('narrative', 'N/A'))[:80] if isinstance(sub_event, dict) else 'N/A'
    print(f"  - Sub Event: {sub_event_preview}...")

    return {"event_result": event_result}


# ===== Node 2: Monster Balancing =====
def monster_node(state: SuperDungeonState) -> Dict[str, Any]:
    print("\n[Monster Node] 몬스터 밸런싱 시작...")

    # Monster Agent 입력 state 구성
    monster_state = {
        "heroine_stat": state.get("heroine_stat"),
        "monster_db": state.get("monster_db"),
        "dungeon_data": state.get("dungeon_base_data"),
        "dungeon_player_data": state.get("dungeon_player_data"),
        "floor": state.get("dungeon_base_data", {}).get("floor_count", 1),
    }

    # Monster Graph 실행
    monster_result = monster_graph.invoke(monster_state)

    filled_dungeon_data = monster_result.get("filled_dungeon_data", {})

    print(f"[Monster Node] 완료:")
    print(f"  - 전투력: {monster_result.get('combat_score', 0):.2f}")
    print(
        f"  - 난이도 배율: {monster_result['difficulty_log'].get('ai_multiplier', 1.0):.2f}x"
    )
    print(
        f"  - 배치된 몬스터: {monster_result['difficulty_log'].get('normal_monster_count', 0)}마리"
    )
    print(
        f"  - 보스방: {'있음' if monster_result['difficulty_log'].get('has_boss_room') else '없음'}"
    )

    return {
        "filled_dungeon_data": filled_dungeon_data,
        "difficulty_log": monster_result.get("difficulty_log"),
    }


# ===== Node 3: Merge Results =====
def merge_results_node(state: SuperDungeonState) -> Dict[str, Any]:
    """
    Event와 Monster 결과를 알고리즘적으로 병합
    LLM 사용 없이 순수 로직으로 구현
    """
    print("\n[Merge Node] 결과 병합 시작...")


    # 1. 각 Agent 결과 가져오기
    # Monster Agent의 결과(rooms[].monsters)를 무조건 덮어쓴다 (중복/합산 방지)
    filled_dungeon = state.get("filled_dungeon_data", {})
    event_result = state.get("event_result", {})
    difficulty_log = state.get("difficulty_log", {})

    # 1.5. 방의 position 필드 제거 (sanitization)
    sanitized_dungeon = copy.deepcopy(filled_dungeon)
    for room in sanitized_dungeon.get("rooms", []):
        room.pop("position", None)
        # 몬스터 배치는 Monster Agent 결과만 반영 (event 등에서 추가된 몬스터가 있으면 무시)
        # (이미 filled_dungeon이 Monster Agent 결과이므로 별도 합산/append 금지)

    # 2. 몬스터 통계 계산
    total_monsters = 0
    boss_count = 0
    normal_monster_count = 0

    for room in filled_dungeon.get("rooms", []):
        monsters = room.get("monsters", [])
        total_monsters += len(monsters)
        
        # monster는 이제 integer ID이므로 monster_db에서 조회 필요
        room_type = room.get("room_type", "")
        if room_type == "boss":
            boss_count += len(monsters)
        elif room_type == "monster":
            normal_monster_count += len(monsters)

    # 3. 최종 JSON 구조 생성 (Unreal에 필요한 정보만)
    final_json = {
        # 몬스터가 배치된 완전한 던전 데이터
        "dungeon_data": sanitized_dungeon,
        # Event 정보 (구조화된 JSON)
        "events": {
            "main_event": event_result.get("selected_main_event", {}),
            "sub_event": event_result.get("sub_event", {}),
            "event_room_index": event_result.get("event_room", -1),
        },
        # Monster 통계 (간소화)
        "monster_stats": {
            "total_count": total_monsters,
            "boss_count": boss_count,
            "normal_count": normal_monster_count,
        },
        # 난이도 정보 (간소화 - 디버그용 제외)
        "difficulty_info": {
            "combat_score": difficulty_log.get("combat_score", 0),
            "ai_multiplier": difficulty_log.get("ai_multiplier", 1.0),
        },
    }

    print(f"[Merge Node] 병합 완료:")
    main_event_title = final_json['events']['main_event'].get('title', 'N/A') if isinstance(final_json['events']['main_event'], dict) else 'N/A'
    print(f"  - Event: {main_event_title}")
    print(
        f"  - 총 몬스터: {total_monsters}마리 (보스: {boss_count}, 일반: {normal_monster_count})"
    )
    print(f"  - AI 난이도 배율: x{final_json['difficulty_info']['ai_multiplier']:.2f}")
    print(f"  - 전투력: {final_json['difficulty_info']['combat_score']:.2f}")

    return {"final_dungeon_json": final_json}


# ===== Graph Construction =====
def create_super_dungeon_graph():
    """
    Super Dungeon Agent의 LangGraph 생성
    Event와 Monster를 병렬 실행하고 결과를 병합
    """
    graph_builder = StateGraph(SuperDungeonState)

    # 노드 추가
    graph_builder.add_node("event_node", event_node)
    graph_builder.add_node("monster_node", monster_node)
    graph_builder.add_node("merge_results_node", merge_results_node)

    # Edge 연결 (병렬 실행, 단 skip_event_node 플래그가 있으면 event_node 생략)
    def start_conditional(state):
        # skip_event_node가 True면 event_node 생략
        if state.get("skip_event_node"):
            return ["monster_node"]
        return ["event_node", "monster_node"]

    graph_builder.add_conditional_edges(START, start_conditional)

    # 두 노드가 완료되면 merge로 이동
    graph_builder.add_edge("event_node", "merge_results_node")
    graph_builder.add_edge("monster_node", "merge_results_node")

    # 최종 종료
    graph_builder.add_edge("merge_results_node", END)

    return graph_builder.compile()
