KEYWORD_MAP = {
    0: "high_defense",
    1: "low_defense",
    2: "fast_movement",
    3: "slow_movement",
    4: "fast_attack_speed",
    5: "slow_attack_speed",
    6: "strong_one_shot",
    7: "many_hits",
    8: "high_stagger",
    9: "low_stagger",
    10: "knockback",
    11: "knockdown",
    12: "impact",
    13: "piercing",
    14: "high_defense",
    15: "low_defense",
    16: "high_hp",
    17: "low_hp",
    18: "ranged",
    19: "melee",
}


def keywords_to_tags(keyword_ids):
    if not keyword_ids:
        return []
    return [KEYWORD_MAP.get(k, f"unknown_{k}") for k in keyword_ids]
