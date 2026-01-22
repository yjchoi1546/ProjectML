from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
from agents.dungeon.monster.monster_database import MONSTER_DATABASE
from agents.dungeon.monster.monster_tags import keywords_to_tags

from services.dungeon_service import get_dungeon_service

# Router 생성
router = APIRouter(prefix="/api/dungeon", tags=["dungeon"])


# =============================================================================
# Pydantic Models (요청/응답 데이터 구조)
# =============================================================================


class RawMapRoom(BaseModel):
    """Unreal에서 보낸 room 구조"""

    roomId: int
    type: int  # 0=empty, 1=monster, 2=event, 3=treasure, 4=boss
    size: int
    neighbors: List[int]
    monsters: List[Dict[str, Any]] = []
    eventType: int = 0


class RawMapRequest(BaseModel):
    """Unreal에서 보낸 raw_map 구조 (방 정보만)"""

    floor: int
    rooms: List[RawMapRoom]
    rewards: List[int] = []


class EntranceRequest(BaseModel):
    """던전 입장 요청 (최상위에 playerIds, heroineIds, heroineData, rawMaps)"""

    playerIds: List[str]
    heroineIds: List[int]
    heroineData: Optional[List[Any]] = None
    rawMaps: List[RawMapRequest]
    usedEvents: Optional[List[Any]] = None


class EventChoice(BaseModel):
    """이벤트 선택지"""

    action: str
    reward: Optional[dict] = None  # 보상 dict (id/description 제외)
    penalty: Optional[dict] = None  # 패널티 dict (id/description 제외)


class EventResponse(BaseModel):
    """이벤트 정보 응답 (클라 요구: reward/penalty dict)"""

    roomId: int
    eventType: int
    eventTitle: str
    scenarioText: str
    scenarioNarrative: Any  # str(공용) 또는 dict(개인)


class EntranceResponse(BaseModel):
    """던전 입장 응답 (클라 요구: 최상위 배열)"""

    success: bool
    playerIds: List[str]
    events: Optional[List[EventResponse]] = None


class PlayerBalanceData(BaseModel):
    """플레이어별 밸런싱 데이터"""

    # `playerId`, `heroineId`, `heroineStat`, `weaponId`, `skillIds`, etc.
    heroineData: Dict[str, Any]


class BalanceRequest(BaseModel):
    """밸런싱 요청 (보스방 입장)"""

    firstPlayerId: str  # 방장 ID로 던전 식별
    playerDataList: List[PlayerBalanceData]
    usedEvents: Optional[List[Any]] = None


class RoomMonsterPlacement(BaseModel):
    roomId: int
    monsterIds: List[int] = []


class BalanceResponse(BaseModel):
    """밸런싱 응답 (room별 그룹화된 몬스터 ID 배열)"""

    success: bool
    firstPlayerId: str
    monsterPlacements: List[RoomMonsterPlacement] = []


class ClearRequest(BaseModel):
    """층 완료 요청"""

    playerIds: List[str]


class ClearResponse(BaseModel):
    """층 완료 응답"""

    success: bool
    finishedFloor: Optional[int] = None


class EventSelectRequest(BaseModel):
    """이벤트 선택 요청"""

    firstPlayerId: str
    selectingPlayerId: str
    roomId: int
    choice: str


class EventSelectResponse(BaseModel):
    """이벤트 선택 응답"""

    success: bool
    firstPlayerId: str
    selectingPlayerId: str
    roomId: int
    outcome: str
    rewardId: Optional[Any] = None
    penaltyId: Optional[Any] = None


class NextFloorRequest(BaseModel):
    """다음 층 입장 요청 (playerIds, heroineIds 최상위)"""

    playerIds: List[str]
    heroineIds: List[int]
    heroineData: Optional[List[Any]] = None  # int/dict 모두 허용
    rawMap: RawMapRequest  # 다음 층 raw_map
    usedEvents: Optional[List[Any]] = None


