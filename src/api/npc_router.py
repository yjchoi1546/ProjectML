"""
NPC API 라우터

언리얼 엔진과 NPC 시스템 간의 통신 프로토콜입니다.
"""

import asyncio
import random
import base64
import time
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from langchain_core.messages import HumanMessage

from db.redis_manager import redis_manager
from db.session_checkpoint_manager import session_checkpoint_manager
from agents.npc.heroine_agent import heroine_agent
from agents.npc.sage_agent import sage_agent
from agents.npc.heroine_heroine_agent import heroine_heroine_agent
from agents.npc.base_npc_agent import MAX_CONVERSATION_BUFFER_SIZE
from agents.npc.npc_constants import NPC_ID_TO_NAME_EN
from tools.audio.tts_typecast import typecast_tts_service

# ============================================
# TTS 음성 파일 로컬 저장 (디버그/피드백용)
# ============================================

# 음성 저장 디렉토리 (프로젝트 루트/audio_logs)
AUDIO_LOG_DIR = Path(__file__).parent.parent.parent / "audio_logs"


def save_audio_file_background(
    audio_bytes: bytes,
    player_id: str,
    npc_id: int,
    text: str,
    emotion: int,
    endpoint_type: str = "chat",
):
    """백그라운드에서 음성 파일을 로컬에 저장합니다.

    저장 경로: audio_logs/{날짜}/{endpoint_type}/{npc_name}/{timestamp}_{player_id}.wav
    """
    try:
        # 날짜별 디렉토리 생성
        today = datetime.now().strftime("%Y-%m-%d")
        npc_name = NPC_ID_TO_NAME_EN.get(npc_id, f"npc_{npc_id}")

        save_dir = AUDIO_LOG_DIR / today / endpoint_type / npc_name
        save_dir.mkdir(parents=True, exist_ok=True)

        # 파일명: timestamp_playerid_emotion.wav
        timestamp = datetime.now().strftime("%H%M%S_%f")
        filename = f"{timestamp}_{player_id}_e{emotion}.wav"
        filepath = save_dir / filename

        # WAV 파일 저장
        with open(filepath, "wb") as f:
            f.write(audio_bytes)

        # 텍스트도 함께 저장 (어떤 대사인지 확인용)
        text_filepath = save_dir / f"{timestamp}_{player_id}_e{emotion}.txt"
        with open(text_filepath, "w", encoding="utf-8") as f:
            f.write(f"NPC: {npc_name}\n")
            f.write(f"Emotion: {emotion}\n")
            f.write(f"Text: {text}\n")

        print(f"[AUDIO LOG] Saved: {filepath}")
    except Exception as e:
        print(f"[AUDIO LOG ERROR] Failed to save audio: {e}")


router = APIRouter(prefix="/api/npc", tags=["NPC"])

# ============================================
# 음성 포함 Response 모델 (TTS)
# ============================================


class ChatResponseWithVoice(BaseModel):
    """히로인 대화 응답 (음성 포함)"""

    text: str
    emotion: int
    emotion_intensity: float
    affection: int
    sanity: int
    memoryProgress: int
    audio_base64: str


class SageChatResponseWithVoice(BaseModel):
    """대현자 대화 응답 (음성 포함)"""

    text: str
    emotion: int
    emotion_intensity: float
    scenarioLevel: int
    infoRevealed: bool
    audio_base64: str


class ConversationTurnWithVoice(BaseModel):
    """히로인간 대화 턴 (음성 포함)"""

    speaker_id: int
    speaker_name: str
    text: str
    emotion: int
    emotion_intensity: float
    audio_base64: str


class HeroineConversationResponseWithVoice(BaseModel):
    """히로인간 대화 응답 (음성 포함)"""

    id: str
    heroine1_id: int
    heroine2_id: int
    situation: str
    conversation: List[ConversationTurnWithVoice]
    importance_score: int
    timestamp: str


# 백그라운드 NPC 대화 태스크 관리
_background_tasks: Dict[int, asyncio.Task] = {}


# ============================================
# Request/Response 모델
# ============================================


class HeroineData(BaseModel):
    heroineId: int
    affection: int
    memoryProgress: int
    sanity: int


class LoginRequest(BaseModel):
    playerId: str
    scenarioLevel: int
    heroines: List[HeroineData]


