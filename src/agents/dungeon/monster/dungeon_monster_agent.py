from langchain.chat_models import init_chat_model
from enums.LLM import LLM
from agents.dungeon.dungeon_state import DungeonMonsterState, MonsterStrategyParser
from agents.dungeon.monster.monster_database import MONSTER_DATABASE, MonsterData
from core.game_dto.StatData import StatData
from typing import Dict, List, Any
from prompts.promptmanager import PromptManager
from prompts.prompt_type.dungeon.DungeonPromptType import DungeonPromptType
import random
import math
from agents.dungeon.monster.monster_tags import KEYWORD_MAP, keywords_to_tags

llm = init_chat_model(model=LLM.GPT5_MINI, temperature=0.7)




def calculate_combat_score_node(state: DungeonMonsterState) -> DungeonMonsterState:
    heroine_stat = state.get("heroine_stat")

    if not heroine_stat:
        print("[calculate_combat_score_node] 히로인 스탯 없음, 기본값 100.0 사용")
        return {"combat_score": 100.0}

    # 멀티 플레이어 감지 (List인 경우)
    is_party = isinstance(heroine_stat, list)

    if is_party:
        stats_list = heroine_stat
        if not stats_list:
            return {"combat_score": 100.0}

        # StatData 객체로 변환
        if isinstance(stats_list[0], dict):
            stats_objects = [StatData(**_ensure_stat_dict(stat)) for stat in stats_list]
        else:
            stats_objects = stats_list

        total_score = 0.0
        for stat in stats_objects:
            score = _calculate_single_combat_score(stat)
            total_score += score

        combat_score = total_score / len(stats_objects)
        print(f"[calculate_combat_score_node] 파티 평균 전투력: {combat_score:.2f}")
        print(f"[calculate_combat_score_node] 파티 인원: {len(stats_objects)}명")
    else:
        # 단일 플레이어
        if isinstance(heroine_stat, dict):
            stat = StatData(**_ensure_stat_dict(heroine_stat))
        else:
            stat = heroine_stat

        combat_score = _calculate_single_combat_score(stat)
        print(f"[calculate_combat_score_node] 플레이어 전투력: {combat_score:.2f}")
        print(
            f"[calculate_combat_score_node] HP: {stat.hp}, STR: {stat.strength}, DEX: {stat.dexterity}"
        )

    return {"combat_score": combat_score}


def _calculate_single_combat_score(stat: StatData) -> float:
    """개별 히로인의 전투력을 계산하는 헬퍼 함수"""
    # 기본 가중치
    hp_score = stat.hp * 0.25
    attack_score = (stat.strength + stat.dexterity) * 0.45
    attack_speed_score = stat.attackSpeed * 12.0
    crit_score = stat.critChance * 0.12
    skill_damage_score = stat.skillDamageMultiplier * 6.0

    base = (
        hp_score + attack_score + attack_speed_score + crit_score + skill_damage_score
    )

    bonus = 0.0
    hero_keywords = []
    if hasattr(stat, "keywords") and stat.keywords:
        hero_keywords = list(stat.keywords)
    elif hasattr(stat, "skill_keywords") and stat.skill_keywords:
        hero_keywords = list(stat.skill_keywords)

    hero_keywords_lower = [k.lower() for k in hero_keywords]
    if any("fast" in k or "빠른" in k for k in hero_keywords_lower):
        bonus += attack_speed_score * 0.15
    if any("strong" in k or "한방" in k or "강한" in k for k in hero_keywords_lower):
        bonus += attack_score * 0.15
    if any("many" in k or "타수" in k for k in hero_keywords_lower):
        bonus += skill_damage_score * 0.1

    return base + bonus


def _ensure_stat_dict(stat: dict) -> dict:
    if stat is None:
        stat = {}
    s = dict(stat)
    s.setdefault("strength", 1)
    s.setdefault("dexterity", 1)
    s.setdefault("intelligence", 1)
    s.setdefault("hp", 100)
    s.setdefault("attackSpeed", 1.0)
    s.setdefault("critChance", 0.0)
    s.setdefault("skillDamageMultiplier", 1.0)
    s.setdefault("keywords", [])
    s.setdefault("skill_keywords", [])
    return s


