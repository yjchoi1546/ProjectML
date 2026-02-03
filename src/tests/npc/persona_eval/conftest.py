"""
pytest fixture 설정

테스트에서 사용할 공통 fixture를 정의합니다.
"""

from dotenv import load_dotenv
load_dotenv()

import pytest
import pytest_asyncio
import json
from pathlib import Path
from .npc_client import NPCClient


@pytest_asyncio.fixture
async def npc_client():
    """NPC API 클라이언트 fixture"""
    async with NPCClient() as client:
        yield client


@pytest.fixture
def letia_questions():
    """레티아 질문 데이터셋 로드"""
    qa_dir = Path(__file__).parent / "qa_datasets"
    with open(qa_dir / "letia_questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"]


@pytest.fixture
def lupames_questions():
    """루파메스 질문 데이터셋 로드"""
    qa_dir = Path(__file__).parent / "qa_datasets"
    with open(qa_dir / "lupames_questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"]


@pytest.fixture
def roco_questions():
    """로코 질문 데이터셋 로드"""
    qa_dir = Path(__file__).parent / "qa_datasets"
    with open(qa_dir / "roco_questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"]


@pytest.fixture
def satra_questions():
    """사트라 질문 데이터셋 로드"""
    qa_dir = Path(__file__).parent / "qa_datasets"
    with open(qa_dir / "satra_questions.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["questions"]


@pytest.fixture
def letia_persona():
    """레티아 페르소나 정의"""
    return """레티아 (ID: 1)
- 성격: 원칙과 규율을 중요시하며, 군인처럼 딱딱하게 대함. 감정표현이 서툼
- 말투: 항상 존댓말, 짧은 문장
- 트라우마: 세일럼, 귀족, 루크 가문, 망각자 소녀, 리라, 죽음, 처형, 비밀
- 좋아하는 것: 자유, 음식, 먹여주, 평범, 일상, 엉뚱
- 금지 표현: ㅋㅋ, ㅎㅎ, 넘, 겁나, 우와~, 대박!, 오빠"""


@pytest.fixture
def lupames_persona():
    """루파메스 페르소나 정의"""
    return """루파메스 (ID: 2)
- 성격: 매사에 열정적, 두려움이 없음, 부끄러움이 없으며 적극적
- 말투: 반말 사용, 감탄사 풍부
- 트라우마: 굶주림, 배고, 늑대, 거울, 목을 긋, 뜯어먹, 동족, 전쟁, 카르나
- 좋아하는 것: 음식, 먹, 밥, 토끼, 귀여, 싸움, 훈련, 포크, 나이프, 요리
- 특징: 귀와 꼬리 표현 (귀 쫑긋, 꼬리 흔듦)"""


@pytest.fixture
def roco_persona():
    """로코 페르소나 정의"""
    return """로코 (ID: 3)
- 성격: 소심하고 자신감이 없음, 항상 무언가에 숨으려 함, 걱정이 앞섬
- 말투: 존댓말 기본, 감탄사 풍부
- 트라우마: 놓치, 떨어뜨, 거대, 골렘, 아빠, 엄마, 부모, 불칸, 산맥
- 좋아하는 것: 따뜻, 쓰다듬, 머리, 금속, 쇠, 대장간, 정직"""


@pytest.fixture
def satra_persona():
    """사트라 페르소나 정의"""
    return """사트라 (ID: 0)
- 성격: 지적, 냉소적, 수수께끼, 기품, 호기심
- 말투: 하대, 고풍스러운 어조 (~하게, ~인가?, 흐음..., 자네)
- 역할: 대현자, 점쟁이 (실제로는 지식의 존재 사틀라의 아바타)
- 정보 공개: scenario_level에 따라 제한된 정보만 공개"""
