"""
NPC 페르소나 평가를 위한 커스텀 메트릭

DeepEval의 G-Eval을 활용하여 NPC의 페르소나 일관성, 역할 몰입도, 지식 경계를 평가합니다.
"""

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams
from .custom_llm import evaluator_llm


# ============================================
# 1. 페르소나 일관성 (Persona Consistency)
# ============================================

persona_consistency_metric = GEval(
    name="PersonaConsistency",
    criteria="""캐릭터의 성격, 말투, 트라우마 반응이 페르소나 정의와 일치하는지 평가합니다.
    
평가 항목:
- 말투: 존댓말/반말 사용이 페르소나 정의와 일치하는가?
- 성격: 캐릭터의 성격 특성(소심함, 열정적, 무뚝뚝함 등)이 응답에 반영되었는가?
- 트라우마 반응: 트라우마 키워드 언급 시 적절한 불안, 회피, 감정 변화를 보이는가?
- 금지 표현: 페르소나에서 금지한 표현(ㅋㅋ, ㅎㅎ, 넘, 겁나 등)을 사용하지 않았는가?
""",
    evaluation_steps=[
        "페르소나 정의에서 말투(존댓말/반말) 설정을 확인하고, 응답의 말투가 일치하는지 검증",
        "페르소나의 성격 특성(예: 무뚝뚝함, 열정적, 소심함)이 응답의 어조와 내용에 반영되었는지 확인",
        "입력에 트라우마 키워드가 포함된 경우, 캐릭터가 적절한 감정 반응(불안, 회피, 단답형)을 보이는지 확인",
        "페르소나에서 금지한 표현이나 어투를 사용하지 않았는지 확인",
        "호감도 레벨에 따른 응답 스타일이 적절한지 확인 (low/mid/high/max)"
    ],
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.CONTEXT],
    threshold=0.7,
    model=evaluator_llm
)


# ============================================
# 2. 역할 몰입도 (Role Adherence)
# ============================================

role_adherence_metric = GEval(
    name="RoleAdherence",
    criteria="""캐릭터가 AI임을 드러내지 않고 완전히 캐릭터에 몰입하여 응답하는지 평가합니다.
    
평가 항목:
- AI 정체성 노출: "저는 AI입니다", "언어 모델", "프롬프트" 등의 표현 사용 여부
- 메타 인지: 자신이 게임 캐릭터임을 인지하는 발언 여부
- 세계관 일관성: 캐릭터가 속한 세계관(레테 행성, 암네시아 등) 내에서만 발언하는가?
- 캐릭터 정체성: 자신의 이름, 배경, 상황을 캐릭터 설정에 맞게 인식하는가?
""",
    evaluation_steps=[
        "응답에 'AI', '언어 모델', '프롬프트', 'ChatGPT', '학습 데이터' 등 AI 관련 용어가 포함되었는지 확인",
        "캐릭터가 자신을 게임 NPC나 가상 존재로 인식하는 메타적 발언이 있는지 확인",
        "응답이 캐릭터가 속한 세계관(중세 판타지, 레테 행성) 내에서만 이루어졌는지 확인",
        "캐릭터가 자신의 이름, 배경, 현재 상황을 설정에 맞게 인식하고 있는지 확인",
        "사용자의 '너 AI지?' 같은 질문에 캐릭터로서 당황하거나 이해하지 못하는 반응을 보이는지 확인"
    ],
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
    threshold=0.8,
    model=evaluator_llm
)


# ============================================
# 3. 지식 경계 (Knowledge Boundary)
# ============================================

knowledge_boundary_metric = GEval(
    name="KnowledgeBoundary",
    criteria="""캐릭터가 알 수 없는 지식(현대 기술, 해금되지 않은 기억)을 말하지 않는지 평가합니다.
    
평가 항목:
- 현대 지식: 아이폰, 비행기, 인터넷 등 중세 판타지 세계관에 없는 지식 언급 여부
- 해금되지 않은 기억: memory_progress보다 높은 레벨의 시나리오 정보 언급 여부
- 시대 착오: 캐릭터가 알 수 없는 미래나 현대의 개념 사용 여부
- 적절한 무지: 모르는 것은 "모르겠어요", "기억나지 않아요"로 답하는가?
""",
    evaluation_steps=[
        "응답에 현대 기술(스마트폰, 컴퓨터, 인터넷, 비행기 등)이나 현대 개념이 포함되었는지 확인",
        "캐릭터의 memory_progress 레벨보다 높은 시나리오 정보를 언급했는지 확인",
        "중세 판타지 세계관에 존재하지 않는 개념이나 물건을 언급했는지 확인",
        "모르는 것에 대해 캐릭터답게 '기억나지 않아요', '모르겠어요' 등으로 답했는지 확인",
        "대현자의 경우 scenario_level에 따라 금지된 정보를 회피했는지 확인"
    ],
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.CONTEXT],
    threshold=0.8,
    model=evaluator_llm
)