def llm_strategy_node(state: DungeonMonsterState) -> DungeonMonsterState:
    combat_score = state["combat_score"]
    floor = state.get("floor", 1)
    heroine_stat = state.get("heroine_stat")
    dungeon_player_data = state.get("dungeon_player_data", {})

    # 멀티 플레이어 감지
    is_party = isinstance(heroine_stat, list)

    if is_party:
        first_stat = heroine_stat[0] if heroine_stat else None
        if isinstance(first_stat, dict):
            hero = StatData(**_ensure_stat_dict(first_stat))
        elif first_stat is None:
            hero = StatData(**_ensure_stat_dict({}))
        else:
            hero = first_stat
        player_count = len(heroine_stat)
    else:
        # 단일 플레이어
        if isinstance(heroine_stat, dict):
            hero = StatData(**_ensure_stat_dict(heroine_stat))
        elif heroine_stat is None:
            hero = StatData(**_ensure_stat_dict({}))
        else:
            hero = heroine_stat
        player_count = 1

    # 던전 진행 정보
    current_floor = dungeon_player_data.get("scenarioLevel", floor)
    difficulty_level = dungeon_player_data.get("difficulty", 1)
    affection = dungeon_player_data.get("affection", 50)
    sanity = dungeon_player_data.get("sanity", 50)

    # 히로인 요약 정보 생성
    player_type = "파티 평균" if is_party else "플레이어"
    player_info = f" ({player_count}명)" if is_party else ""

    hero_summary = f"""
전투 스탯{player_info}:
- HP: {hero.hp}
- 근력(Strength): {hero.strength}
- 기량(Dexterity): {hero.dexterity}
- 치명타 확률: {hero.critChance:.1f}%
- 공격 속도: {hero.attackSpeed:.2f}x
- 스킬 데미지 배율: {hero.skillDamageMultiplier:.2f}x
- 종합 전투력: {combat_score:.1f} ({player_type})

던전 진행 상황:
- 현재 층: {current_floor}
- 난이도: {difficulty_level}
- 호감도: {affection}
- 정신력: {sanity}
"""

    # DEBUG: hero_summary와 floor 값 및 타입 출력
    print("[llm_strategy_node DEBUG] hero_summary type:", type(hero_summary))
    print("[llm_strategy_node DEBUG] hero_summary value:\n", hero_summary)
    print("[llm_strategy_node DEBUG] floor type:", type(current_floor))
    print("[llm_strategy_node DEBUG] floor value:", current_floor)

    MIN_ROOM_THREAT = 50.0  # 방별 최소 위협도 (적절히 조정)
    try:
        # 프롬프트 생성
        try:
            prompts = PromptManager(DungeonPromptType.MONSTER_STRATEGY).get_prompt(
                hero_summary=hero_summary, floor=current_floor
            )
        except ValueError as ve:
            print("[llm_strategy_node ERROR] PromptManager ValueError:", ve)
            raise
        # hero_summary가 프롬프트에 포함되었는지 확인 (치환 실패만 에러로 출력)
        if isinstance(prompts, str):
            if "hero_summary" in prompts or "{hero_summary}" in prompts:
                print("[llm_strategy_node ERROR] 프롬프트에 hero_summary 치환 실패!")

        # LLM 호출 (Structured Output)
        parser_llm = llm.with_structured_output(MonsterStrategyParser)
        response = parser_llm.invoke(prompts)

        strategy = {
            "difficulty_multiplier": response.difficulty_multiplier,
            "preferred_tags": response.preferred_tags,
            "monster_preferences": response.monster_preferences,
            "avoid_conditions": response.avoid_conditions,
            "reasoning": response.reasoning,
        }

        return {"llm_strategy": strategy}

    except Exception as e:
        print(f"[llm_strategy_node] LLM 오류 발생, 기본 전략 사용: {e}")
        # Fallback 전략
        fallback_strategy = {
            "difficulty_multiplier": 1.0,
            "preferred_tags": [],
            "reasoning": "LLM 응답 실패로 기본값 적용",
        }
        return {"llm_strategy": fallback_strategy}