class NextFloorResponse(BaseModel):
    """다음 층 입장 응답 (클라 요구: 최상위 배열)"""

    success: bool
    playerIds: List[str]
    events: Optional[List[EventResponse]] = None


# =============================================================================
# API Endpoints
# =============================================================================


import time


@router.post("/entrance", response_model=EntranceResponse)
def entrance(request: EntranceRequest):
    total_start = time.time()
    try:
        service = get_dungeon_service()

        # 여러 층 raw_map을 dict로 변환 (playerIds, heroineIds는 최상위에서 받음)
        raw_maps = [raw_map.model_dump() for raw_map in request.rawMaps]

        # 던전 입장
        result = service.entrance(
            player_ids=request.playerIds,
            heroine_ids=request.heroineIds,
            raw_maps=raw_maps,
            heroine_data=request.heroineData,
            used_events=request.usedEvents or [],
        )

        # 이벤트 정보 매핑 (floor 구분 포함, reward/penalty dict)
        events_list = []
        if result.get("events"):
            events_data = result["events"]
            # 1층 이벤트만 추출
            if isinstance(events_data, list):
                for evt in events_data:
                    if evt.get("floor", 1) != 1:
                        continue
                    scenario_narrative = evt.get("scenario_narrative", "")
                    if evt.get("is_personal") and evt.get("heroineNarratives"):
                        scenario_narrative = {
                            str(n["playerId"]): n["narrative"]
                            for n in evt["heroineNarratives"]
                            if isinstance(n, dict)
                            and "playerId" in n
                            and "narrative" in n
                        }
                    events_list.append(
                        EventResponse(
                            roomId=evt.get("room_id", 0),
                            eventType=evt.get("event_type", 0),
                            eventTitle=evt.get("event_title", ""),
                            scenarioText=evt.get("scenario_text", ""),
                            scenarioNarrative=scenario_narrative,
                            choices=[
                                EventChoice(
                                    action=c.get("action", ""),
                                    reward=c.get("reward"),
                                    penalty=c.get("penalty"),
                                )
                                for c in evt.get("choices", [])
                                if isinstance(c, dict)
                            ],
                        )
                    )
            elif isinstance(events_data, dict):
                evt = events_data
                if evt.get("floor", 1) == 1:
                    scenario_narrative = evt.get("scenario_narrative", "")
                    if evt.get("is_personal") and evt.get("heroineNarratives"):
                        scenario_narrative = {
                            str(n["playerId"]): n["narrative"]
                            for n in evt["heroineNarratives"]
                            if isinstance(n, dict)
                            and "playerId" in n
                            and "narrative" in n
                        }
                    events_list.append(
                        EventResponse(
                            roomId=evt.get("room_id", 0),
                            eventType=evt.get("event_type", 0),
                            eventTitle=evt.get("event_title", ""),
                            scenarioText=evt.get("scenario_text", ""),
                            scenarioNarrative=scenario_narrative,
                            choices=[
                                EventChoice(
                                    action=c.get("action", ""),
                                    reward=c.get("reward"),
                                    penalty=c.get("penalty"),
                                )
                                for c in evt.get("choices", [])
                                if isinstance(c, dict)
                            ],
                        )
                    )

        # 최상위 배열 추출 (중복 없이)
        player_ids = request.playerIds
        heroine_ids = request.heroineIds
        heroine_data = request.heroineData or []
        heroine_memory_progress = []
        for h in heroine_data:
            if isinstance(h, dict):
                mp = h.get("memory_progress")
                if mp is None:
                    mp = h.get("memoryProgress", 0)
                heroine_memory_progress.append(mp)
            elif isinstance(h, int):
                heroine_memory_progress.append(h)
            else:
                heroine_memory_progress.append(0)
        while len(heroine_memory_progress) < len(heroine_ids):
            heroine_memory_progress.append(0)
        total_elapsed = time.time() - total_start
        print(f"[TIMING] 던전 입장~이벤트 생성 전체 처리 시간: {total_elapsed:.3f}s")
        return EntranceResponse(
            success=True,
            playerIds=player_ids,
            events=events_list if events_list else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"던전 입장 실패: {str(e)}")


