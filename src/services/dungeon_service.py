"""
Dungeon Service Layer
fairy_service.py 구조를 따라 던전 밸런싱을 통합 관리
"""

import json
from typing import Dict, Any, List, Optional
from sqlalchemy import text
from db.RDBRepository import RDBRepository
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.agents.dungeon.event import event_rewards_penalties as er
from agents.dungeon.event.event_rewards_penalties import (
    normalize_reward_payload,
    normalize_penalty_payload,
)


# ============================================================
# Unreal JSON 정규화 (camelCase -> snake_case + type 변환)
# ============================================================
def _normalize_room_keys(raw_map: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw_map, dict) or "rooms" not in raw_map:
        return raw_map

    normalized = json.loads(json.dumps(raw_map))  # deep copy

    # room type 매핑
    # Unreal: 0=빈방, 1=전투방, 2=이벤트방, 3=보물방, 4=보스방
    TYPE_MAP = {
        0: "empty",  # 빈방 - 몬스터 없음
        1: "monster",  # 전투방 - 일반 몬스터
        2: "event",  # 이벤트방
        3: "treasure",  # 보물방
        4: "boss",  # 보스방
    }

    # 최상위 playerIds, heroineIds 정규화
    if "playerIds" in normalized:
        normalized["player_ids"] = normalized.pop("playerIds")
    if "heroineIds" in normalized:
        normalized["heroine_ids"] = normalized.pop("heroineIds")

    for room in normalized.get("rooms", []):
        # roomId -> room_id
        if "roomId" in room and "room_id" not in room:
            room["room_id"] = room.pop("roomId")

        # type (숫자) -> room_type (문자열)
        if "type" in room:
            room_type_num = room.pop("type")
            room["room_type"] = TYPE_MAP.get(room_type_num, "monster")

        # eventType -> event_type
        if "eventType" in room and "event_type" not in room:
            room["event_type"] = room.pop("eventType")

        # monsters 내 필드 정규화
        for monster in room.get("monsters", []):
            if "monsterId" in monster and "monster_id" not in monster:
                monster["monster_id"] = monster.pop("monsterId")
            if "posX" in monster and "pos_x" not in monster:
                monster["pos_x"] = monster.pop("posX")
            if "posY" in monster and "pos_y" not in monster:
                monster["pos_y"] = monster.pop("posY")

    return normalized