class LoginResponse(BaseModel):
    success: bool
    message: str


class ChatRequest(BaseModel):
    playerId: str
    heroineId: int
    text: str


class ChatResponse(BaseModel):
    text: str
    emotion: int
    affection: int
    sanity: int
    memoryProgress: int


class SageChatRequest(BaseModel):
    playerId: str
    text: str


class SageChatResponse(BaseModel):
    text: str
    emotion: int
    scenarioLevel: int
    infoRevealed: bool


class HeroineConversationRequest(BaseModel):
    playerId: str
    heroine1Id: int
    heroine2Id: int
    situation: Optional[str] = None
    turnCount: Optional[int] = 10


class ConversationInterruptRequest(BaseModel):
    playerId: str
    conversationId: str
    interruptedTurn: int
    heroine1Id: int
    heroine2Id: int


class GuildRequest(BaseModel):
    playerId: str


class GuildResponse(BaseModel):
    success: bool
    message: str
    activeConversation: Optional[Dict[str, Any]] = None


# ============================================
# 백그라운드 NPC 대화 태스크
# ============================================


async def background_npc_conversation_loop(player_id: str):
    """백그라운드에서 주기적으로 NPC간 대화 생성"""
    heroine_ids = [1, 2, 3]

    while redis_manager.is_in_guild(player_id):
        active_conv = redis_manager.get_active_npc_conversation(player_id)

        if not active_conv:
            pair = random.sample(heroine_ids, 2)
            npc1_id = pair[0]
            npc2_id = pair[1]

            redis_manager.start_npc_conversation(player_id, npc1_id, npc2_id)

            try:
                await heroine_heroine_agent.generate_and_save_conversation(
                    player_id=player_id,
                    heroine1_id=npc1_id,
                    heroine2_id=npc2_id,
                    turn_count=10,
                )
            except Exception as e:
                print(f"Background NPC conversation error: {e}")
            finally:
                if redis_manager.is_in_guild(player_id):
                    redis_manager.stop_npc_conversation(player_id)

        await asyncio.sleep(random.randint(30, 60))

    if player_id in _background_tasks:
        del _background_tasks[player_id]


# ============================================
# 로그인/세션 엔드포인트
# ============================================


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """게임 로그인시 세션 초기화 및 checkpoint 복원"""
    player_id = request.playerId
    scenario_level = request.scenarioLevel

    for heroine in request.heroines:
        checkpoint = session_checkpoint_manager.load_checkpoints(
            player_id, heroine.heroineId
        )

        conversation_buffer = []
        for conv in checkpoint.get("conversations", []):
            conversation_buffer.append(
                {"role": "user", "content": conv.get("user", "")}
            )
            conversation_buffer.append(
                {"role": "assistant", "content": conv.get("npc", "")}
            )

        # checkpoint의 state에서 player_known_name 복원
        checkpoint_state = checkpoint.get("state", {})
        player_known_name = checkpoint_state.get("player_known_name") if checkpoint_state else None

        session = {
            "player_id": player_id,
            "npc_id": heroine.heroineId,
            "npc_type": "heroine",
            "conversation_buffer": conversation_buffer[-MAX_CONVERSATION_BUFFER_SIZE:],
            "short_term_summary": "",
            "summary_list": checkpoint.get("summary_list", []),
            "turn_count": len(checkpoint.get("conversations", [])),
            "last_summary_at": None,
            "recent_used_keywords": [],
            "state": {
                "affection": heroine.affection,
                "sanity": heroine.sanity,
                "memoryProgress": heroine.memoryProgress,
                "emotion": 0,
            },
            "last_chat_at": checkpoint.get("last_chat_at"),
        }
        
        # player_known_name이 있으면 state에 포함
        if player_known_name:
            session["state"]["player_known_name"] = player_known_name
        
        redis_manager.save_session(player_id, heroine.heroineId, session)

    sage_checkpoint = session_checkpoint_manager.load_checkpoints(player_id, 0)

    sage_conversation_buffer = []
    for conv in sage_checkpoint.get("conversations", []):
        sage_conversation_buffer.append(
            {"role": "user", "content": conv.get("user", "")}
        )
        sage_conversation_buffer.append(
            {"role": "assistant", "content": conv.get("npc", "")}
        )

    # checkpoint의 state에서 player_known_name 복원
    sage_checkpoint_state = sage_checkpoint.get("state", {})
    sage_player_known_name = sage_checkpoint_state.get("player_known_name") if sage_checkpoint_state else None

    sage_session = {
        "player_id": player_id,
        "npc_id": 0,
        "npc_type": "sage",
        "conversation_buffer": sage_conversation_buffer[-MAX_CONVERSATION_BUFFER_SIZE:],
        "short_term_summary": "",
        "summary_list": sage_checkpoint.get("summary_list", []),
        "turn_count": len(sage_checkpoint.get("conversations", [])),
        "last_summary_at": None,
        "state": {"scenarioLevel": scenario_level, "emotion": 0},
        "last_chat_at": sage_checkpoint.get("last_chat_at"),
    }
    
    # player_known_name이 있으면 state에 포함
    if sage_player_known_name:
        sage_session["state"]["player_known_name"] = sage_player_known_name
    
    redis_manager.save_session(player_id, 0, sage_session)

    return LoginResponse(success=True, message="세션 초기화 완료")


