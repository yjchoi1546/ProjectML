"""
히로인 NPC Agent

기억을 잃은 3명의 히로인(레티아, 루파메스, 로코)과의 대화를 처리합니다.

주요 기능:
1. 호감도(affection), 정신력(sanity), 기억진척도(memoryProgress) 관리
2. 키워드 기반 호감도 변화 계산 (좋아하는것 +10, 트라우마 -10)
3. 의도 분류에 따른 컨텍스트 검색 (기억/시나리오)
4. 캐릭터 페르소나 기반 응답 생성

스트리밍/비스트리밍 동일 응답:
- 둘 다 동일한 컨텍스트(기억/시나리오)를 사용
- 둘 다 동일한 프롬프트로 응답 생성
- LLM 호출은 1번만

저장 위치:
- Redis: 세션 상태 (affection, sanity, memoryProgress, conversation_buffer)
- PostgreSQL (user_memories): User-NPC 장기 기억 (4요소 하이브리드 검색)
"""

import json
import yaml
import asyncio
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator, Dict, Any, Optional, Tuple, List
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import START, END, StateGraph

from agents.npc.npc_state import HeroineState, IntentType
from agents.npc.base_npc_agent import (
    BaseNPCAgent,
    calculate_memory_progress,
    calculate_affection_change,
    detect_memory_unlock,
)
from agents.npc.emotion_mapper import heroine_emotion_to_int
from db.redis_manager import redis_manager
from db.user_memory_manager import user_memory_manager
from db.npc_npc_memory_manager import npc_npc_memory_manager
from db.session_checkpoint_manager import session_checkpoint_manager
from services.heroine_scenario_service import heroine_scenario_service
from enums.LLM import LLM

# ============================================
# 페르소나 데이터 로드
# ============================================

# 페르소나 YAML 파일 경로
PERSONA_PATH = (
    Path(__file__).parent.parent.parent
    / "prompts"
    / "prompt_type"
    / "npc"
    / "heroine_persona.yaml"
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
        "letia": {
            "name": "레티아",
            "personality": {"base": "차갑고 무뚝뚝하지만 속정이 깊음"},
            "speech_style": {"honorific": False},
            "affection_responses": {
                "low": {"description": "경계", "examples": ["...뭐야."]},
                "mid": {"description": "중립", "examples": ["흠..."]},
                "high": {"description": "친근", "examples": ["...고마워."]},
                "max": {"description": "애정", "examples": ["...바보."]},
            },
            "sanity_responses": {"zero": {"description": "우울", "examples": ["..."]}},
            "liked_keywords": ["검", "훈련", "강해지기"],
            "trauma_keywords": ["화재", "불", "가족"],
        }
    }


# 페르소나 데이터 로드 (모듈 로드시 1회)
PERSONA_DATA = load_persona_data()

# 히로인 ID -> 페르소나 키 매핑
HEROINE_KEY_MAP = {1: "letia", 2: "lupames", 3: "roco"}  # 레티아  # 루파메스  # 로코

# 요일 매핑 (시간 기반 기억 검색용)
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
    """지난주/지지난주 특정 요일의 날짜 계산

    Args:
        weekday: 요일 (0=월요일, 6=일요일)
        weeks_ago: 몇 주 전인지 (1=지난주, 2=지지난주)

    Returns:
        해당 날짜의 datetime
    """
    today = datetime.now()
    days_since = (today.weekday() - weekday) % 7
    if days_since == 0:
        days_since = 7
    target = today - timedelta(days=days_since + (weeks_ago - 1) * 7)
    return target