def select_monsters_node(state: DungeonMonsterState) -> DungeonMonsterState:
    # ===== 1. 입력값 준비 =====
    combat_score = state["combat_score"]
    llm_strategy = state["llm_strategy"]
    monster_db = state.get("monster_db", MONSTER_DATABASE)
    dungeon_data = (
        state.get("dungeon_data")
        or state.get("dungeon_base_data")
        or state.get("filled_dungeon_data")
        or {}
    )

    rooms = (
        dungeon_data.get("rooms") if isinstance(dungeon_data.get("rooms"), list) else []
    )
    for r in rooms:
        if "room_id" not in r and "roomId" in r:
            r["room_id"] = r.get("roomId")
        if "type" not in r and "room_type" in r:
            try:
                r["type"] = int(r.get("room_type"))
            except Exception:
                pass
        if "room_type" not in r and "type" in r:
            r["room_type"] = r.get("type")
        if "monsters" in r and isinstance(r["monsters"], list):
            norm_monsters = []
            for m in r["monsters"]:
                if isinstance(m, dict):
                    if "monsterId" in m and "monster_id" not in m:
                        m["monster_id"] = m.get("monsterId")
                    if "posX" in m and "pos_x" not in m:
                        m["pos_x"] = m.get("posX")
                    if "posY" in m and "pos_y" not in m:
                        m["pos_y"] = m.get("posY")
                norm_monsters.append(m)
            r["monsters"] = norm_monsters

    if rooms:
        dungeon_data["rooms"] = rooms
        
    player_count = 1
    try:
        pc = state.get("player_count")
        if isinstance(pc, int) and pc > 0:
            player_count = pc
        else:
            heroine_stat = state.get("heroine_stat")
            if isinstance(heroine_stat, list) and len(heroine_stat) > 0:
                player_count = len(heroine_stat)
            else:
                # try dungeon_data player_ids
                pdlist = dungeon_data.get("player_ids") or dungeon_data.get("playerIds")
                if isinstance(pdlist, list) and len(pdlist) > 0:
                    player_count = len(pdlist)
                else:
                    player_count = 1
    except Exception:
        player_count = 1

    difficulty_multiplier = llm_strategy["difficulty_multiplier"]
    preferred_tags = llm_strategy.get("preferred_tags", [])

    normal_monsters = [
        m for m in monster_db.values() if getattr(m, "monster_type", 0) == 0
    ]
    boss_monsters = [
        m for m in monster_db.values() if getattr(m, "monster_type", 0) == 2
    ]
    if normal_monsters:
        mean_threat = sum(m.threat_level for m in normal_monsters) / len(
            normal_monsters
        )
        min_normal_threat = min(m.threat_level for m in normal_monsters)
    else:
        mean_threat = min_normal_threat = 1
    if boss_monsters:
        mean_boss_threat = sum(m.threat_level for m in boss_monsters) / len(
            boss_monsters
        )
    else:
        mean_boss_threat = 1

    target_general_threat = combat_score * difficulty_multiplier
    boss_scale = mean_boss_threat / mean_threat if mean_threat > 0 else 1.0
    target_boss_threat = combat_score * difficulty_multiplier * boss_scale

    rooms = dungeon_data.get("rooms", [])
    combat_rooms = [
        room
        for room in rooms
        if (
            room.get("type") == 1
            or room.get("room_type") == 1
            or str(room.get("room_type")).lower() == "monster"
        )
    ]
    boss_rooms = [
        room
        for room in rooms
        if (
            room.get("type") == 4
            or room.get("room_type") == 4
            or str(room.get("room_type")).lower() == "boss"
        )
    ]
    n_combat = len(combat_rooms)
    n_boss = len(boss_rooms)

    dynamic_min_room_threat = min(
        (
            m.threat_level
            for m in monster_db.values()
            if getattr(m, "monster_type", 0) == 0
        ),
        default=1,
    )
    per_room_target = max(
        target_general_threat / n_combat if n_combat else min_normal_threat,
        dynamic_min_room_threat,
    )

    # ===== 3. 일반 몬스터 배치 =====
    # compute average room size to use as fallback when a room has no size
    sizes = [r.get("size") for r in rooms if isinstance(r.get("size"), (int, float))]
    avg_size = int(round(sum(sizes) / len(sizes))) if sizes else 4

    for room in combat_rooms:
        room["monsters"] = []
        room_threat = per_room_target

        # compute room capacity from size and player count: ceil(size * 0.5 * player_count)
        room_size = (
            room.get("size") if isinstance(room.get("size"), (int, float)) else avg_size
        )
        max_monsters = max(1, math.ceil(room_size * 0.5 * player_count))
        print(
            f"[select_monsters_node DEBUG] room_id={room.get('room_id')} room_size={room_size} player_count={player_count} max_monsters={max_monsters}"
        )

        # 최소 위협도보다 작으면 동적 스케일링 또는 최소값 보장
        if room_threat < min_normal_threat:
            scale = room_threat / min_normal_threat
            weakest = min(
                [m for m in monster_db.values() if getattr(m, "monster_type", 0) == 0],
                key=lambda m: m.threat_level,
            )
            room["monsters"].append(
                {"monster_id": weakest.monster_id, "scale": round(scale, 2)}
            )
            room["final_threat"] = weakest.threat_level * scale
            print(
                f"[select_monsters_node DEBUG] room_id={room.get('room_id')} placed=1/{max_monsters} final_threat={room.get('final_threat')}"
            )
        else:
            # 목표 위협도에 맞게 몬스터 여러 마리 배치 (greedy), 단 방당 최대 수 준수
            threat_sum = 0
            attempts = 0
            normal_pool = [
                m for m in monster_db.values() if getattr(m, "monster_type", 0) == 0
            ]
            while (
                threat_sum < room_threat
                and len(room["monsters"]) < max_monsters
                and attempts < 100
            ):
                remaining = room_threat - threat_sum

                # 우선: remaining 이하인 후보 중 작은 몬스터 위주로 가중 랜덤 선택
                cands = [m for m in normal_pool if m.threat_level <= remaining]
                if cands:
                    try:
                        max_t = max(m.threat_level for m in cands)
                        weights = [(max_t - m.threat_level) + 0.1 for m in cands]
                        candidate = random.choices(cands, weights=weights, k=1)[0]
                    except Exception:
                        candidate = min(cands, key=lambda m: m.threat_level)
                else:
                    # 없으면 남은 범위에 가장 근접한 몬스터(위협도 차이가 가장 작은) 선택
                    candidate = min(
                        normal_pool, key=lambda m: abs(m.threat_level - remaining)
                    )

                room["monsters"].append(
                    {"monster_id": candidate.monster_id, "scale": 1.0}
                )
                threat_sum += candidate.threat_level
                attempts += 1

            # 보장: 최소 1마리 이상 배치 (가능한 경우)
            if len(room["monsters"]) == 0 and normal_pool:
                weakest = min(normal_pool, key=lambda m: m.threat_level)
                room["monsters"].append(
                    {"monster_id": weakest.monster_id, "scale": 1.0}
                )
                threat_sum += weakest.threat_level

            room["final_threat"] = threat_sum
            print(
                f"[select_monsters_node DEBUG] room_id={room.get('room_id')} placed={len(room['monsters'])}/{max_monsters} final_threat={room.get('final_threat')}"
            )

    # ===== 4. 보스 몬스터 배치 (별도) =====
    for room in boss_rooms:
        room["monsters"] = []
        # 가장 가까운 보스 몬스터 선택
        boss_candidates = [
            m for m in monster_db.values() if getattr(m, "monster_type", 0) == 2
        ]
        if boss_candidates:
            boss = min(
                boss_candidates, key=lambda m: abs(m.threat_level - target_boss_threat)
            )
            room["monsters"].append({"monster_id": boss.monster_id, "scale": 1.0})
            room["final_threat"] = boss.threat_level
            print(
                f"[select_monsters_node DEBUG] boss_room_id={room.get('room_id')} selected_boss={boss.monster_id} player_count={player_count} final_threat={room.get('final_threat')}"
            )

    # ===== 5. 결과 요약 =====
    total_general_actual = sum(room.get("final_threat", 0) for room in combat_rooms)
    total_boss_actual = sum(room.get("final_threat", 0) for room in boss_rooms)

    # 배치된 몬스터 수 집계
    normal_monster_count = sum(len(room.get("monsters", [])) for room in combat_rooms)
    boss_count = sum(1 for room in boss_rooms if room.get("monsters"))
    has_boss_room = True if len(boss_rooms) > 0 else False

    # ===== 6. 결과 반환 =====
    return {
        "filled_dungeon_data": dungeon_data,
        "difficulty_log": {
            "combat_score": combat_score,
            "difficulty_multiplier": difficulty_multiplier,
            "target_general_threat": target_general_threat,
            "target_boss_threat": target_boss_threat,
            "total_general_actual": total_general_actual,
            "total_boss_actual": total_boss_actual,
            "per_room_target": per_room_target,
            "min_normal_threat": min_normal_threat,
            "n_combat": n_combat,
            "n_boss": n_boss,
            "has_boss_room": has_boss_room,
            "normal_monster_count": normal_monster_count,
            "boss_count": boss_count,
        },
    }