# ============================================
# 히로인 대화 엔드포인트
# ============================================


@router.post("/heroine/chat/sync", response_model=ChatResponse)
async def heroine_chat_sync(request: ChatRequest, background_tasks: BackgroundTasks):
    """히로인과 대화 (비스트리밍)"""
    api_start = time.time()

    player_id = request.playerId
    heroine_id = request.heroineId
    user_message = request.text

    # 해당 히로인이 NPC 대화 중이면 인터럽트
    if redis_manager.is_heroine_in_conversation(player_id, heroine_id):
        redis_manager.stop_npc_conversation(player_id)

    # 세션 로드
    t_session = time.time()
    session = redis_manager.load_session(player_id, heroine_id)
    if session is None:
        session = heroine_agent._create_initial_session(player_id, heroine_id)
        redis_manager.save_session(player_id, heroine_id, session)
    print(f"[TIMING] Redis 세션 로드: {time.time() - t_session:.3f}s")

    # 상태 안전하게 가져오기
    session_state = session.get("state", {})

    # 상태 구성
    state = {
        "player_id": player_id,
        "npc_id": heroine_id,
        "npc_type": "heroine",
        "messages": [HumanMessage(content=user_message)],
        "affection": session_state.get("affection", 0),
        "sanity": session_state.get("sanity", 100),
        "memoryProgress": session_state.get("memoryProgress", 0),
        "emotion": session_state.get("emotion", 0),
        "conversation_buffer": session.get("conversation_buffer", []),
        "short_term_summary": session.get("short_term_summary", ""),
        "recent_used_keywords": session.get("recent_used_keywords", []),
    }

    # 메시지 처리 (LangGraph 전체 파이프라인)
    t_process = time.time()
    result = await heroine_agent.process_message(state)
    print(f"[TIMING] LangGraph 파이프라인 총합: {time.time() - t_process:.3f}s")

    response_text = result.get("response_text", "")
    
    # Redis 세션에서 player_known_name 가져오기
    session = redis_manager.load_session(player_id, heroine_id)
    player_known_name = None
    if session and "state" in session:
        player_known_name = session["state"].get("player_known_name")
    
    new_state = {
        "affection": result.get("affection", state["affection"]),
        "sanity": result.get("sanity", state["sanity"]),
        "memoryProgress": result.get("memoryProgress", state["memoryProgress"]),
        "emotion": result.get("emotion", 0),
    }
    
    # player_known_name이 있으면 state에 포함
    if player_known_name:
        new_state["player_known_name"] = player_known_name

    background_tasks.add_task(
        session_checkpoint_manager.save_checkpoint_background,
        player_id,
        heroine_id,
        user_message,
        response_text,
        new_state,
    )

    print(
        f"[TIMING] === API 총 소요시간 (heroine_chat_sync): {time.time() - api_start:.3f}s ==="
    )
    return ChatResponse(
        text=response_text,
        emotion=new_state["emotion"],
        affection=new_state["affection"],
        sanity=new_state["sanity"],
        memoryProgress=new_state["memoryProgress"],
    )


# ============================================
# 대현자 대화 엔드포인트
# ============================================