class HeroineAgent(BaseNPCAgent):
    """히로인 NPC Agent

    기억을 잃은 히로인과의 대화를 처리합니다.
    스트리밍과 비스트리밍 모두 동일한 응답을 생성합니다.

    사용 예시:
        agent = HeroineAgent()

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
        """히로인 초기 세션 생성

        Args:
            player_id: 플레이어 ID
            npc_id: 히로인 ID

        Returns:
            초기 세션 딕셔너리
        """
        return {
            "player_id": player_id,
            "npc_id": npc_id,
            "npc_type": "heroine",
            "conversation_buffer": [],  # 최근 대화 목록 (최대 20개)
            "short_term_summary": "",  # 단기 요약
            "recent_used_keywords": [],  # 최근 5턴 내 사용된 좋아하는 키워드
            "recently_unlocked_memory": None,  # 최근 해금된 기억 (TTL 기반)
            "state": {
                "affection": 0,  # 호감도 (0-100)
                "sanity": 100,  # 정신력 (0-100)
                "memoryProgress": 0,  # 기억 진척도 (0-100)
                "emotion": "neutral",  # 현재 감정
            },
        }

    def _get_persona(self, heroine_id: int) -> Dict[str, Any]:
        """히로인 페르소나 가져오기

        Args:
            heroine_id: 히로인 ID (1=레티아, 2=루파메스, 3=로코)

        Returns:
            페르소나 딕셔너리
        """
        key = HEROINE_KEY_MAP.get(heroine_id, "letia")
        return PERSONA_DATA.get(key, PERSONA_DATA.get("letia", {}))

    def _get_affection_level(self, affection: int) -> str:
        """호감도 레벨 결정

        Args:
            affection: 호감도 (0-100)

        Returns:
            레벨 문자열 (low/mid/high/max)
        """
        if affection >= 90:
            return "max"
        elif affection >= 60:
            return "high"
        elif affection >= 30:
            return "mid"
        return "low"

    def _format_preference_changes(self, preference_changes: list) -> str:
        """취향 변화 정보를 프롬프트용 문자열로 포맷

        Args:
            preference_changes: 취향 변화 리스트 [{"old": ..., "new": ...}]

        Returns:
            포맷된 문자열 또는 빈 문자열
        """
        if not preference_changes:
            return ""

        lines = ["[취향 변화 감지됨 - 자연스럽게 언급해주세요]"]
        for change in preference_changes:
            lines.append(f"- 과거: {change['old']} -> 현재: {change['new']}")

        return "\n".join(lines) + "\n"

    def _format_newly_unlocked_scenario(self, scenario_content: Optional[str]) -> str:
        """방금 해금된 시나리오를 프롬프트용 문자열로 포맷

        호감도 변화로 memoryProgress 임계값을 넘어 기억이 해금되었을 때 사용합니다.

        Args:
            scenario_content: 해금된 시나리오 내용 또는 None

        Returns:
            포맷된 문자열 또는 빈 문자열
        """
        if not scenario_content:
            return ""

        lines = [
            "<must_include>",
            "<memory_content>",
            scenario_content,
            "</memory_content>",
            "- 이 기억이 방금 떠올랐습니다.",
            "- 페르소나에 맞는 말투로 '<memory_content>에 대한 기억이 돌아왔다' 라고 반드시 언급하세요.",
            "</must_include>",
        ]

        return (
            "\n".join(lines) + "\n"
        )  # join은 문자와 문자 사이에 작용하므로 + "\n"은 마지막 문자 뒤에 줄바꿈 추가

    def _format_persona(
        self, persona: Dict[str, Any], affection: int, sanity: int
    ) -> str:
        """페르소나를 프롬프트용 문자열로 포맷

        Args:
            persona: 페르소나 딕셔너리
            affection: 현재 호감도
            sanity: 현재 정신력

        Returns:
            포맷된 문자열
        """
        level = self._get_affection_level(affection)

        # 기본 정보
        lines = [
            f"이름: {persona.get('name', '알 수 없음')}",
            f"풀네임: {persona.get('name_full', '알 수 없음')}",
            f"나이: {persona.get('basic_info', {}).get('age', '알 수 없음')}",
            f"종족: {persona.get('basic_info', {}).get('species', '알 수 없음')}",
            f"성격: {persona.get('personality', {}).get('base', '알 수 없음')}",
            f"말투: {'존댓말' if persona.get('speech_style', {}).get('honorific', False) else '반말'}",
            f"대화길이: {persona.get('speech_style', {}).get('sentence_length', '보통')}",
            f"감탄사: {'풍부' if persona.get('speech_style', {}).get('exclamations', False) else '적음'}",
            f"키: {persona.get('basic_info', {}).get('height', '알 수 없음')}",
            f"주무기: {persona.get('basic_info', {}).get('weapon', '알 수 없음')}",
            "",
            f"[현재 호감도 레벨: {level}]",
        ]

        # 호감도 레벨별 반응
        affection_resp = persona.get("affection_responses", {}).get(level, {})
        lines.append(f"반응 스타일: {affection_resp.get('description', '')}")
        lines.append("예시 대사:")
        for example in affection_resp.get("examples", []):
            lines.append(f"  - {example}")

        # 정신력 0이면 우울 상태 추가
        if sanity == 0:
            lines.append("")
            lines.append("[경고: 정신력 0 - 우울 상태]")
            sanity_resp = persona.get("sanity_responses", {}).get("zero", {})
            lines.append(f"반응: {sanity_resp.get('description', '우울함')}")
            for example in sanity_resp.get("examples", [])[:2]:
                lines.append(f"  - {example}")
        lines.append("----")
        lines.append("좋아하는거:")
        for keyword in persona.get("liked_keywords", []):
            lines.append(f"  - {keyword}")
        lines.append("----")
        lines.append("매우 싫어하는거:")
        for keyword in persona.get("trauma_keywords", []):
            lines.append(f"  - {keyword}")
        return "\n".join(lines)

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

    async def _analyze_keywords(self, state: HeroineState) -> Tuple[int, Optional[str]]:
        """키워드 분석 - 호감도 변화량 사전 계산

        사용자 메시지에서 좋아하는 키워드/트라우마 키워드를 찾아
        호감도 변화량을 미리 계산합니다.

        Args:
            state: 현재 상태

        Returns:
            (호감도 변화량, 사용된 좋아하는 키워드 또는 None)
        """
        user_message = state["messages"][-1].content
        npc_id = state["npc_id"]
        persona = self._get_persona(npc_id)

        # 현재 상태
        affection = state.get("affection", 0)
        recent_used_keywords = state.get("recent_used_keywords", [])

        # 페르소나에서 키워드 가져오기
        liked_keywords = persona.get("liked_keywords", [])
        trauma_keywords = persona.get("trauma_keywords", [])

        # 호감도 변화량 계산 (5턴 내 반복 키워드 방지)
        affection_delta, used_keyword = calculate_affection_change(
            current_affection=affection,
            liked_keywords=liked_keywords,
            trauma_keywords=trauma_keywords,
            user_message=user_message,
            recent_used_keywords=recent_used_keywords,
        )

        return affection_delta, used_keyword

    def _format_recent_turns(self, conversation_buffer: list) -> str:
        """최근 대화를 포맷팅

        Args:
            conversation_buffer: 대화 버퍼 리스트

        Returns:
            포맷된 대화 문자열
        """
        if not conversation_buffer:
            return "없음"

        lines = []
        for item in conversation_buffer:
            role = "플레이어" if item.get("role") == "user" else "히로인"
            content = item.get("content", "")
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _format_recently_unlocked_memory(
        self, recently_unlocked: Optional[dict]
    ) -> str:
        """최근 해금된 기억 정보를 포맷팅

        Args:
            recently_unlocked: 최근 해금된 기억 딕셔너리

        Returns:
            포맷된 문자열 또는 빈 문자열
        """
        if not recently_unlocked:
            return ""

        return f"""
<recently_unlocked_memory>
- memory_progress: {recently_unlocked.get('memory_progress', 0)}
- 제목: {recently_unlocked.get('title', '')}
- 키워드: {recently_unlocked.get('keywords', [])}
- 남은 턴: {recently_unlocked.get('ttl_turns', 0)}턴
</recently_unlocked_memory>
"""

    async def _classify_intent(self, state: HeroineState) -> str:
        """의도 분류 (최근 3턴 맥락 포함)

        사용자 메시지의 의도를 분류합니다:
        - general: 일반 대화
        - memory_recall: 과거 대화/경험 질문 (User Memory 검색)
        - scenario_inquiry: 히로인 과거/비밀 질문 (시나리오 DB 검색)

        최근 3턴 대화와 최근 해금된 기억 정보를 참조하여
        "그때", "그거" 같은 지시어가 포함된 꼬리질문도 처리합니다.

        Args:
            state: 현재 상태

        Returns:
            의도 문자열
        """
        user_message = state["messages"][-1].content

        # 최근 3턴 대화 가져오기 (6개 메시지 = 3턴)
        conversation_buffer = state.get("conversation_buffer", [])
        recent_turns = conversation_buffer[-6:]
        recent_dialogue = self._format_recent_turns(recent_turns)

        # 최근 해금된 기억 정보
        recently_unlocked = state.get("recently_unlocked_memory")
        unlocked_context = self._format_recently_unlocked_memory(recently_unlocked)

        prompt = f"""
        <GOAL>
        다음 <player_message>의 의도를 분류하세요.
        </GOAL>