def _select_monsters_by_strategy(
    monster_db: Dict[int, MonsterData],
    target_threat: float,
    preferred_tags: List[str],
    monster_preferences: List[Dict[str, Any]] = None,
    avoid_conditions: List[str] = None,
    hero_tags: List[str] = None,
) -> List[MonsterData]:
    # 일반 몬스터만 사용 (보스는 별도 처리)
    all_normal_monsters = [m for m in monster_db.values() if m.monster_type == 0]

    if not all_normal_monsters:
        print("[_select_monsters_by_strategy] 사용 가능한 일반 몬스터가 없습니다")
        return []

    # 선호도와 회피 조건으로 몬스터 필터링
    filtered_monsters = _filter_monsters_by_preferences(
        all_normal_monsters, monster_preferences, avoid_conditions
    )

    if not filtered_monsters:
        print("[_select_monsters_by_strategy] 조건에 맞는 몬스터가 없어 전체 풀 사용")
        filtered_monsters = all_normal_monsters

    selected = []
    current_threat = 0.0

    # 타겟 위협도의 90~110% 범위 내로 조정
    min_threat = target_threat * 0.9
    max_threat = target_threat * 1.1

    max_attempts = 100
    attempts = 0

    print(
        f"[_select_monsters_by_strategy] 타겟: {target_threat:.2f}, 필터된 몬스터 수: {len(filtered_monsters)}"
    )

    try:
        print(
            "[_select_monsters_by_strategy] 후보 몬스터 목록 (id, name, threat, hp, attack, speed):"
        )
        for m in filtered_monsters:
            try:
                print(
                    f"  - {m.monster_id}, {m.monster_name}, threat={m.threat_level:.2f}, hp={m.hp}, atk={m.attack}, spd={m.speed}"
                )
            except Exception:
                print(f"  - {getattr(m,'monster_id', '?')} (failed to print details)")
    except Exception:
        pass

    while current_threat < min_threat and attempts < max_attempts:
        # 가중치 기반 몬스터 선택 (히로인 키워드 반영)
        monster = _select_weighted_monster(
            filtered_monsters, monster_preferences or [], hero_tags or []
        )

        # 추가했을 때 max_threat를 너무 초과하지 않는지 확인
        if current_threat + monster.threat_level <= max_threat * 1.2:
            selected.append(monster)
            current_threat += monster.threat_level

        attempts += 1

    if not selected:
        sorted_monsters = sorted(filtered_monsters, key=lambda m: m.threat_level)
        for m in sorted_monsters:
            if current_threat >= min_threat:
                break
            selected.append(m)
            current_threat += m.threat_level

        try:
            print(
                "[_select_monsters_by_strategy] Fallback 적용: 작은 위협도 몬스터로 채움"
            )
            for m in selected:
                print(
                    f"  -> {m.monster_id} {m.monster_name} threat={m.threat_level:.2f}"
                )
        except Exception:
            pass

    return selected


