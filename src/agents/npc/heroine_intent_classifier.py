"""
HeroineIntentClassifier - 히로인 의도 분류 전문 클래스

히로인과의 대화에서 사용자 메시지의 의도를 분류합니다.

의도 종류 (4가지):
1. general: 일상 대화, 감정 표현
2. memory_recall: 플레이어-히로인 과거 대화/경험 질문
3. scenario_inquiry: 히로인 본인의 과거/신상 질문
4. heroine_recall: 다른 히로인과 나눈 대화 내용 질문

이 클래스가 없을 경우 발생할 문제:
- 의도 분류 프롬프트 수정 시 HeroineAgent 전체를 수정해야 함
- 의도 분류 로직 테스트가 Agent 전체 테스트에 종속됨
- SRP 위반으로 유지보수 어려움
"""

from typing import Optional, List, Dict, Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from agents.npc.base_npc_agent import NO_DATA
from utils.langfuse_tracker import tracker


class HeroineIntentClassifier:
    """히로인 의도 분류 전문 클래스

    사용자 메시지의 의도를 분류하여 적절한 검색 전략을 결정합니다.
    최근 대화 맥락과 해금된 기억 정보를 참조하여 꼬리질문도 처리합니다.

    아키텍처 위치:
    - HeroineAgent의 의도 분류 책임을 위임받음
    - LLM과 직접 통신하여 의도 분류

    사용 예시:
        classifier = HeroineIntentClassifier(intent_llm)
        intent = await classifier.classify(
            user_message="어제 뭐 얘기했지?",
            conversation_buffer=[...],
            recently_unlocked=None
        )
        # -> "memory_recall"
    """

    # 유효한 의도 목록
    VALID_INTENTS = ["general", "memory_recall", "scenario_inquiry", "heroine_recall"]
    DEFAULT_INTENT = "general"

    def __init__(self, intent_llm: BaseChatModel):
        """초기화

        Args:
            intent_llm: 의도 분류용 LLM (temperature=0 권장)
        """
        self.intent_llm = intent_llm

    async def classify(
        self,
        user_message: str,
        conversation_buffer: List[Dict[str, str]],
        recently_unlocked: Optional[Dict[str, Any]] = None,
        heroine_name: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """의도 분류

        사용자 메시지의 의도를 분류합니다.

        Args:
            user_message: 사용자 메시지
            conversation_buffer: 최근 대화 버퍼 [{"role": "user/assistant", "content": "..."}, ...]
            recently_unlocked: 최근 해금된 기억 정보 (TTL 기반)
            heroine_name: 히로인 이름 (로깅용)
            session_id: 세션 ID (LangFuse용)
            user_id: 유저 ID (LangFuse용)

        Returns:
            의도 문자열 (general/memory_recall/scenario_inquiry/heroine_recall)
        """
        # 최근 3턴 대화 (6개 메시지)
        recent_turns = conversation_buffer[-6:]
        recent_dialogue = self._format_recent_turns(recent_turns)

        # 최근 해금된 기억 정보
        unlocked_context = self._format_recently_unlocked_memory(recently_unlocked)

        prompt = self._build_classification_prompt(
            user_message, recent_dialogue, unlocked_context
        )

        # 의도 분류 프롬프트 로그
        print(f"[INTENT_PROMPT]\n{prompt}\n{'='*50}")

        # LangFuse 토큰 추적
        config = tracker.get_langfuse_config(
            tags=["npc", "heroine", "intent", heroine_name or "unknown"],
            session_id=session_id,
            user_id=user_id,
            metadata={"heroine_name": heroine_name}
        )

        response = await self.intent_llm.ainvoke(prompt, **config)
        intent = response.content.strip().lower()

        # 유효성 검증
        if intent not in self.VALID_INTENTS:
            intent = self.DEFAULT_INTENT

        print(f"[INTENT_RESULT] {intent}")
        return intent

    def _format_recent_turns(self, conversation_buffer: List[Dict[str, str]]) -> str:
        """최근 대화를 포맷팅

        Args:
            conversation_buffer: 대화 버퍼 리스트

        Returns:
            포맷된 대화 문자열
        """
        if not conversation_buffer:
            return NO_DATA

        lines = []
        for item in conversation_buffer:
            role = "플레이어" if item.get("role") == "user" else "히로인"
            content = item.get("content", "")
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def _format_recently_unlocked_memory(
        self, recently_unlocked: Optional[Dict[str, Any]]
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

    def _build_classification_prompt(
        self, user_message: str, recent_dialogue: str, unlocked_context: str
    ) -> str:
        """의도 분류 프롬프트 생성

        Args:
            user_message: 사용자 메시지
            recent_dialogue: 포맷된 최근 대화
            unlocked_context: 해금된 기억 컨텍스트

        Returns:
            프롬프트 문자열
        """
        return f"""
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


# 팩토리 함수 (필요시 사용)
def create_heroine_intent_classifier(
    model_name: str, temperature: float = 0, max_tokens: int = 20
) -> HeroineIntentClassifier:
    """HeroineIntentClassifier 인스턴스 생성

    Args:
        model_name: LLM 모델명
        temperature: LLM temperature (기본 0)
        max_tokens: 최대 토큰 수 (기본 20)

    Returns:
        HeroineIntentClassifier 인스턴스
    """
    intent_llm = init_chat_model(
        model=model_name, temperature=temperature, max_tokens=max_tokens
    )
    return HeroineIntentClassifier(intent_llm)
