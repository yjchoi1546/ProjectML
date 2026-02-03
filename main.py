import sys
from pathlib import Path

# src 디렉토리를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent / "src"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request

import logging, time
from api.npc_router import router as npc_router
from api.fairy_router import router as fairy_router
from api.dungeon_router import router as dungeon_router
from api.common_router import router as common_router


# FastAPI 앱 생성
app = FastAPI(
    title="AI Agent System",
    description="AI 에이전트 시스템 API 입니다.",
    version="1.0.0_alpha"
)

# CORS 설정 (언리얼 엔진에서 접근 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인만 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(npc_router)
app.include_router(fairy_router)
app.include_router(dungeon_router)
app.include_router(common_router)


# 로그 포맷 설정
_fmt = logging.Formatter(
    fmt="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

ch = logging.StreamHandler()
ch.setFormatter(_fmt)

# STT 로거
logger = logging.getLogger("stt")
logger.setLevel(logging.INFO)
logger.addHandler(ch)

# User Memory 로거 (fact 추출/저장 과정 추적)
memory_logger = logging.getLogger("user_memory")
memory_logger.setLevel(logging.INFO)  # DEBUG로 변경하면 더 상세한 로그 출력
memory_logger.addHandler(ch)

import uuid
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = uuid.uuid4().hex[:10]
    request.state.request_id = request_id

    start = time.perf_counter()
    client = request.client.host if request.client else "unknown"
    logger.info(f"[{request_id}] -> {client} {request.method} {request.url.path}")

    try:
        response = await call_next(request)
        dur = time.perf_counter() - start
        logger.info(f"[{request_id}] <- {response.status_code} ({dur:.3f}s)")
        return response
    except Exception:
        dur = time.perf_counter() - start
        logger.exception(f"[{request_id}] !! unhandled error ({dur:.3f}s)")
        raise



@app.get("/")
async def root():
    """헬스 체크"""
    return {"status": "ok", "message": "AI Agent System is running"}


@app.get("/health")
async def health():
    """상세 헬스 체크"""
    return {
        "status": "healthy",
        "services": {
            "api": "ok",
            "redis": "check required",
            "database": "check required"
        }
    }

# if __name__ == "__main__":
#     uvicorn.run(
#         "main:app",
#         host="0.0.0.0",
#         port=8090,
#         reload=True
#     )

# uv run uvicorn main:app --host 0.0.0.0 --port 8000
# nohup uv run uvicorn main:app --host 0.0.0.0 --port 9999 --log-level info --access-log   > uvicorn_9999.out 2>&1 &