def _filter_monsters_by_preferences(
    monsters: List[MonsterData],
    preferences: List[Dict[str, Any]],
    avoid_conditions: List[str],
) -> List[MonsterData]:
    """선호도와 회피 조건으로 몬스터 필터링"""
    if not preferences and not avoid_conditions:
        return monsters

    filtered = []

    for monster in monsters:
        # 회피 조건 체크
        if avoid_conditions and _should_avoid_monster(monster, avoid_conditions):
            continue

        # 선호도 조건 체크
        if preferences:
            if _matches_any_preference(monster, preferences):
                filtered.append(monster)
        else:
            filtered.append(monster)

    return filtered if filtered else monsters


def _should_avoid_monster(monster: MonsterData, avoid_conditions: List[str]) -> bool:
    """몬스터가 회피 조건에 해당하는지 확인"""
    for condition in avoid_conditions:
        condition_lower = condition.lower()

        if "slow" in condition_lower and monster.speed < 250:
            return True
        if "fast" in condition_lower and monster.speed > 400:
            return True
        if "weak" in condition_lower and monster.attack < 12:
            return True
        if "highattack" in condition_lower and monster.attack > 20:
            return True
        if "lowhp" in condition_lower and monster.hp < 200:
            return True

    return False


def _matches_any_preference(
    monster: MonsterData, preferences: List[Dict[str, Any]]
) -> bool:
    """몬스터가 하나 이상의 선호도 조건에 맞는지 확인"""
    for pref in preferences:
        if _matches_preference(monster, pref):
            return True
    return False