<recent_dialogue>
{recent_dialogue}
</recent_dialogue>
{unlocked_context}
<player_message>
{user_message}
</player_message>

<classification_rules>
- general: 일상 대화, 감정 표현, 질문 없는 대화
- memory_recall: 플레이어와 히로인이 함께 나눈 과거 대화/경험, 다른 히로인에 대한 의견/평가 질문 ("루파메스 어때?", "레티아를 어떻게 생각해?")
- scenario_inquiry: 히로인 본인의 신상정보 (고향, 어린시절, 가족), 히로인의 과거, 기억 상실 전 이야기, 정체성. "최근에 돌아온 기억", "새로 기억난 거" 같은 질문도 포함
  - "그때", "그거", "방금 말한 거" 같은 지시어가 최근 히로인 발화의 기억/과거 이야기를 가리키면 scenario_inquiry
  - 최근 해금된 기억이 있고 그것과 관련된 질문이면 scenario_inquiry
- heroine_recall: 다른 히로인과 나눈 대화 내용 질문 ("루파메스랑 뭐 얘기했어?", "레티아와 무슨 대화 했어?", "로코한테 뭐라고 했어?")
</classification_rules>

<output>
반드시 general, memory_recall, scenario_inquiry, heroine_recall 중 하나만 출력하세요.
</output>
"""

        # 의도 분류 프롬프트 로그 출력
        print(f"[INTENT_PROMPT]\n{prompt}\n{'='*50}")

        response = await self.intent_llm.ainvoke(prompt)
        intent = response.content.strip().lower()

        # 유효하지 않으면 기본값
        if intent not in [
            "general",
            "memory_recall",
            "scenario_inquiry",
            "heroine_recall",
        ]:
            intent = "general"

        print(f"[INTENT_RESULT] {intent}")
        return intent

    async def _retrieve_memory(self, state: HeroineState) -> str:
        """기억 검색

        1. 시간 키워드 분석 (어제, N일 전, 최근 등)
        2. User Memory에서 플레이어-NPC 대화 기억 검색 (4요소 하이브리드)
        3. 다른 히로인 이름 언급시 NPC-NPC 대화 검색

        Args:
            state: 현재 상태

        Returns:
            검색된 기억 텍스트
        """
        user_message = state["messages"][-1].content
        player_id = state["player_id"]
        npc_id = state["npc_id"]

        facts_parts = []

        # 1. 시간 키워드 분석 (정규식)
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
        # 전체 기억 요청
        elif re.search(r"(전부|다\s|모든|기억하는\s*거)", user_message):
            print("[MEMORY_FUNC] get_valid_memories_sync")
            user_memories = user_memory_manager.get_valid_memories_sync(
                player_id, npc_id, limit=10
            )
        # 특정 날짜 (N월 N일)
        elif date_match := re.search(r"(\d{1,2})월\s*(\d{1,2})일", user_message):
            month = int(date_match.group(1))
            day = int(date_match.group(2))
            year = datetime.now().year
            point_in_time = datetime(year, month, day)
            print(f"[MEMORY_FUNC] get_memories_at_point_sync({month}/{day})")
            user_memories = user_memory_manager.get_memories_at_point_sync(
                player_id, npc_id, point_in_time, limit=5
            )
        # 지지난주 X요일
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
        # 지난주 X요일
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
            # 기본: 4요소 하이브리드 검색
            print("[MEMORY_FUNC] search_memory_sync (hybrid)")
            user_memories = user_memory_manager.search_memory_sync(
                player_id, npc_id, user_message, limit=3
            )

        if user_memories:
            facts_parts.append("[플레이어와의 기억]")
            for m in user_memories:
                memory_text = m.get("memory", m.get("text", ""))
                facts_parts.append(f"- {memory_text}")

        # 2. 다른 히로인 이름 언급시 NPC-NPC 장기기억 검색
        other_id = None
        if "사트라" in user_message or "대현자" in user_message:
            other_id = 0
        elif "레티아" in user_message:
            other_id = 1
        elif "루파메스" in user_message:
            other_id = 2
        elif "로코" in user_message:
            other_id = 3

        if other_id is not None and int(other_id) != int(npc_id):
            npc_memories = npc_npc_memory_manager.search_memories(
                player_id=str(player_id),
                npc1_id=int(npc_id),
                npc2_id=int(other_id),
                query=user_message,
                limit=3,
            )
            if npc_memories:
                facts_parts.append("\n[다른 히로인과의 대화 기억]")
                for m in npc_memories:
                    facts_parts.append(f"- {m.get('content', '')}")

        return "\n".join(facts_parts) if facts_parts else "관련 기억 없음"

    def _is_recent_memory_question(self, message: str) -> bool:
        """최근 기억 관련 질문인지 확인

        Args:
            message: 사용자 메시지

        Returns:
            최근 기억 질문 여부
        """
        recent_memory_keywords = [
            "최근",
            "돌아온 기억",
            "새로 기억",
            "떠오른 기억",
            "방금 기억",
            "이제 기억",
            "생각난",
            "떠올랐",
        ]
        return any(keyword in message for keyword in recent_memory_keywords)

    def _is_follow_up_question(self, message: str) -> bool:
        """꼬리질문(지시어 포함)인지 확인

        "그때", "그거" 같은 지시어가 포함된 질문을 감지합니다.

        Args:
            message: 사용자 메시지

        Returns:
            꼬리질문 여부
        """
        follow_up_keywords = [
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
        return any(keyword in message for keyword in follow_up_keywords)

    async def _retrieve_scenario(self, state: HeroineState) -> str:
        """시나리오 DB 검색

        현재 기억진척도 이하로 해금된 시나리오를 검색합니다.

        우선순위:
        1. recently_unlocked_memory가 있고 꼬리질문이면 -> 해당 시나리오 우선
        2. "최근에 돌아온 기억" 질문이면 -> 가장 최근 해금된 시나리오
        3. 일반 시나리오 질문 -> PGroonga + Vector 하이브리드 검색

        Args:
            state: 현재 상태

        Returns:
            검색된 시나리오 텍스트
        """
        user_message = state["messages"][-1].content
        npc_id = state["npc_id"]
        memory_progress = state.get("memoryProgress", 0)

        # 1. recently_unlocked_memory가 있고 꼬리질문이면 해당 시나리오 우선 검색
        recently_unlocked = state.get("recently_unlocked_memory")
        if recently_unlocked and self._is_follow_up_question(user_message):
            unlocked_progress = recently_unlocked.get("memory_progress")
            if unlocked_progress is not None:
                scenario = heroine_scenario_service.get_scenario_by_exact_progress(
                    heroine_id=npc_id, memory_progress=unlocked_progress
                )
                if scenario:
                    print(
                        f"[DEBUG] 꼬리질문 감지 - recently_unlocked_memory 시나리오 반환: {scenario.get('title', 'N/A')}"
                    )
                    return scenario["content"]

        # 2. 최근 기억 질문이면 가장 최근 해금된 시나리오 반환
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

        # 3. 일반 시나리오 질문은 PGroonga + Vector 하이브리드 검색
        scenarios = heroine_scenario_service.search_scenarios_pgroonga(
            query=user_message,
            heroine_id=npc_id,
            max_memory_progress=memory_progress,
            limit=2,
        )

        if scenarios:
            return "\n\n".join([s["content"] for s in scenarios])
        return "해금된 시나리오 없음"

    def _detect_other_heroine_id(
        self, user_message: str, current_npc_id: int
    ) -> Optional[int]:
        """사용자 메시지에서 다른 히로인 ID 감지

        Args:
            user_message: 사용자 메시지
            current_npc_id: 현재 대화중인 NPC ID

        Returns:
            다른 히로인 ID 또는 None
        """
        other_id = None
        if "사트라" in user_message or "대현자" in user_message:
            other_id = 0
        elif "레티아" in user_message:
            other_id = 1
        elif "루파메스" in user_message:
            other_id = 2
        elif "로코" in user_message:
            other_id = 3

        # 현재 NPC와 다른 경우만 반환
        if other_id is not None and int(other_id) != int(current_npc_id):
            return other_id
        return None

    async def _retrieve_heroine_conversation(self, state: HeroineState) -> str:
        """다른 히로인과의 최근 대화 검색

        npc_npc_checkpoints 테이블에서 가장 최신의 대화를 가져옵니다.

        Args:
            state: 현재 상태

        Returns:
            포맷된 대화 내용 문자열
        """
        user_message = state["messages"][-1].content
        player_id = state["player_id"]
        npc_id = state["npc_id"]

        # 다른 히로인 ID 감지
        other_id = self._detect_other_heroine_id(user_message, npc_id)

        if other_id is None:
            return "관련 대화 없음"

        # 최신 checkpoint에서 대화 가져오기
        conversation = npc_npc_memory_manager.get_latest_checkpoint_conversation(
            player_id=str(player_id),
            npc1_id=int(npc_id),
            npc2_id=int(other_id),
        )

        if not conversation:
            return "관련 대화 없음"

        # 대화 포맷팅
        npc_names = {0: "사트라", 1: "레티아", 2: "루파메스", 3: "로코"}
        lines = ["[다른 히로인과의 최근 대화]"]
        for msg in conversation:
            speaker_id = msg.get("speaker_id")
            text = msg.get("text", "")
            speaker_name = npc_names.get(speaker_id, f"NPC_{speaker_id}")
            lines.append(f"{speaker_name}: {text}")

        return "\n".join(lines)

    async def _prepare_context(self, state: HeroineState) -> Dict[str, Any]:
        """컨텍스트 준비 (스트리밍/비스트리밍 공통)

        LLM 호출 전에 필요한 모든 정보를 준비합니다:
        1. 키워드 분석 (호감도 변화량 계산)
        2. 의도 분류
        3. 의도에 따른 검색 (기억/시나리오)

        Args:
            state: 현재 상태

        Returns:
            컨텍스트 딕셔너리 (affection_delta, used_liked_keyword, intent, retrieved_facts, unlocked_scenarios)
        """
        import time

        total_start = time.time()

        # 1. 키워드 분석
        t1 = time.time()
        affection_delta, used_keyword = await self._analyze_keywords(state)
        print(f"[TIMING] 키워드 분석: {time.time() - t1:.3f}s")

        # 2. 의도 분류
        t2 = time.time()
        intent = await self._classify_intent(state)
        print(f"[TIMING] 의도 분류: {time.time() - t2:.3f}s")

        user_message = state["messages"][-1].content
        print(f"[DEBUG] 의도 분류 결과: {intent}")

        # 3. 시나리오 관련 키워드 확인 (의도 분류 보완)
        """
        scenario_keywords = [
            "고향",
            "과거",
            "기억",
            "옛날",
            "가족",
            "어렸을",
            "예전",
            "해금",
            "비밀",
            "정체",
        ]
        has_scenario_keyword = any(kw in user_message for kw in scenario_keywords)

        if has_scenario_keyword and intent != "scenario_inquiry":
            intent = "scenario_inquiry"
            print(f"[DEBUG] 키워드 감지로 의도 변경: scenario_inquiry")
        """
        # 4. 의도에 따른 검색
        retrieved_facts = "없음"
        unlocked_scenarios = "없음"
        heroine_conversation = "없음"
        preference_changes = []

        if intent == "memory_recall":
            # 기억 회상 -> User Memory + NPC간 기억 검색
            t3 = time.time()
            retrieved_facts = await self._retrieve_memory(state)
            print(f"[TIMING] 기억 검색: {time.time() - t3:.3f}s")
            print(
                f"[DEBUG] 기억 검색 결과: {retrieved_facts[:200] if retrieved_facts else 'None'}..."
            )
        elif intent == "scenario_inquiry":
            # 시나리오 질문 -> 시나리오 DB 검색
            t3 = time.time()
            unlocked_scenarios = await self._retrieve_scenario(state)
            print(f"[TIMING] 시나리오 검색: {time.time() - t3:.3f}s")
            print(
                f"[DEBUG] 시나리오 검색 결과: {unlocked_scenarios[:200] if unlocked_scenarios else 'None'}..."
            )
        elif intent == "heroine_recall":
            # 다른 히로인과의 대화 -> npc_npc_checkpoints에서 최신 대화
            t3 = time.time()
            heroine_conversation = await self._retrieve_heroine_conversation(state)
            print(f"[TIMING] 히로인 대화 검색: {time.time() - t3:.3f}s")
            print(
                f"[DEBUG] 히로인 대화 검색 결과: {heroine_conversation[:200] if heroine_conversation else 'None'}..."
            )

        # 5. 기억 해금 감지 및 recently_unlocked_memory TTL 관리
        newly_unlocked_scenario = None
        recently_unlocked_memory = None
        current_affection = state.get("affection", 0)
        current_memory_progress = state.get("memoryProgress", 0)
        npc_id = state["npc_id"]

        # 예상 new_affection 계산
        expected_new_affection = max(0, min(100, current_affection + affection_delta))

        # 예상 new_memory_progress 계산
        expected_new_progress = calculate_memory_progress(
            expected_new_affection, current_memory_progress, affection_delta
        )

        # 새로 해금되는 임계값 감지
        unlocked_threshold = detect_memory_unlock(
            current_memory_progress, expected_new_progress
        )

        if unlocked_threshold is not None:
            # 새로 기억 해금됨
            t4 = time.time()
            scenario = heroine_scenario_service.get_scenario_by_exact_progress(
                heroine_id=npc_id, memory_progress=unlocked_threshold
            )
            if scenario:
                newly_unlocked_scenario = scenario.get("content", "")
                # recently_unlocked_memory 생성 (TTL 5턴)
                recently_unlocked_memory = {
                    "memory_progress": unlocked_threshold,
                    "title": scenario.get("title", ""),
                    "keywords": scenario.get("metadata", {}).get("keywords", []),
                    "unlocked_at": datetime.now().isoformat(),
                    "ttl_turns": 5,
                }
                print(
                    f"[DEBUG] 기억 해금 감지! threshold={unlocked_threshold}, title={scenario.get('title', 'N/A')}"
                )
                print(
                    f"[DEBUG] recently_unlocked_memory 생성: keywords={recently_unlocked_memory['keywords']}"
                )
            print(f"[TIMING] 해금 시나리오 조회: {time.time() - t4:.3f}s")
        else:
            # 기존 recently_unlocked_memory TTL 관리
            existing_memory = state.get("recently_unlocked_memory")
            if existing_memory:
                ttl = existing_memory.get("ttl_turns", 0) - 1
                if ttl > 0:
                    # TTL 감소해서 유지
                    recently_unlocked_memory = {
                        "memory_progress": existing_memory.get("memory_progress"),
                        "title": existing_memory.get("title", ""),
                        "keywords": existing_memory.get("keywords", []),
                        "unlocked_at": existing_memory.get("unlocked_at", ""),
                        "ttl_turns": ttl,
                    }
                    print(f"[DEBUG] recently_unlocked_memory TTL 감소: {ttl}턴 남음")
                else:
                    print("[DEBUG] recently_unlocked_memory TTL 만료, 삭제됨")

        print(f"[TIMING] 컨텍스트 준비 총합: {time.time() - total_start:.3f}s")
        return {
            "affection_delta": affection_delta,
            "used_liked_keyword": used_keyword,
            "intent": intent,
            "retrieved_facts": retrieved_facts,
            "unlocked_scenarios": unlocked_scenarios,
            "heroine_conversation": heroine_conversation,
            "preference_changes": preference_changes,
            "newly_unlocked_scenario": newly_unlocked_scenario,
            "recently_unlocked_memory": recently_unlocked_memory,
        }

    def _build_full_prompt(
        self, state: HeroineState, context: Dict[str, Any]
    ) -> str:
        """전체 프롬프트 생성

        Args:
            state: 현재 상태
            context: 컨텍스트 (검색 결과 등)

        Returns:
            프롬프트 문자열
        """
        npc_id = state["npc_id"]
        persona = self._get_persona(npc_id)

        affection = state.get("affection", 0)
        sanity = state.get("sanity", 100)
        memory_progress = state.get("memoryProgress", 0)

        # 호감도 변화 힌트 (LLM에게 알려줌)
        pre_calculated_delta = context.get("affection_delta", 0)
        if pre_calculated_delta > 0:
            affection_hint = f"플레이어가 당신이 좋아하는 것에 대해 말했습니다. [페르소나]를 참조해서 매우 좋아하며 대답하세요 (호감도 +{pre_calculated_delta})"
        elif pre_calculated_delta < 0:
            affection_hint = f"플레이어가 당신의 트라우마를 건드렸습니다. [페르소나]를 참고해서 매우 단호하고 불쾌해 하며 대답하세요 (호감도 {pre_calculated_delta})"
        else:
            affection_hint = "특별한 호감도 변화 없음"

        # 출력 형식
        output_format = """[출력 형식]
