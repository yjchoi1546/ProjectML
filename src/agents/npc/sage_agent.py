"""
대현자 NPC Agent

대현자 사트라(Satra)와의 대화를 처리합니다.
세계관과 시나리오 정보를 제공하는 역할입니다.

주요 기능:
1. 시나리오 레벨(scenarioLevel) 기반 정보 공개 관리
2. 레벨에 따른 태도 변화 (거리감 -> 친근함)
3. 허용된 정보만 제공, 금지된 정보는 회피

스트리밍/비스트리밍 동일 응답:
- 둘 다 동일한 컨텍스트(시나리오)를 사용
- 둘 다 동일한 프롬프트로 응답 생성
- LLM 호출은 1번만

저장 위치:
- Redis: 세션 상태 (scenarioLevel, emotion, conversation_buffer)
- Mem0: User-NPC 장기 기억 (대화 내용)
"""

import json
import yaml
import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator, Dict, Any, Tuple, List
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import START, END, StateGraph

from agents.npc.npc_state import SageState
from agents.npc.base_npc_agent import BaseNPCAgent
from agents.npc.emotion_mapper import sage_emotion_to_int
from db.redis_manager import redis_manager
from db.user_memory_manager import user_memory_manager
from db.session_checkpoint_manager import session_checkpoint_manager
from services.sage_scenario_service import sage_scenario_service
from enums.LLM import LLM

# ============================================
# 시간 기반 기억 검색용 상수/헬퍼
# ============================================

WEEKDAY_MAP = {
    "월요일": 0,
    "화요일": 1,
    "수요일": 2,
    "목요일": 3,
    "금요일": 4,
    "토요일": 5,
    "일요일": 6,
}


def _get_last_weekday(weekday: int, weeks_ago: int = 1) -> datetime:
    """지난주/지지난주 특정 요일의 날짜 계산"""
    today = datetime.now()
    days_since = (today.weekday() - weekday) % 7
    if days_since == 0:
        days_since = 7
    target = today - timedelta(days=days_since + (weeks_ago - 1) * 7)
    return target


# ============================================
# 페르소나 데이터 로드
# ============================================

# 페르소나 YAML 파일 경로
PERSONA_PATH = (
    Path(__file__).parent.parent.parent
    / "prompts"
    / "prompt_type"
    / "npc"
    / "sage_persona.yaml"
)


def load_persona_data() -> Dict[str, Any]:
    """페르소나 YAML 파일 로드

    파일이 없거나 오류가 있으면 기본값 반환

    Returns:
        페르소나 데이터 딕셔너리
    """
    try:
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"경고: 페르소나 파일을 찾을 수 없습니다: {PERSONA_PATH}")
        return _get_default_persona()
    except Exception as e:
        print(f"경고: 페르소나 로드 실패: {e}")
        return _get_default_persona()


def _get_default_persona() -> Dict[str, Any]:
    """기본 페르소나 데이터 (파일 없을 때 사용)"""
    return {
        "satra": {
            "name": "사트라",
            "basic_info": {
                "apparent_age": "20대 중반 외모",
                "appearance": "은발, 붉은 눈, 하얀 피부",
                "role": "셀레파이스의 대현자",
            },
            "speech_style": {"tone": "기품 있는 하대", "mentor_address": "멘토"},
            "level_attitudes": {
                "low": {
                    "description": "거리감 있음, 수수께끼처럼 말함",
                    "examples": ["흠, 그건 아직 알 필요 없어."],
                },
                "mid": {
                    "description": "조금 친밀해짐",
                    "examples": ["그건... 때가 되면 알려줄게."],
                },
                "high": {
                    "description": "친근함, 솔직해짐",
                    "examples": ["좋아, 솔직히 말해볼게."],
                },
            },
            "personality": {"surface": ["알 수 없는 미소", "기품 있음", "지혜로움"]},
            "info_rules": {
                "level_1": {
                    "allowed": ["기초 세계관", "길드 정보"],
                    "forbidden": ["플레이어 과거", "히로인 비밀"],
                    "evasion": "아직 때가 아니야.",
                }
            },
        }
    }


# 페르소나 데이터 로드 (모듈 로드시 1회)
PERSONA_DATA = load_persona_data()


