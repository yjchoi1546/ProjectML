from agents.fairy.fairy_state import (
    FairyDungeonIntentOutput,
    FairyDungeonState,
    FairyDungeonIntentType,
)
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.types import interrupt
from agents.fairy.cache_data import reverse_questions, GAME_SYSTEM_INFO
from prompts.promptmanager import PromptManager
from prompts.prompt_type.fairy.FairyPromptType import FairyPromptType
import random, asyncio, time
from agents.fairy.util import (
    add_ai_message,
    add_human_message,
    get_groq_llm_lc,
    find_monsters_info,
)
from core.game_dto.StatData import StatData
from enums.LLM import LLM
from langchain.chat_models import init_chat_model
from typing import List
from db.RDBRepository import RDBRepository
from db.rdb_entity.DungeonRow import DungeonRow
from agents.fairy.dynamic_prompt import (
    monster_spec_prompt,
)
from agents.fairy.util import (
    contains_hanja,
    replace_hanja_naively,
    get_human_few_shot_prompts,
    describe_dungeon_row,
)
from agents.fairy.dungeon.fairy_dungeon_model_logics import FairyDungeonIntentModel
import asyncio

intent_llm = get_groq_llm_lc(model=LLM.LLAMA_3_3_70B_VERSATILE, max_token=43)

# action_llm = get_groq_llm_lc(max_token=80, temperature=0)
# small_talk_llm = get_groq_llm_lc(max_token=120, temperature=0)
action_llm = init_chat_model(
    model=LLM.GROK_4_FAST_NON_REASONING, max_tokens=80, temperature=0
)
# small_talk_llm = init_chat_model(model=LLM.GROK_4_FAST_NON_REASONING, max_tokens=80)
rdb_repository = RDBRepository()
intent_model = FairyDungeonIntentModel()


def _rdb_fairy_messages_bg(user_args, ai_args):
    try:
        rdb_repository.insert_fairy_message(**user_args)
        rdb_repository.insert_fairy_message(**ai_args)
    except Exception as e:
        print("fairy_message insert failed:", e)


async def get_monsters_info(target_monster_ids: List[int], inventory_ids, stats: StatData):
    monster_prompt = monster_spec_prompt.format(
        monster_infos_json=find_monsters_info(target_monster_ids)
    )
    monster_info_prompt = (
        f"        <MONSTER_INFO>\n" f"{monster_prompt}\n" f"        </MONSTER_INFO>"
    )
    
    return monster_info_prompt



async def get_event_info(dungeon_row: DungeonRow, curr_room_id: int):
    event = dungeon_row.event
    if event is None:
        return '이벤트가 생성되지 않았습니다. 페이몬은 "응? 확인된 이벤트는 아직 없어!"라고 장난스럽게 답해주세요.'

    if event.room_id != curr_room_id:
        return '이벤트방에 입장하지 않아서 정보를 확인할 수 없습니다. 페이몬은 "아직은 아무일 없어보여! 무슨 사건이 일어날 때 말해!" 라는식으로 장난스럽게 답해주세요.'

    print("이벤트", event)
    return event


async def dungeon_navigator(dungeon_row: DungeonRow, curr_room_id: int):
    summary_info = dungeon_row.summary_info
    dungeon_prompt = describe_dungeon_row(
        curr_room_id, dungeon_row.balanced_map, dungeon_row.floor
    )
    dungeon_map_prompt = (
        f"        <DUNGEON_MAP>\n" f"{dungeon_prompt}\n" f"        </DUNGEON_MAP>"
    )

    dungeon_summary_prompt = (
        f"        <DUNGEON_SUMMARY>\n" f"{summary_info}\n" f"        </DUNGEON_SUMMARY>"
    )

    dungeon_current_prompt = (
        f"        <CURRENT_ROOM_ID>\n" f"{curr_room_id}\n" f"        </CURRENT_ROOM_ID>"
    )
    total_prompt = (
        dungeon_map_prompt
        + "\n"
        + dungeon_summary_prompt
        + "\n"
        + dungeon_current_prompt
    )
    return total_prompt





async def get_system_info():
    return GAME_SYSTEM_INFO


async def _clarify_intent(query) -> FairyDungeonIntentOutput:
    intent_prompt = PromptManager(FairyPromptType.FAIRY_DUNGEON_INTENT).get_prompt()
    messages = [SystemMessage(content=intent_prompt), HumanMessage(content=query)]
    parser_llm = intent_llm.with_structured_output(FairyDungeonIntentOutput)
    intent_output: FairyDungeonIntentOutput = await parser_llm.ainvoke(messages)
    # raw_labels, _ = intent_model.predict(query)
    # enum_list = FairyDungeonIntentModel.parse_intents_to_enum(raw_labels)
    # intent_output: FairyDungeonIntentOutput = FairyDungeonIntentOutput(intents=enum_list)
    # print("전체 의도::", intent_output)
    return intent_output


async def analyze_intent(state: FairyDungeonState):
    start = time.perf_counter()
    last = state["messages"][-1]
    target_monster_ids = state.get("target_monster_ids", [])
    last_message = last.content
    clarify_intent_type: FairyDungeonIntentOutput = await _clarify_intent(last_message)

    if clarify_intent_type.intents[0] == FairyDungeonIntentType.UNKNOWN_INTENT:
        clarification = reverse_questions[random.randint(0, 148)]
        user_resp = interrupt(clarification)
        return {
            "messages": [
                add_ai_message(
                    content=clarification, intent_types=clarify_intent_type.intents
                ),
                add_human_message(content=user_resp),
            ],
            "intent_types": clarify_intent_type.intents,
            "is_multi_small_talk": False,
        }

    if FairyDungeonIntentType.MONSTER_GUIDE not in clarify_intent_type.intents:
        if target_monster_ids:
            clarify_intent_type.intents.append(FairyDungeonIntentType.MONSTER_GUIDE)

    latency = time.perf_counter() - start
    return {
        "intent_types": clarify_intent_type.intents,
        "latency_analyze_intent": latency,
    }


