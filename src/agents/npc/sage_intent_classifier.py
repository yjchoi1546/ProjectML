"""
SageIntentClassifier - 대현자 의도 분류 전문 클래스

대현자와의 대화에서 사용자 메시지의 의도를 분류합니다.

의도 종류 (3가지):
1. general: 일상 대화, 안부, 농담, 사트라 본인에 대한 질문
2. memory_recall: 플레이어-대현자 과거 대화/경험 질문
3. worldview_inquiry: 세계관, 국가, 종족, 던전 등 정보 질문

이 클래스가 없을 경우 발생할 문제:
- 의도 분류 프롬프트 수정 시 SageAgent 전체 수정 필요
- 의도 분류 로직 테스트가 Agent에 종속됨
"""

from typing import Optional, List, Dict, Any

from langchain_core.language_models.chat_models import BaseChatModel

from utils.langfuse_tracker import tracker


class SageIntentClassifier:
    """대현자 의도 분류 전문 클래스

    사용자 메시지의 의도를 분류하여 적절한 검색 전략을 결정합니다.

    아키텍처 위치:
    - SageAgent의 의도 분류 책임을 위임받음
    - LLM과 직접 통신하여 의도 분류

    사용 예시:
        classifier = SageIntentClassifier(intent_llm)
        intent = await classifier.classify(
            user_message="던전이 뭐야?",
            conversation_context="..."
        )
        # -> "worldview_inquiry"
    """

    # 유효한 의도 목록
    VALID_INTENTS = ["general", "memory_recall", "worldview_inquiry"]
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
        conversation_context: str = "",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """의도 분류

        사용자 메시지의 의도를 분류합니다.

        Args:
            user_message: 사용자 메시지
            conversation_context: 최근 대화 맥락 (short_term_summary)
            session_id: 세션 ID (LangFuse용)
            user_id: 유저 ID (LangFuse용)

        Returns:
            의도 문자열 (general/memory_recall/worldview_inquiry)
        """
        prompt = self._build_classification_prompt(user_message, conversation_context)

        # LangFuse 토큰 추적
        config = tracker.get_langfuse_config(
            tags=["npc", "sage", "intent"],
            session_id=session_id,
            user_id=user_id,
            metadata={"npc_name": "sage_satra"}
        )

        response = await self.intent_llm.ainvoke(prompt, **config)
        intent = response.content.strip().lower()

        # 유효성 검증
        if intent not in self.VALID_INTENTS:
            intent = self.DEFAULT_INTENT

        return intent

    def _build_classification_prompt(
        self, user_message: str, conversation_context: str
    ) -> str:
        """의도 분류 프롬프트 생성

        Args:
            user_message: 사용자 메시지
            conversation_context: 최근 대화 맥락

        Returns:
            프롬프트 문자열
        """
        return f"""다음 플레이어 메시지의 의도를 분류하세요.

[최근 대화 맥락]
{conversation_context}

[플레이어 메시지]
{user_message}

[분류 기준]
- general: 일상 대화, 안부, 농담, 사트라 본인에 대한 질문
- memory_recall: "우리 전에 뭐 얘기했지?", "어제 뭐 했어?", "기억나?" 등 플레이어와 대현자가 함께 나눈 과거 대화/경험 질문
- worldview_inquiry: 세계관, 국가, 종족, 던전, 디멘시움, 플레이어(멘토)의 과거/능력 등에 대한 질문

반드시 general, memory_recall, worldview_inquiry 중 하나만 출력하세요."""