@router.post("/sage/chat/sync", response_model=SageChatResponse)
async def sage_chat_sync(request: SageChatRequest, background_tasks: BackgroundTasks):
    """대현자와 대화 (비스트리밍)"""
    api_start = time.time()

    player_id = request.playerId
    user_message = request.text
    npc_id = 0

    t_session = time.time()
    session = redis_manager.load_session(player_id, npc_id)
    if session is None:
        session = sage_agent._create_initial_session(player_id, npc_id)
        redis_manager.save_session(player_id, npc_id, session)
    print(f"[TIMING] Redis 세션 로드: {time.time() - t_session:.3f}s")

    # 상태 안전하게 가져오기
    session_state = session.get("state", {})
    scenario_level = session_state.get("scenarioLevel", 1)

    state = {
        "player_id": player_id,
        "npc_id": npc_id,
        "npc_type": "sage",
        "messages": [HumanMessage(content=user_message)],
        "scenarioLevel": scenario_level,
        "emotion": session_state.get("emotion", 0),
        "conversation_buffer": session.get("conversation_buffer", []),
        "short_term_summary": session.get("short_term_summary", ""),
    }

    t_process = time.time()
    result = await sage_agent.process_message(state)
    print(f"[TIMING] LangGraph 파이프라인 총합: {time.time() - t_process:.3f}s")

    response_text = result.get("response_text", "")
    
    # Redis 세션에서 player_known_name 가져오기
    session = redis_manager.load_session(player_id, npc_id)
    player_known_name = None
    if session and "state" in session:
        player_known_name = session["state"].get("player_known_name")
    
    new_state = {
        "scenarioLevel": scenario_level,
        "emotion": result.get("emotion", 0),
    }
    
    # player_known_name이 있으면 state에 포함
    if player_known_name:
        new_state["player_known_name"] = player_known_name

    background_tasks.add_task(
        session_checkpoint_manager.save_checkpoint_background,
        player_id,
        npc_id,
        user_message,
        response_text,
        new_state,
    )

    print(
        f"[TIMING] === API 총 소요시간 (sage_chat_sync): {time.time() - api_start:.3f}s ==="
    )
    return SageChatResponse(
        text=response_text,
        emotion=new_state["emotion"],
        scenarioLevel=new_state["scenarioLevel"],
        infoRevealed=result.get("info_revealed", False),
    )


# ============================================
# 히로인간 대화 엔드포인트
# ============================================


@router.post("/heroine-conversation/generate")
async def generate_heroine_conversation(request: HeroineConversationRequest):
    """히로인간 대화 생성 (비스트리밍)"""
    api_start = time.time()

    t = time.time()
    result = await heroine_heroine_agent.generate_and_save_conversation(
        player_id=request.playerId,
        heroine1_id=request.heroine1Id,
        heroine2_id=request.heroine2Id,
        situation=request.situation,
        turn_count=request.turnCount or 10,
    )
    print(f"[TIMING] heroine_conversation_generate agent 처리: {time.time() - t:.3f}s")
    print(
        f"[TIMING] === API 총 소요시간 (heroine_conversation_generate): {time.time() - api_start:.3f}s ==="
    )
    return result


@router.get("/heroine-conversation")
async def get_heroine_conversations(
    player_id: str,
    heroine1_id: Optional[int] = None,
    heroine2_id: Optional[int] = None,
    limit: int = 10,
):
    """히로인간 대화 기록 조회"""
    conversations = heroine_heroine_agent.get_conversations(
        player_id=player_id,
        heroine1_id=heroine1_id,
        heroine2_id=heroine2_id,
        limit=limit,
    )
    return {"conversations": conversations}


@router.post("/heroine-conversation/interrupt")
async def interrupt_heroine_conversation(request: ConversationInterruptRequest):
    """NPC-NPC 대화 인터럽트 처리

    유저가 NPC 대화 중간에 끊고 들어왔을 때 호출합니다.
    interruptedTurn 이후의 대화는 NPC가 모르는 것으로 처리됩니다.

    예: 10턴 대화 중 3턴에서 끊기면 interruptedTurn=3
    → 1,2,3턴 대화만 유지, 4턴 이후는 삭제
    """
    result = heroine_heroine_agent.interrupt_conversation(
        player_id=request.playerId,
        conversation_id=request.conversationId,
        interrupted_turn=request.interruptedTurn,
        heroine1_id=request.heroine1Id,
        heroine2_id=request.heroine2Id,
    )
    return result