def _matches_preference(monster: MonsterData, preference: Dict[str, Any]) -> bool:
    """몬스터가 특정 선호도 조건에 맞는지 확인"""
    # 몬스터 타입 체크
    if "monster_type" in preference and preference["monster_type"] is not None:
        if monster.monster_name.lower() != preference["monster_type"].lower():
            return False

    # HP 범위 체크
    if "min_hp" in preference and preference["min_hp"] is not None:
        if monster.hp < preference["min_hp"]:
            return False
    if "max_hp" in preference and preference["max_hp"] is not None:
        if monster.hp > preference["max_hp"]:
            return False

    # 공격력 범위 체크
    if "min_attack" in preference and preference["min_attack"] is not None:
        if monster.attack < preference["min_attack"]:
            return False
    if "max_attack" in preference and preference["max_attack"] is not None:
        if monster.attack > preference["max_attack"]:
            return False

    # 이동속도 범위 체크
    if "min_speed" in preference and preference["min_speed"] is not None:
        if monster.speed < preference["min_speed"]:
            return False
    if "max_speed" in preference and preference["max_speed"] is not None:
        if monster.speed > preference["max_speed"]:
            return False

    return True


def _select_weighted_monster(
    monsters: List[MonsterData], preferences: List[Dict[str, Any]], hero_tags: List[str]
) -> MonsterData:
    """가중치를 고려하여 몬스터 선택"""
    if not preferences:
        # 히로인 태그가 있으면 약점이 있는 몬스터 우선
        if hero_tags:
            candidates = []
            for m in monsters:
                m_tags = (
                    keywords_to_tags(m.weaknesses)
                    if getattr(m, "weaknesses", None)
                    else []
                )
                if any(ht.lower() in [t.lower() for t in m_tags] for ht in hero_tags):
                    candidates.append(m)
            if candidates:
                return random.choice(candidates)
        return random.choice(monsters)

    # 각 몬스터의 가중치 계산
    weights = []
    for monster in monsters:
        weight = 0.0
        for pref in preferences:
            if _matches_preference(monster, pref):
                weight += pref.get("weight", 1.0)

        # 히로인 태그와 몬스터 약점/강점으로 가중치 보정
        try:
            monster_weak_tags = (
                keywords_to_tags(monster.weaknesses)
                if getattr(monster, "weaknesses", None)
                else []
            )
            monster_strong_tags = (
                keywords_to_tags(monster.strengths)
                if getattr(monster, "strengths", None)
                else []
            )
        except Exception:
            monster_weak_tags = []
            monster_strong_tags = []

        if hero_tags:
            # 약점과 일치하면 가중치 상승
            if any(
                ht.lower() in [t.lower() for t in monster_weak_tags] for ht in hero_tags
            ):
                weight *= 1.6 if weight > 0 else 1.6
            # 강점과 일치하면 가중치 감소
            if any(
                ht.lower() in [t.lower() for t in monster_strong_tags]
                for ht in hero_tags
            ):
                weight *= 0.6

        weights.append(weight if weight > 0 else 0.1)  # 최소 가중치

    # 가중치 기반 랜덤 선택
    return random.choices(monsters, weights=weights, k=1)[0]


