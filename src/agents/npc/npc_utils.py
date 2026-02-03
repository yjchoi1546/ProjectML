"""
NPC Agent 공통 유틸리티 함수

여러 Agent에서 공통으로 사용되는 헬퍼 함수들을 정의합니다.
"""

import json
import yaml
from pathlib import Path
from typing import Dict, Any


def parse_llm_json_response(content: str, default: Dict[str, Any] = None) -> Dict[str, Any]:
    """LLM 응답에서 JSON을 파싱합니다.
    
    LLM이 ```json 블록으로 감싸거나 일반 텍스트로 응답할 수 있으므로
    여러 케이스를 처리합니다.
    
    Args:
        content: LLM 응답 문자열
        default: 파싱 실패 시 반환할 기본값 (None이면 빈 딕셔너리)
    
    Returns:
        파싱된 JSON 딕셔너리
    
    Examples:
        >>> parse_llm_json_response('{"text": "hello"}')
        {'text': 'hello'}
        
        >>> parse_llm_json_response('```json\\n{"text": "hello"}\\n```')
        {'text': 'hello'}
    """
    if default is None:
        default = {}
    
    try:
        # ```json 블록 제거
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        # ``` 블록 제거
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        # JSON 파싱
        return json.loads(content.strip())
    
    except (json.JSONDecodeError, IndexError):
        return default


def load_persona_yaml(persona_file_name: str, default_persona_func=None) -> Dict[str, Any]:
    """페르소나 YAML 파일을 로드합니다.
    
    파일이 없거나 오류가 있으면 기본값을 반환합니다.
    
    Args:
        persona_file_name: 페르소나 파일명 (예: "heroine_persona.yaml", "sage_persona.yaml")
        default_persona_func: 파일 로드 실패 시 호출할 기본값 생성 함수
    
    Returns:
        페르소나 데이터 딕셔너리
    
    Examples:
        >>> load_persona_yaml("heroine_persona.yaml")
        {'letia': {...}, 'lupames': {...}, ...}
    """
    persona_path = (
        Path(__file__).parent.parent.parent
        / "prompts"
        / "prompt_type"
        / "npc"
        / persona_file_name
    )
    
    try:
        with open(persona_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"경고: 페르소나 파일을 찾을 수 없습니다: {persona_path}")
        return default_persona_func() if default_persona_func else {}
    except Exception as e:
        print(f"경고: 페르소나 로드 실패: {e}")
        return default_persona_func() if default_persona_func else {}