@router.post("/balance", response_model=BalanceResponse)
def balance_dungeon(request: BalanceRequest):
    try:
        service = get_dungeon_service()

        # Monster DB 로드

        normalized_players: List[Dict[str, Any]] = []
        for pd in request.playerDataList:
            hd = pd.heroineData or {}
            # prefer nested playerId inside heroineData
            if isinstance(hd, dict) and "playerId" in hd:
                player_id = hd.get("playerId")
                hd_copy = hd.copy()
                hd_copy.pop("playerId", None)
            else:
                # fallback: see if pd has top-level playerId attribute
                player_id = getattr(pd, "playerId", None)
                hd_copy = hd
            # --- derive keyword ids from weaponId / skillIds (heuristic rules) ---
            keyword_ids: List[int] = []
            try:
                wid = hd_copy.get("weaponId") if isinstance(hd_copy, dict) else None
            except Exception:
                wid = None
            if isinstance(wid, int):
                # dual blades (20-27) -> fast attack, many hits
                if 20 <= wid <= 27:
                    keyword_ids += [4, 7]
                # greatswords (40-47) -> strong one-shot, slow attack
                elif 40 <= wid <= 47:
                    keyword_ids += [6, 5]
                # hammers (60-67) -> high stagger, strong one-shot
                elif 60 <= wid <= 67:
                    keyword_ids += [8, 6]
                # default: add based on attack power if available
                else:
                    try:
                        # if weaponId is legendary high id, add strong_one_shot
                        if wid >= 100:
                            keyword_ids.append(6)
                    except Exception:
                        pass

            # skills
            try:
                sids = hd_copy.get("skillIds") if isinstance(hd_copy, dict) else None
            except Exception:
                sids = None
            if isinstance(sids, list):
                for sid in sids:
                    if not isinstance(sid, int):
                        continue
                    # heuristic mapping for common skills
                    if sid in (0, 102):
                        keyword_ids.append(1)  # low_defense
                    elif sid in (1, 2):
                        keyword_ids.append(2)  # fast_movement
                    elif sid == 3:
                        keyword_ids.append(4)  # fast_attack_speed
                    elif sid >= 100:
                        keyword_ids.append(16)  # high_hp (example)

            keyword_ids = list(dict.fromkeys(keyword_ids))
            if isinstance(hd_copy, dict):
                hd_copy["keyword_ids"] = keyword_ids
                hd_copy["tags"] = keywords_to_tags(keyword_ids)
                # Ensure heroineStat also carries keyword information (service reads heroineStat)
                try:
                    hs = hd_copy.get("heroineStat")
                    if hs is None:
                        hd_copy["heroineStat"] = {
                            "keyword_ids": keyword_ids,
                            "tags": keywords_to_tags(keyword_ids),
                        }
                    elif isinstance(hs, dict):
                        hs["keyword_ids"] = list(
                            dict.fromkeys(hs.get("keyword_ids", []) + keyword_ids)
                        )
                        hs["tags"] = keywords_to_tags(
                            hs.get("keyword_ids", []) + keyword_ids
                        )
                except Exception:
                    pass

            normalized_players.append({"playerId": player_id, "heroineData": hd_copy})

        # 밸런싱 실행 (기존 service 인터페이스 호출)
        result = service.balance_dungeon(
            first_player_id=request.firstPlayerId,
            player_data_list=normalized_players,
            monster_db=MONSTER_DATABASE,
            used_events=request.usedEvents,
            player_count=(
                len(request.playerDataList)
                if isinstance(request.playerDataList, list)
                else None
            ),
        )

        if not result.get("success"):
            raise Exception(result.get("error", "Unknown error"))

        raw_mp = result.get("monster_placements", []) or []
        grouped_out: List[Dict[str, Any]] = []
        if all(isinstance(x, dict) and "monsters" in x for x in raw_mp):
            grouped_out = raw_mp
        else:
            grouped_map: Dict[Any, Dict[str, Any]] = {}
            for mp in raw_mp:
                try:
                    rid = mp.get("roomId")
                    mid = mp.get("monsterId")
                    cnt = mp.get("count", 0)
                except Exception:
                    continue
                if rid not in grouped_map:
                    grouped_map[rid] = {"roomId": rid, "monsters": []}
                grouped_map[rid]["monsters"].append({"monsterId": mid, "count": cnt})
            grouped_out = list(grouped_map.values())

        # Build monster_placements from grouped_out (works for both grouped and flat service outputs)
        monster_placements: List[RoomMonsterPlacement] = []
        for g in grouped_out:
            room_id = g.get("roomId")
            monster_ids: List[int] = []
            for m in g.get("monsters", []):
                mid = m.get("monsterId")
                cnt = int(m.get("count", 0) or 0)
                if mid is None:
                    continue
                monster_ids.extend([mid] * max(0, cnt))
            # only include rooms that actually have monsters
            if monster_ids:
                monster_placements.append(
                    RoomMonsterPlacement(roomId=room_id, monsterIds=monster_ids)
                )

        resp_first_player_id = None
        try:
            if hasattr(request, "firstPlayerId") and request.firstPlayerId:
                resp_first_player_id = request.firstPlayerId
        except Exception:
            resp_first_player_id = None

        if resp_first_player_id is None:
            try:
                first_pd = request.playerDataList[0]
                if (
                    isinstance(first_pd.heroineData, dict)
                    and "heroineId" in first_pd.heroineData
                ):
                    resp_first_player_id = first_pd.heroineData.get("heroineId")
                else:
                    # fallback: use normalized_players[0].playerId if available
                    try:
                        if normalized_players and isinstance(normalized_players, list):
                            pid = normalized_players[0].get("playerId")
                            if pid is not None:
                                resp_first_player_id = pid
                    except Exception:
                        pass
            except Exception:
                resp_first_player_id = None

        if resp_first_player_id is None:
            # final fallback to the incoming firstPlayerId
            resp_first_player_id = request.firstPlayerId

        return BalanceResponse(
            success=True,
            firstPlayerId=(
                str(resp_first_player_id) if resp_first_player_id is not None else ""
            ),
            monsterPlacements=monster_placements,
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"밸런싱 실패: {str(e)}")