반드시 아래 JSON 형식으로 출력하세요:
{
    "thought": "(내면의 생각 - 플레이어에게 보이지 않음)",
    "text": "(실제 대화 내용)",
    "emotion": "neutral|joy|fun|sorrow|angry|surprise|mysterious",
    "emotion_intensity": 0.5~2.0 사이의 실수 (0.5=약한 감정, 1.0=보통, 1.5=강함, 2.0=극도로 강함)
}"""

        time_since_last_chat = self.get_time_since_last_chat(state["player_id"], npc_id)

        # 플레이어 이름 가져오기
        player_known_name = None
        session = redis_manager.load_session(state["player_id"], npc_id)
        if session and "state" in session:
            player_known_name = session["state"].get("player_known_name")

        # 세계관 컨텍스트 가져오기
        world_context = PERSONA_DATA.get("world_context", {})

        prompt = f"""당신은 히로인 {persona.get('name', '알 수 없음')}입니다.

[핵심 목표]
- 최근 대화는 '맥락 파악'에만 사용합니다.
- [페르소나]에 충실하게 답변하세요.
- 같은 질문이 반복되어도 과거 답변 문장을 그대로 복사하지 않습니다.
- 반드시 [현재 호감도 레벨], [페르소나], [호감도 변화 정보], [장기 기억 (검색 결과)], [해금된 시나리오], [플레이어 메세지]를 근거로 새로 답합니다.
- <must_include>이 있으면 반드시 언급해야 합니다.