def _place_monsters_in_rooms(
    dungeon_data: Dict,
    normal_monsters: List[MonsterData],
    combat_rooms: List[Dict],
    boss_rooms: List[Dict],
    monster_db: Dict[int, MonsterData],
) -> Dict:
    """
    몬스터를 전투방과 보스방에 배치

    - 전투방(room_type == "monster"): 일반 몬스터 1~3마리 배치
    - 보스방(room_type == "boss"): 보스 몬스터 1마리 배치
    """
    import copy

    filled_dungeon = copy.deepcopy(dungeon_data)

    # filled_dungeon의 rooms에서 room_id로 매칭하여 직접 수정
    rooms_by_id = {room["room_id"]: room for room in filled_dungeon["rooms"]}

    # (no local avg_size/player_count fallback — use values from surrounding scope or callers)

    # 보스방에 보스 몬스터 배치 (최우선)
    if boss_rooms:
        boss_monsters = [m for m in monster_db.values() if m.monster_type == 2]

        if not boss_monsters:
            print("[_place_monsters_in_rooms] 경고: 보스 몬스터가 DB에 없습니다")
        else:
            for boss_room_ref in boss_rooms:
                # 보스 몬스터 선택 (여러 개 있으면 랜덤)
                boss = random.choice(boss_monsters)

                # filled_dungeon의 실제 room에 배치 (monster_id만 저장)
                room_id = boss_room_ref.get("room_id")
                if room_id in rooms_by_id:
                    rooms_by_id[room_id]["monsters"] = [boss.monster_id]
                    print(f"[보스방] 방 {room_id}: 몬스터 ID {boss.monster_id} 배치")
    else:
        print("[_place_monsters_in_rooms] 경고: 보스방이 없습니다")

    # 전투방에 일반 몬스터 배치
    if not combat_rooms:
        # Fallback: detect rooms by numeric 'type' == 1 or 'roomType' == 1
        fallback_combat = [
            r
            for r in filled_dungeon.get("rooms", [])
            if r.get("type") == 1 or r.get("roomType") == 1
        ]
        if fallback_combat:
            combat_rooms = fallback_combat
            print(
                "[_place_monsters_in_rooms] 전투방이 탐지되지 않아 'type==1' 룸들을 전투방으로 처리합니다",
                [r.get("room_id") for r in combat_rooms],
            )
        else:
            print("[_place_monsters_in_rooms] 전투방이 없습니다")
            return filled_dungeon

    if not normal_monsters:
        print("[_place_monsters_in_rooms] 배치할 일반 몬스터가 없습니다")
        return filled_dungeon

    # 몬스터를 각 전투방에 분배
    monster_index = 0

    for combat_room_ref in combat_rooms:
        if monster_index >= len(normal_monsters):
            break

        # 방당 몬스터 수는 room.size와 player_count 기반으로 계산
        room_ref = combat_room_ref
        room_size = (
            room_ref.get("size")
            if isinstance(room_ref.get("size"), (int, float))
            else avg_size
        )
        players = dungeon_data.get("player_ids") or dungeon_data.get("playerIds") or []
        pcount = (
            len(players)
            if isinstance(players, (list, tuple)) and len(players) > 0
            else player_count
        )
        monsters_per_room = min(
            max(1, math.ceil(room_size * 0.5 * pcount)),
            len(normal_monsters) - monster_index,
        )
        room_monsters = []

        for _ in range(monsters_per_room):
            if monster_index >= len(normal_monsters):
                break

            monster = normal_monsters[monster_index]
            monster_index += 1

            # monster_id만 저장
            room_monsters.append(monster.monster_id)

        # filled_dungeon의 실제 room에 배치
        room_id = combat_room_ref.get("room_id")
        if room_id in rooms_by_id:
            rooms_by_id[room_id]["monsters"] = room_monsters
            print(f"[전투방] 방 {room_id}: {len(room_monsters)}마리 배치")

    return filled_dungeon


# ===== LangGraph 구성 =====
from langgraph.graph import START, END, StateGraph

graph_builder = StateGraph(DungeonMonsterState)

# 노드 추가
graph_builder.add_node("calculate_combat_score_node", calculate_combat_score_node)
graph_builder.add_node("llm_strategy_node", llm_strategy_node)
graph_builder.add_node("select_monsters_node", select_monsters_node)

# 엣지 연결
graph_builder.add_edge(START, "calculate_combat_score_node")
graph_builder.add_edge("calculate_combat_score_node", "llm_strategy_node")
graph_builder.add_edge("llm_strategy_node", "select_monsters_node")
graph_builder.add_edge("select_monsters_node", END)

# 그래프 컴파일
monster_graph = graph_builder.compile()
