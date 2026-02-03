"""
HeroineScenarioRetriever - 히로인 시나리오 검색 전문 클래스

히로인의 과거/비밀에 대한 질문이 들어왔을 때 시나리오 DB를 검색합니다.

주요 기능:
1. PGroonga + Vector 하이브리드 검색
2. 최근 해금된 기억에 대한 꼬리질문 처리
3. 기억진척도(memoryProgress) 기반 접근 제어

이 클래스가 없을 경우 발생할 문제:
- 시나리오 검색 로직 수정 시 HeroineAgent 전체 수정 필요
- 검색 전략 테스트가 Agent에 종속됨
"""

from typing import Optional, List, Dict, Any

from services.heroine_scenario_service import heroine_scenario_service


class HeroineScenarioRetriever:
    """히로인 시나리오 검색 전문 클래스

    기억진척도(memoryProgress) 이하로 해금된 시나리오를 검색합니다.
    꼬리질문과 최근 기억 질문에 대해 특별 처리를 수행합니다.

    아키텍처 위치:
    - HeroineAgent의 시나리오 검색 책임을 위임받음
    - heroine_scenario_service와 직접 통신

    사용 예시:
        retriever = HeroineScenarioRetriever()
        scenario = await retriever.retrieve(
            user_message="고향이 어디야?",
            npc_id=1,
            memory_progress=50,
            recently_unlocked=None
        )
    """

    # 최근 기억 관련 키워드
    RECENT_MEMORY_KEYWORDS = [
        "최근",
        "돌아온 기억",
        "새로 기억",
        "떠오른 기억",
        "방금 기억",
        "이제 기억",
        "생각난",
        "떠올랐",
    ]

    # 꼬리질문 키워드
    FOLLOW_UP_KEYWORDS = [
        "그때",
        "그거",
        "그게",
        "그건",
        "방금",
        "아까",
        "그것",
        "그 이야기",
        "그 기억",
        "더 알려줘",
        "더 말해줘",
        "자세히",
    ]

    async def retrieve(
        self,
        user_message: str,
        npc_id: int,
        memory_progress: int,
        recently_unlocked: Optional[Dict[str, Any]] = None,
    ) -> str:
        """시나리오 검색

        우선순위:
        1. recently_unlocked가 있고 꼬리질문이면 -> 해당 시나리오 우선
        2. "최근에 돌아온 기억" 질문이면 -> 가장 최근 해금된 시나리오
        3. 일반 시나리오 질문 -> PGroonga + Vector 하이브리드 검색

        Args:
            user_message: 사용자 메시지
            npc_id: 히로인 ID
            memory_progress: 현재 기억진척도 (이 값 이하의 시나리오만 검색)
            recently_unlocked: 최근 해금된 기억 정보 (TTL 기반)

        Returns:
            검색된 시나리오 텍스트 또는 "해금된 시나리오 없음"
        """
        # 1. 꼬리질문 + recently_unlocked 존재
        if recently_unlocked and self._is_follow_up_question(user_message):
            scenario = self._get_unlocked_scenario(npc_id, recently_unlocked)
            if scenario:
                print(
                    f"[DEBUG] 꼬리질문 감지 - recently_unlocked_memory 시나리오 반환: {scenario.get('title', 'N/A')}"
                )
                return scenario["content"]

        # 2. 최근 기억 질문
        if self._is_recent_memory_question(user_message):
            latest_scenario = heroine_scenario_service.get_latest_unlocked_scenario(
                heroine_id=npc_id,
                max_memory_progress=memory_progress,
            )
            if latest_scenario:
                print(
                    f"[DEBUG] 최근 기억 질문 감지 - 최신 시나리오 반환: {latest_scenario.get('title', 'N/A')}"
                )
                return latest_scenario["content"]
            return "해금된 시나리오 없음"

        # 3. 일반 시나리오 질문 - PGroonga + Vector 하이브리드 검색
        scenarios = heroine_scenario_service.search_scenarios_pgroonga(
            query=user_message,
            heroine_id=npc_id,
            max_memory_progress=memory_progress,
            limit=2,
        )

        if scenarios:
            return "\n\n".join([s["content"] for s in scenarios])

        return "해금된 시나리오 없음"

    def _is_recent_memory_question(self, message: str) -> bool:
        """최근 기억 관련 질문인지 확인

        Args:
            message: 사용자 메시지

        Returns:
            최근 기억 질문 여부
        """
        return any(keyword in message for keyword in self.RECENT_MEMORY_KEYWORDS)

    def _is_follow_up_question(self, message: str) -> bool:
        """꼬리질문(지시어 포함)인지 확인

        "그때", "그거" 같은 지시어가 포함된 질문을 감지합니다.

        Args:
            message: 사용자 메시지

        Returns:
            꼬리질문 여부
        """
        return any(keyword in message for keyword in self.FOLLOW_UP_KEYWORDS)

    def _get_unlocked_scenario(
        self, npc_id: int, recently_unlocked: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """해금된 시나리오 조회

        Args:
            npc_id: 히로인 ID
            recently_unlocked: 최근 해금된 기억 정보

        Returns:
            시나리오 딕셔너리 또는 None
        """
        unlocked_progress = recently_unlocked.get("memory_progress")
        if unlocked_progress is None:
            return None

        return heroine_scenario_service.get_scenario_by_exact_progress(
            heroine_id=npc_id, memory_progress=unlocked_progress
        )


# 싱글톤 인스턴스
heroine_scenario_retriever = HeroineScenarioRetriever()
