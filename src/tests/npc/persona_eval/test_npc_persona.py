"""
NPC 페르소나 평가 테스트

DeepEval을 사용하여 NPC의 페르소나 일관성, 역할 몰입도, 지식 경계를 평가합니다.
"""

import pytest
from .custom_metrics import (
    get_metrics_for_type, 
    calculate_weighted_score,
    get_primary_metric
)
from deepeval.test_case import LLMTestCase
from .npc_client import NPCClient

# 전역 결과 저장소 (마지막에 종합 리포트를 출력하기 위함)
GLOBAL_RESULTS = []

@pytest.fixture(scope="session", autouse=True)
def summary_report_fixture():
    """모든 테스트 세션이 끝나면 종합 리포트를 출력합니다."""
    yield
    print_final_summary()

def run_evaluation_by_type(test_cases_by_type, character_name):
    """
    유형별로 테스트를 실행하고 가중 점수를 계산하여 결과를 수집합니다.

    [입력 데이터 구조 예시]
    test_cases_by_type = {
        "memory": [
            (test_case1, question_info1), 
            (test_case2, question_info2)
        ]


    1. test_case (LLMTestCase): 채점관(DeepEval)을 위한 '기술적 시험지'
       - input: "아이폰 써봤어?" (질문 텍스트)
       - actual_output: "아이폰? 그게 무엇인지 모르겠군요." (AI의 실제 답변)
       - context: ["성격...", "지침..."] (채점 기준들)

    2. question_info (dict): 개발자를 위한 '질문 상세 정보 주머니'
       - id: "letia_005" (관리용 번호)
       - type: "knowledge_boundary" (질문 유형)
       - turns: [{"role": "user", "content": "..."}] (질문 원본)
       - persona_context: "테스트 의도"
       - expected_behavior: "채점 가이드라인"

    """
    character_summary = {
        "character": character_name,
        "results": []
    }
    
    for question_type, case_list in test_cases_by_type.items():
        if not case_list:
            continue
        
        metrics = get_metrics_for_type(question_type)
        primary_metric_name = get_primary_metric(question_type)
        
        print(f"\n>>> [{character_name}] '{question_type}' 유형 평가 시작 ({len(case_list)}개)")
        
        type_scores = []
        for test_case, q_info in case_list:
            metric_scores = {}
            
            # 개별 채점(measure) 수행
            for metric in metrics:
                metric.measure(test_case)
                metric_scores[metric.name] = metric.score if metric.score else 0.0
            
            weighted_score = calculate_weighted_score(question_type, metric_scores)
            type_scores.append(weighted_score)
            
            # 개별 질문 결과 즉시 출력
            print(f"  * [{q_info['id']}] {q_info['persona_context']}")
            print(f"    - 질문: {test_case.input}")
            print(f"    - 답변: {test_case.actual_output}")
            print(f"    - 가중 점수: {weighted_score:.2%}")
            # 주요 메트릭의 이유(Reason) 출력
            for metric in metrics:
                if metric.name == primary_metric_name:
                    print(f"    - 판단 이유: {metric.reason}")
        
        if type_scores:
            type_avg = sum(type_scores) / len(type_scores)
            character_summary["results"].append({
                "type": question_type,
                "score": type_avg,
                "count": len(type_scores)
            })
    
    GLOBAL_RESULTS.append(character_summary)

def print_final_summary():
    """모든 캐릭터의 테스트 결과를 깔끔하게 정리하여 출력합니다."""
    print("\n\n" + "="*60)
    print("             [ NPC 페르소나 평가 종합 리포트 ]")
    print("="*60)
    
    total_score_sum = 0
    total_test_count = 0
    
    # 캐릭터 이름순 정렬 (출력 순서 고정)
    sorted_results = sorted(GLOBAL_RESULTS, key=lambda x: x['character'])
    
    for char_data in sorted_results:
        print(f"\n● 캐릭터: {char_data['character']}")
        char_score_sum = 0
        char_test_count = 0
        
        # 유형별 결과 출력
        for res in char_data["results"]:
            print(f"  - {res['type']:<20} | 평균 {res['score']:>7.2%} ({res['count']}개 질문)")
            char_score_sum += res['score'] * res['count']
            char_test_count += res['count']
        
        if char_test_count > 0:
            char_avg = char_score_sum / char_test_count
            print(f"  [ {char_data['character']} 합계 점수: {char_avg:.2%} ]")
            total_score_sum += char_score_sum
            total_test_count += char_test_count
            
    print("\n" + "="*60)
    if total_test_count > 0:
        total_avg = total_score_sum / total_test_count
        print(f"■ 최종 결과: 총 {total_test_count}개 질문 평가 완료 / 전체 평균 점수 {total_avg:.2%}")
    else:
        print("평가 데이터가 없습니다.")
    print("="*60 + "\n")


# ============================================
# 캐릭터별 테스트 함수 (데이터 조립소)
# ============================================