class SageAgent(BaseNPCAgent):
    """대현자 NPC Agent

    대현자 사트라와의 대화를 처리합니다.
    시나리오 레벨에 따라 공개할 수 있는 정보가 달라집니다.

    스트리밍과 비스트리밍 모두 동일한 응답을 생성합니다.

    사용 예시:
        agent = SageAgent()

        # 비스트리밍
        result = await agent.process_message(state)

        # 스트리밍
        async for chunk in agent.generate_response_stream(state):
            print(chunk, end="")
    """

    def __init__(self, model_name: str = LLM.GROK_4_FAST_NON_REASONING):
        """초기화

        Args:
            model_name: 사용할 LLM 모델명
        """
        super().__init__(model_name)
        self.llm = init_chat_model(model=model_name, temperature=1, max_tokens=200)

        # 의도 분류용 LLM (temperature=0으로 일관된 분류)
        self.intent_llm = init_chat_model(
            model=model_name, temperature=0, max_tokens=20
        )

        # LangGraph 빌드 (비스트리밍용)
        self.graph = self._build_graph()

    # ============================================
    # 세션 및 페르소나 관련 메서드
    # ============================================

    def _create_initial_session(self, player_id: int, npc_id: int) -> dict:
        """대현자 초기 세션 생성

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID (대현자는 0)

        Returns:
            초기 세션 딕셔너리
        """
        return {
            "player_id": player_id,
            "npc_id": npc_id,
            "npc_type": "sage",
            "conversation_buffer": [],  # 최근 대화 목록
            "short_term_summary": "",  # 단기 요약
            "state": {
                "scenarioLevel": 1,  # 시나리오 레벨 (1-10)
                "emotion": "neutral",  # 현재 감정
            },
        }

    def _get_attitude(self, scenario_level: int) -> str:
        """레벨에 따른 태도 설명

        Args:
            scenario_level: 시나리오 레벨 (1-10)

        Returns:
            태도 설명 문자열
        """
        if scenario_level <= 3:
            return "거리감 있음, 수수께끼처럼 말함"
        elif scenario_level <= 6:
            return "조금 친밀해짐, 정보 제공 늘어남"
        return "친근함, 솔직해짐"

    def _get_attitude_key(self, scenario_level: int) -> str:
        """레벨에 따른 태도 키

        Args:
            scenario_level: 시나리오 레벨 (1-10)

        Returns:
            태도 키 (low/mid/high)
        """
        if scenario_level <= 3:
            return "low"
        elif scenario_level <= 6:
            return "mid"
        return "high"

    def _format_persona(self, scenario_level: int) -> str:
        """페르소나를 프롬프트용 문자열로 포맷

        Args:
            scenario_level: 시나리오 레벨

        Returns:
            포맷된 문자열
        """
        persona = PERSONA_DATA.get("satra", {})
        attitude_key = self._get_attitude_key(scenario_level)

        # 기본 정보
        basic = persona.get("basic_info", {})
        speech = persona.get("speech_style", {})
        level_attitudes = persona.get("level_attitudes", {})
        attitude_data = level_attitudes.get(attitude_key, {})

        lines = [
            f"이름: {persona.get('name', '사트라')}",
            f"외형: {basic.get('apparent_age', '')}, {basic.get('appearance', '')}",
            f"역할: {basic.get('role', '대현자')}",
            "",
            "[말투 특징]",
            f"- 기본: {speech.get('tone', '기품 있는 하대')}",
            f"- 호칭: {speech.get('mentor_address', '멘토')}",
            f"- 대화패턴: {','.join(speech.get('patterns', []))}",
            "",
            f"[현재 레벨 {scenario_level} 태도]",
            f"스타일: {attitude_data.get('description', '')}",
            "예시 대사:",
        ]

        for example in attitude_data.get("examples", []):
            lines.append(f"  - {example}")

        # 성격 특성
        personality = persona.get("personality", {})
        lines.append("")
        lines.append("[성격]")
        for trait in personality.get("surface", []):
            lines.append(f"  - {trait}")
        if attitude_key == "high":
            for trait in personality.get("hidden", []):
                lines.append(f"  - {trait}")

        return "\n".join(lines)

    def _get_info_rules(self, scenario_level: int) -> dict:
        """현재 레벨의 정보 공개 규칙

        Args:
            scenario_level: 시나리오 레벨

        Returns:
            정보 규칙 딕셔너리 (allowed, forbidden, evasion)
        """
        persona = PERSONA_DATA.get("satra", {})
        info_rules = persona.get("info_rules", {})
        level_key = f"level_{scenario_level}"
        return info_rules.get(level_key, info_rules.get("level_1", {}))

    def _extract_recent_user_questions(self, conversation_buffer: list) -> str:
        """최근 대화에서 유저 질문만 추출하여 요약

        Args:
            conversation_buffer: 대화 버퍼 리스트

        Returns:
            유저 질문 요약 문자열
        """
        user_messages = []
        for item in conversation_buffer:
            if item.get("role") == "user":
                content = item.get("content", "")
                if content:
                    user_messages.append(content)

        if not user_messages:
            return "없음"

        # 최근 5개만 추출
        recent = user_messages[-5:]
        return ", ".join(recent)

    def _format_summary_list(self, summary_list: List[Dict[str, Any]]) -> str:
        """summary_list를 프롬프트용 텍스트로 포맷팅

        Args:
            summary_list: 요약 리스트

        Returns:
            포맷된 문자열
        """
        if not summary_list:
            return "없음"

        formatted = []
        for item in summary_list:
            summary = item.get("summary", "")
            if summary:
                formatted.append(f"- {summary}")

        if not formatted:
            return "없음"

        return "\n".join(formatted)

    # ============================================
    # 컨텍스트 준비 메서드 (스트리밍/비스트리밍 공통)
    # ============================================

    async def _classify_intent(self, state: SageState) -> str:
        """의도 분류

        사용자 메시지의 의도를 분류합니다:
        - general: 일반 대화
        - memory_recall: 과거 대화 질문 (User Memory 검색)
        - worldview_inquiry: 세계관 질문 (시나리오 DB 검색)

        Args:
            state: 현재 상태

        Returns:
            의도 문자열
        """
        user_message = state["messages"][-1].content
        conversation_context = state.get("short_term_summary", "")

        prompt = f"""다음 플레이어 메시지의 의도를 분류하세요.

[최근 대화 맥락]
{conversation_context}

[플레이어 메시지]
{user_message}

[분류 기준]
- general: 일상 대화, 안부, 농담, 사트라 본인에 대한 질문
- memory_recall: "우리 전에 뭐 얘기했지?", "어제 뭐 했어?", "기억나?" 등 플레이어와 대현자가 함께 나눈 과거 대화/경험 질문
- worldview_inquiry: 세계관, 국가, 종족, 던전, 디멘시움, 플레이어(멘토)의 과거/능력 등에 대한 질문

반드시 general, memory_recall, worldview_inquiry 중 하나만 출력하세요."""

        response = await self.intent_llm.ainvoke(prompt)
        intent = response.content.strip().lower()

        # 유효하지 않으면 기본값
        valid_intents = ["general", "memory_recall", "worldview_inquiry"]
        if intent not in valid_intents:
            intent = "general"

        return intent

    async def _retrieve_memory(self, state: SageState) -> str:
        """기억 검색 (시간 키워드 분석)

        Args:
            state: 현재 상태

        Returns:
            검색된 기억 텍스트
        """
        user_message = state["messages"][-1].content
        player_id = state["player_id"]
        npc_id = 0  # sage

        facts_parts = []

        # 시간 키워드 분석 (정규식)
        days_ago_match = re.search(r"(\d+)\s*일\s*전", user_message)

        if "어제" in user_message:
            print("[MEMORY_FUNC] get_memories_days_ago_sync(1)")
            user_memories = user_memory_manager.get_memories_days_ago_sync(
                player_id, npc_id, 1, limit=5
            )
        elif "그제" in user_message or "그저께" in user_message:
            print("[MEMORY_FUNC] get_memories_days_ago_sync(2)")
            user_memories = user_memory_manager.get_memories_days_ago_sync(
                player_id, npc_id, 2, limit=5
            )
        elif days_ago_match:
            days = int(days_ago_match.group(1))
            print(f"[MEMORY_FUNC] get_memories_days_ago_sync({days})")
            user_memories = user_memory_manager.get_memories_days_ago_sync(
                player_id, npc_id, days, limit=5
            )
        elif re.search(r"(최근|요즘|며칠)", user_message):
            print("[MEMORY_FUNC] get_recent_memories_sync(7)")
            user_memories = user_memory_manager.get_recent_memories_sync(
                player_id, npc_id, 7, limit=5
            )
        elif re.search(r"(바뀌|변하|전에는|바꼈|바뀐|변했)", user_message):
            print("[MEMORY_FUNC] get_preference_history_sync")
            user_memories = user_memory_manager.get_preference_history_sync(
                player_id, npc_id, user_message
            )
        elif re.search(r"(전부|다\s|모든|기억하는\s*거)", user_message):
            print("[MEMORY_FUNC] get_valid_memories_sync")
            user_memories = user_memory_manager.get_valid_memories_sync(
                player_id, npc_id, limit=10
            )
        elif date_match := re.search(r"(\d{1,2})월\s*(\d{1,2})일", user_message):
            month = int(date_match.group(1))
            day = int(date_match.group(2))
            year = datetime.now().year
            point_in_time = datetime(year, month, day)
            print(f"[MEMORY_FUNC] get_memories_at_point_sync({month}/{day})")
            user_memories = user_memory_manager.get_memories_at_point_sync(
                player_id, npc_id, point_in_time, limit=5
            )
        elif week_match := re.search(
            r"지지난주\s*(월|화|수|목|금|토|일)요일", user_message
        ):
            weekday = WEEKDAY_MAP[week_match.group(1) + "요일"]
            point_in_time = _get_last_weekday(weekday, weeks_ago=2)
            print(
                f"[MEMORY_FUNC] get_memories_at_point_sync(지지난주 {week_match.group(1)}요일)"
            )
            user_memories = user_memory_manager.get_memories_at_point_sync(
                player_id, npc_id, point_in_time, limit=5
            )
        elif week_match := re.search(
            r"지난주\s*(월|화|수|목|금|토|일)요일", user_message
        ):
            weekday = WEEKDAY_MAP[week_match.group(1) + "요일"]
            point_in_time = _get_last_weekday(weekday, weeks_ago=1)
            print(
                f"[MEMORY_FUNC] get_memories_at_point_sync(지난주 {week_match.group(1)}요일)"
            )
            user_memories = user_memory_manager.get_memories_at_point_sync(
                player_id, npc_id, point_in_time, limit=5
            )
        else:
            print("[MEMORY_FUNC] search_memory_sync (hybrid)")
            user_memories = user_memory_manager.search_memory_sync(
                player_id, npc_id, user_message, limit=3
            )

        if user_memories:
            facts_parts.append("[플레이어와의 기억]")
            for m in user_memories:
                memory_text = m.get("memory", m.get("text", ""))
                facts_parts.append(f"- {memory_text}")

        return "\n".join(facts_parts) if facts_parts else "관련 기억 없음"

    async def _retrieve_scenario(self, state: SageState) -> str:
        """시나리오 DB 검색

        현재 시나리오 레벨 이하로 해금된 시나리오를 검색합니다.

        Args:
            state: 현재 상태

        Returns:
            검색된 시나리오 텍스트
        """
        user_message = state["messages"][-1].content
        scenario_level = state.get("scenarioLevel", 1)

        scenarios = sage_scenario_service.search_scenarios(
            query=user_message, max_scenario_level=scenario_level, limit=2
        )

        if scenarios:
            return "\n\n".join([s["content"] for s in scenarios])
        return "해금된 정보 없음"

    async def _prepare_context(self, state: SageState) -> Dict[str, Any]:
        """컨텍스트 준비 (스트리밍/비스트리밍 공통)

        LLM 호출 전에 필요한 모든 정보를 준비합니다:
        1. 의도 분류
        2. 의도에 따른 검색 (시나리오)

        Args:
            state: 현재 상태

        Returns:
            컨텍스트 딕셔너리 (intent, unlocked_scenarios)
        """
        import time

        total_start = time.time()

        # 1. 의도 분류
        t1 = time.time()
        intent = await self._classify_intent(state)
        print(f"[TIMING] 의도 분류: {time.time() - t1:.3f}s")

        # 2. 의도에 따른 검색
        unlocked_scenarios = "없음"
        retrieved_facts = "없음"

        if intent == "memory_recall":
            t2 = time.time()
            retrieved_facts = await self._retrieve_memory(state)
            print(f"[TIMING] 기억 검색: {time.time() - t2:.3f}s")
        elif intent == "worldview_inquiry":
            t2 = time.time()
            unlocked_scenarios = await self._retrieve_scenario(state)
            print(f"[TIMING] 시나리오 검색: {time.time() - t2:.3f}s")

        print(f"[TIMING] 컨텍스트 준비 총합: {time.time() - total_start:.3f}s")
        return {
            "intent": intent,
            "unlocked_scenarios": unlocked_scenarios,
            "retrieved_facts": retrieved_facts,
        }

    def _build_full_prompt(
        self, state: SageState, context: Dict[str, Any]
    ) -> str:
        """전체 프롬프트 생성

        Args:
            state: 현재 상태
            context: 컨텍스트 (검색 결과 등)

        Returns:
            프롬프트 문자열
        """
        scenario_level = state.get("scenarioLevel", 1)
        info_rules = self._get_info_rules(scenario_level)

        # 금지 정보와 회피 응답
        forbidden_info = info_rules.get("forbidden", [])
        evasion_response = info_rules.get("evasion", "아직 때가 아니야.")

        # 출력 형식
        output_format = """[출력 형식]
반드시 아래 JSON 형식으로 출력하세요:
{
    "thought": "(내면의 생각 - 플레이어에게 보이지 않음)",
    "text": "(실제 대화 내용)",
    "emotion": "neutral|joy|fun|sorrow|angry|surprise|mysterious",
    "emotion_intensity": 0.5~2.0 사이의 실수 (0.5=약한 감정, 1.0=보통, 1.5=강함, 2.0=극도로 강함),
    "info_revealed": true 또는 false
}"""

        npc_id = state["npc_id"]
        time_since_last_chat = self.get_time_since_last_chat(state["player_id"], npc_id)

        # 플레이어 이름 가져오기
        player_known_name = None
        session = redis_manager.load_session(state["player_id"], npc_id)
        if session and "state" in session:
            player_known_name = session["state"].get("player_known_name")

        # 세계관 컨텍스트 가져오기
        world_context = PERSONA_DATA.get("world_context", {})

        prompt = f"""당신은 대현자 사트라(Satra)입니다.

[핵심 목표]
- 최근 대화는 '맥락 파악'에만 사용합니다.
- [페르소나]에 충실하게 답변하세요.
- 같은 질문이 반복되어도 과거 답변 문장을 그대로 복사하지 않습니다.
- 반드시 [현재 레벨 태도], [페르소나], [정보 공개 규칙], [장기 기억 (검색 결과)], [해금된 세계관 정보], [플레이어 메시지]를 근거로 새로 답합니다.

[답변 결정 절차 - 반드시 준수]
1) 질문 유형 판별 (두 가지로 구분)
A) 플레이어와의 대화/경험 질문: "N일 전에 뭐 했지?", "어제 뭐 얘기했지?", "우리 전에 뭐 얘기했지?" 등
B) 세계관/정보 질문: "던전이 뭐야?", "히로인들은 누구야?, "자신의 신상에 대한 질문" 등

2) [장기 기억] 우선 적용 규칙 (가장 중요!)
- [장기 기억 (검색 결과)]에 "없음"이 아닌 내용이 있으면, 반드시 그 내용을 text에 포함해야 합니다.
- 예: [장기 기억]에 "송파구", "귤 이야기"가 있으면 => "송파구랑 귤 이야기 했었지." 처럼 반드시 언급
- <raw_recent_dialogue_do_not_quote>에서 "기억 안 나"라고 했어도, [장기 기억]에 내용이 있으면 이번엔 기억난 것처럼 답합니다.
- 이 규칙은 다른 모든 규칙보다 우선합니다.

3) '정보 없음' 처리 (B유형 질문 + 두 조건 모두 충족시에만)
- [플레이어 메시지]가 B유형(세계관/정보) 질문이고,
- [페르소나]에 없는 내용이고,
- [해금된 세계관 정보]가 "없음"이며,
- [장기 기억 (검색 결과)]도 "없음" 또는 관련 없는 내용이면
=> text에 회피 응답을 사용합니다(30자 이내).
- 주의: A유형(플레이어와의 대화 질문)에는 이 규칙을 적용하지 않습니다!

4) 최근대화 '비복사' 규칙(실패 조건)
- <raw_recent_dialogue_do_not_quote> 안의 문장/구문을 그대로 복사하면 실패입니다.
- "기억 안 나", "희미해" 같은 표현은 [장기 기억]에 내용이 있으면 절대 사용하지 않습니다.

5) 출력/말투 규칙
- 기품 있는 하대 어조를 유지합니다.
- text는 반드시 50자 이내로 답합니다.
- [플레이어 정보]를 참고하여 플레이어를 호칭하세요. 이름을 알면 이름으로, 모르면 "멘토"로 부르세요.

[플레이어 정보]
- 이름: {player_known_name if player_known_name else '알 수 없음'}
- 호칭: {player_known_name if player_known_name else '멘토'} (이름을 알면 이름으로, 모르면 "멘토"로 호칭)

[세계관 컨텍스트 - 당신이 알고 있는 기본 정보]
- 길드: {world_context.get('guild', '셀레파이스 길드')}
- 멘토: {world_context.get('mentor', '기억을 되찾게 해줄 수 있는 특별한 존재')}
- 내 역할: {world_context.get('my_role', '멘토에게 세계관 정보와 조언을 제공')}
- 히로인들: {world_context.get('heroines', '레티아, 루파메스, 로코 - 암네시아로 기억을 잃은 히로인들')}

[마지막 대화로부터 경과 시간]
{time_since_last_chat}

[현재 상태]
- 시나리오 레벨(ScenarioLevel): {scenario_level}
- 태도: {self._get_attitude(scenario_level)}

[페르소나]
{self._format_persona(scenario_level)}

[정보 공개 규칙]
- 허용된 정보: {', '.join(info_rules.get('allowed', []))}
- 금지된 정보: {', '.join(forbidden_info) if forbidden_info else '없음'}
- 금지 정보 질문시 회피: "{evasion_response}"

[페르소나 규칙]
- [세계관 컨텍스트]는 당신이 현재 알고 있는 정보입니다.
- [해금된 세계관 정보]는 시나리오 레벨에 따라 공개할 수 있는 정보입니다.
- 해금되지 않은 정보는 절대 말하지 않습니다. 회피 응답을 사용하세요.
- 기본적으로 하대하며 기품 있는 어조를 유지합니다.
- 감정을 크게 드러내지 않고 항상 알 수 없는 미소를 띱니다.
- 거짓말은 하지 않지만, 말하지 않을 수는 있습니다.

[장기 기억 (검색 결과)]
{context.get('retrieved_facts', '없음')}

[해금된 세계관 정보]
{context.get('unlocked_scenarios', '없음')}

<recent_context_observations>
- 목적: 최근 대화의 흐름(대화 주제) 파악용입니다.
- 규칙: 아래 정보는 '참고용'이며 문장/구문을 그대로 인용하지 않습니다.
- 최근 대화 요약: {self._format_summary_list(state.get('summary_list', []))}
</recent_context_observations>

<raw_recent_dialogue_do_not_quote>
- 목적: 최근 대화의 흐름(대화 주제) 파악용입니다.
- 규칙: 아래 정보는 '참고용'이며 문장/구문을 그대로 인용하지 않습니다.
- 최근 대화 내용:{self.format_conversation_history(state.get('conversation_buffer', []))}
</raw_recent_dialogue_do_not_quote>

[플레이어 메시지]
{state['messages'][-1].content}

{output_format}"""

        return prompt

    async def _update_state_after_response(
        self,
        state: SageState,
        context: Dict[str, Any],
        response_text: str,
        emotion_int: int = 0,
        info_revealed: bool = False,
    ) -> Dict[str, Any]:
        """응답 후 상태 업데이트 (LLM 재호출 없이)

        스트리밍/비스트리밍 모두 이 메서드로 상태를 업데이트합니다.

        저장 위치:
        - Redis: 세션 상태 (emotion, conversation_buffer)
        - Mem0: User-NPC 대화 기억

        Args:
            state: 현재 상태
            context: 컨텍스트
            response_text: 생성된 응답 텍스트
            emotion_int: 감정 정수값 (기본값 0=neutral)
            info_revealed: 정보 공개 여부

        Returns:
            업데이트된 상태 값들
        """
        player_id = state["player_id"]
        npc_id = state["npc_id"]

        # Redis 세션 업데이트
        session = redis_manager.load_session(player_id, npc_id)
        player_known_name = None
        if session:
            # 상태 업데이트
            session["state"]["emotion"] = emotion_int

            # 기존 player_known_name 유지 (백그라운드에서 업데이트될 수 있음)
            if "player_known_name" in session.get("state", {}):
                player_known_name = session["state"]["player_known_name"]

            # 대화 버퍼에 추가
            session["conversation_buffer"].append(
                {"role": "user", "content": state["messages"][-1].content}
            )
            session["conversation_buffer"].append(
                {"role": "assistant", "content": response_text}
            )

            # turn_count 업데이트
            turn_count = session.get("turn_count", 0) + 1
            session["turn_count"] = turn_count

            # last_chat_at 업데이트
            session["last_chat_at"] = datetime.now().isoformat()

            # 요약 생성 조건 확인 (20턴 또는 1시간 경과)
            last_summary_at = session.get("last_summary_at")
            should_generate_summary = False

            if turn_count >= 20:
                should_generate_summary = True
            elif last_summary_at:
                last_summary_time = datetime.fromisoformat(last_summary_at)
                if datetime.now() - last_summary_time > timedelta(hours=1):
                    should_generate_summary = True
            elif turn_count >= 10:
                should_generate_summary = True

            if should_generate_summary:
                session["turn_count"] = 0
                session["last_summary_at"] = datetime.now().isoformat()

                conversations = []
                for i in range(0, len(session["conversation_buffer"]), 2):
                    if i + 1 < len(session["conversation_buffer"]):
                        conversations.append(
                            {
                                "user": session["conversation_buffer"][i].get(
                                    "content", ""
                                ),
                                "npc": session["conversation_buffer"][i + 1].get(
                                    "content", ""
                                ),
                            }
                        )

                asyncio.create_task(
                    self._generate_and_save_summary(player_id, npc_id, conversations)
                )

            # 세션 저장
            redis_manager.save_session(player_id, npc_id, session)

        # User Memory에 대화 저장 (백그라운드)
        user_msg = state["messages"][-1].content
        asyncio.create_task(
            self._save_to_user_memory_background(
                player_id, npc_id, user_msg, response_text
            )
        )

        return {
            "response_text": response_text,
            "emotion": emotion_int,
            "info_revealed": info_revealed,
            "player_known_name": player_known_name,
        }

    async def _save_to_user_memory_background(
        self, player_id: int, npc_id: int, user_msg: str, npc_response: str
    ) -> None:
        """백그라운드로 User Memory에 대화 저장

        이름이 추출되면 Redis 세션에 저장

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            user_msg: 유저 메시지
            npc_response: NPC 응답
        """
        try:
            # sage NPC는 heroine_id를 "sage"로 설정
            result = await user_memory_manager.save_conversation(
                player_id=str(player_id),
                heroine_id="sage",
                user_message=user_msg,
                npc_response=npc_response,
            )

            # 이름이 추출되었으면 Redis 세션에 저장
            extracted_name = result.get("extracted_player_name")
            if extracted_name:
                session = redis_manager.load_session(player_id, npc_id)
                if session:
                    if "state" not in session:
                        session["state"] = {}
                    session["state"]["player_known_name"] = extracted_name
                    redis_manager.save_session(player_id, npc_id, session)
                    print(f"[DEBUG] 플레이어 이름 저장: {extracted_name}")
        except Exception as e:
            print(f"[ERROR] User Memory 저장 실패: {e}")

    async def _generate_and_save_summary(
        self, player_id: int, npc_id: int, conversations: list
    ) -> None:
        """백그라운드로 요약 생성 및 저장

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            conversations: 대화 목록
        """
        try:
            summary_item = await session_checkpoint_manager.generate_summary(
                player_id, npc_id, conversations
            )

            session = redis_manager.load_session(player_id, npc_id)
            summary_list = []

            if session:
                summary_list = session.get("summary_list", [])
                summary_list.append(summary_item)

                summary_list = session_checkpoint_manager.prune_summary_list(
                    summary_list
                )
                session["summary_list"] = summary_list

                redis_manager.save_session(player_id, npc_id, session)
            else:
                summary_list = [summary_item]
                summary_list = session_checkpoint_manager.prune_summary_list(
                    summary_list
                )

            session_checkpoint_manager.save_summary(player_id, npc_id, summary_list)

        except Exception as e:
            print(f"[ERROR] _generate_and_save_summary 실패: {e}")

    # ============================================
    # LangGraph 빌드 (비스트리밍용)
    # ============================================

    def _build_graph(self) -> StateGraph:
        """LangGraph 빌드

        노드 흐름:
        START -> router
        router -> (분기)
            - general -> generate
            - memory_recall -> memory_retrieve -> generate
            - worldview_inquiry -> scenario_retrieve -> generate
        generate -> post_process -> END

        Returns:
            컴파일된 StateGraph
        """
        graph = StateGraph(SageState)

        # 노드 추가
        graph.add_node("router", self._router_node)
        graph.add_node("memory_retrieve", self._memory_retrieve_node)
        graph.add_node("scenario_retrieve", self._scenario_retrieve_node)
        graph.add_node("generate", self._generate_node)
        graph.add_node("post_process", self._post_process_node)

        # 엣지 추가
        graph.add_edge(START, "router")

        # 조건부 분기
        graph.add_conditional_edges(
            "router",
            self._route_by_intent,
            {
                "general": "generate",
                "memory_recall": "memory_retrieve",
                "worldview_inquiry": "scenario_retrieve",
            },
        )

        graph.add_edge("memory_retrieve", "generate")
        graph.add_edge("scenario_retrieve", "generate")
        graph.add_edge("generate", "post_process")
        graph.add_edge("post_process", END)

        return graph.compile()

    # ============================================
    # LangGraph 노드 구현
    # ============================================

    async def _router_node(self, state: SageState) -> dict:
        """의도 분류 노드"""
        import time

        t = time.time()
        intent = await self._classify_intent(state)
        print(f"[TIMING] 의도 분류: {time.time() - t:.3f}s")
        return {"intent": intent}

    def _route_by_intent(self, state: SageState) -> str:
        """의도에 따라 라우팅"""
        return state.get("intent", "general")

    async def _memory_retrieve_node(self, state: SageState) -> dict:
        """기억 검색 노드"""
        import time

        t = time.time()
        facts = await self._retrieve_memory(state)
        print(f"[TIMING] 기억 검색: {time.time() - t:.3f}s")
        return {"retrieved_facts": facts}

    async def _scenario_retrieve_node(self, state: SageState) -> dict:
        """시나리오 DB 검색 노드"""
        import time

        t = time.time()
        scenarios = await self._retrieve_scenario(state)
        print(f"[TIMING] 시나리오 검색: {time.time() - t:.3f}s")
        return {"unlocked_scenarios": scenarios}

    async def _generate_node(self, state: SageState) -> dict:
        """응답 생성 노드"""
        import time

        total_start = time.time()

        # 컨텍스트 구성
        context = {
            "unlocked_scenarios": state.get("unlocked_scenarios", "없음"),
            "retrieved_facts": state.get("retrieved_facts", "없음"),
        }

        # 프롬프트 생성 및 LLM 호출
        t1 = time.time()
        prompt = self._build_full_prompt(state, context)
        print(f"[TIMING] 프롬프트 빌드: {time.time() - t1:.3f}s")

        print(f"[PROMPT]\n{prompt}\n{'='*50}")

        t2 = time.time()
        response = await self.llm.ainvoke(prompt)
        print(f"[TIMING] LLM 호출: {time.time() - t2:.3f}s")

        # JSON 파싱
        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            result = json.loads(content.strip())
        except (json.JSONDecodeError, IndexError):
            result = {
                "thought": "",
                "text": response.content,
                "emotion": "neutral",
                "emotion_intensity": 1.0,
                "info_revealed": False,
            }

        emotion_str = result.get("emotion", "neutral")
        emotion_intensity = result.get("emotion_intensity", 1.0)
        print(f"[TIMING] generate 노드 총합: {time.time() - total_start:.3f}s")
        return {
            "response_text": result.get("text", ""),
            "emotion": sage_emotion_to_int(emotion_str),
            "emotion_intensity": emotion_intensity,
            "info_revealed": result.get("info_revealed", False),
        }

    async def _post_process_node(self, state: SageState) -> dict:
        """후처리 노드 - 상태 업데이트"""
        import time

        t = time.time()

        context = {}

        emotion_int = state.get("emotion", 0)
        await self._update_state_after_response(
            state,
            context,
            state.get("response_text", ""),
            emotion_int,
            state.get("info_revealed", False),
        )

        print(f"[TIMING] 상태 업데이트: {time.time() - t:.3f}s")
        return {"info_revealed": state.get("info_revealed", False)}

    # ============================================
    # 공개 메서드
    # ============================================

    async def process_message(self, state: SageState) -> SageState:
        """메시지 처리 (비스트리밍)

        LangGraph 전체 파이프라인을 실행합니다.

        Args:
            state: 입력 상태

        Returns:
            처리 후 상태
        """
        result = await self.graph.ainvoke(state)
        return result

# 싱글톤 인스턴스 (앱 전체에서 하나만 사용)
sage_agent = SageAgent()