[답변 결정 절차 - 반드시 준수]
1) 질문 유형 판별 (두 가지로 구분)
A) 플레이어와의 대화/경험 질문: "N일 전에 뭐 했지?", "어제 뭐 얘기했지?", "우리 전에 뭐 얘기했지?" 등
B) 자신의 과거/신상 질문: "고향이 어디야?", "어린시절 어땠어?", "가족은?" 등

2) [장기 기억] 우선 적용 규칙 (가장 중요!)
- [장기 기억 (검색 결과)]에 "없음"이 아닌 내용이 있으면, 반드시 그 내용을 text에 포함해야 합니다.
- 예: [장기 기억]에 내용이 있으면 해당 키워드를 반드시 언급
- <raw_recent_dialogue_do_not_quote>에서 "기억 안 나"라고 했어도, [장기 기억]에 내용이 있으면 이번엔 기억난 것처럼 답합니다.
- 이 규칙은 다른 모든 규칙보다 우선합니다.

3) '기억 없음' 처리 (B유형 질문 + 두 조건 모두 충족시에만)
- [플레이어 메세지]가 B유형(자신의 과거/신상) 질문이고,
- [페르소나]에 없는 내용이고,
- [해금된 시나리오]가 "없음"이며,
- [장기 기억 (검색 결과)]도 "없음" 또는 관련 없는 내용이면
=> text에 "잘 기억이 안 나..." 라고 답합니다(30자 이내).
- 주의: A유형(플레이어와의 대화 질문)에는 이 규칙을 적용하지 않습니다!