# ============================================
# 길드 시스템 엔드포인트
# ============================================


@router.post("/guild/enter", response_model=GuildResponse)
async def enter_guild(request: GuildRequest, background_tasks: BackgroundTasks):
    """길드 진입 - NPC간 백그라운드 대화 시작"""
    player_id = request.playerId

    if redis_manager.is_in_guild(player_id):
        return GuildResponse(
            success=True,
            message="이미 길드에 있습니다",
            activeConversation=redis_manager.get_active_npc_conversation(player_id),
        )

    redis_manager.enter_guild(player_id)

    if player_id not in _background_tasks:
        task = asyncio.create_task(background_npc_conversation_loop(player_id))
        _background_tasks[player_id] = task

    return GuildResponse(
        success=True, message="길드에 진입했습니다. NPC 대화가 시작됩니다."
    )


@router.post("/guild/leave", response_model=GuildResponse)
async def leave_guild(request: GuildRequest):
    """길드 퇴장 - NPC간 백그라운드 대화 중단"""
    player_id = request.playerId

    if not redis_manager.is_in_guild(player_id):
        return GuildResponse(success=True, message="길드에 있지 않습니다")

    active_conv = redis_manager.get_active_npc_conversation(player_id)
    redis_manager.leave_guild(player_id)

    if player_id in _background_tasks:
        _background_tasks[player_id].cancel()
        del _background_tasks[player_id]

    return GuildResponse(
        success=True,
        message="길드에서 퇴장했습니다. NPC 대화가 중단됩니다.",
        activeConversation=active_conv,
    )


@router.get("/guild/status/{player_id}")
async def get_guild_status(player_id: str):
    """길드 상태 조회"""
    return {
        "in_guild": redis_manager.is_in_guild(player_id),
        "active_conversation": redis_manager.get_active_npc_conversation(player_id),
        "has_background_task": player_id in _background_tasks,
    }


# ============================================
# 디버그 엔드포인트
# ============================================


@router.get("/session/{player_id}/{npc_id}")
async def get_session(player_id: str, npc_id: int):
    """세션 정보 조회 (디버그용)"""
    session = redis_manager.load_session(player_id, npc_id)
    if session is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다")
    return session


@router.get("/npc-conversation/active/{player_id}")
async def get_active_npc_conversation(player_id: str):
    """현재 진행 중인 NPC 대화 조회"""
    conv = redis_manager.get_active_npc_conversation(player_id)
    if conv is None:
        return {"active": False, "conversation": None}
    return {"active": True, "conversation": conv}


# ============================================
# TTS 음성 포함 엔드포인트
# ============================================