def _normalize_heroine_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    히로인 데이터 키 정규화 (camelCase -> snake_case)
    """
    if not data:
        return {}

    normalized = data.copy()

    # heroineId -> heroine_id
    if "heroineId" in normalized:
        normalized["heroine_id"] = normalized.pop("heroineId")

    # memoryProgress -> memory_progress
    if "memoryProgress" in normalized:
        normalized["memory_progress"] = normalized.pop("memoryProgress")

    # 기본값 설정 (Agent에서 필수)
    if "heroine_id" not in normalized:
        normalized["heroine_id"] = 1  # 기본값
    if "memory_progress" not in normalized:
        normalized["memory_progress"] = 0  # 기본값

    return normalized


def _remove_message_recursive(obj: Any) -> Any:
    """Recursively remove 'message' keys from dicts/lists in the object."""
    try:
        if isinstance(obj, dict):
            obj = {
                k: _remove_message_recursive(v)
                for k, v in obj.items()
                if k != "message"
            }
            return obj
        elif isinstance(obj, list):
            return [_remove_message_recursive(v) for v in obj]
        else:
            return obj
    except Exception:
        return obj


_dungeon_graph = None


def get_dungeon_graph():
    """Lazy initialization으로 Super Agent Graph 반환"""
    global _dungeon_graph
    if _dungeon_graph is None:
        from agents.dungeon.super.dungeon_agent import create_super_dungeon_graph

        _dungeon_graph = create_super_dungeon_graph()
    return _dungeon_graph


class DungeonService:
    def __init__(self):
        self.repo = RDBRepository()

    def _strip_applied_actions(self, events: Any) -> None:
        """Remove `applied_actions` keys from event dict or list before persisting."""
        if events is None:
            return
        if isinstance(events, dict):
            evs = [events]
        elif isinstance(events, list):
            evs = events
        else:
            return

        for ev in evs:
            if not isinstance(ev, dict):
                continue
            ev.pop("applied_actions", None)
            # also remove applied_actions from heroineNarratives if present (defensive)
            if "heroineNarratives" in ev and isinstance(ev["heroineNarratives"], list):
                for hn in ev["heroineNarratives"]:
                    if isinstance(hn, dict):
                        hn.pop("applied_actions", None)

    def entrance(
        self,
        player_ids: List[str],
        heroine_ids: List[int],
        raw_maps: List[Dict[str, Any]],  # 여러 층 raw_map
        heroine_data: Optional[List] = None,
        used_events: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        events_list = []
        floor_ids = []
        try:
            with self.repo.engine.begin() as conn:
                # heroine_data가 int 리스트면 dict로 변환
                normalized_heroines = []
                if heroine_data:
                    if all(isinstance(h, int) for h in heroine_data):
                        for hid, mp in zip(heroine_ids, heroine_data):
                            normalized_heroines.append(
                                {"heroine_id": hid, "memory_progress": mp}
                            )
                    elif isinstance(heroine_data, list):
                        for h in heroine_data:
                            normalized_heroines.append(_normalize_heroine_data(h))
                    else:
                        normalized_heroines.append(
                            _normalize_heroine_data(heroine_data)
                        )
                # 동일 플레이어로 재입장 시 이전 미완료 던전이 DB에 남아있으면
                # 충돌을 방지하기 위해 모두 완료 처리(is_finishing = TRUE) 합니다.
                if player_ids:
                    for _pid in player_ids:
                        try:
                            conn.execute(
                                text(
                                    """
                                    UPDATE dungeon
                                    SET is_finishing = TRUE
                                    WHERE is_finishing = FALSE
                                    AND (player1 = :pid OR player2 = :pid OR player3 = :pid OR player4 = :pid)
                                    """
                                ),
                                {"pid": str(_pid)},
                            )
                        except Exception as e:
                            # 실패 시 로그만 남기고 진행 (DB 상태에 따라 다르게 처리 가능)
                            print(
                                f"[WARN] failed to mark previous dungeons finished for pid={_pid}: {e}"
                            )
                for idx, raw_map in enumerate(raw_maps):
                    floor_num = idx + 1
                    if floor_num > 2:
                        break  # 1,2층만 생성
                    normalized_raw_map = _normalize_room_keys(raw_map)
                    normalized_raw_map["floor"] = floor_num
                    # playerIds, heroineIds를 모든 층 raw_map에 주입
                    normalized_raw_map["player_ids"] = player_ids
                    normalized_raw_map["heroine_ids"] = heroine_ids

                    check_sql = text(
                        """
                        SELECT id, event FROM dungeon WHERE floor = :floor AND is_finishing = FALSE AND (
                            player1 = :player_id OR player2 = :player_id OR player3 = :player_id OR player4 = :player_id
                        )
                    """
                    )
                    # Try to find an existing dungeon row for any provided player id (normalize to str)
                    row = None
                    if player_ids:
                        for pid in player_ids:
                            try:
                                pid_str = str(pid) if pid is not None else None
                                res = conn.execute(
                                    check_sql,
                                    {"floor": floor_num, "player_id": pid_str},
                                )
                                row = res.fetchone()
                                if row:
                                    break
                            except Exception as _e:
                                print(
                                    f"[WARN] entrance select failed for pid={pid}: {_e}"
                                )
                    if row:
                        floor_id = row[0]
                        existing_event = row[1]
                    else:
                        floor_id = self._insert_dungeon_in_transaction(
                            conn, floor=floor_num, raw_map=normalized_raw_map
                        )
                        existing_event = None
                    floor_ids.append(floor_id)

                    # Always generate events for this floor (do not prefer existing DB event)
                    events_for_this_floor = []
                    # 이벤트 생성 (이벤트 방이 있는 경우에만)
                    event_rooms = [
                        room
                        for room in normalized_raw_map.get("rooms", [])
                        if room.get("room_type") == "event"
                        or room.get("event_type", 0) != 0
                    ]
                    # 병렬 생성: 메인 이벤트들을 병렬로 요청한 뒤,
                    # 필요 시 각 플레이어에 대해 개인화 이벤트를 병렬로 생성합니다.
                    used_events_snapshot = list(used_events) if used_events else []
                    max_workers_main = min(8, max(1, len(event_rooms)))
                    with ThreadPoolExecutor(max_workers=max_workers_main) as ex:
                        fut_to_room = {
                            ex.submit(
                                self._create_event_for_floor,
                                heroine_data=normalized_heroines[0],
                                player_id=player_ids[0] if player_ids else None,
                                next_floor=floor_num,
                                used_events=used_events_snapshot,
                                room_id=room.get("room_id"),
                            ): room
                            for room in event_rooms
                        }

                        for fut in as_completed(fut_to_room):
                            room = fut_to_room[fut]
                            try:
                                main_event_data = fut.result()
                            except Exception as e:
                                print(f"[WARN] main event future failed: {e}")
                                continue
                            if not main_event_data:
                                continue
                            main_event_data["floor"] = floor_num

                            # 개인화 이벤트가 필요하면 각 플레이어에 대해 병렬 생성
                            if main_event_data.get("is_personal", False) and player_ids:
                                heroine_narratives = []
                                workers = min(4, max(1, len(player_ids)))
                                with ThreadPoolExecutor(max_workers=workers) as ex2:
                                    fut2_to_info = {
                                        ex2.submit(
                                            self._create_event_for_floor,
                                            heroine_data=h,
                                            player_id=pid,
                                            next_floor=floor_num,
                                            used_events=used_events_snapshot,
                                            room_id=room.get("room_id"),
                                        ): (pid, h)
                                        for pid, h in zip(
                                            player_ids, normalized_heroines
                                        )
                                    }
                                    for f2 in as_completed(fut2_to_info):
                                        pid, h = fut2_to_info[f2]
                                        try:
                                            indiv_event = f2.result()
                                        except Exception as e:
                                            print(
                                                f"[WARN] individual event future failed: {e}"
                                            )
                                            indiv_event = None
                                        if indiv_event:
                                            heroine_narratives.append(
                                                {
                                                    "playerId": pid,
                                                    "heroineId": h.get("heroine_id"),
                                                    "memoryProgress": h.get(
                                                        "memory_progress"
                                                    ),
                                                    "narrative": indiv_event.get(
                                                        "scenario_narrative", ""
                                                    ),
                                                }
                                            )
                                main_event_data["heroineNarratives"] = (
                                    heroine_narratives
                                )

                            events_for_this_floor.append(main_event_data)
                            used_events.append(main_event_data)

                    # 정렬: room_id가 작은 순서대로 반환하도록 정렬
                    events_for_this_floor = sorted(
                        events_for_this_floor, key=lambda e: e.get("room_id", 0)
                    )
                    # 알파: 정렬된 이벤트에 대해 인메모리로 적용 결과를 단순화하여 첨부합니다 (DB에 저장하지 않음)
                    try:
                        self._attach_in_memory_applications(events_for_this_floor)
                    except Exception as _e:
                        print(f"[WARN] attach_in_memory_applications failed: {_e}")
                    summary_info_value = self._generate_raw_map_summary(
                        normalized_raw_map
                    )
                    # Always overwrite the stored event with the newly generated events_for_this_floor
                    # Strip transient applied_actions before persisting
                    try:
                        self._strip_applied_actions(events_for_this_floor)
                    except Exception:
                        pass
                    conn.execute(
                        text(
                            "UPDATE dungeon SET event = :event, summary_info = :summary_info WHERE id = :id"
                        ),
                        {
                            "event": json.dumps(events_for_this_floor),
                            "summary_info": summary_info_value,
                            "id": floor_id,
                        },
                    )
                    events_list.extend(events_for_this_floor)
        except Exception as e:
            print(f"[ERROR] entrance 트랜잭션 실패: {e}")
            raise
        result = {
            "first_player_id": player_ids[0] if player_ids else 0,
            "floor_ids": floor_ids,
            "events": events_list,
        }
        return _remove_message_recursive(result)
        result = {
            "first_player_id": player_ids[0] if player_ids else 0,
            "floor_ids": floor_ids,
            "events": events_list,
        }
        return _remove_message_recursive(result)

    def next_floor_entrance(
        self,
        player_ids: List[str],
        heroine_ids: List[int],
        raw_map: Dict[str, Any],
        heroine_data: Optional[List[Dict[str, Any]]] = None,
        used_events: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """
        nextfloor에서 n+1층 raw_map을 받으면, 해당 층 row가 없으면 생성하고, 이벤트/summary_info도 즉시 생성해서 저장.
        """
        events_list = []
        used_events = used_events or []
        try:
            with self.repo.engine.begin() as conn:
                normalized_raw_map = _normalize_room_keys(raw_map)
                # 항상 player_ids, heroine_ids를 주입하여 DB에 반영
                normalized_raw_map["player_ids"] = [str(pid) for pid in player_ids]
                normalized_raw_map["heroine_ids"] = list(heroine_ids)

                floor_num = normalized_raw_map.get("floor")
                print(f"[DEBUG] next_floor_entrance: floor_num={floor_num}")
                if not floor_num:
                    raise ValueError("raw_map에 floor 정보가 없습니다.")

                check_sql = text(
                    """
                    SELECT id, event FROM dungeon WHERE floor = :floor AND is_finishing = FALSE AND (
                        player1 = :player_id OR player2 = :player_id OR player3 = :player_id OR player4 = :player_id
                    )
                    """
                )
                # Try to find existing row by any player in player_ids (string-normalized)
                row = None
                if player_ids:
                    for pid in player_ids:
                        try:
                            pid_str = str(pid)
                            print(
                                f"[DEBUG] next_floor_entrance: trying player_id={pid_str}"
                            )
                            res = conn.execute(
                                check_sql, {"floor": floor_num, "player_id": pid_str}
                            )
                            row = res.fetchone()
                            if row:
                                break
                        except Exception as _e:
                            print(
                                f"[WARN] next_floor_entrance select failed for pid={pid}: {_e}"
                            )
                print(f"[DEBUG] next_floor_entrance: select row={row}")
                if row:
                    floor_id = row[0]
                    existing_event = row[1]
                    print(
                        f"[DEBUG] next_floor_entrance: row exists, floor_id={floor_id}"
                    )
                    # If an event payload already exists in DB for this floor, return it immediately
                    if existing_event not in [None, "", "{}", "null", []]:
                        try:
                            parsed = (
                                json.loads(existing_event)
                                if isinstance(existing_event, str)
                                else existing_event
                            )
                        except Exception:
                            parsed = []
                        if isinstance(parsed, dict):
                            parsed = [parsed]
                        print(
                            f"[DEBUG] next_floor_entrance: returning existing DB events for floor {floor_num}"
                        )
                        return {"floor_id": floor_id, "events": parsed}
                else:
                    print(
                        f"[DEBUG] next_floor_entrance: inserting new floor {floor_num}"
                    )
                    floor_id = self._insert_dungeon_in_transaction(
                        conn, floor=floor_num, raw_map=normalized_raw_map
                    )
                    print(f"[DEBUG] next_floor_entrance: inserted floor_id={floor_id}")
                    existing_event = None

                # 이벤트 생성 (이벤트 방이 있는 경우에만)
                event_rooms = [
                    room
                    for room in normalized_raw_map.get("rooms", [])
                    if room.get("room_type") == "event"
                    or room.get("event_type", 0) != 0
                ]
                print(f"[DEBUG] next_floor_entrance: event_rooms={event_rooms}")
                events_for_this_floor = []
                # 멀티 히로인/플레이어 지원: 각 이벤트룸마다 매칭되는 히로인/플레이어 데이터 사용
                normalized_heroines = []
                if heroine_data:
                    # If int list, pad or trim to match heroine_ids length
                    if all(isinstance(h, int) for h in heroine_data):
                        # Pad heroine_data if shorter than heroine_ids
                        padded = list(heroine_data)[:]
                        while len(padded) < len(heroine_ids):
                            padded.append(0)
                        for hid, mp in zip(heroine_ids, padded):
                            normalized_heroines.append(
                                {"heroine_id": hid, "memory_progress": mp}
                            )
                    elif isinstance(heroine_data, list):
                        for h in heroine_data:
                            normalized_heroines.append(_normalize_heroine_data(h))
                    else:
                        normalized_heroines.append(
                            _normalize_heroine_data(heroine_data)
                        )
                # Defensive: if normalized_heroines is empty, raise clear error
                if not normalized_heroines:
                    raise ValueError(
                        "heroineData가 비어 있거나 유효하지 않습니다. (nextfloor)"
                    )
                # 병렬 생성: 메인 이벤트들을 병렬로 요청한 뒤,
                # 필요 시 각 플레이어에 대해 개인화 이벤트를 병렬로 생성합니다.
                used_events_snapshot = list(used_events) if used_events else []
                max_workers_main = min(8, max(1, len(event_rooms)))
                with ThreadPoolExecutor(max_workers=max_workers_main) as ex:
                    fut_to_room = {
                        ex.submit(
                            self._create_event_for_floor,
                            heroine_data=normalized_heroines[0],
                            player_id=player_ids[0] if player_ids else None,
                            next_floor=floor_num,
                            used_events=used_events_snapshot,
                            room_id=room.get("room_id"),
                        ): room
                        for room in event_rooms
                    }

                    for fut in as_completed(fut_to_room):
                        room = fut_to_room[fut]
                        try:
                            main_event_data = fut.result()
                        except Exception as e:
                            print(f"[WARN] next_floor main event future failed: {e}")
                            continue
                        if not main_event_data:
                            continue
                        main_event_data["floor"] = floor_num

                        # 개인화 이벤트가 필요하면 각 플레이어에 대해 병렬 생성
                        if main_event_data.get("is_personal", False) and player_ids:
                            heroine_narratives = []
                            workers = min(4, max(1, len(player_ids)))
                            with ThreadPoolExecutor(max_workers=workers) as ex2:
                                fut2_to_info = {
                                    ex2.submit(
                                        self._create_event_for_floor,
                                        heroine_data=h,
                                        player_id=pid,
                                        next_floor=floor_num,
                                        used_events=used_events_snapshot,
                                        room_id=room.get("room_id"),
                                    ): (pid, h)
                                    for pid, h in zip(player_ids, normalized_heroines)
                                }
                                for f2 in as_completed(fut2_to_info):
                                    pid, h = fut2_to_info[f2]
                                    try:
                                        indiv_event = f2.result()
                                    except Exception as e:
                                        print(
                                            f"[WARN] next_floor individual event future failed: {e}"
                                        )
                                        indiv_event = None
                                    if indiv_event:
                                        heroine_narratives.append(
                                            {
                                                "playerId": pid,
                                                "heroineId": h.get("heroine_id"),
                                                "memoryProgress": h.get(
                                                    "memory_progress"
                                                ),
                                                "narrative": indiv_event.get(
                                                    "scenario_narrative", ""
                                                ),
                                            }
                                        )
                            main_event_data["heroineNarratives"] = heroine_narratives

                        events_for_this_floor.append(main_event_data)
                        used_events.append(main_event_data)

                # 정렬: room_id가 작은 순서대로 반환하도록 정렬
                events_for_this_floor = sorted(
                    events_for_this_floor, key=lambda e: e.get("room_id", 0)
                )
                # 알파: 정렬된 이벤트에 대해 인메모리로 적용 결과를 단순화하여 첨부합니다 (DB에 저장하지 않음)
                try:
                    self._attach_in_memory_applications(events_for_this_floor)
                except Exception as _e:
                    print(f"[WARN] attach_in_memory_applications failed: {_e}")
                summary_info_value = self._generate_raw_map_summary(normalized_raw_map)

                # Strip transient applied_actions before persisting
                try:
                    self._strip_applied_actions(events_for_this_floor)
                except Exception:
                    pass

                # Always update the dungeon.row with generated events and summary_info
                if row:
                    conn.execute(
                        text(
                            "UPDATE dungeon SET event = :event, summary_info = :summary_info WHERE id = :id"
                        ),
                        {
                            "event": json.dumps(
                                events_for_this_floor, ensure_ascii=False
                            ),
                            "summary_info": summary_info_value,
                            "id": floor_id,
                        },
                    )
                else:
                    conn.execute(
                        text(
                            "UPDATE dungeon SET raw_map = :raw_map, event = :event, summary_info = :summary_info WHERE id = :id"
                        ),
                        {
                            "raw_map": json.dumps(
                                normalized_raw_map, ensure_ascii=False
                            ),
                            "event": json.dumps(
                                events_for_this_floor, ensure_ascii=False
                            ),
                            "summary_info": summary_info_value,
                            "id": floor_id,
                        },
                    )
                print(f"[DEBUG] next_floor_entrance: updated dungeon row id={floor_id}")
                events_list.extend(events_for_this_floor)
            print(
                f"[DEBUG] next_floor_entrance: returning floor_id={floor_id}, events={events_list}"
            )
            return {
                "floor_id": floor_id,
                "events": events_list,
            }
        except Exception as e:
            print(f"[ERROR] next_floor_entrance 트랜잭션 실패: {e}")
            raise

    def _insert_dungeon_in_transaction(
        self, conn, floor: int, raw_map: Dict[str, Any]
    ) -> int:
        """트랜잭션 내에서 던전 삽입 (연결 재사용)"""

        raw_map_dict = raw_map if isinstance(raw_map, dict) else json.loads(raw_map)
        player_ids = [str(pid) for pid in raw_map_dict.get("player_ids", [])]
        heroine_ids = raw_map_dict.get("heroine_ids", [])

        player_with_heroine = []
        for i in range(0, 4):
            player_id = str(player_ids[i]) if i < len(player_ids) else None
            heroine_id = str(heroine_ids[i]) if i < len(heroine_ids) else None
            player_with_heroine.append((player_id, heroine_id))

        sql = """
        INSERT INTO dungeon 
        (floor, raw_map, balanced_map, is_finishing, summary_info,
         player1, player2, player3, player4, 
         heroine1, heroine2, heroine3, heroine4)
        VALUES 
        (:floor, :raw_map, :balanced_map, :is_finishing, :summary_info,
         :player1, :player2, :player3, :player4,
         :heroine1, :heroine2, :heroine3, :heroine4)
        RETURNING id
        """

        raw_map_json = (
            json.dumps(raw_map) if isinstance(raw_map, (dict, list)) else raw_map
        )
        balanced_map_value = raw_map_json if floor == 1 else None

        # floor 1일 때 raw_map 기반 summary_info 생성
        summary_info_value = ""
        if floor == 1:
            summary_info_value = self._generate_raw_map_summary(raw_map_dict)

        params = {
            "floor": floor,
            "raw_map": raw_map_json,
            "balanced_map": balanced_map_value,
            "is_finishing": False,
            "summary_info": summary_info_value,
            "player1": player_with_heroine[0][0],
            "player2": player_with_heroine[1][0],
            "player3": player_with_heroine[2][0],
            "player4": player_with_heroine[3][0],
            "heroine1": player_with_heroine[0][1],
            "heroine2": player_with_heroine[1][1],
            "heroine3": player_with_heroine[2][1],
            "heroine4": player_with_heroine[3][1],
        }

        result = conn.execute(text(sql), params)
        return result.fetchone()[0]

    # ============================================================
    # 2. 다음 층 raw_map 업데이트
    # ============================================================
    def update_raw_map(self, dungeon_id: int, raw_map: Dict[str, Any]) -> bool:
        """
        다음 층의 raw_map 업데이트 (Unreal이 생성 후 전달)

        Args:
            dungeon_id: 업데이트할 던전 ID
            raw_map: Unreal이 생성한 raw_map (camelCase)

        Returns:
            성공 여부
        """
        try:
            # Unreal JSON 정규화
            normalized_raw_map = _normalize_room_keys(raw_map)

            with self.repo.engine.begin() as conn:
                conn.execute(
                    text("UPDATE dungeon SET raw_map = :raw_map WHERE id = :id"),
                    {"raw_map": json.dumps(normalized_raw_map), "id": dungeon_id},
                )
            return True
        except Exception as e:
            print(f"[ERROR] raw_map 업데이트 실패: {e}")
            return False

    def update_raw_map_and_event_for_floor(
        self, first_player_id: str, floor: int, raw_map: Dict[str, Any], event: Any
    ) -> bool:
        try:

            with self.repo.engine.begin() as conn:
                # 해당 플레이어의 진행 중인 던전 중 floor에 해당하는 row 찾기
                sql = text(
                    """
                    SELECT id FROM dungeon WHERE floor = :floor AND is_finishing = FALSE AND (
                        player1 = :player_id OR player2 = :player_id OR player3 = :player_id OR player4 = :player_id
                    )
                    """
                )
                player_id_str = (
                    str(first_player_id) if first_player_id is not None else None
                )
                result = conn.execute(sql, {"floor": floor, "player_id": player_id_str})
                row = result.fetchone()
                if not row:
                    print(
                        f"[ERROR] 해당 플레이어와 층에 대한 던전 row를 찾을 수 없음: player_id={first_player_id}, floor={floor}"
                    )
                    return False
                dungeon_id = row[0]
                # raw_map, event 업데이트
                update_sql = text(
                    """
                    UPDATE dungeon SET raw_map = :raw_map, event = :event WHERE id = :dungeon_id
                    """
                )
                conn.execute(
                    update_sql,
                    {
                        "raw_map": (
                            json.dumps(raw_map)
                            if isinstance(raw_map, (dict, list))
                            else raw_map
                        ),
                        "event": (
                            json.dumps(
                                (lambda e: (self._strip_applied_actions(e), e)[1])(
                                    event
                                )
                            )
                            if isinstance(event, (dict, list))
                            else event
                        ),
                        "dungeon_id": dungeon_id,
                    },
                )
            return True
        except Exception as e:
            print(f"[ERROR] update_raw_map_and_event_for_floor 실패: {e}")
            return False

    # ============================================================
    # 2-1. Summary Info 생성 헬퍼
    # ============================================================
    def _generate_raw_map_summary(self, raw_map: Dict[str, Any]) -> str:
        """
        Raw Map 정보로부터 간단한 요약 정보 생성 (1층용)
        """
        rooms = raw_map.get("rooms", [])
        rooms_count = len(rooms)

        room_types = {}
        total_monsters = 0
        event_room_ids = []

        for room in rooms:
            r_type = room.get("room_type", "unknown")
            room_types[r_type] = room_types.get(r_type, 0) + 1

            monsters = room.get("monsters", [])
            total_monsters += len(monsters)

            # 이벤트 방 확인
            if r_type == "event" or room.get("event_type", 0) != 0:
                event_room_ids.append(room.get("room_id"))

        type_summary = ", ".join([f"{k}: {v}" for k, v in room_types.items()])

        event_summary = "없음"
        if event_room_ids:
            event_summary = (
                f"{len(event_room_ids)}곳 (Room {', '.join(map(str, event_room_ids))})"
            )

        summary = (
            f"던전 1층 진입.\n"
            f"- 총 방 개수: {rooms_count}\n"
            f"- 방 구성: {type_summary}\n"
            f"- 감지된 몬스터 수: {total_monsters}\n"
            f"- 감지된 이벤트 지점: {event_summary}\n"
        )
        return summary

    def _generate_summary_info(
        self, balanced_map: Dict[str, Any], agent_result: Dict[str, Any]
    ) -> str:
        """
        Super Agent 결과로부터 summary_info 생성

        Args:
            balanced_map: 밸런싱된 맵 데이터
            agent_result: Super Agent 최종 결과

        Returns:
            생성된 summary_info 문자열
        """
        events = agent_result.get("events", {})
        monster_stats = agent_result.get("monster_stats", {})
        difficulty_info = agent_result.get("difficulty_info", {})

        rooms = balanced_map.get("rooms", [])
        rooms_count = len(rooms)
        room_types = {}
        for room in rooms:
            room_type = room.get("room_type", "unknown")
            room_types[room_type] = room_types.get(room_type, 0) + 1

        room_type_str = ", ".join(
            [f"{k}실 {v}개" for k, v in sorted(room_types.items())]
        )

        # 이벤트 정보 추출 (이제 dict 형식)
        main_event = events.get("main_event", {})
        sub_event = events.get("sub_event", {})

        main_event_title = (
            main_event.get("title", "N/A") if isinstance(main_event, dict) else "N/A"
        )
        sub_event_narrative = (
            sub_event.get("narrative", "N/A") if isinstance(sub_event, dict) else "N/A"
        )

        # 문자열로 변환 후 슬라이싱
        sub_event_preview = (
            str(sub_event_narrative)[:80] if sub_event_narrative != "N/A" else "N/A"
        )

        summary_lines = [
            f"[맵 구성]",
            f"  - 총 방: {rooms_count}개 ({room_type_str})",
            f"",
            f"[몬스터 배치]",
            f"  - 총 {monster_stats.get('total_count', 0)}마리 (보스: {monster_stats.get('boss_count', 0)}, 일반: {monster_stats.get('normal_count', 0)})",
            f"  - 위협도 달성률: {monster_stats.get('achievement_rate', 0):.1f}%",
            f"",
            f"[난이도]",
            f"  - 전투력: {difficulty_info.get('combat_score', 0):.2f}",
            f"  - AI 배율: x{difficulty_info.get('ai_multiplier', 1.0):.2f}",
            f"",
            f"[이벤트]",
            f"  - 주요: {main_event_title}",
            f"  - 보조: {sub_event_preview}...",
        ]
        return "\n".join(summary_lines)

    # --------------------------------------------------
    # 무기 -> weaponId, 악세서리 -> AccessoryItem
    # - 몬스터: monsterId와 monsterType(기본값 normal=0)을 반환
    # - 스탯: stat, value, duration 정보를 반환
    # - 알파 단계에서는 DB에 저장하지 않음
    # --------------------------------------------------
    def _attach_in_memory_applications(self, events: List[Dict[str, Any]]) -> None:
        def _simplify_reward(r: Dict[str, Any]) -> Dict[str, Any]:
            t = r.get("type")
            if t == "drop_item":
                item_type = r.get("item_type") or r.get("itemType")
                item_id = r.get("item_id") or r.get("itemId") or r.get("itemId")
                if item_type == "weapon":
                    return {
                        "action": "drop_item",
                        "weaponId": item_id,
                        "count": r.get("count", 1),
                    }
                if item_type == "accessory":
                    return {
                        "action": "drop_item",
                        "AccessoryItem": item_id,
                        "count": r.get("count", 1),
                    }
                return {
                    "action": "drop_item",
                    "itemId": item_id,
                    "count": r.get("count", 1),
                }
            if t == "spawn_monster":
                return {
                    "action": "spawn_monster",
                    "monsterId": r.get("monster_id") or r.get("monsterId"),
                    "monsterType": r.get("monster_type", 0),
                    "count": r.get("count", 1),
                }
            if t == "change_stat":
                return {
                    "action": "change_stat",
                    "stat": r.get("stat"),
                    "value": r.get("value"),
                    "duration": r.get("duration", 0),
                }
            return {"action": "unknown", "raw": r}

        for ev in events:
            applied = []

            # 보상 id에서 실제 객체를 찾아 단순화하여 applied에 추가
            for key in ("reward_ids", "rewards", "rewardId", "reward_id"):
                if key in ev and ev.get(key):
                    vals = ev.get(key)
                    if isinstance(vals, (list, tuple)):
                        for rid in vals:
                            r = er.get_reward_dict(rid)
                            if r:
                                applied.append(_simplify_reward(r))
                    else:
                        r = er.get_reward_dict(vals)
                        if r:
                            applied.append(_simplify_reward(r))

            # 패널티 id 처리
            for key in ("penalty_ids", "penalties", "penaltyId", "penalty_id"):
                if key in ev and ev.get(key):
                    vals = ev.get(key)
                    if isinstance(vals, (list, tuple)):
                        for pid in vals:
                            p = er.get_penalty_dict(pid)
                            if p:
                                applied.append(_simplify_reward(p))
                    else:
                        p = er.get_penalty_dict(vals)
                        if p:
                            applied.append(_simplify_reward(p))

            # applied_rewards 등 이미 객체로 포함된 보상들도 허용
            for key in ("applied_rewards", "applied", "applies"):
                if key in ev and ev.get(key):
                    vals = ev.get(key)
                    if isinstance(vals, (list, tuple)):
                        for obj in vals:
                            if isinstance(obj, dict):
                                applied.append(_simplify_reward(obj))

            # Attach simplified applied list and remove verbose fields
            ev["applied_actions"] = applied
            for drop_key in (
                "choice",
                "choices",
                "reward_ids",
                "penalty_ids",
                "rewards",
                "penalties",
            ):
                if drop_key in ev:
                    ev.pop(drop_key, None)

    def balance_dungeon(
        self,
        first_player_id: str,
        player_data_list: List[Dict[str, Any]],
        monster_db: Dict[str, Any],
        used_events: List[Any] = None,
        player_count: int = None,
    ) -> Dict[str, Any]:
        """
        Args:
            first_player_id: 방장 ID (던전 식별용)
            player_data_list: 플레이어별 데이터 리스트 [{playerId, heroineData, heroineStat, ...}]
            monster_db: 몬스터 데이터베이스
            used_events: 이미 사용한 이벤트 리스트

        Returns:
            {
                "success": bool,
                "dungeon_id": int,
                "agent_result": dict (super_agent 최종 결과),
                "summary": str,
            }
        """
        try:
            host_data_wrapper = None
            for pd in player_data_list:
                # pd가 dict인지 확인
                if not isinstance(pd, dict):
                    continue

                h_data = pd.get("heroineData", {})
                if not isinstance(h_data, dict):
                    continue

                # Accept playerId either inside heroineData or at the top-level of pd
                if (
                    h_data.get("playerId") == first_player_id
                    or pd.get("playerId") == first_player_id
                ):
                    host_data_wrapper = pd
                    break

            if not host_data_wrapper:
                host_data_wrapper = (
                    player_data_list[0]
                    if player_data_list and isinstance(player_data_list[0], dict)
                    else {}
                )

            host_data = (
                host_data_wrapper.get("heroineData", {})
                if isinstance(host_data_wrapper, dict)
                else {}
            )

            # heroine_data 정규화 (host) - keep for backward compatibility
            heroine_data = _normalize_heroine_data(host_data)

            # Build heroine_stat list and heroine_data list for all players
            heroine_stat_list: List[Any] = []
            heroine_data_list: List[Dict[str, Any]] = []
            try:
                for pd in player_data_list:
                    if not isinstance(pd, dict):
                        continue
                    hd = pd.get("heroineData", {}) or {}
                    if isinstance(hd, dict):
                        # normalize individual heroineData
                        normalized_hd = _normalize_heroine_data(hd)
                        heroine_data_list.append(normalized_hd)
                        # extract heroineStat (may be under 'heroineStat' or 'heroine_stat')
                        hs = hd.get("heroineStat") or hd.get("heroine_stat") or {}
                        heroine_stat_list.append(hs if isinstance(hs, dict) else hs)
            except Exception:
                heroine_stat_list = [host_data.get("heroineStat", {})]
                heroine_data_list = [heroine_data]

            heroine_stat = heroine_stat_list
            heroine_memories = host_data.get("heroineMemories", [])
            dungeon_player_data = host_data.get("dungeonPlayerData", {})

            # If explicit player_count was not provided, derive from player_data_list
            if not isinstance(player_count, int) or player_count <= 0:
                try:
                    player_count = len(
                        [p for p in player_data_list if isinstance(p, dict)]
                    )
                except Exception:
                    player_count = 1

            # 1. 현재 진행 중인 던전 찾기 (first_player_id로)
            unfinished = self.repo.get_unfinished_dungeons(player_ids=[first_player_id])
            if not unfinished:
                return {
                    "success": False,
                    "error": f"플레이어 {first_player_id}의 진행 중인 던전을 찾을 수 없습니다",
                }

            dungeon_id = unfinished.get("id")
            current_floor = unfinished.get("floor", 1)

            # DB에서 현재 던전 조회 (연결 블록 외부에서)

            with self.repo.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT * FROM dungeon WHERE id = :id"), {"id": dungeon_id}
                ).fetchone()
                if not result:
                    return {
                        "success": False,
                        "error": f"던전 {dungeon_id}를 찾을 수 없습니다",
                    }
                dungeon_row = dict(result._mapping)

            # raw_map 파싱 (연결 블록 외부에서)
            raw_map_value = dungeon_row.get("raw_map")
            raw_map = (
                json.loads(raw_map_value)
                if isinstance(raw_map_value, str)
                else raw_map_value
            )

            # DEBUG: raw_map 확인
            print(f"[DEBUG] balance_dungeon - raw_map keys: {raw_map.keys()}")

            print(f"\n[DEBUG] 던전 {dungeon_id} raw_map 읽음:")
            print(f"  - rooms count: {len(raw_map.get('rooms', []))}")
            for i, room in enumerate(raw_map.get("rooms", [])):
                monsters = room.get("monsters", [])
                print(
                    f"  - room {i}: type={room.get('room_type')}, monsters={monsters}"
                )
            # 다음 층 ID 조회
            next_floor = current_floor + 1
            next_floor_id = None

            # player_ids 추출
            player_ids_list = raw_map.get("player_ids") or raw_map.get("playerIds", [])

            # player_ids_list가 정수형 리스트일 경우 처리
            if isinstance(player_ids_list, int):
                player_ids_list = [player_ids_list]

            with self.repo.engine.connect() as conn:
                if (
                    player_ids_list
                    and isinstance(player_ids_list, list)
                    and len(player_ids_list) > 0
                ):
                    # Try each provided player id and match against any player column
                    next_floor_id = None
                    next_dungeon_query = """
                        SELECT id FROM dungeon
                        WHERE floor = :next_floor
                        AND is_finishing = FALSE
                        AND (
                            player1 = :pid OR player2 = :pid OR player3 = :pid OR player4 = :pid
                        )
                        LIMIT 1
                    """
                    for pid in player_ids_list:
                        try:
                            pid_str = str(pid) if pid is not None else None
                            next_result = conn.execute(
                                text(next_dungeon_query),
                                {"next_floor": next_floor, "pid": pid_str},
                            ).fetchone()
                            if next_result:
                                next_floor_id = next_result[0]
                                break
                        except Exception as _e:
                            print(
                                f"[WARN] next_floor lookup failed for pid={pid}: {_e}"
                            )

            if not next_floor_id:
                return {
                    "success": False,
                    "error": f"다음 층({next_floor}층)을 찾을 수 없습니다.",
                }

            # 다음 층의 raw_map 또는 balanced_map을 DB에서 우선 조회하여 사용
            next_floor_raw_map = None
            with self.repo.engine.connect() as conn:
                next_row = conn.execute(
                    text("SELECT raw_map, balanced_map FROM dungeon WHERE id = :id"),
                    {"id": next_floor_id},
                ).fetchone()
                if next_row:
                    next_raw_val = next_row[0]
                    next_balanced_val = next_row[1] if len(next_row) > 1 else None

                    # Prefer explicit raw_map if present
                    if next_raw_val not in [None, "", "{}", "null"]:
                        try:
                            next_floor_raw_map = (
                                json.loads(next_raw_val)
                                if isinstance(next_raw_val, str)
                                else next_raw_val
                            )
                        except Exception:
                            next_floor_raw_map = None

                    # If raw_map missing, try balanced_map (agent-produced)
                    if not next_floor_raw_map and next_balanced_val not in [
                        None,
                        "",
                        "{}",
                        "null",
                    ]:
                        try:
                            parsed_bal = (
                                json.loads(next_balanced_val)
                                if isinstance(next_balanced_val, str)
                                else next_balanced_val
                            )
                            # balanced map may wrap rooms under 'dungeon_data' or be direct
                            if isinstance(parsed_bal, dict) and "rooms" in parsed_bal:
                                next_floor_raw_map = parsed_bal
                            elif (
                                isinstance(parsed_bal, dict)
                                and "dungeon_data" in parsed_bal
                            ):
                                next_floor_raw_map = parsed_bal.get("dungeon_data")
                        except Exception:
                            next_floor_raw_map = None

            # If no next-floor map is found, fail early rather than copying current floor
            if not next_floor_raw_map:
                return {
                    "success": False,
                    "error": f"다음 층({next_floor}층)의 raw_map 또는 balanced_map이 없습니다. 먼저 /nextfloor로 raw_map을 저장하세요.",
                }

            # Defensive normalization for the next-floor map and rooms
            try:
                normalized_next_floor_map = _normalize_room_keys(
                    next_floor_raw_map if isinstance(next_floor_raw_map, dict) else {}
                )
            except Exception:
                normalized_next_floor_map = next_floor_raw_map or {}

            # Ensure player_count is available for agent nodes (fallbacks to 1)
            try:
                pids = (
                    player_ids_list
                    if isinstance(player_ids_list, list)
                    else normalized_next_floor_map.get("player_ids", [])
                )
                player_count = (
                    len(pids) if isinstance(pids, list) and len(pids) > 0 else 1
                )
            except Exception:
                player_count = 1

            # Ensure every room has a numeric 'size'. If missing, fill with the rooms' average size or 4.
            import math

            rooms_for_agent = normalized_next_floor_map.get("rooms", []) or []
            sizes = [
                r.get("size")
                for r in rooms_for_agent
                if isinstance(r.get("size"), (int, float))
            ]
            if sizes:
                avg_size = int(round(sum(sizes) / len(sizes)))
            else:
                avg_size = 4
            for r in rooms_for_agent:
                if not isinstance(r.get("size"), (int, float)):
                    r["size"] = avg_size

            # Attach player_count back into the normalized map for downstream nodes
            normalized_next_floor_map["player_ids"] = (
                pids if isinstance(pids, list) else []
            )
            normalized_next_floor_map["player_count"] = player_count

            agent_state = {
                "dungeon_base_data": {
                    "dungeon_id": next_floor_id,
                    "floor_count": next_floor,
                    "rooms": rooms_for_agent,
                    "player_count": player_count,
                },
                "player_count": player_count,
                "heroine_data": heroine_data,
                "heroine_stat": heroine_stat,
                "heroine_memories": heroine_memories,
                "monster_db": monster_db,
                "dungeon_player_data": dungeon_player_data,
                "used_events": used_events if used_events is not None else [],
                "event_result": {},
                "filled_dungeon_data": {},
                "difficulty_log": {},
                "final_dungeon_json": {},
                "skip_event_node": True,
            }

            print(
                f"\n[Dungeon {next_floor_id}] Super Agent 실행 중 (Floor {next_floor})..."
            )
            # Debug: show which map (raw/balanced) will be used for monster balancing
            try:
                rooms_preview = next_floor_raw_map.get("rooms", [])
                print(
                    f"[DEBUG] Using next_floor_raw_map for balancing: dungeon_id={next_floor_id}, rooms_count={len(rooms_preview)}"
                )
                for i, r in enumerate(rooms_preview):
                    print(
                        f"  - room {i}: type={r.get('room_type') or r.get('type') or r.get('roomType')}, monsters={r.get('monsters', [])}"
                    )
            except Exception:
                print("[DEBUG] next_floor_raw_map preview failed")
            dungeon_graph = get_dungeon_graph()
            agent_result = dungeon_graph.invoke(agent_state)

            final_json = agent_result.get("final_dungeon_json", {})
            balanced_map_data = final_json.get("dungeon_data", {})

            # DEBUG: agent_result 구조 출력
            print(f"\n[DEBUG] final_json keys: {list(final_json.keys())}")
            print(f"[DEBUG] balanced_map_data keys: {list(balanced_map_data.keys())}")
            print(
                f"[DEBUG] balanced_map_data.get('rooms'): {len(balanced_map_data.get('rooms', []))} rooms"
            )
            print(f"[DEBUG] events keys: {list(final_json.get('events', {}).keys())}")
            print(f"[DEBUG] monster_stats: {final_json.get('monster_stats', {})}")

            # summary_info 생성 (다음 층 데이터 기반)
            summary_info = self._generate_summary_info(balanced_map_data, final_json)

            next_floor_events = None

            # DB 업데이트 (단일 연결 블록으로 통합)
            with self.repo.engine.begin() as conn:
                # 다음 층의 raw_map이 이미 존재하는지 확인 (NULL/빈 값만 업데이트)
                check_sql = text("SELECT raw_map FROM dungeon WHERE id = :id")
                result = conn.execute(check_sql, {"id": next_floor_id}).fetchone()
                raw_map_exists = False
                if result:
                    existing_raw_map = result[0]
                    if existing_raw_map not in [None, "", "{}", "null"]:
                        raw_map_exists = True

                update_params = {
                    "balanced_map": json.dumps(balanced_map_data),
                    "summary_info": summary_info,
                    "id": next_floor_id,
                }
                update_sql = None
                if not raw_map_exists:
                    update_params["raw_map"] = json.dumps(next_floor_raw_map)
                    if next_floor >= 3 or (next_floor_events not in [None, [], {}]):
                        update_params["event"] = json.dumps(next_floor_events)
                        update_sql = text(
                            "UPDATE dungeon SET raw_map = :raw_map, balanced_map = :balanced_map, event = :event, summary_info = :summary_info WHERE id = :id"
                        )
                    else:
                        update_sql = text(
                            "UPDATE dungeon SET raw_map = :raw_map, balanced_map = :balanced_map, summary_info = :summary_info WHERE id = :id"
                        )
                else:
                    # raw_map이 이미 있으면 raw_map은 건드리지 않음
                    if next_floor >= 3 or (next_floor_events not in [None, [], {}]):
                        update_params["event"] = json.dumps(next_floor_events)
                        update_sql = text(
                            "UPDATE dungeon SET balanced_map = :balanced_map, event = :event, summary_info = :summary_info WHERE id = :id"
                        )
                    else:
                        update_sql = text(
                            "UPDATE dungeon SET balanced_map = :balanced_map, summary_info = :summary_info WHERE id = :id"
                        )
                conn.execute(update_sql, update_params)
                print(
                    f"[SUCCESS] 다음 층({next_floor}층) 밸런싱 및 저장 완료 (raw_map {'업데이트' if not raw_map_exists else '유지'})"
                )

            # 몬스터 배치 정보 추출 및 방별 그룹화 (다음 층 기준)
            monster_placements_grouped = []
            for room in balanced_map_data.get("rooms", []):
                room_id = room.get("room_id")
                monsters = room.get("monsters", [])

                # 몬스터 ID별 카운트
                monster_counts = {}
                for m in monsters:
                    if isinstance(m, dict):
                        m_id = m.get("monster_id")
                    elif isinstance(m, int):
                        m_id = m
                    else:
                        continue

                    if m_id is not None:
                        monster_counts[m_id] = monster_counts.get(m_id, 0) + 1

                mons_list = []
                for m_id, count in monster_counts.items():
                    mons_list.append({"monsterId": m_id, "count": count})

                monster_placements_grouped.append(
                    {"roomId": room_id, "monsters": mons_list}
                )

            result = {
                "success": True,
                "dungeon_id": next_floor_id,
                "balanced_floor": next_floor,
                "source_dungeon_id": dungeon_id,
                "agent_result": final_json,
                "summary": summary_info,
                "monster_placements": monster_placements_grouped,
                "next_floor_event": next_floor_events,
            }
            return _remove_message_recursive(result)
        except Exception as e:
            print(f"[ERROR] 던전 밸런싱 실패: {e}")
            import traceback

            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
            }

    # ============================================================
    # 4. 다음 층 준비 (Prepare Next Floor - 이벤트 생성)
    # ============================================================
    def prepare_next_floor(
        self,
        first_player_id: str,
        heroine_data: Dict[str, Any],
        used_events: List[Any] = None,
    ) -> Dict[str, Any]:
        try:
            # 1. 현재 진행 중인 던전 찾기
            unfinished = self.repo.get_unfinished_dungeons(player_ids=[first_player_id])
            if not unfinished:
                return {
                    "success": False,
                    "error": f"플레이어 {first_player_id}의 진행 중인 던전을 찾을 수 없습니다",
                }

            current_floor = unfinished.get("floor", 1)
            next_floor = current_floor + 1

            if next_floor > 3:
                return {
                    "success": False,
                    "error": "더 이상 진행할 층이 없습니다 (최대 3층)",
                }

            # 2. 다음 층 던전 ID 찾기

            next_floor_id = None

            with self.repo.engine.begin() as conn:
                next_dungeon_query = """
                    SELECT id FROM dungeon 
                    WHERE floor = :next_floor 
                    AND player1 = :player1
                    AND is_finishing = FALSE
                    LIMIT 1
                """
                next_result = conn.execute(
                    text(next_dungeon_query),
                    {"next_floor": next_floor, "player1": str(first_player_id)},
                ).fetchone()

                if not next_result:
                    return {
                        "success": False,
                        "error": f"다음 층({next_floor}층) 던전을 찾을 수 없습니다",
                    }

                next_floor_id = next_result[0]

                # 3. 다음 층 이벤트 생성 및 저장
                events = self._create_event_for_floor(
                    heroine_data=heroine_data,
                    next_floor=next_floor,
                    used_events=used_events or [],
                )

                if events:
                    try:
                        self._strip_applied_actions(events)
                    except Exception:
                        pass
                    conn.execute(
                        text("UPDATE dungeon SET event = :event WHERE id = :id"),
                        {"event": json.dumps(events), "id": next_floor_id},
                    )

            result = {"success": True, "next_floor_id": next_floor_id, "events": events}
            return _remove_message_recursive(result)

        except Exception as e:
            print(f"[ERROR] 다음 층 준비 실패: {e}")
            import traceback

            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
            }

    # ============================================================
    # 5. 층 완료 (Clear - is_finishing = TRUE)
    # ============================================================
    def clear_floor(self, player_ids: List[str]) -> Dict[str, Any]:
        """
        현재 층 완료 처리 및 balanced_map 반환
        (Unreal에 다음 층 raw_map 생성을 위해 전달할 데이터)

        Args:
            player_ids: 플레이어 ID 리스트

        Returns:
            {
                "success": bool,
                "finished_dungeon": dict,
                "balanced_map": dict,
            }
        """
        try:
            finished = self.repo.is_finishing_dungeon(player_ids=player_ids)

            if not finished:
                return {
                    "success": False,
                    "error": "완료할 던전을 찾을 수 없습니다",
                }

            # balanced_map 추출
            balanced_map_value = finished.get("balanced_map")
            balanced_map = (
                (
                    json.loads(balanced_map_value)
                    if isinstance(balanced_map_value, str)
                    else balanced_map_value
                )
                if balanced_map_value
                else {}
            )

            # Remove any transient/display 'message' fields from DB row before returning
            try:
                if isinstance(finished, dict) and "message" in finished:
                    finished.pop("message", None)
            except Exception:
                pass
            try:
                if isinstance(balanced_map, dict) and "message" in balanced_map:
                    balanced_map.pop("message", None)
            except Exception:
                pass

            return {
                "success": True,
                "finished_dungeon": finished,
                "balanced_map": balanced_map,
            }
        except Exception as e:
            print(f"[ERROR] 층 완료 처리 실패: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    # ============================================================
    # 5. 상태 조회 (Status)
    # ============================================================
    def get_status(self, player_ids: List[str]) -> Dict[str, Any]:
        """플레이어의 현재 진행 중인 던전 상태 조회"""
        return self.repo.get_unfinished_dungeons(player_ids=player_ids)

    def get_all(self) -> List[Dict[str, Any]]:
        """모든 던전 조회 (관리자용)"""
        try:

            with self.repo.engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT * FROM dungeon ORDER BY id DESC")
                ).fetchall()
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            print(f"[ERROR] 던전 조회 실패: {e}")
            return []

    # ============================================================
    # 6. 이벤트 선택 (Event Select)
    # ============================================================
    def select_event(
        self, first_player_id: str, selecting_player_id: str, room_id: int, choice: str
    ) -> Dict[str, Any]:
        """
        플레이어의 이벤트 선택 처리
        """
        try:
            # 1. 현재 진행 중인 던전 찾기
            unfinished = self.repo.get_unfinished_dungeons(player_ids=[first_player_id])
            if not unfinished:
                return {
                    "success": False,
                    "error": f"플레이어 {first_player_id}의 진행 중인 던전을 찾을 수 없습니다",
                }

            dungeon_id = unfinished.get("id")

            # 2. DB에서 이벤트 정보 조회
            event_data = None

            with self.repo.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT event FROM dungeon WHERE id = :id"), {"id": dungeon_id}
                ).fetchone()

                if result and result[0]:
                    event_val = result[0]
                    event_data = (
                        json.loads(event_val)
                        if isinstance(event_val, str)
                        else event_val
                    )

            if not event_data:
                return {
                    "success": False,
                    "error": "이벤트 정보를 찾을 수 없습니다",
                }

            # 3. 해당 방의 이벤트 찾기
            target_event = None

            # DEBUG: 이벤트 데이터 확인
            print(
                f"[DEBUG] select_event - dungeon_id: {dungeon_id}, target room_id: {room_id}"
            )

            if isinstance(event_data, list):
                for evt in event_data:
                    # 타입 안전 비교 (str 변환)
                    # room_id(snake_case) 또는 roomId(camelCase) 모두 확인
                    evt_room_id = evt.get("room_id")
                    if evt_room_id is None:
                        evt_room_id = evt.get("roomId")

                    if str(evt_room_id) == str(room_id):
                        target_event = evt
                        break
            elif isinstance(event_data, dict):
                evt_room_id = event_data.get("room_id")
                if evt_room_id is None:
                    evt_room_id = event_data.get("roomId")

                if str(evt_room_id) == str(room_id):
                    target_event = event_data

            if not target_event:
                # 디버깅을 위해 현재 로드된 이벤트들의 room_id 목록을 에러 메시지에 포함
                loaded_room_ids = []
                if isinstance(event_data, list):
                    loaded_room_ids = [
                        e.get("room_id") or e.get("roomId") for e in event_data
                    ]
                elif isinstance(event_data, dict):
                    loaded_room_ids = [
                        event_data.get("room_id") or event_data.get("roomId")
                    ]

                print(f"[ERROR] Event not found. Loaded room_ids: {loaded_room_ids}")

                return {
                    "success": False,
                    "error": f"Room {room_id}에 해당하는 이벤트를 찾을 수 없습니다 (Loaded: {loaded_room_ids})",
                }

            # 4. 선택지에 따른 결과 도출 (LLM 사용)
            from langchain.chat_models import init_chat_model
            from enums.LLM import LLM
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = init_chat_model(model=LLM.GPT5_MINI, temperature=0.7)

            scenario_narrative = target_event.get("scenario_narrative", "")
            choices = target_event.get("choices", [])
            # If choices missing but expected_outcome present, try to parse it into choices
            if not choices:
                eo = target_event.get("expected_outcome") or target_event.get(
                    "expectedOutcome"
                )
                if eo and isinstance(eo, str) and eo.strip():
                    from agents.dungeon.event.event_rewards_penalties import (
                        parse_expected_outcome_to_choices,
                    )

                    parsed = parse_expected_outcome_to_choices(eo)
                    if parsed:
                        choices = parsed
                        # attach back for downstream processing
                        target_event["choices"] = choices
            if not choices:
                print(
                    f"[WARN] select_event - room {room_id} has no choices. event: {target_event.get('event_code') or target_event.get('event_code', '')}"
                )
                return {
                    "success": True,
                    "outcome": f"No choices available for room {room_id}.",
                    "rewardId": None,
                    "penaltyId": None,
                }
            print(f"[DEBUG] select_event - choices count: {len(choices)}")

            matched_action = ""
            is_unexpected = False
            reward_id: Optional[str] = None
            penalty_id: Optional[str] = None

            # 선택지가 있는 경우 분류 로직 수행
            if choices:
                options_text = ""
                actions = []
                for idx, c in enumerate(choices):
                    act = c.get("action", "")
                    actions.append(act)
                    options_text += f"{idx}. {act}\n"

                import difflib, re

                def _norm(s: str) -> str:
                    return re.sub(r"\s+", " ", (s or "").strip().lower())

                choice_norm = _norm(choice)
                best_idx = None
                best_ratio = 0.0
                for i, act in enumerate(actions):
                    r = difflib.SequenceMatcher(None, choice_norm, _norm(act)).ratio()
                    if r > best_ratio:
                        best_ratio = r
                        best_idx = i

                # Hostile / clearly out-of-scope keywords (Korean only)
                hostile_kw = [
                    "공격",
                    "죽",
                    "찔",
                    "불태",
                    "파괴",
                    "살해",
                    "도둑",
                    "훔치",
                    "팬다",
                    "좆",
                    "썅",
                ]

                contains_hostile = any(kw in choice_norm for kw in hostile_kw)

                if best_ratio >= 0.60 and best_idx is not None:
                    idx = best_idx
                    selected = choices[idx]
                    print(
                        f"[DEBUG] FUZZY_SELECTED idx={idx} ratio={best_ratio}: {selected}"
                    )
                    matched_action = selected.get("action")
                    r = (
                        selected.get("reward_id")
                        or selected.get("rewardId")
                        or selected.get("reward")
                    )
                    reward_id = r
                    p = (
                        selected.get("penalty_id")
                        or selected.get("penaltyId")
                        or selected.get("penalty")
                    )
                    penalty_id = p
                elif best_ratio < 0.35 and contains_hostile:
                    # clearly out-of-scope / hostile: unexpected
                    is_unexpected = True
                else:
                    # use LLM fallback for ambiguous cases
                    classification_prompt = f"""
                    [상황]
                    {scenario_narrative}

                    [가능한 선택지]
                    {options_text}

                    [플레이어 입력]
                    {choice}

                    플레이어의 입력이 위 [가능한 선택지] 중 어느 것과 가장 유사한지 판단해.
                    1. 선택지와 의미가 유사하면 해당 번호(0, 1, 2...)를 반환해.
                    2. 만약 선택지에 없는 돌발 행동이거나, 적대적인 행동, 혹은 전혀 다른 행동이라면 "UNEXPECTED"라고 반환해.

                    오직 숫자 혹은 "UNEXPECTED" 만 출력해.
                    """
                    try:
                        class_response = llm.invoke(
                            [HumanMessage(content=classification_prompt)]
                        )
                        class_result = class_response.content.strip()
                        print(f"[DEBUG] Event Classification Result: {class_result}")

                        if class_result.isdigit():
                            idx = int(class_result)
                            if 0 <= idx < len(choices):
                                selected = choices[idx]
                                print(
                                    f"[DEBUG] SELECTED_CHOICE (idx={idx}): {selected}"
                                )
                                matched_action = selected.get("action")
                                r = (
                                    selected.get("reward_id")
                                    or selected.get("rewardId")
                                    or selected.get("reward")
                                )
                                print(f"[DEBUG] EXTRACTED_REWARD_RAW: {r}")
                                reward_id = r
                                p = (
                                    selected.get("penalty_id")
                                    or selected.get("penaltyId")
                                    or selected.get("penalty")
                                )
                                print(f"[DEBUG] EXTRACTED_PENALTY_RAW: {p}")
                                penalty_id = p
                            else:
                                is_unexpected = True
                        else:
                            is_unexpected = True
                    except Exception as e:
                        print(f"[ERROR] 분류 중 오류 발생: {e}")
                        is_unexpected = True

            # 결과 서술 생성
            if is_unexpected:
                # 돌발 행동에 대한 패널티 및 서술
                penalty_id = "penalty_unexpected_action"  # 기본 패널티 ID 부여
                prompt = f"""
                [상황]
                {scenario_narrative}

                [플레이어 돌발 행동]
                {choice}

                플레이어가 예상치 못한 행동을 했습니다. 
                이 행동은 상황에 맞지 않거나 위험한 행동일 수 있습니다.
                이에 대한 부정적인 결과나 당황스러운 상황을 2~3문장으로 묘사해줘.
                플레이어에게 직접 이야기하듯이 서술해.
                """
            else:
                # 매칭된 행동에 대한 서술
                prompt = f"""
                [상황]
                {scenario_narrative}

                [플레이어 선택]
                {choice} (의도: {matched_action})

                위 상황에서 플레이어가 선택한 행동에 대한 결과를 2~3문장으로 묘사해줘. 
                플레이어에게 직접 이야기하듯이 서술해. (예: "당신은 ~했습니다. 그 결과...")
                """

            response = llm.invoke([HumanMessage(content=prompt)])
            outcome = response.content

            # If reward/penalty ids are missing, attempt to extract tokens from the matched action text
            if (reward_id is None or penalty_id is None) and matched_action:
                try:
                    import re

                    tokens = re.findall(r"(drop_[a-zA-Z0-9_]+)", matched_action)
                    for t in tokens:
                        tl = t.lower()
                        # heuristics: cursed tokens -> penalty, others -> reward
                        if (
                            ("cursed" in tl)
                            or ("curse" in tl)
                            or ("drop_cursed" in tl)
                            or ("pen_" in tl)
                            or ("penalty" in tl)
                        ):
                            if penalty_id is None:
                                penalty_id = t
                        else:
                            if reward_id is None:
                                reward_id = t
                    if tokens:
                        print(
                            f"[DEBUG] select_event - extracted tokens from action: {tokens}, reward_id={reward_id}, penalty_id={penalty_id}"
                        )
                except Exception as e:
                    print(f"[WARN] select_event - token extraction failed: {e}")

            reward_payload = normalize_reward_payload(reward_id)
            penalty_payload = normalize_penalty_payload(penalty_id)

            from agents.dungeon.event.event_rewards_penalties import (
                select_best_reward,
                select_best_penalty,
            )

            if reward_payload is None:
                try:
                    reward_payload = select_best_reward(
                        reward_id, matched_action, scenario_narrative
                    )
                except Exception:
                    reward_payload = None

            if penalty_payload is None:
                try:
                    penalty_payload = select_best_penalty(
                        penalty_id, matched_action, scenario_narrative
                    )
                except Exception:
                    penalty_payload = None

            # Ensure reward/penalty payloads expose full change_stat/item/monster info
            try:
                from agents.dungeon.event.event_rewards_penalties import (
                    get_reward_dict,
                    get_penalty_dict,
                    _to_client_payload,
                )

                def _resolve_payload(p):
                    if p is None:
                        return None
                    # list of payloads (penalties may be list)
                    if isinstance(p, list):
                        out = []
                        for it in p:
                            if isinstance(it, dict) and "id" in it and len(it) == 1:
                                r = get_reward_dict(it["id"]) or get_penalty_dict(
                                    it["id"]
                                )
                                out.append(_to_client_payload(r) if r else it)
                            else:
                                out.append(it)
                        return out
                    # dict with only id -> try to expand
                    if isinstance(p, dict) and "id" in p and len(p) == 1:
                        rid = p["id"]
                        r = get_reward_dict(rid)
                        if r:
                            return _to_client_payload(r)
                        rp = get_penalty_dict(rid)
                        if rp:
                            return _to_client_payload(rp)
                        return p
                    return p

                reward_full = _resolve_payload(reward_payload)
                penalty_full = _resolve_payload(penalty_payload)
            except Exception:
                reward_full = reward_payload
                penalty_full = penalty_payload

            return {
                "success": True,
                "outcome": outcome,
                "rewardId": reward_full,
                "penaltyId": penalty_full,
            }

        except Exception as e:
            print(f"[ERROR] 이벤트 선택 처리 실패: {e}")
            return {
                "success": False,
                "error": str(e),
            }

    # ============================================================
    # 7. 이벤트 생성 및 저장 헬퍼 메서드
    # ============================================================
    def _create_event_for_floor(
        self,
        heroine_data: Dict[str, Any],
        player_id: int = None,
        next_floor: int = 1,
        used_events: List[Any] = None,
        room_id: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        특정 층에 대한 이벤트 생성
        """

        try:
            print(
                f"[DEBUG] _create_event_for_floor: player_id={player_id}, heroine_data={heroine_data}"
            )
            from agents.dungeon.event.dungeon_event_agent import graph_builder
            from agents.dungeon.dungeon_state import DungeonEventState

            # 이벤트 에이전트 실행
            event_state: DungeonEventState = {
                "messages": [],
                "heroine_data": heroine_data,
                "player_id": player_id,
                "heroine_memories": [],
                "event_room": room_id,
                "next_floor": next_floor,
                "used_events": used_events,
                "selected_main_event": "",
                "sub_event": "",
                "final_answer": "",
            }
            print(f"[DEBUG] event_state: {event_state}")
            event_graph = graph_builder.compile()
            event_result = event_graph.invoke(event_state)
            print(f"[DEBUG] _create_event_for_floor - event_result: {event_result}")

            # 전체 이벤트 JSON 구성
            main_event = event_result.get("selected_main_event", {})
            sub_event = event_result.get("sub_event", {})

            # sub_event가 dict가 아닐 수 있음 (문자열일 경우 처리)
            scenario_narrative = ""
            choices = []
            expected_outcome = ""

            if isinstance(sub_event, dict):
                scenario_narrative = sub_event.get("narrative", "")
                choices = sub_event.get("choices", [])
                expected_outcome = sub_event.get("expected_outcome", "")

            if not isinstance(sub_event, dict) or not choices:
                print(
                    f"[WARN] _create_event_for_floor - missing sub_event or empty choices for room {room_id}, main_event={main_event}"
                )
                scenario_narrative = scenario_narrative or main_event.get(
                    "scenario_text", ""
                )

                choices = [
                    {"action": "조용히 관찰한다", "reward": None, "penalty": None},
                    {"action": "상호작용을 시도한다", "reward": None, "penalty": None},
                ]

            event_json = {
                "room_id": room_id,
                "event_type": main_event.get("event_id", 0),
                "event_title": main_event.get("title", ""),
                "event_code": main_event.get("event_code", ""),
                "scenario_text": main_event.get("scenario_text", ""),
                "scenario_narrative": scenario_narrative,
                "choices": choices,
                "expected_outcome": expected_outcome,
                "player_id": player_id,
                "is_personal": main_event.get("is_personal", False),
                "floor": next_floor,
            }

            return event_json

        except Exception as e:
            print(f"[ERROR] 이벤트 생성 실패: {e}")
            import traceback

            traceback.print_exc()
            return None

    def _save_event_to_db(self, dungeon_id: int, event_data: Any) -> bool:
        """
        생성된 이벤트 JSON을 DB의 event 컬럼에 저장
        """
        if event_data is None:
            print(
                f"[WARNING] 이벤트 데이터가 None 입니다.저장을 건너뜁니다. (dungeon_id={dungeon_id}"
            )
            return False
        try:
            # 리스트인지 단일 객체인지 확인하여 JSON 변환
            try:
                self._strip_applied_actions(event_data)
            except Exception:
                pass
            event_json_str = (
                json.dumps(event_data)
                if isinstance(event_data, (dict, list))
                else event_data
            )

            with self.repo.engine.begin() as conn:
                conn.execute(
                    text("UPDATE dungeon SET event = :event WHERE id = :id"),
                    {"event": event_json_str, "id": dungeon_id},
                )

            print(f"[SUCCESS] 이벤트가 던전 {dungeon_id}에 저장되었습니다.")
            return True

        except Exception as e:
            print(f"[ERROR] 이벤트 DB 저장 실패: {e}")
            return False


# ============================================================
# 서비스 초기화 (매 요청마다 인스턴스 생성)
# ============================================================
def get_dungeon_service() -> DungeonService:
    """항상 새로운 DungeonService 인스턴스 반환"""
    return DungeonService()