@router.put("/clear", response_model=ClearResponse)
def clear_floor(request: ClearRequest):
    try:
        service = get_dungeon_service()

        # 층 완료 처리
        result = service.clear_floor(player_ids=request.playerIds)

        if not result["success"]:
            raise Exception(result.get("error", "Unknown error"))

        finished_floor = result["finished_dungeon"]["floor"]

        # balanced_map 반환 제거, 완료 처리만 응답
        return ClearResponse(
            success=True,
            finishedFloor=finished_floor,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"층 완료 처리 실패: {str(e)}")


@router.post("/event/select", response_model=EventSelectResponse)
def select_event(request: EventSelectRequest):
    """
    플레이어가 이벤트 선택지를 선택했을 때 처리
    """
    try:
        service = get_dungeon_service()

        # 이벤트 선택 처리
        result = service.select_event(
            first_player_id=request.firstPlayerId,
            selecting_player_id=request.selectingPlayerId,
            room_id=request.roomId,
            choice=request.choice,
        )

        if not result["success"]:
            raise Exception(result.get("error", "Unknown error"))

        return EventSelectResponse(
            success=True,
            firstPlayerId=request.firstPlayerId,
            selectingPlayerId=request.selectingPlayerId,
            roomId=request.roomId,
            outcome=result.get("outcome", ""),
            rewardId=result.get("rewardId"),
            penaltyId=result.get("penaltyId"),
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"이벤트 선택 처리 실패: {str(e)}")


