"""
DeepEval용 커스텀 LLM 래퍼

GPT-5-mini 모델을 DeepEval의 평가 모델로 사용하기 위한 래퍼 클래스
"""

from dotenv import load_dotenv
load_dotenv()

from pathlib import Path
import sys

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from deepeval.models.base_model import DeepEvalBaseLLM
from langchain.chat_models import init_chat_model

# LangFuse 임포트 (테스트 환경에서도 추적)
try:
    from utils.langfuse_tracker import tracker, LANGFUSE_ENABLED
except ImportError:
    tracker = None
    LANGFUSE_ENABLED = False


class GPT5MiniEvaluator(DeepEvalBaseLLM):
    """
    DeepEval 평가용 GPT-5-mini 모델 래퍼
    
    DeepEvalBaseLLM을 상속하여 GPT-5-mini를 평가 모델로 사용할 수 있게 합니다.
    """
    
    def __init__(self, temperature: float = 0):
        """
        Args:
            temperature: LLM 온도 설정 (기본값 0으로 일관된 평가)
        """
        self.model = init_chat_model(model="gpt-5-mini", temperature=temperature)
        super().__init__()
    
    def _get_callback_config(self, is_async: bool = False) -> dict:
        """LangFuse 콜백 설정 반환 (v3 API)"""
        if not tracker or not LANGFUSE_ENABLED:
            return {}
            
        return tracker.get_langfuse_config(
            tags=["deepeval", "evaluation", "persona_test"],
            metadata={"async": is_async}
        )
    
    def generate(self, prompt: str) -> str:
        """
        동기 방식으로 프롬프트에 대한 응답 생성 - LangFuse 추적 포함
        
        Args:
            prompt: 평가를 위한 프롬프트
            
        Returns:
            생성된 응답 텍스트
        """
        config = self._get_callback_config(is_async=False)
        response = self.model.invoke(prompt, **config)
        return response.content
    
    async def a_generate(self, prompt: str) -> str:
        """
        비동기 방식으로 프롬프트에 대한 응답 생성 - LangFuse 추적 포함
        
        Args:
            prompt: 평가를 위한 프롬프트
            
        Returns:
            생성된 응답 텍스트
        """
        config = self._get_callback_config(is_async=True)
        response = await self.model.ainvoke(prompt, **config)
        return response.content
    
    def load_model(self):
        """
        모델 로드 (이미 __init__에서 로드됨)

        Returns:
            로드된 모델 인스턴스
        """
        return self.model

    def get_model_name(self) -> str:
        """
        모델 이름 반환

        Returns:
            모델 이름 문자열
        """
        return "gpt-5-mini"


# 싱글톤 인스턴스 (테스트 전체에서 재사용)
evaluator_llm = GPT5MiniEvaluator()
