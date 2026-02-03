"""
히로인간 대화 Agent

두 히로인 사이의 대화를 생성하고 저장합니다.

주요 기능:
1. 두 히로인간의 자연스러운 대화 생성
2. 대화 내용을 npc_npc_checkpoints 테이블에 저장 (대화 전체)
3. 대화 내용을 npc_npc_memories 테이블에 저장 (턴 단위 장기기억)

스트리밍/비스트리밍 동일 응답:
- 둘 다 동일한 프롬프트 사용
- 둘 다 DB에 저장
- 출력 형식만 다름 (스트리밍: 텍스트, 비스트리밍: JSON)

저장 위치:
- npc_npc_checkpoints: 대화 전체 기록
- npc_npc_memories: 장기기억(핵심/턴 단위)
"""

import asyncio
import json
import yaml
import time
from pathlib import Path
from datetime import datetime
from typing import List, AsyncIterator, Optional, Dict, Any, Tuple
from langchain.chat_models import init_chat_model
from enums.LLM import LLM
from agents.npc.emotion_mapper import heroine_emotion_to_int
from agents.npc.npc_utils import parse_llm_json_response, load_persona_yaml
from db.redis_manager import redis_manager
from db.npc_npc_memory_manager import npc_npc_memory_manager
from services.sage_scenario_service import sage_scenario_service
from services.heroine_scenario_service import heroine_scenario_service
from utils.langfuse_tracker import tracker


# ============================================
# 페르소나 데이터 로드
# ============================================

def _get_default_heroine_heroine_persona() -> Dict[str, Any]:
    """기본 페르소나 데이터 (파일 없을 때 사용)"""
    return {
        "letia": {
            "name": "레티아",
            "personality": {"base": "차갑고 무뚝뚝하지만 속정이 깊음"},
            "speech_style": {"honorific": False},
        },
        "lupames": {
            "name": "루파메스",
            "personality": {"base": "활발하고 호탕함"},
            "speech_style": {"honorific": False},
        },
        "roco": {
            "name": "로코",
            "personality": {"base": "순수하고 어린아이 같음"},
            "speech_style": {"honorific": True},
        },
        "satra": {
            "name": "사트라",
            "personality": {"base": "기품 있고 신비로운 대현자"},
            "speech_style": {"honorific": False},
        },
    }


# 페르소나 데이터 로드 (모듈 로드시 1회)
PERSONA_DATA = load_persona_yaml("heroine_persona.yaml", _get_default_heroine_heroine_persona)

# NPC ID -> 페르소나 키 매핑
# - 0: 대현자(사트라)
# - 1~3: 히로인
HEROINE_KEY_MAP = {0: "satra", 1: "letia", 2: "lupames", 3: "roco"}