@router.post("/nextfloor", response_model=NextFloorResponse)
def nextfloor(request: NextFloorRequest):
    """
    다음 층 입장 시 raw_map과 heroineData를 받아 이벤트 생성 및 DB 저장
    """
    try:
        service = get_dungeon_service()
        raw_map = (
            request.rawMap.model_dump()
            if hasattr(request.rawMap, "model_dump")
            else dict(request.rawMap)
        )
        print(f"[DEBUG] API nextfloor raw_map: {raw_map}")
        # Patch: ensure 'floor' is present in raw_map
        if "floor" not in raw_map:
            # Try to extract from request or rooms if possible
            if hasattr(request.rawMap, "floor"):
                raw_map["floor"] = request.rawMap.floor
            # If still not found, raise clear error
            if "floor" not in raw_map:
                raise HTTPException(
                    status_code=400, detail="raw_map에 floor 정보가 없습니다. (API)"
                )
        heroine_data = request.heroineData
        if heroine_data is None or (
            isinstance(heroine_data, list) and len(heroine_data) == 0
        ):
            raise HTTPException(
                status_code=400,
                detail="heroineData가 비어 있거나 유효하지 않습니다. (API)",
            )
        if heroine_data is not None and not isinstance(heroine_data, list):
            heroine_data = [heroine_data]
        result = service.next_floor_entrance(
            player_ids=request.playerIds,
            heroine_ids=request.heroineIds,
            raw_map=raw_map,
            heroine_data=heroine_data,
            used_events=request.usedEvents or [],
        )

        # 현재 입장해야 하는 층(가장 낮은 is_finishing=False인 floor) 구하기
        repo = service.repo
        player_id = request.playerIds[0] if request.playerIds else None
        unfinished_row = repo.get_unfinished_dungeons([player_id])
        current_floor = None
        if unfinished_row:
            current_floor = unfinished_row.get("floor")

        events_list = []
        if player_id and current_floor is not None:
            # DB에서 해당 층 이벤트 조회
            previous_events = repo.get_event_by_floor(player_id, current_floor)
            if previous_events:
                if isinstance(previous_events, list):
                    for evt in previous_events:
                        events_list.append(
                            EventResponse(
                                roomId=evt.get("room_id", 0),
                                eventType=evt.get("event_type", 0),
                                eventTitle=evt.get("event_title", ""),
                                scenarioText=evt.get("scenario_text", ""),
                                scenarioNarrative=evt.get("scenario_narrative", ""),
                                choices=[
                                    EventChoice(
                                        action=c.get("action", ""),
                                        reward=c.get("reward"),
                                        penalty=c.get("penalty"),
                                    )
                                    for c in evt.get("choices", [])
                                    if isinstance(c, dict)
                                ],
                            )
                        )
                elif isinstance(previous_events, dict):
                    evt = previous_events
                    events_list.append(
                        EventResponse(
                            roomId=evt.get("room_id", 0),
                            eventType=evt.get("event_type", 0),
                            eventTitle=evt.get("event_title", ""),
                            scenarioText=evt.get("scenario_text", ""),
                            scenarioNarrative=evt.get("scenario_narrative", ""),
                            choices=[
                                EventChoice(
                                    action=c.get("action", ""),
                                    reward=c.get("reward"),
                                    penalty=c.get("penalty"),
                                )
                                for c in evt.get("choices", [])
                                if isinstance(c, dict)
                            ],
                        )
                    )

        player_ids = request.playerIds
        heroine_ids = request.heroineIds
        heroine_data = heroine_data or []
        heroine_memory_progress = []
        for h in heroine_data:
            if isinstance(h, dict):
                mp = h.get("memory_progress")
                if mp is None:
                    mp = h.get("memoryProgress", 0)
                heroine_memory_progress.append(mp)
            elif isinstance(h, int):
                heroine_memory_progress.append(h)
            else:
                heroine_memory_progress.append(0)
        while len(heroine_memory_progress) < len(heroine_ids):
            heroine_memory_progress.append(0)
        return NextFloorResponse(
            success=True,
            playerIds=player_ids,
            events=events_list if events_list else None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"다음 층 입장 실패: {str(e)}")
