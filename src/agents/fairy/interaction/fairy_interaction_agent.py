import time
from agents.fairy.fairy_state import (
    FairyInteractionState,
    FairyInterationIntentType,
    FairyInterationIntentOutput,
)
from prompts.promptmanager import PromptManager
from prompts.prompt_type.fairy.FairyPromptType import FairyPromptType
from enums.LLM import LLM
from langgraph.graph import StateGraph, START, END
from typing import List
from core.common import get_inventory_items
from agents.fairy.util import get_groq_llm_lc, get_groq_gpt
from agents.fairy.fairy_state import FairyItemUseOutput
from agents.fairy.interaction.fairy_interaction_model_logics import ItemEmbeddingLogic, IsItemUseEmbeddingLogic, FairyInteractionIntentModel
from langchain.messages import SystemMessage, HumanMessage
from langchain.chat_models import init_chat_model


item_embedding_logic = ItemEmbeddingLogic()
is_item_use_embedding_logic = IsItemUseEmbeddingLogic()
fairy_interaction_intent_model = FairyInteractionIntentModel()

# item_use_llm = get_groq_llm_lc(model = LLM.OPENAI_GPT_OSS_20B, max_token=2)
def _clarify_intent(query:str):
    # interation_intent_prompt = PromptManager(
    #     FairyPromptType.FAIRY_INTERACTION_INTENT
    # ).get_prompt(question=query)
    # parser_llm = llm.with_structured_output(FairyInterationIntentOutput)
    # intent_output: FairyInterationIntentOutput = parser_llm.invoke(
    #     interation_intent_prompt
    # )
    raw_labels, _ = fairy_interaction_intent_model.predict(query)
    enum_list = FairyInteractionIntentModel.parse_intents_to_enum(raw_labels)    
    intent_output = FairyInterationIntentOutput(intents=enum_list)

    return intent_output


def analyze_intent(state: FairyInteractionState):
    start = time.perf_counter()

    last = state["messages"][-1]
    last_message = last.content

    intent_output: FairyInterationIntentOutput = _clarify_intent(last_message)

    latency = time.perf_counter() - start
    return {
        "intent_types": intent_output.intents,
        "latency_analyze_intent": latency,
    }

from pprint import pformat

# LLM Call을 한번이라도 줄이기 위해 의도 분석과 함께 병렬 호출 Node
def create_temp_use_item_id(state: FairyInteractionState):
    start = time.perf_counter()
    messages = state["messages"]
    last_messages = messages[-1]
    inventory = state["inventory"]
    weapon = state["weapon"]
    stats = state["stats"]

    my_items = get_inventory_items(inventory, stats)
    prettry_items = pformat(
        [item.model_dump() for item in my_items],
        width=120,
        sort_dicts=False
    )   
    print(prettry_items)
    
    system_prompt = PromptManager(FairyPromptType.FAIRY_ITEM_USE).get_prompt(
        inventory_items=prettry_items, 
        weapon = weapon,
    )
    new_messages = [SystemMessage(content=system_prompt)] + messages
    # ai_answer = get_groq_gpt(new_messages)
    ai_answer = get_groq_llm_lc(max_token=1).invoke([SystemMessage(content=system_prompt)] + new_messages).content
    # ai_answer = get_groq_llm_lc(max_token=1).invoke([SystemMessage(content=system_prompt)] + [last_messages]).content
    try: 
        item_id = int(ai_answer)
    except Exception as e:
        print(e)
        item_id = None

    # parser_llm = llm.with_structured_output(FairyItemUseOutput)
    output = FairyItemUseOutput(item_id=item_id)  # for type hinting
    latency = time.perf_counter() - start
    return {"temp_use_item_id": output.item_id,
            "latency_create_temp_use_item_id": latency}
    # item_id = item_embedding_logic.pick_items(last_message, inventory, top_k=1)[0]
    # latency = time.perf_counter() - start
    # return {
    #     "temp_use_item_id": item_id,
    #     "latency_create_temp_use_item_id": latency,
    # }

def check_use_item(state:FairyInteractionState): 
    start = time.perf_counter()
    last = state["messages"][-1]
    last_message = last.content
    is_item_use = is_item_use_embedding_logic.is_item_use(last_message)
    latency = time.perf_counter() - start
    return {
        "is_item_use": is_item_use,
        "latency_check_use_item": latency,
    }


def create_interation(state: FairyInteractionState):
    intent_types: List[FairyInterationIntentType] = state["intent_types"]
    is_item_use = state["is_item_use"]

    item_id = None
    if is_item_use:
        item_id = state["temp_use_item_id"]

    room_light = 0
    if FairyInterationIntentType.LIGHT_ON_ROOM in intent_types:
        room_light = 1

    if FairyInterationIntentType.LIGHT_OFF_ROOM in intent_types:
        room_light = 2

    return {
        "useItemId": item_id,
        "roomLight": room_light,
    }


graph_builder = StateGraph(FairyInteractionState)
graph_builder.add_node("analyze_intent", analyze_intent)
graph_builder.add_node("create_temp_use_item_id", create_temp_use_item_id)
graph_builder.add_node("create_interation", create_interation)
graph_builder.add_node("check_use_item", check_use_item)

graph_builder.add_edge(START, "analyze_intent")
graph_builder.add_edge(START, "create_temp_use_item_id")
graph_builder.add_edge(START, "check_use_item")

graph_builder.add_edge("analyze_intent", "create_interation")
graph_builder.add_edge("create_temp_use_item_id", "create_interation")
graph_builder.add_edge("check_use_item", "create_interation")

graph_builder.add_edge("create_interation", END)
graph = graph_builder.compile()