@pytest.mark.asyncio
async def test_letia_persona(npc_client, letia_questions, letia_persona):
    """레티아 페르소나 평가 테스트"""
    player_id = "test_letia_player"
    heroine_id = 1
    await npc_client.login(player_id)
    
    test_cases_by_type = {}
    
    for question_info in letia_questions:
        q_type = question_info["type"]
        if q_type not in test_cases_by_type:
            test_cases_by_type[q_type] = []
        
        # AI에게 답변 받아오기 및 시험지(test_case) 만들기
        if q_type == "multi_turn_memory":
            turns = question_info["turns"]
            await npc_client.chat_heroine(player_id, heroine_id, turns[0]["content"])
            response = await npc_client.chat_heroine(player_id, heroine_id, turns[1]["content"])
            
            test_case = LLMTestCase(
                input=f"{turns[0]['content']} -> {turns[1]['content']}",
                actual_output=response["text"],
                context=[letia_persona, question_info["expected_behavior"]]
            )
        else:
            response = await npc_client.chat_heroine(
                player_id,
                heroine_id,
                question_info["turns"][0]["content"]
            )
            test_case = LLMTestCase(
                input=question_info["turns"][0]["content"],
                actual_output=response["text"],
                context=[letia_persona, question_info["expected_behavior"]]
            )
        
        # (시험지, 상세정보) 세트로 상자에 담기
        test_cases_by_type[q_type].append((test_case, question_info))
    
    run_evaluation_by_type(test_cases_by_type, "레티아")

@pytest.mark.asyncio
async def test_lupames_persona(npc_client, lupames_questions, lupames_persona):
    """루파메스 페르소나 평가 테스트"""
    player_id = "test_lupames_player"
    heroine_id = 2
    await npc_client.login(player_id)
    
    test_cases_by_type = {}
    
    for question_info in lupames_questions:
        q_type = question_info["type"]
        if q_type not in test_cases_by_type:
            test_cases_by_type[q_type] = []
        
        if q_type == "multi_turn_memory":
            turns = question_info["turns"]
            await npc_client.chat_heroine(player_id, heroine_id, turns[0]["content"])
            response = await npc_client.chat_heroine(player_id, heroine_id, turns[1]["content"])
            test_case = LLMTestCase(
                input=f"{turns[0]['content']} -> {turns[1]['content']}",
                actual_output=response["text"],
                context=[lupames_persona, question_info["expected_behavior"]]
            )
        else:
            response = await npc_client.chat_heroine(
                player_id,
                heroine_id,
                question_info["turns"][0]["content"]
            )
            test_case = LLMTestCase(
                input=question_info["turns"][0]["content"],
                actual_output=response["text"],
                context=[lupames_persona, question_info["expected_behavior"]]
            )
        
        test_cases_by_type[q_type].append((test_case, question_info))
    
    run_evaluation_by_type(test_cases_by_type, "루파메스")


@pytest.mark.asyncio
async def test_roco_persona(npc_client, roco_questions, roco_persona):
    """로코 페르소나 평가 테스트"""
    player_id = "test_roco_player"
    heroine_id = 3
    await npc_client.login(player_id)
    
    test_cases_by_type = {}
    
    for question_info in roco_questions:
        q_type = question_info["type"]
        if q_type not in test_cases_by_type:
            test_cases_by_type[q_type] = []
        
        if q_type == "multi_turn_memory":
            turns = question_info["turns"]
            await npc_client.chat_heroine(player_id, heroine_id, turns[0]["content"])
            response = await npc_client.chat_heroine(player_id, heroine_id, turns[1]["content"])
            test_case = LLMTestCase(
                input=f"{turns[0]['content']} -> {turns[1]['content']}",
                actual_output=response["text"],
                context=[roco_persona, question_info["expected_behavior"]]
            )
        else:
            response = await npc_client.chat_heroine(
                player_id,
                heroine_id,
                question_info["turns"][0]["content"]
            )
            test_case = LLMTestCase(
                input=question_info["turns"][0]["content"],
                actual_output=response["text"],
                context=[roco_persona, question_info["expected_behavior"]]
            )
        
        test_cases_by_type[q_type].append((test_case, question_info))
    
    run_evaluation_by_type(test_cases_by_type, "로코")


@pytest.mark.asyncio
async def test_satra_persona(npc_client, satra_questions, satra_persona):
    """사트라 페르소나 평가 테스트"""
    player_id = "test_satra_player"
    await npc_client.login(player_id, scenario_level=1)
    
    test_cases_by_type = {}
    
    for question_info in satra_questions:
        q_type = question_info["type"]
        if q_type not in test_cases_by_type:
            test_cases_by_type[q_type] = []
        
        if q_type == "multi_turn_memory":
            turns = question_info["turns"]
            await npc_client.chat_sage(player_id, turns[0]["content"])
            response = await npc_client.chat_sage(player_id, turns[1]["content"])
            test_case = LLMTestCase(
                input=f"{turns[0]['content']} -> {turns[1]['content']}",
                actual_output=response["text"],
                context=[satra_persona, question_info["expected_behavior"]]
            )
        else:
            response = await npc_client.chat_sage(
                player_id,
                question_info["turns"][0]["content"]
            )
            test_case = LLMTestCase(
                input=question_info["turns"][0]["content"],
                actual_output=response["text"],
                context=[satra_persona, question_info["expected_behavior"]]
            )
        
        test_cases_by_type[q_type].append((test_case, question_info))
    
    run_evaluation_by_type(test_cases_by_type, "사트라")