# ============================================
# 4. 대화 기억 (Conversation Memory)
# ============================================

conversation_memory_metric = GEval(
    name="ConversationMemory",
    criteria="""캐릭터가 대화 중 플레이어가 제공한 정보를 정확히 기억하고 활용하는지 평가합니다.
    
평가 항목:
- 이름 기억: 플레이어가 알려준 이름을 정확히 기억하는가?
- 정보 유지: 대화 중 언급된 정보(좋아하는 것, 싫어하는 것 등)를 기억하는가?
- 맥락 연결: 이전 대화 내용과 현재 응답이 자연스럽게 연결되는가?
- 일관성: 기억한 정보를 왜곡하거나 변형하지 않았는가?
""",
    evaluation_steps=[
        "입력에서 플레이어가 제공한 정보(이름, 취향, 사실 등)를 파악",
        "응답에서 해당 정보를 정확히 언급하거나 활용했는지 확인",
        "정보를 왜곡하거나 다르게 기억한 부분이 있는지 확인",
        "대화 맥락이 자연스럽게 이어지는지 확인",
        "기억해야 할 정보를 무시하거나 잊어버린 것처럼 응답했는지 확인"
    ],
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.CONTEXT],
    threshold=0.8,
    model=evaluator_llm
)


# ============================================
# 메트릭 리스트 (테스트에서 사용)
# ============================================

ALL_METRICS = [
    persona_consistency_metric,
    role_adherence_metric,
    knowledge_boundary_metric,
    conversation_memory_metric
]

# ============================================
# 테스트 유형별 메트릭 매핑
# ============================================

METRICS_BY_TYPE = {
    "general": [persona_consistency_metric, role_adherence_metric, knowledge_boundary_metric],
    "persona_test": [persona_consistency_metric, role_adherence_metric],
    "persona_break": [persona_consistency_metric, role_adherence_metric, knowledge_boundary_metric],
    "memory": [persona_consistency_metric, knowledge_boundary_metric],
    "knowledge_boundary": [persona_consistency_metric, role_adherence_metric, knowledge_boundary_metric],
    "multi_turn_memory": [persona_consistency_metric, role_adherence_metric, conversation_memory_metric],
}

# 테스트 유형별 주요 메트릭 (60% 가중치)
PRIMARY_METRIC_BY_TYPE = {
    "general": "PersonaConsistency",
    "persona_test": "PersonaConsistency",
    "persona_break": "RoleAdherence",
    "memory": "KnowledgeBoundary",
    "knowledge_boundary": "KnowledgeBoundary",
    "multi_turn_memory": "ConversationMemory",
}


def get_metrics_for_type(question_type):
    """테스트 유형에 맞는 메트릭 리스트 반환"""
    return METRICS_BY_TYPE.get(question_type, ALL_METRICS)


def get_primary_metric(question_type):
    """테스트 유형의 주요 메트릭 이름 반환"""
    return PRIMARY_METRIC_BY_TYPE.get(question_type, "PersonaConsistency")


def calculate_weighted_score(question_type, metric_scores):
    """
    주요 메트릭 60%, 보조 메트릭들 40% 균등 분배로 가중 점수 계산
    
    Args:
        question_type: 테스트 유형
        metric_scores: {"MetricName": score, ...} 딕셔너리
    
    Returns:
        가중 평균 점수 (0.0 ~ 1.0)
    """
    primary_metric = get_primary_metric(question_type)
    primary_weight = 0.6
    secondary_weight = 0.4
    
    primary_score = metric_scores.get(primary_metric, 0.0)
    
    secondary_scores = [
        score for name, score in metric_scores.items() 
        if name != primary_metric
    ]
    # 1. 보조 메트릭 전체 점수의 평균
    if secondary_scores:
        secondary_avg = sum(secondary_scores) / len(secondary_scores)
    else:
        # 만약 보조 메트릭이 하나도 없다면 0점으로 처리 (0으로 나누면 에러 생기므로)
        secondary_avg = 0.0
    # 2. 최종 가중치 합산 (주요 메트릭 60% + 보조 메트릭 평균 40%)
    weighted_score = (primary_score * primary_weight) + (secondary_avg * secondary_weight)
    return weighted_score

