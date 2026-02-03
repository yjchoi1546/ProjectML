"""
LangFuse 토큰 추적 유틸리티 (v3 API 호환)

모든 LLM 호출 지점에서 사용할 수 있는 공통 콜백 핸들러 및 메타데이터 관리

이 모듈이 없을 경우 발생하는 문제:
- 각 LLM 호출 지점에서 개별적으로 콜백을 설정해야 함
- 일관된 태깅/세션 관리가 어려움
- 코드 중복 발생
- 토큰 사용량 및 비용 추적 불가

LangFuse v3 API 변경사항:
- CallbackHandler()는 인자를 받지 않음 (싱글톤 패턴)
- session_id, user_id, tags는 metadata로 invoke 시점에 전달
- metadata 키: langfuse_session_id, langfuse_user_id, langfuse_tags
"""

import os
from typing import Optional, Dict, Any, List

# LangFuse 초기화 (환경 변수 기반)
try:
    from langfuse import Langfuse, get_client
    from langfuse.langchain import CallbackHandler
    
    # 싱글톤 클라이언트 초기화
    # 환경 변수: LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_HOST
    _langfuse_client = Langfuse()
    _langfuse_handler = CallbackHandler()  # v3: 인자 없음
    LANGFUSE_ENABLED = True
    print("[INFO] LangFuse 토큰 추적 활성화됨 (v3 API)")
except Exception as e:
    _langfuse_client = None
    _langfuse_handler = None
    LANGFUSE_ENABLED = False
    print(f"[WARNING] LangFuse 비활성화: {e}")


class TokenTracker:
    """
    LangFuse 토큰 추적을 위한 유틸리티 클래스 (v3 API 호환)
    
    LangFuse v3 변경사항:
    - CallbackHandler()는 싱글톤 (인자 없음)
    - session_id, user_id, tags는 metadata로 전달
    
    사용 예시:
        from utils.langfuse_tracker import tracker
        
        config = tracker.get_langfuse_config(
            tags=["npc", "heroine"],
            session_id=session_id,
            user_id=user_id,
        )
        
        response = await llm.ainvoke(prompt, **config)
    """
    
    @staticmethod
    def get_callback_handler() -> Optional[CallbackHandler]:
        """
        LangFuse 콜백 핸들러 반환 (v3: 싱글톤)
        
        LangFuse v3에서는 CallbackHandler()가 인자를 받지 않습니다.
        모든 속성(session_id, user_id, tags)은 invoke 시점에 
        metadata로 전달해야 합니다.
        
        Returns:
            LangFuse CallbackHandler 또는 None (비활성화 시)
        """
        if not LANGFUSE_ENABLED:
            return None
            
        return _langfuse_handler
    
    @staticmethod
    def build_metadata(
        tags: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        custom_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        LangFuse v3 metadata 딕셔너리 생성
        
        LangFuse v3에서는 session_id, user_id, tags를 
        특정 키 이름으로 metadata에 넣어야 합니다.
        
        Args:
            tags: 태그 리스트 (예: ["npc", "heroine", "letia"])
            session_id: 세션 ID
            user_id: 사용자 ID
            custom_metadata: 추가 메타데이터 (예: {"heroine_name": "letia"})
            
        Returns:
            LangFuse metadata 딕셔너리
        """
        metadata = {}
        
        if session_id:
            metadata["langfuse_session_id"] = session_id
        if user_id:
            metadata["langfuse_user_id"] = user_id
        if tags:
            metadata["langfuse_tags"] = tags
        
        # 커스텀 메타데이터 병합
        if custom_metadata:
            metadata.update(custom_metadata)
        
        return metadata
    
    @staticmethod
    def get_langfuse_config(
        tags: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        LangChain invoke용 config 딕셔너리 반환 (v3 호환)
        
        이 메서드가 없을 경우 발생하는 문제:
        - LangFuse에서 토큰 사용량을 추적할 수 없음
        - API 비용 분석 불가
        - 세션별/유저별 필터링 불가
        
        사용 예시:
            config = tracker.get_langfuse_config(
                tags=["npc", "heroine", "letia"],
                session_id=state.get("session_id"),
                user_id=state.get("user_id"),
                metadata={"heroine_name": "letia", "affection": 50}
            )
            
            response = await llm.ainvoke(prompt, **config)
            
        Args:
            tags: 태그 리스트 (LangFuse 필터링용)
            session_id: 세션 ID (동일 세션의 LLM 호출 그룹화)
            user_id: 사용자 ID (유저별 비용 분석)
            metadata: 추가 메타데이터 (커스텀 분석용)
            
        Returns:
            {"config": {"callbacks": [handler], "metadata": {...}}} 
            또는 {} (비활성화 시)
        """
        if not LANGFUSE_ENABLED:
            return {}
        
        # LangFuse metadata 생성
        langfuse_metadata = TokenTracker.build_metadata(
            tags=tags,
            session_id=session_id,
            user_id=user_id,
            custom_metadata=metadata,
        )
        
        return {
            "config": {
                "callbacks": [_langfuse_handler],
                "metadata": langfuse_metadata
            }
        }
    
    @staticmethod
    def flush():
        """
        보류 중인 모든 이벤트를 LangFuse에 전송
        
        이 메서드가 없을 경우 발생하는 문제:
        - 단기 실행 스크립트에서 이벤트가 전송되지 않을 수 있음
        - 서버 종료 시 일부 이벤트가 유실될 수 있음
        
        사용 시점:
        - 테스트 종료 시
        - 스크립트 종료 전
        - 중요한 이벤트 직후 (선택적)
        """
        if LANGFUSE_ENABLED and _langfuse_client:
            _langfuse_client.flush()
    
    @staticmethod
    def shutdown():
        """
        LangFuse 클라이언트 종료
        
        이 메서드가 없을 경우 발생하는 문제:
        - 백그라운드 스레드가 정리되지 않을 수 있음
        - 리소스 누수 가능성
        
        사용 시점:
        - 애플리케이션 종료 시 (FastAPI shutdown 이벤트 등)
        - 테스트 스위트 종료 시
        """
        if LANGFUSE_ENABLED and _langfuse_client:
            _langfuse_client.shutdown()


# 편의를 위한 싱글톤 인스턴스
# 모든 모듈에서 "from utils.langfuse_tracker import tracker"로 임포트
tracker = TokenTracker()