def check_condition(state: FairyDungeonState):
    intent_types = state.get("intent_types", [])
    if intent_types[0] == FairyDungeonIntentType.UNKNOWN_INTENT:
        return "retry"
    return "continue"


async def fairy_action(state: FairyDungeonState):
    start = time.perf_counter()
    intent_types = state.get("intent_types")
    dungenon_player = state["dungenon_player"]
    target_monster_ids = state.get("target_monster_ids", [])
    currRoomId = dungenon_player.currRoomId
    dungeon_row = rdb_repository.get_current_dungeon_by_player(
        dungenon_player.playerId, dungenon_player.heroineId
    )

    messages = state["messages"]
    INTENT_HANDLERS = {
        FairyDungeonIntentType.MONSTER_GUIDE: lambda: get_monsters_info(
            target_monster_ids,dungenon_player.inventory, dungenon_player.stats
        ),
        FairyDungeonIntentType.EVENT_GUIDE: lambda: get_event_info(
            dungeon_row, currRoomId
        ),
        FairyDungeonIntentType.DUNGEON_NAVIGATOR: lambda: dungeon_navigator(
            dungeon_row, currRoomId
        ),
        FairyDungeonIntentType.USAGE_GUIDE: get_system_info,
    }
    
    INTENT_LABELS = {
        FairyDungeonIntentType.MONSTER_GUIDE: "MONSTER_GUIDE",
        FairyDungeonIntentType.EVENT_GUIDE: "EVENT_GUIDE",
        FairyDungeonIntentType.DUNGEON_NAVIGATOR: "DUNGEON_NAVIGATOR",
        FairyDungeonIntentType.USAGE_GUIDE: "USAGE_GUIDE",
    }

    handlers = [INTENT_HANDLERS[i]() for i in intent_types if i in INTENT_HANDLERS]
    results = await asyncio.gather(*handlers)

    prompt_info = ""
    idx = 0
    for i, index in enumerate(intent_types):
        handler = INTENT_HANDLERS.get(index)
        if not handler:
            continue

        value = results[idx]
        label = INTENT_LABELS.get(index, "정보")
        if i == 0:
            prompt_info += f"    <{label}>\n{value}\n    </{label}>"
        else:
            prompt_info += f"\n    <{label}>\n{value}\n    </{label}>"
        idx += 1

    pretty_dungenon_player = dungenon_player.model_dump_json(indent=2)
    system_prompt = PromptManager(FairyPromptType.FAIRY_DUNGEON_SYSTEM).get_prompt()

    question = messages[-1].content

    fewshots = get_human_few_shot_prompts(intent_types)

    human_prompt = PromptManager(FairyPromptType.FAIRY_DUNGEON_HUMAN).get_prompt(
        dungenon_player=pretty_dungenon_player,
        use_intents=[rt.value if hasattr(rt, "value") else rt for rt in intent_types],
        ability_examples=fewshots,
        info=prompt_info,
        question=question,
    )

    print("총 질문", human_prompt)

    # if  FairyDungeonIntentType.SMALLTALK in intent_types:
    #     ai_answer = action_llm.invoke(
    #         [SystemMessage(content=system_prompt)]
    #         + messages
    #         + [HumanMessage(content=human_prompt)]
    #     )
    # else:
    #     ai_answer = action_llm.invoke(
    #         [   
    #             SystemMessage(content=system_prompt),
    #             HumanMessage(content=human_prompt),
    #         ]
    #     )

    ai_answer = action_llm.invoke(
        [SystemMessage(content=system_prompt)]
        + messages
        + [HumanMessage(content=human_prompt)]
    )

    # ai_answer = action_llm.invoke(
    #     [SystemMessage(content=system_prompt)]
    #     + [HumanMessage(content=human_prompt)]
    # )
        
    if contains_hanja(ai_answer.content):
        ai_answer.content = replace_hanja_naively(ai_answer.content)

    asyncio.create_task(
        asyncio.to_thread(
            _rdb_fairy_messages_bg,
            {
                "sender_type": "USER",
                "message": question,
                "context_type": "DUNGEON",
                "player_id": dungenon_player.playerId,
                "heroine_id": dungenon_player.heroineId,
                "intent_type": None,
            },
            {
                "sender_type": "AI",
                "message": ai_answer.content,
                "context_type": "DUNGEON",
                "player_id": dungenon_player.playerId,
                "heroine_id": dungenon_player.heroineId,
                "intent_type": intent_types,
            },
        )
    )
    latency = time.perf_counter() - start
    return {
        "messages": [
            add_ai_message(content=ai_answer.content, intent_types=intent_types)
        ],
        "latency_fairy_action": latency,
    }


from langgraph.graph import START, END, StateGraph

graph_builder = StateGraph(FairyDungeonState)

graph_builder.add_node("analyze_intent", analyze_intent)
graph_builder.add_node("fairy_action", fairy_action)
graph_builder.add_edge(START, "analyze_intent")

graph_builder.add_conditional_edges(
    "analyze_intent",
    check_condition,
    {
        "retry": "analyze_intent",
        "continue": "fairy_action",
    },
)
graph_builder.add_edge("fairy_action", END)
graph_builder.compile()
