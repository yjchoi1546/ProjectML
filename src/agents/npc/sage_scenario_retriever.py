"""
SageScenarioRetriever - 대현자 시나리오 검색 전문 클래스

세계관 관련 질문이 들어왔을 때 시나리오 DB를 검색합니다.

주요 기능:
1. 시나리오 레벨(scenarioLevel) 기반 접근 제어
2. 세계관 정보 검색

이 클래스가 없을 경우 발생할 문제:
- 시나리오 검색 로직 수정 시 SageAgent 전체 수정 필요
- 검색 전략 테스트가 Agent에 종속됨
"""

from typing import List, Dict, Any

from services.sage_scenario_service import sage_scenario_service


class SageScenarioRetriever:
    """대현자 시나리오 검색 전문 클래스

    시나리오 레벨(scenarioLevel) 이하로 해금된 세계관 정보를 검색합니다.

    아키텍처 위치:
    - SageAgent의 시나리오 검색 책임을 위임받음
    - sage_scenario_service와 직접 통신

    사용 예시:
        retriever = SageScenarioRetriever()
        scenario = await retriever.retrieve(
            user_message="던전이 뭐야?",
            scenario_level=3
        )
    """

    async def retrieve(
        self,
        user_message: str,
        scenario_level: int,
        limit: int = 2,
    ) -> str:
        """시나리오 검색

        현재 시나리오 레벨 이하로 해금된 시나리오를 검색합니다.

        Args:
            user_message: 사용자 메시지
            scenario_level: 현재 시나리오 레벨 (이 값 이하의 시나리오만 검색)
            limit: 검색 결과 개수 제한

        Returns:
            검색된 시나리오 텍스트 또는 "해금된 정보 없음"
        """
        scenarios = sage_scenario_service.search_scenarios(
            query=user_message,
            max_scenario_level=scenario_level,
            limit=limit
        )

        if scenarios:
            return "\n\n".join([s["content"] for s in scenarios])

        return "해금된 정보 없음"


# 싱글톤 인스턴스
sage_scenario_retriever = SageScenarioRetriever()
