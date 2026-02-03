"""
NPC API 호출 클라이언트

실제 NPC 엔드포인트를 호출하여 응답을 획득하는 클라이언트
"""

import httpx
from typing import Dict, Any, Optional


class NPCClient:
    """
    NPC API 호출을 위한 클라이언트
    
    실제 NPC 시스템의 엔드포인트를 호출하여 응답을 받습니다.
    """
    
    def __init__(self, base_url: str = "http://localhost:8091"):
        """
        Args:
            base_url: NPC API 서버의 기본 URL
        """
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def login(
        self,
        player_id: str,
        scenario_level: int = 1,
        heroines: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        플레이어 로그인 및 세션 초기화
        
        Args:
            player_id: 플레이어 ID
            scenario_level: 대현자 시나리오 레벨
            heroines: 히로인 초기 상태 리스트
            
        Returns:
            로그인 응답
        """
        if heroines is None: # 기본 세팅값
            heroines = [
                {"heroineId": 1, "affection": 50, "memoryProgress": 30, "sanity": 100},
                {"heroineId": 2, "affection": 50, "memoryProgress": 30, "sanity": 100},
                {"heroineId": 3, "affection": 50, "memoryProgress": 30, "sanity": 100}
            ]
                
# /api/npc/login 엔드포인트에 플레이어 ID, 시나리오 레벨, 히로인 상태 정보를 NPC 서버에 전달해서 세션을 초기화(로그인)합니다.
        response = await self.client.post(
            f"{self.base_url}/api/npc/login",
            json={
                "playerId": player_id,
                "scenarioLevel": scenario_level,
                "heroines": heroines
            }
        )
        response.raise_for_status() # 응답 상태 코드가 200이 아니면 예외를 발생시킵니다. 응답이 정상인지 체크
        return response.json()
    
    async def chat_heroine(
        self,
        player_id: str,
        heroine_id: int,
        text: str
    ) -> Dict[str, Any]:
        """
        히로인과 대화 (동기 방식)
        
        Args:
            player_id: 플레이어 ID
            heroine_id: 히로인 ID (1=레티아, 2=루파메스, 3=로코)
            text: 사용자 메시지
            
        Returns:
            히로인 응답 (text, emotion, affection, sanity, memoryProgress)
        """
        response = await self.client.post(
            f"{self.base_url}/api/npc/heroine/chat/sync",
            json={
                "playerId": player_id,
                "heroineId": heroine_id,
                "text": text
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def chat_sage(
        self,
        player_id: str,
        text: str
    ) -> Dict[str, Any]:
        """
        대현자와 대화 (동기 방식)
        
        Args:
            player_id: 플레이어 ID
            text: 사용자 메시지
            
        Returns:
            대현자 응답 (text, emotion, scenarioLevel, infoRevealed)
        """
        response = await self.client.post(
            f"{self.base_url}/api/npc/sage/chat/sync",
            json={
                "playerId": player_id,
                "text": text
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def get_session(
        self,
        player_id: str,
        npc_id: int
    ) -> Dict[str, Any]:
        """
        세션 정보 조회
        
        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID (0=사트라, 1=레티아, 2=루파메스, 3=로코)
            
        Returns:
            세션 정보
        """
        response = await self.client.get(
            f"{self.base_url}/api/npc/session/{player_id}/{npc_id}"
        )
        response.raise_for_status()
        return response.json()
    
    async def close(self):
        """클라이언트 연결 종료"""
        await self.client.aclose()
    
    async def __aenter__(self):
        """비동기 컨텍스트 매니저 진입"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """비동기 컨텍스트 매니저 종료"""
        await self.close()