@router.post("/heroine/chat/sync/voice", response_model=ChatResponseWithVoice)
async def heroine_chat_sync_voice(
    request: ChatRequest, background_tasks: BackgroundTasks
):
    """히로인과 대화 (음성 포함)

    기존 /heroine/chat/sync와 동일하지만 TTS 음성이 포함됩니다.
    """
    api_start = time.time()

    player_id = request.playerId
    heroine_id = request.heroineId
    user_message = request.text

    # 해당 히로인이 NPC 대화 중이면 인터럽트
    if redis_manager.is_heroine_in_conversation(player_id, heroine_id):
        redis_manager.stop_npc_conversation(player_id)

    # 세션 로드
    session = redis_manager.load_session(player_id, heroine_id)
    if session is None:
        session = heroine_agent._create_initial_session(player_id, heroine_id)
        redis_manager.save_session(player_id, heroine_id, session)

    session_state = session.get("state", {})

    state = {
        "player_id": player_id,
        "npc_id": heroine_id,
        "npc_type": "heroine",
        "messages": [HumanMessage(content=user_message)],
        "affection": session_state.get("affection", 0),
        "sanity": session_state.get("sanity", 100),
        "memoryProgress": session_state.get("memoryProgress", 0),
        "emotion": session_state.get("emotion", 0),
        "conversation_buffer": session.get("conversation_buffer", []),
        "short_term_summary": session.get("short_term_summary", ""),
        "recent_used_keywords": session.get("recent_used_keywords", []),
    }

    # 메시지 처리
    result = await heroine_agent.process_message(state)

    response_text = result.get("response_text", "")
    emotion = result.get("emotion", 0)
    emotion_intensity = result.get("emotion_intensity", 1.0)

    # Redis 세션에서 player_known_name 가져오기
    session = redis_manager.load_session(player_id, heroine_id)
    player_known_name = None
    if session and "state" in session:
        player_known_name = session["state"].get("player_known_name")

    new_state = {
        "affection": result.get("affection", state["affection"]),
        "sanity": result.get("sanity", state["sanity"]),
        "memoryProgress": result.get("memoryProgress", state["memoryProgress"]),
        "emotion": emotion,
    }
    
    # player_known_name이 있으면 state에 포함
    if player_known_name:
        new_state["player_known_name"] = player_known_name

    # TTS 생성
    t_tts = time.time()
    print(f"[DEBUG] TTS 입력 텍스트: {response_text}")
    audio_bytes = await typecast_tts_service.text_to_speech(
        text=response_text,
        npc_id=heroine_id,
        emotion=emotion,
        emotion_intensity=emotion_intensity,
    )
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    print(f"[TIMING] TTS 생성: {time.time() - t_tts:.3f}s")

    # 데이터 저장 (백그라운드)
    background_tasks.add_task(
        session_checkpoint_manager.save_checkpoint_background,
        player_id,
        heroine_id,
        user_message,
        response_text,
        new_state,
    )

    # 음성 파일 로컬 저장 (백그라운드, 피드백용)
    background_tasks.add_task(
        save_audio_file_background,
        audio_bytes,
        player_id,
        heroine_id,
        response_text,
        emotion,
        "heroine_chat",
    )

    print(
        f"[TIMING] === API 총 소요시간 (heroine_chat_sync_voice): {time.time() - api_start:.3f}s ==="
    )

    return ChatResponseWithVoice(
        text=response_text,
        emotion=emotion,
        emotion_intensity=emotion_intensity,
        affection=new_state["affection"],
        sanity=new_state["sanity"],
        memoryProgress=new_state["memoryProgress"],
        audio_base64=audio_base64,
    )


@router.post("/sage/chat/sync/voice", response_model=SageChatResponseWithVoice)
async def sage_chat_sync_voice(
    request: SageChatRequest, background_tasks: BackgroundTasks
):
    """대현자와 대화 (음성 포함)

    기존 /sage/chat/sync와 동일하지만 TTS 음성이 포함됩니다.
    """
    api_start = time.time()

    player_id = request.playerId
    user_message = request.text
    npc_id = 0

    session = redis_manager.load_session(player_id, npc_id)
    if session is None:
        session = sage_agent._create_initial_session(player_id, npc_id)
        redis_manager.save_session(player_id, npc_id, session)

    session_state = session.get("state", {})
    scenario_level = session_state.get("scenarioLevel", 1)

    state = {
        "player_id": player_id,
        "npc_id": npc_id,
        "npc_type": "sage",
        "messages": [HumanMessage(content=user_message)],
        "scenarioLevel": scenario_level,
        "emotion": session_state.get("emotion", 0),
        "conversation_buffer": session.get("conversation_buffer", []),
        "short_term_summary": session.get("short_term_summary", ""),
    }

    result = await sage_agent.process_message(state)

    response_text = result.get("response_text", "")
    emotion = result.get("emotion", 0)
    emotion_intensity = result.get("emotion_intensity", 1.0)

    # Redis 세션에서 player_known_name 가져오기
    session = redis_manager.load_session(player_id, npc_id)
    player_known_name = None
    if session and "state" in session:
        player_known_name = session["state"].get("player_known_name")

    new_state = {
        "scenarioLevel": scenario_level,
        "emotion": emotion,
    }
    
    # player_known_name이 있으면 state에 포함
    if player_known_name:
        new_state["player_known_name"] = player_known_name

    # TTS 생성
    t_tts = time.time()
    audio_bytes = await typecast_tts_service.text_to_speech(
        text=response_text,
        npc_id=npc_id,
        emotion=emotion,
        emotion_intensity=emotion_intensity,
    )
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    print(f"[TIMING] TTS 생성: {time.time() - t_tts:.3f}s")

    # 데이터 저장 (백그라운드)
    background_tasks.add_task(
        session_checkpoint_manager.save_checkpoint_background,
        player_id,
        npc_id,
        user_message,
        response_text,
        new_state,
    )

    # 음성 파일 로컬 저장 (백그라운드, 피드백용)
    background_tasks.add_task(
        save_audio_file_background,
        audio_bytes,
        player_id,
        npc_id,
        response_text,
        emotion,
        "sage_chat",
    )

    print(
        f"[TIMING] === API 총 소요시간 (sage_chat_sync_voice): {time.time() - api_start:.3f}s ==="
    )

    return SageChatResponseWithVoice(
        text=response_text,
        emotion=emotion,
        emotion_intensity=emotion_intensity,
        scenarioLevel=scenario_level,
        infoRevealed=result.get("info_revealed", False),
        audio_base64=audio_base64,
    )