4) 최근대화 '비복사' 규칙(실패 조건)
- <raw_recent_dialogue_do_not_quote> 안의 문장/구문을 그대로 복사하면 실패입니다.
- "잘 떠오르지 않아요", "희미해요", "기억 안 나요" 같은 표현은 [장기 기억]에 내용이 있으면 절대 사용하지 않습니다.

5) 출력/말투 규칙
- 캐릭터 말투와 성격을 일관되게 유지합니다.
- text는 반드시 30자 이내로 답합니다.
- **순수하게 페르소나에 입각해서 캐릭터의 대사만 출력하세요**
- [플레이어 정보]를 참고하여 플레이어를 호칭하세요. 이름을 알면 이름으로, 모르면 "멘토"로 부르세요.

[페르소나 규칙]
- [세계관 컨텍스트]는 당신이 현재 알고 있는 정보입니다. 이 정보를 통해 당신은 이곳에 왜 있는지 플레이어가 누군지 알 수 있습니다.
- [해금된 시나리오]는 당신의 과거 기억입니다. [플레이어 메세지]가 과거/어린시절/고향 등을 물어볼 때만 참조하세요.
- [해금된 시나리오]가 "없음"인데 자신의 과거 기억(어린시절, 고향, 가족 등)을 물어볼 때만 "잘 기억이 안 나..." 라고 답합니다.
- [다른 히로인과의 대화 기억]은 다른 히로인에 대한 의견/평가 질문에 참조합니다.
- [다른 히로인과의 최근 대화]는 다른 히로인과 나눈 대화 내용 질문에 참조합니다. 이 대화를 바탕으로 "뭐 얘기했어?" 같은 질문에 답하세요.
- [해금된 시나리오]에 관련 내용이 있으면, 이전에 "기억 안 나"라고 했어도 이번엔 기억난 것처럼 답하세요.
- 해금되지 않은 기억(memoryProgress > {memory_progress})은 절대 말하지 않습니다.
- [현재 상태]의 Sanity가 0이면 매우 우울한 상태로 대화합니다.

[음성 입력 처리]
- 플레이어 메시지는 음성->텍스트 변환 결과입니다.
- 발음 유사 오인식 가능 (예: "좋아해"->"조아해")
- 문맥과 대화 흐름으로 의도를 추론하세요.
- 불분명하면 캐릭터 말투로 자연스럽게 되물으세요.
- 기술 용어(음성인식, STT, 오류 등)는 절대 사용 금지.

[플레이어 정보]
- 이름: {player_known_name if player_known_name else '알 수 없음'}
- 호칭: {player_known_name if player_known_name else '멘토'} (이름을 알면 이름으로, 모르면 "멘토"로 호칭)

[세계관 컨텍스트 - 당신이 알고 있는 기본 정보]
- 길드: {world_context.get('guild', '셀레파이스 길드')}
- 멘토: {world_context.get('mentor', '기억을 되찾게 해줄 수 있는 특별한 존재')}
- 내 상황: {world_context.get('amnesia', '암네시아로 기억을 잃음')}
- 던전: {world_context.get('dungeon', '기억의 파편을 얻을 수 있는 곳')}
- 현재: {world_context.get('current_situation', '길드에서 멘토와 함께 생활 중')}

[마지막 대화로부터 경과 시간]
{time_since_last_chat}

[현재 상태]
- 호감도(Affection): {affection}
- 정신력(Sanity): {sanity}
- 기억진척도(MemoryProgress): {memory_progress}

[페르소나]
{self._format_persona(persona, affection, sanity)}

[호감도 변화 정보]
{affection_hint}

[장기 기억 (검색 결과)]
{context.get('retrieved_facts', '없음')}

{self._format_preference_changes(context.get('preference_changes', []))}
[해금된 시나리오]
{context.get('unlocked_scenarios', '없음')}

{self._format_newly_unlocked_scenario(context.get('newly_unlocked_scenario'))}

[다른 히로인과의 최근 대화]
{context.get('heroine_conversation', '없음')}



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

<STRONG_RULE>
- 캐릭터의 대사 이외의 데이터 출력 금지
</STRONG_RULE>

[플레이어 메세지]
{state['messages'][-1].content}