class HeroineHeroineAgent:
    """히로인간 대화 Agent

    두 히로인 사이의 대화를 생성하고 저장합니다.
    스트리밍과 비스트리밍 모두 동일한 대화를 생성하고 DB에 저장합니다.

    사용 예시:
        agent = HeroineHeroineAgent()

        # 비스트리밍 (JSON 배열 반환)
        result = await agent.generate_and_save_conversation(player_id="10001", heroine1_id=1, heroine2_id=2)

        # 스트리밍 (텍스트 스트림 + DB 저장)
        async for chunk in agent.generate_conversation_stream(player_id="10001", heroine1_id=1, heroine2_id=2):
            print(chunk, end="")
    """

    def __init__(self, model_name: str = LLM.GROK_4_1_FAST_NON_REASONING):
        """초기화

        Args:
            model_name: 사용할 LLM 모델명
        """
        # 대화 생성용 LLM (temperature=0.8로 다양한 대화)
        self.llm = init_chat_model(model=model_name, temperature=1.0)

    # ============================================
    # 페르소나 및 관계 헬퍼 메서드
    # ============================================

    def _get_persona(self, heroine_id: int) -> Dict[str, Any]:
        """NPC 페르소나 가져오기

        Args:
            heroine_id: NPC ID (0=사트라, 1=레티아, 2=루파메스, 3=로코)

        Returns:
            페르소나 딕셔너리
        """
        key = HEROINE_KEY_MAP.get(heroine_id, "letia")
        return PERSONA_DATA.get(key, PERSONA_DATA.get("letia", {}))

    def _get_relationship(self, heroine1_id: int, heroine2_id: int) -> str:
        """두 히로인간의 관계 설명

        각 히로인이 상대방을 어떻게 생각하는지 반환합니다.

        Args:
            heroine1_id: 관점의 주체 히로인 ID
            heroine2_id: 관계 대상 히로인 ID

        Returns:
            관계 설명 문자열
        """
        if heroine1_id == 0 or heroine2_id == 0:
            return "대현자와 대화하는 관계"

        relationships = {
            (
                1,
                2,
            ): "라이벌이자 동료. 레티아는 루파메스를 시끄럽지만 믿을 수 있다고 생각함",
            (1, 3): "레티아는 로코를 보호해야 할 순수한 존재로 봄",
            (2, 1): "루파메스는 레티아를 재수없게 강하지만 믿을 수 있다고 생각함",
            (2, 3): "루파메스는 로코를 귀여운 동생처럼 대함. 맛있는 것을 많이 줌",
            (3, 1): "로코는 레티아 언니를 동경하지만 약간 무서워함",
            (3, 2): "로코는 루파메스 언니가 따뜻하다고 느낌. 맛있는 것도 많이 줌",
        }
        return relationships.get((heroine1_id, heroine2_id), "동료 관계")

    def _is_valid_situation(self, situation: str) -> bool:
        """situation이 유효한 값인지 확인

        None, 빈 문자열, "string" 같은 기본값은 무효로 처리

        Args:
            situation: 검사할 상황 문자열

        Returns:
            유효하면 True, 아니면 False
        """
        if situation is None:
            return False
        if not situation.strip():
            return False
        if situation.strip().lower() == "string":
            return False
        return True

    async def generate_situation(self) -> str:
        """대화 상황 자동 생성

        미리 정의된 상황 목록 중 하나를 선택하여 구체화합니다.

        Returns:
            구체적인 상황 설명 문자열
        """
        situations = [
            "셀레파이스 길드 휴게실에서 쉬는 중",
            "던전 탐험을 마치고 돌아온 직후",
            "함께 식사를 하는 중",
            "훈련장에서 훈련을 마친 후",
            "밤에 길드 옥상에서 별을 보는 중",
            "비가 와서 실내에 갇힌 상황",
            "서로의 기억을 공유하는 중",
        ]

        situations_text = "\n".join([f"- {s}" for s in situations])

        prompt = f"""다음 상황 목록 중 하나를 선택하고, 서로가 흥미롭게 대화 할만한 구체적인 상황 설명을 만들어주세요.

상황 목록:
{situations_text}

출력 형식:
선택한 상황과 함께 2-3문장으로 구체적인 상황을 설명하세요."""

        # LangFuse 토큰 추적 (v3 API)
        config = tracker.get_langfuse_config(
            tags=["npc", "heroine_heroine", "situation"],
            metadata={"action": "situation_generation"}
        )
        
        response = await self.llm.ainvoke(prompt, **config)
        return response.content

    # ============================================
    # 프롬프트 생성 (스트리밍/비스트리밍 공통)
    # ============================================

    def _build_conversation_prompt(
        self,
        heroine1_id: int,
        heroine2_id: int,
        situation: str,
        turn_count: int,
        memory_progress_1: int = 0,
        memory_progress_2: int = 0,
        sanity_1: int = 100,
        sanity_2: int = 100,
        recent_turns: Optional[List[Dict[str, Any]]] = None,
        unlocked_1_text: str = "없음",
        unlocked_2_text: str = "없음",
    ) -> str:
        """대화 생성 프롬프트

        Args:
            heroine1_id: 첫 번째 히로인 ID
            heroine2_id: 두 번째 히로인 ID
            situation: 대화 상황
            turn_count: 대화 턴 수

        Returns:
            프롬프트 문자열
        """
        if recent_turns is None:
            recent_turns = []

        persona1 = self._get_persona(heroine1_id)
        persona2 = self._get_persona(heroine2_id)

        relationship1to2 = self._get_relationship(heroine1_id, heroine2_id)
        relationship2to1 = self._get_relationship(heroine2_id, heroine1_id)

        honorific1 = (
            "존댓말"
            if persona1.get("speech_style", {}).get("honorific", False)
            else "반말"
        )
        honorific2 = (
            "존댓말"
            if persona2.get("speech_style", {}).get("honorific", False)
            else "반말"
        )

        name1 = persona1.get("name", "히로인1")
        name2 = persona2.get("name", "히로인2")

        # memoryProgress에 따른 아주 단순한 규칙 텍스트
        unlocked_rule = "해금되지 않은 과거/비밀은 말하지 않는다."
        min_progress = (
            memory_progress_1
            if memory_progress_1 < memory_progress_2
            else memory_progress_2
        )
        if min_progress < 30:
            unlocked_rule = "과거/비밀 이야기는 피하고, 현재 상황 중심으로만 말한다."
        if 30 <= min_progress < 70:
            unlocked_rule = "깊은 비밀은 피하되, 가벼운 과거 이야기는 할 수 있다."

        # liked_keywords 가져오기
        liked_keywords_1 = persona1.get("liked_keywords", [])
        liked_keywords_2 = persona2.get("liked_keywords", [])
        liked_text_1 = ", ".join(liked_keywords_1[:5]) if liked_keywords_1 else "없음"
        liked_text_2 = ", ".join(liked_keywords_2[:5]) if liked_keywords_2 else "없음"

        # sanity에 따른 대사 예시 선택
        # sanity가 0이면 sanity_responses.zero 사용, 아니면 affection_responses.mid 사용
        if sanity_1 == 0:
            sanity_resp_1 = persona1.get("sanity_responses", {}).get("zero", {})
            examples_1 = sanity_resp_1.get("examples", [])
            sanity_status_1 = "우울 (sanity 0)"
        else:
            affection_resp_1 = persona1.get("affection_responses", {}).get("mid", {})
            examples_1 = affection_resp_1.get("examples", [])
            sanity_status_1 = "정상"

        if sanity_2 == 0:
            sanity_resp_2 = persona2.get("sanity_responses", {}).get("zero", {})
            examples_2 = sanity_resp_2.get("examples", [])
            sanity_status_2 = "우울 (sanity 0)"
        else:
            affection_resp_2 = persona2.get("affection_responses", {}).get("mid", {})
            examples_2 = affection_resp_2.get("examples", [])
            sanity_status_2 = "정상"

        example_text_1 = (
            ", ".join([f'"{e}"' for e in examples_1[:3]]) if examples_1 else "없음"
        )
        example_text_2 = (
            ", ".join([f'"{e}"' for e in examples_2[:3]]) if examples_2 else "없음"
        )

        # 최근 대화 포맷 (간단)
        turn_lines = []
        for t in recent_turns:
            speaker_name = t.get("speaker_name", "")
            text_value = t.get("text", "")
            if speaker_name and text_value:
                turn_lines.append(f"{speaker_name}: {text_value}")
        # 토큰 최소화: 최근 6줄만
        recent_text = "\n".join(turn_lines[-6:]) if turn_lines else "없음"

        # 출력 형식
        output_format = f"""[출력 형식]
JSON 배열로 출력하세요:
[
    {{"speaker_id": {heroine1_id}, "speaker_name": "{name1}", "text": "대사", "emotion": "neutral|joy|fun|sorrow|angry|surprise|mysterious", "emotion_intensity": 0.5~2.0}},
    {{"speaker_id": {heroine2_id}, "speaker_name": "{name2}", "text": "대사", "emotion": "neutral|joy|fun|sorrow|angry|surprise|mysterious", "emotion_intensity": 0.5~2.0}},
    ...
]
(emotion_intensity: 0.5=약한 감정, 1.0=보통, 1.5=강함, 2.0=극도로 강함)"""

        prompt = f"""두 NPC 사이의 자연스러운 대화를 생성해주세요.

[규칙]
- 각 히로인의 성격과 말투를 일관되게 유지
- 서로의 관계를 반영한 자연스러운 대화
- [상황]에 맞게 다양한 주제와 흐름으로 대화 생성 (매번 같은 패턴 금지)
- 각 히로인의 [좋아하는 것]을 대화 소재로 자연스럽게 활용
- [대사 예시]의 톤과 스타일을 참고하되, 내용은 새롭게 생성
- {unlocked_rule}
- 전용 정보는 해당 화자만 참고 (예: {name1}의 대사에는 "{name1}만 사용" 섹션만, {name2}도 동일)
- 총 {turn_count}번의 대화 턴 (각 히로인이 번갈아 말함)

[상황]
{situation}

[현재 상태]
- {name1} memoryProgress: {memory_progress_1}
- {name2} memoryProgress: {memory_progress_2}

[전용 정보 - {name1}만 사용]
{unlocked_1_text}

[전용 정보 - {name2}만 사용]
{unlocked_2_text}

[최근 대화(세션)]
{recent_text}

[히로인 1: {name1}]
- 성격: {persona1.get('personality', {}).get('base', '')}
- 말투: {honorific1}
- 현재 상태: {sanity_status_1}
- {name2}에 대한 관계: {relationship1to2}
- 좋아하는 것: {liked_text_1}
- 대사 예시: {example_text_1}

[히로인 2: {name2}]
- 성격: {persona2.get('personality', {}).get('base', '')}
- 말투: {honorific2}
- 현재 상태: {sanity_status_2}
- {name1}에 대한 관계: {relationship2to1}
- 좋아하는 것: {liked_text_2}
- 대사 예시: {example_text_2}

{output_format}"""

        return prompt

    def _save_conversation_to_db(
        self,
        player_id: str,
        heroine1_id: int,
        heroine2_id: int,
        conversation: List[Dict[str, Any]],
        situation: str,
        importance_score: int = 5,
    ) -> str:
        """대화를 DB에 저장

        저장 내용:
        1. npc_npc_checkpoints: 대화 전체 기록 (동기)
        2. npc_npc_memories: LLM으로 중요 fact 추출 후 저장 (백그라운드)

        Args:
            heroine1_id: 첫 번째 히로인 ID
            heroine2_id: 두 번째 히로인 ID
            conversation: 대화 리스트
            situation: 대화 상황
            importance_score: 중요도 (1-10)

        Returns:
            저장된 대화 ID
        """
        # 1) 체크포인트 저장 (동기)
        checkpoint_id = npc_npc_memory_manager.save_checkpoint(
            player_id=str(player_id),
            npc1_id=heroine1_id,
            npc2_id=heroine2_id,
            situation=situation,
            conversation=conversation,
        )

        # 2) 장기기억 저장 (백그라운드)
        asyncio.create_task(
            self._save_to_npc_npc_memory_background(
                player_id=str(player_id),
                npc1_id=heroine1_id,
                npc2_id=heroine2_id,
                checkpoint_id=checkpoint_id,
                situation=situation,
                conversation=conversation,
            )
        )

        # 3) Redis에 NPC-NPC 세션 저장 (동기)
        session_data = {
            "player_id": str(player_id),
            "npc1_id": heroine1_id,
            "npc2_id": heroine2_id,
            "conversation_id": checkpoint_id,
            "situation": situation,
            "conversation_buffer": conversation,
            "turn_count": len(conversation),
            "interrupted_turn": None,
        }
        redis_manager.save_npc_npc_session(
            str(player_id), heroine1_id, heroine2_id, session_data
        )

        return checkpoint_id

    async def _save_to_npc_npc_memory_background(
        self,
        player_id: str,
        npc1_id: int,
        npc2_id: int,
        checkpoint_id: str,
        situation: str,
        conversation: List[Dict[str, Any]],
    ) -> None:
        """백그라운드로 NPC-NPC 장기기억 저장

        LLM으로 중요 fact 추출 후 저장

        Args:
            player_id: 플레이어 ID
            npc1_id: 첫 번째 NPC ID
            npc2_id: 두 번째 NPC ID
            checkpoint_id: 체크포인트 ID
            situation: 대화 상황
            conversation: 대화 리스트
        """
        try:
            inserted = await npc_npc_memory_manager.save_conversation(
                player_id=player_id,
                npc1_id=npc1_id,
                npc2_id=npc2_id,
                checkpoint_id=checkpoint_id,
                situation=situation,
                conversation=conversation,
            )
            print(f"[INFO] NPC-NPC 장기기억 저장 완료: {inserted}개 fact")
        except Exception as e:
            print(f"[ERROR] NPC-NPC 장기기억 저장 실패: {e}")

    # ============================================
    # 대화 생성 메서드
    # ============================================

    async def generate_conversation(
        self,
        player_id: Optional[str],
        heroine1_id: int,
        heroine2_id: int,
        situation: str = None,
        turn_count: int = 5,
    ) -> List[Dict[str, Any]]:
        """대화 생성 (비스트리밍, 저장 안함)

        DB 저장 없이 대화만 생성합니다.

        Args:
            heroine1_id: 첫 번째 히로인 ID
            heroine2_id: 두 번째 히로인 ID
            situation: 대화 상황 (None이면 자동 생성)
            turn_count: 대화 턴 수

        Returns:
            대화 리스트 (각 항목: speaker_id, speaker_name, text, emotion)
        """
        total_start = time.time()

        if not self._is_valid_situation(situation):
            t = time.time()
            situation = await self.generate_situation()
            print(f"[TIMING] NPC-NPC 상황 생성: {time.time() - t:.3f}s")

        memory_progress_1 = 0
        memory_progress_2 = 0
        sanity_1 = 100
        sanity_2 = 100
        recent_turns: List[Dict[str, Any]] = []
        unlocked_1_text = "없음"
        unlocked_2_text = "없음"

        if player_id is not None:
            t = time.time()
            session1 = redis_manager.load_session(str(player_id), heroine1_id) or {}
            session2 = redis_manager.load_session(str(player_id), heroine2_id) or {}
            state1 = session1.get("state", {}) if isinstance(session1, dict) else {}
            state2 = session2.get("state", {}) if isinstance(session2, dict) else {}
            print(f"[TIMING] NPC-NPC Redis 세션 로드: {time.time() - t:.3f}s")

            # sanity 값 가져오기 (NPC-NPC 대화에도 sanity 반영)
            sanity_1 = int(state1.get("sanity", 100))
            sanity_2 = int(state2.get("sanity", 100))

            # 히로인: memoryProgress로 "가장 최근 해금 시나리오 1개" 무조건 주입
            # 사트라(0): scenarioLevel로 "가장 최근 해금 세계관 1개" 무조건 주입
            t = time.time()
            if heroine1_id == 0:
                scenario_level = int(state1.get("scenarioLevel", 1) or 1)
                memory_progress_1 = scenario_level * 10
                latest = sage_scenario_service.get_latest_unlocked_scenario(
                    scenario_level
                )
                if latest and latest.get("content"):
                    unlocked_1_text = str(latest.get("content"))
            else:
                memory_progress_1 = int(state1.get("memoryProgress", 0) or 0)
                latest = heroine_scenario_service.get_latest_unlocked_scenario(
                    heroine_id=heroine1_id, max_memory_progress=memory_progress_1
                )
                if latest and latest.get("content"):
                    unlocked_1_text = str(latest.get("content"))

            if heroine2_id == 0:
                scenario_level = int(state2.get("scenarioLevel", 1) or 1)
                memory_progress_2 = scenario_level * 10
                latest = sage_scenario_service.get_latest_unlocked_scenario(
                    scenario_level
                )
                if latest and latest.get("content"):
                    unlocked_2_text = str(latest.get("content"))
            else:
                memory_progress_2 = int(state2.get("memoryProgress", 0) or 0)
                latest = heroine_scenario_service.get_latest_unlocked_scenario(
                    heroine_id=heroine2_id, max_memory_progress=memory_progress_2
                )
                if latest and latest.get("content"):
                    unlocked_2_text = str(latest.get("content"))
            print(f"[TIMING] NPC-NPC 최신 해금 1개 조회: {time.time() - t:.3f}s")

            t = time.time()
            npc_npc_session = redis_manager.load_npc_npc_session(
                str(player_id), heroine1_id, heroine2_id
            )
            if npc_npc_session:
                recent_turns = npc_npc_session.get("conversation_buffer", [])[-10:]
            print(f"[TIMING] NPC-NPC Redis pair 세션 로드: {time.time() - t:.3f}s")

        t = time.time()
        prompt = self._build_conversation_prompt(
            heroine1_id,
            heroine2_id,
            situation,
            turn_count,
            memory_progress_1=memory_progress_1,
            memory_progress_2=memory_progress_2,
            sanity_1=sanity_1,
            sanity_2=sanity_2,
            recent_turns=recent_turns,
            unlocked_1_text=unlocked_1_text,
            unlocked_2_text=unlocked_2_text,
        )
        print(f"[TIMING] NPC-NPC 프롬프트 빌드: {time.time() - t:.3f}s")
        print(f"[PROMPT][NPC-NPC]\n{prompt}\n{'='*50}")

        t = time.time()
        
        # LangFuse 토큰 추적 (v3 API)
        config = tracker.get_langfuse_config(
            tags=["npc", "heroine_heroine", "conversation"],
            metadata={
                "heroine1_id": heroine1_id,
                "heroine2_id": heroine2_id,
                "turn_count": turn_count,
            }
        )
        
        response = await self.llm.ainvoke(prompt, **config)
        
        # 로컬 디버깅용 토큰 로깅
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            print(f"[TOKEN] heroine_heroine - "
                  f"input: {response.usage_metadata.get('input_tokens', 'N/A')}, "
                  f"output: {response.usage_metadata.get('output_tokens', 'N/A')}")
        
        print(f"[TIMING] NPC-NPC LLM 호출: {time.time() - t:.3f}s")

        # JSON 파싱
        t = time.time()
        persona1 = self._get_persona(heroine1_id)
        persona2 = self._get_persona(heroine2_id)
        
        # 기본값 (파싱 실패 시)
        default_conversation = [
            {
                "speaker_id": heroine1_id,
                "speaker_name": persona1.get("name", "히로인"),
                "text": "...",
                "emotion": 0,  # neutral
            }
        ]
        
        # JSON 파싱 (공통 함수 사용)
        parsed = parse_llm_json_response(response.content, default=[])
        
        if isinstance(parsed, list) and parsed:
            conversation = parsed
            
            # speaker_name을 기준으로 올바른 speaker_id 할당
            name_to_id = {
                persona1.get("name"): heroine1_id,
                persona2.get("name"): heroine2_id,
            }

            # emotion 문자열을 정수로 변환, speaker_id 보정, emotion_intensity 기본값 설정
            for msg in conversation:
                # speaker_name으로 올바른 speaker_id 할당
                speaker_name = msg.get("speaker_name")
                if speaker_name in name_to_id:
                    msg["speaker_id"] = name_to_id[speaker_name]

                if "emotion" in msg and isinstance(msg["emotion"], str):
                    msg["emotion"] = heroine_emotion_to_int(msg["emotion"])
                if "emotion_intensity" not in msg:
                    msg["emotion_intensity"] = 1.0
        else:
            conversation = default_conversation
        print(f"[TIMING] NPC-NPC JSON 파싱: {time.time() - t:.3f}s")
        print(
            f"[TIMING] NPC-NPC generate_conversation 총합: {time.time() - total_start:.3f}s"
        )

        return conversation

    async def generate_and_save_conversation(
        self,
        player_id: str,
        heroine1_id: int,
        heroine2_id: int,
        situation: str = None,
        turn_count: int = 5,
        importance_score: int = 5,
    ) -> Dict[str, Any]:
        """대화 생성 후 DB에 저장 (비스트리밍)

        Args:
            heroine1_id: 첫 번째 히로인 ID
            heroine2_id: 두 번째 히로인 ID
            situation: 대화 상황 (None이면 자동 생성)
            turn_count: 대화 턴 수
            importance_score: 중요도 (1-10)

        Returns:
            저장 결과 (id, heroine1_id, heroine2_id, content, situation, conversation, importance_score, timestamp)
        """
        if not self._is_valid_situation(situation):
            situation = await self.generate_situation()

        # 대화 생성
        conversation = await self.generate_conversation(
            str(player_id), heroine1_id, heroine2_id, situation, turn_count
        )

        # DB에 저장
        conv_id = self._save_conversation_to_db(
            str(player_id),
            heroine1_id,
            heroine2_id,
            conversation,
            situation,
            importance_score,
        )

        return {
            "id": conv_id,
            "heroine1_id": heroine1_id,
            "heroine2_id": heroine2_id,
            "situation": situation,
            "conversation": conversation,
            "importance_score": importance_score,
            "timestamp": datetime.now().isoformat(),
        }

    # ============================================
    # 조회 메서드
    # ============================================

    def get_conversations(
        self,
        player_id: str,
        heroine1_id: int = None,
        heroine2_id: int = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """저장된 대화 조회 (최신순)

        Args:
            heroine1_id: 첫 번째 히로인 ID로 필터링 (None이면 필터 없음)
            heroine2_id: 두 번째 히로인 ID로 필터링 (None이면 필터 없음)
            limit: 최대 개수

        Returns:
            대화 목록
        """
        return npc_npc_memory_manager.get_checkpoints(
            player_id=str(player_id),
            npc1_id=heroine1_id,
            npc2_id=heroine2_id,
            limit=limit,
        )

    def interrupt_conversation(
        self,
        player_id: str,
        conversation_id: str,
        interrupted_turn: int,
        heroine1_id: int,
        heroine2_id: int,
    ) -> Dict[str, Any]:
        """NPC-NPC 대화 인터럽트 처리

        유저가 NPC 대화 중간에 끊고 들어왔을 때 호출됩니다.
        interrupted_turn 이후의 대화는 NPC가 모르는 것으로 처리됩니다.

        Args:
            conversation_id: 대화 ID (agent_memories.id)
            interrupted_turn: 유저가 끊은 턴 (이 턴까지만 유효)
            heroine1_id: 첫 번째 히로인 ID
            heroine2_id: 두 번째 히로인 ID

        Returns:
            처리 결과 딕셔너리
        """
        # 1) 체크포인트 자르기
        checkpoint = npc_npc_memory_manager.truncate_checkpoint(
            checkpoint_id=conversation_id,
            interrupted_turn=interrupted_turn,
        )
        if checkpoint is None:
            return {
                "success": False,
                "message": "대화를 찾을 수 없습니다",
                "conversation_id": conversation_id,
            }

        # 2) 장기기억 무효화
        memory_count = npc_npc_memory_manager.invalidate_memories_after_turn(
            checkpoint_id=conversation_id,
            interrupted_turn=interrupted_turn,
        )

        # 3) Redis 세션도 자르기
        redis_manager.truncate_npc_npc_session(
            str(player_id), heroine1_id, heroine2_id, interrupted_turn
        )

        return {
            "success": True,
            "message": f"{interrupted_turn}턴까지의 대화만 유지됩니다",
            "conversation_id": conversation_id,
            "interrupted_turn": interrupted_turn,
            "updated_memories": memory_count,
        }


# 싱글톤 인스턴스 (앱 전체에서 하나만 사용)
heroine_heroine_agent = HeroineHeroineAgent()