@router.post(
    "/heroine-conversation/generate/voice",
    response_model=HeroineConversationResponseWithVoice,
)
async def generate_heroine_conversation_voice(
    request: HeroineConversationRequest, background_tasks: BackgroundTasks
):
    """히로인간 대화 생성 (음성 포함)

    기존 /heroine-conversation/generate와 동일하지만 TTS 음성이 포함됩니다.
    """
    api_start = time.time()

    result = await heroine_heroine_agent.generate_and_save_conversation(
        player_id=request.playerId,
        heroine1_id=request.heroine1Id,
        heroine2_id=request.heroine2Id,
        situation=request.situation,
        turn_count=request.turnCount or 10,
    )

    # 각 턴에 TTS 생성 (턴별로 개별 음성 생성)
    conversation_with_voice = []
    t_tts_total = time.time()

    for turn_idx, turn in enumerate(result.get("conversation", [])):
        speaker_id = turn.get("speaker_id")
        speaker_name = turn.get("speaker_name", "")
        text = turn.get("text", "")
        emotion = turn.get("emotion", 0)
        emotion_intensity = turn.get("emotion_intensity", 1.0)

        # 디버그: 각 턴별로 어떤 텍스트가 TTS로 전달되는지 확인
        print(
            f"[TTS DEBUG] Turn {turn_idx}: speaker={speaker_name}({speaker_id}), text_length={len(text)}, text_preview={text[:50]}..."
        )

        audio_bytes = await typecast_tts_service.text_to_speech(
            text=text,
            npc_id=speaker_id,
            emotion=emotion,
            emotion_intensity=emotion_intensity,
        )

        # 디버그: 생성된 오디오 크기 확인
        print(f"[TTS DEBUG] Turn {turn_idx}: audio_bytes_size={len(audio_bytes)} bytes")

        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

        conversation_with_voice.append(
            ConversationTurnWithVoice(
                speaker_id=speaker_id,
                speaker_name=turn.get("speaker_name", ""),
                text=text,
                emotion=emotion,
                emotion_intensity=emotion_intensity,
                audio_base64=audio_base64,
            )
        )

        # 음성 파일 로컬 저장 (백그라운드, 피드백용)
        background_tasks.add_task(
            save_audio_file_background,
            audio_bytes,
            request.playerId,
            speaker_id,
            text,
            emotion,
            "heroine_conversation",
        )

    print(f"[TIMING] TTS 총 생성: {time.time() - t_tts_total:.3f}s")
    print(
        f"[TIMING] === API 총 소요시간 (heroine_conversation_voice): {time.time() - api_start:.3f}s ==="
    )

    # 디버그: conversation_with_voice 리스트 길이 확인
    print(f"[DEBUG] conversation_with_voice 길이: {len(conversation_with_voice)}")
    for idx, turn in enumerate(conversation_with_voice):
        print(
            f"[DEBUG] Turn {idx}: speaker={turn.speaker_name}, text_preview={turn.text[:30]}..."
        )

    return HeroineConversationResponseWithVoice(
        id=result.get("id", ""),
        heroine1_id=result.get("heroine1_id"),
        heroine2_id=result.get("heroine2_id"),
        situation=result.get("situation", ""),
        conversation=conversation_with_voice,
        importance_score=result.get("importance_score", 5),
        timestamp=result.get("timestamp", ""),
    )