{output_format}"""

        return prompt

    async def _update_state_after_response(
        self,
        state: HeroineState,
        context: Dict[str, Any],
        response_text: str,
        emotion_int: int = 0,
    ) -> Dict[str, Any]:
        """응답 후 상태 업데이트 (LLM 재호출 없이)

        스트리밍/비스트리밍 모두 이 메서드로 상태를 업데이트합니다.

        저장 위치:
        - Redis: 세션 상태 (affection, sanity, memoryProgress, conversation_buffer)
        - Mem0: User-NPC 대화 기억

        Args:
            state: 현재 상태
            context: 컨텍스트 (affection_delta 등)
            response_text: 생성된 응답 텍스트
            emotion_int: 감정 정수값 (기본값 0=neutral)

        Returns:
            업데이트된 상태 값들
        """
        player_id = state["player_id"]
        npc_id = state["npc_id"]

        # 현재 상태
        affection = state.get("affection", 0)
        sanity = state.get("sanity", 100)
        memory_progress = state.get("memoryProgress", 0)

        # 변화량
        affection_delta = context.get("affection_delta", 0)
        sanity_delta = affection_delta
        # if affection_delta > 0 else 0

        print(
            f"[DEBUG] _update_state: current affection={affection}, delta={affection_delta}"
        )

        # 새 값 계산
        new_affection = max(0, min(100, affection + affection_delta))
        new_sanity = max(0, min(100, sanity + sanity_delta))
        new_memory_progress = calculate_memory_progress(
            new_affection, memory_progress, affection_delta
        )
        print(
            f"[DEBUG] _update_state: new_affection={new_affection}, new_memory_progress={new_memory_progress}"
        )

        # Redis 세션 업데이트
        session = redis_manager.load_session(player_id, npc_id)
        player_known_name = None
        if session:
            # 상태 업데이트
            session["state"]["affection"] = new_affection
            session["state"]["sanity"] = new_sanity
            session["state"]["memoryProgress"] = new_memory_progress
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

            # 최근 사용된 좋아하는 키워드 업데이트 (5개 유지)
            used_keyword = context.get("used_liked_keyword")
            recent_keywords = session.get("recent_used_keywords", [])
            if used_keyword:
                recent_keywords.append(used_keyword)
            session["recent_used_keywords"] = recent_keywords[-5:]

            # recently_unlocked_memory Redis 세션 동기화
            recently_unlocked = context.get("recently_unlocked_memory")
            if recently_unlocked:
                session["recently_unlocked_memory"] = recently_unlocked
                print(
                    f"[DEBUG] Redis에 recently_unlocked_memory 저장: ttl={recently_unlocked.get('ttl_turns', 0)}"
                )
            else:
                # TTL 만료시 삭제
                if "recently_unlocked_memory" in session:
                    del session["recently_unlocked_memory"]
                    print("[DEBUG] Redis에서 recently_unlocked_memory 삭제 (TTL 만료)")

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
            "affection": new_affection,
            "sanity": new_sanity,
            "memoryProgress": new_memory_progress,
            "emotion": emotion_int,
            "response_text": response_text,
            "player_known_name": player_known_name,
        }

    async def _save_to_user_memory_background(
        self, player_id: int, npc_id: int, user_msg: str, npc_response: str
    ) -> None:
        """백그라운드로 User Memory에 대화 저장

        LLM으로 fact 추출 후 저장
        이름이 추출되면 Redis 세션에 저장

        Args:
            player_id: 플레이어 ID
            npc_id: NPC ID
            user_msg: 유저 메시지
            npc_response: NPC 응답
        """
        try:
            from db.user_memory_models import NPC_ID_TO_HEROINE

            heroine_id = NPC_ID_TO_HEROINE.get(npc_id, "letia")

            result = await user_memory_manager.save_conversation(
                player_id=str(player_id),
                heroine_id=heroine_id,
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
            session_checkpoint_manager.save_summary(player_id, npc_id, summary_list)

        except Exception as e:
            print(f"[ERROR] _generate_and_save_summary 실패: {e}")

    # ============================================
    # LangGraph 빌드 (비스트리밍용)
    # ============================================

    def _build_graph(self) -> StateGraph:
        """LangGraph 빌드

        노드 흐름:
        START -> keyword_analyze -> router
        router -> (분기)
            - general -> generate
            - memory_recall -> memory_retrieve -> generate
            - scenario_inquiry -> scenario_retrieve -> generate
        generate -> post_process -> END

        Returns:
            컴파일된 StateGraph
        """
        graph = StateGraph(HeroineState)

        # 노드 추가
        graph.add_node("keyword_analyze", self._keyword_analyze_node)
        graph.add_node("router", self._router_node)
        graph.add_node("memory_retrieve", self._memory_retrieve_node)
        graph.add_node("scenario_retrieve", self._scenario_retrieve_node)
        graph.add_node("heroine_retrieve", self._heroine_retrieve_node)
        graph.add_node("generate", self._generate_node)
        graph.add_node("post_process", self._post_process_node)

        # 엣지 추가
        graph.add_edge(START, "keyword_analyze")
        graph.add_edge("keyword_analyze", "router")

        # 조건부 분기
        graph.add_conditional_edges(
            "router",
            self._route_by_intent,
            {
                "general": "generate",
                "memory_recall": "memory_retrieve",
                "scenario_inquiry": "scenario_retrieve",
                "heroine_recall": "heroine_retrieve",
            },
        )

        graph.add_edge("memory_retrieve", "generate")
        graph.add_edge("scenario_retrieve", "generate")
        graph.add_edge("heroine_retrieve", "generate")
        graph.add_edge("generate", "post_process")
        graph.add_edge("post_process", END)

        return graph.compile()

    # ============================================
    # LangGraph 노드 구현
    # ============================================

    async def _keyword_analyze_node(self, state: HeroineState) -> dict:
        """키워드 분석 노드

        기억 해금 및 recently_unlocked_memory TTL 관리를 수행합니다.
        """
        import time

        t = time.time()
        affection_delta, used_keyword = await self._analyze_keywords(state)
        print(f"[TIMING] 키워드 분석: {time.time() - t:.3f}s")
        print(f"[DEBUG] affection_delta={affection_delta}, used_keyword={used_keyword}")

        # 기억 해금 감지
        newly_unlocked_scenario = None
        recently_unlocked_memory = None
        current_affection = state.get("affection", 0)
        current_memory_progress = state.get("memoryProgress", 0)
        npc_id = state["npc_id"]

        # 예상 new_affection 및 new_memory_progress 계산
        expected_new_affection = max(0, min(100, current_affection + affection_delta))
        expected_new_progress = calculate_memory_progress(
            expected_new_affection, current_memory_progress, affection_delta
        )

        # 새로 해금되는 임계값 감지
        unlocked_threshold = detect_memory_unlock(
            current_memory_progress, expected_new_progress
        )

        if unlocked_threshold is not None:
            # 새로 기억 해금됨
            t2 = time.time()
            scenario = heroine_scenario_service.get_scenario_by_exact_progress(
                heroine_id=npc_id, memory_progress=unlocked_threshold
            )
            if scenario:
                newly_unlocked_scenario = scenario.get("content", "")
                # recently_unlocked_memory 생성 (TTL 5턴)
                recently_unlocked_memory = {
                    "memory_progress": unlocked_threshold,
                    "title": scenario.get("title", ""),
                    "keywords": scenario.get("metadata", {}).get("keywords", []),
                    "unlocked_at": datetime.now().isoformat(),
                    "ttl_turns": 5,
                }
                print(
                    f"[DEBUG] 기억 해금 감지! threshold={unlocked_threshold}, title={scenario.get('title', 'N/A')}"
                )
                print(
                    f"[DEBUG] recently_unlocked_memory 생성: keywords={recently_unlocked_memory['keywords']}"
                )
            print(f"[TIMING] 해금 시나리오 조회: {time.time() - t2:.3f}s")
        else:
            # 기존 recently_unlocked_memory TTL 관리
            existing_memory = state.get("recently_unlocked_memory")
            if existing_memory:
                ttl = existing_memory.get("ttl_turns", 0) - 1
                if ttl > 0:
                    # TTL 감소해서 유지
                    recently_unlocked_memory = {
                        "memory_progress": existing_memory.get("memory_progress"),
                        "title": existing_memory.get("title", ""),
                        "keywords": existing_memory.get("keywords", []),
                        "unlocked_at": existing_memory.get("unlocked_at", ""),
                        "ttl_turns": ttl,
                    }
                    print(f"[DEBUG] recently_unlocked_memory TTL 감소: {ttl}턴 남음")
                else:
                    # TTL 만료
                    print("[DEBUG] recently_unlocked_memory TTL 만료, 삭제됨")

        return {
            "affection_delta": affection_delta,
            "used_liked_keyword": used_keyword,
            "newly_unlocked_scenario": newly_unlocked_scenario,
            "recently_unlocked_memory": recently_unlocked_memory,
        }

    async def _router_node(self, state: HeroineState) -> dict:
        """의도 분류 노드"""
        import time

        t = time.time()
        intent = await self._classify_intent(state)
        print(f"[TIMING] 의도 분류: {time.time() - t:.3f}s")
        user_message = state["messages"][-1].content
        print(f"[DEBUG] 의도 분류 결과: {intent}")

        # 시나리오 관련 키워드 확인 (의도 분류 보완)
        """
        scenario_keywords = [
            "고향",
            "과거",
            "기억",
            "전에",
            "옛날",
            "가족",
            "어렸을",
            "예전",
            "해금",
            "비밀",
            "정체",
        ]
        has_scenario_keyword = any(kw in user_message for kw in scenario_keywords)

        if has_scenario_keyword and intent != "scenario_inquiry":
            intent = "scenario_inquiry"
            print(f"[DEBUG] 키워드 감지로 의도 변경: scenario_inquiry")
        """
        return {"intent": intent}

    def _route_by_intent(self, state: HeroineState) -> str:
        """의도에 따라 라우팅"""
        return state.get("intent", "general")

    async def _memory_retrieve_node(self, state: HeroineState) -> dict:
        """기억 검색 노드"""
        import time

        t = time.time()
        facts = await self._retrieve_memory(state)
        print(f"[TIMING] 기억 검색: {time.time() - t:.3f}s")
        return {"retrieved_facts": facts}

    async def _scenario_retrieve_node(self, state: HeroineState) -> dict:
        """시나리오 DB 검색 노드"""
        import time

        t = time.time()
        scenarios = await self._retrieve_scenario(state)
        print(f"[TIMING] 시나리오 검색: {time.time() - t:.3f}s")
        print(
            f"[DEBUG] 시나리오 검색 결과: {scenarios[:200] if scenarios else 'None'}..."
        )
        return {"unlocked_scenarios": scenarios}

    async def _heroine_retrieve_node(self, state: HeroineState) -> dict:
        """다른 히로인과의 대화 검색 노드"""
        import time

        t = time.time()
        conversation = await self._retrieve_heroine_conversation(state)
        print(f"[TIMING] 히로인 대화 검색: {time.time() - t:.3f}s")
        print(
            f"[DEBUG] 히로인 대화 검색 결과: {conversation[:200] if conversation else 'None'}..."
        )
        return {"heroine_conversation": conversation}

    async def _generate_node(self, state: HeroineState) -> dict:
        """응답 생성 노드"""
        import time

        total_start = time.time()

        # 컨텍스트 구성
        context = {
            "affection_delta": state.get("affection_delta", 0),
            "retrieved_facts": state.get("retrieved_facts", "없음"),
            "unlocked_scenarios": state.get("unlocked_scenarios", "없음"),
            "heroine_conversation": state.get("heroine_conversation", "없음"),
            "preference_changes": state.get("preference_changes", []),
            "newly_unlocked_scenario": state.get("newly_unlocked_scenario"),
        }
        print(
            f"[DEBUG] generate 노드 - unlocked_scenarios: {context['unlocked_scenarios'][:200] if context['unlocked_scenarios'] != '없음' else '없음'}..."
        )
        if context["newly_unlocked_scenario"]:
            print(f"[DEBUG] generate 노드 - newly_unlocked_scenario 존재 (기억 해금됨)")

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
            }

        emotion_str = result.get("emotion", "neutral")
        emotion_intensity = result.get("emotion_intensity", 1.0)
        print(f"[TIMING] generate 노드 총합: {time.time() - total_start:.3f}s")
        return {
            "response_text": result.get("text", ""),
            "emotion": heroine_emotion_to_int(emotion_str),
            "emotion_str": emotion_str,
            "emotion_intensity": emotion_intensity,
        }

    async def _post_process_node(self, state: HeroineState) -> dict:
        """후처리 노드 - 상태 업데이트"""
        import time

        t = time.time()

        context = {
            "affection_delta": state.get("affection_delta", 0),
            "used_liked_keyword": state.get("used_liked_keyword"),
            "recently_unlocked_memory": state.get("recently_unlocked_memory"),
        }
        print(
            f"[DEBUG] post_process - affection_delta from state: {context['affection_delta']}"
        )

        result = await self._update_state_after_response(
            state,
            context,
            state.get("response_text", ""),
            state.get("emotion", 0),
        )

        print(
            f"[DEBUG] post_process - result: affection={result['affection']}, memoryProgress={result['memoryProgress']}"
        )
        print(f"[TIMING] 상태 업데이트: {time.time() - t:.3f}s")
        return {
            "affection": result["affection"],
            "sanity": result["sanity"],
            "memoryProgress": result["memoryProgress"],
        }

    # ============================================
    # 공개 메서드
    # ============================================

    async def process_message(self, state: HeroineState) -> HeroineState:
        """메시지 처리 (비스트리밍)

        LangGraph 전체 파이프라인을 실행합니다.

        Args:
            state: 입력 상태

        Returns:
            처리 후 상태
        """
        import time

        t = time.time()
        result = await self.graph.ainvoke(state)
        print(f"[TIMING] graph.ainvoke 내부: {time.time() - t:.3f}s")
        return result

# 싱글톤 인스턴스 (앱 전체에서 하나만 사용)
heroine_agent = HeroineAgent()
