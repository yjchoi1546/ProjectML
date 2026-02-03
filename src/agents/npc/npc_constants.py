"""
NPC 관련 공통 상수

NPC 시스템 전반에서 사용되는 상수들을 중앙 관리합니다.
새로운 NPC 추가 시 이 파일만 수정하면 됩니다.
"""

from typing import Dict

# ============================================
# NPC ID 매핑
# ============================================

# NPC ID -> 영문 이름 (파일명, 로그용)
NPC_ID_TO_NAME_EN: Dict[int, str] = {
    0: "sage_satra",
    1: "heroine_retia",
    2: "heroine_lupames",
    3: "heroine_roco",
}

# NPC ID -> 한글 이름 (UI, 대화용)
NPC_ID_TO_NAME_KR: Dict[int, str] = {
    0: "사트라",
    1: "레티아",
    2: "루파메스",
    3: "로코",
}

# 역방향 매핑 (이름 -> ID)
NPC_NAME_KR_TO_ID: Dict[str, int] = {v: k for k, v in NPC_ID_TO_NAME_KR.items()}

# ============================================
# NPC 타입 분류
# ============================================

NPC_TYPE_SAGE = 0  # 대현자 사트라
NPC_TYPE_HEROINES = [1, 2, 3]  # 히로인들 (레티아, 루파메스, 로코)

def is_sage(npc_id: int) -> bool:
    """대현자인지 확인
    
    Args:
        npc_id: NPC ID
    
    Returns:
        대현자 여부
    """
    return npc_id == NPC_TYPE_SAGE

def is_heroine(npc_id: int) -> bool:
    """히로인인지 확인
    
    Args:
        npc_id: NPC ID
    
    Returns:
        히로인 여부
    """
    return npc_id in NPC_TYPE_HEROINES
