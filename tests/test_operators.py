from core.operators import PROFESSION_CN, find_operator, group_operators


def test_profession_cn_covers_all_eight_professions():
    assert PROFESSION_CN["CASTER"] == "术师"
    assert len(PROFESSION_CN) == 8


def test_group_operators_groups_and_sorts():
    chars = [
        {"charId": "a", "level": 1, "evolvePhase": 0, "potentialRank": 0},
        {"charId": "b", "level": 1, "evolvePhase": 0, "potentialRank": 0},
        {"charId": "c", "level": 1, "evolvePhase": 0, "potentialRank": 0},
    ]
    info = {
        "a": {"name": "低星术师", "rarity": 0, "profession": "CASTER"},
        "b": {"name": "高星术师", "rarity": 5, "profession": "CASTER"},
        "c": {"name": "医疗", "rarity": 3, "profession": "MEDIC"},
    }
    groups = group_operators(chars, info)
    assert groups[0]["profession_cn"] == "术师"
    assert [o["name"] for o in groups[0]["operators"]] == ["高星术师", "低星术师"]
    # rarity from charInfoMap is zero-based, display stars = rarity + 1
    assert groups[0]["operators"][0]["stars"] == 6
    assert groups[1]["profession_cn"] == "医疗"


def test_group_operators_skips_unknown():
    chars = [{"charId": "x", "level": 1, "evolvePhase": 0, "potentialRank": 0}]
    assert group_operators(chars, {}) == []


def test_group_operators_orders_professions_by_fixed_order():
    chars = [
        {"charId": "m", "level": 1, "evolvePhase": 0, "potentialRank": 0},
        {"charId": "p", "level": 1, "evolvePhase": 0, "potentialRank": 0},
    ]
    info = {
        "m": {"name": "医疗", "rarity": 3, "profession": "MEDIC"},
        "p": {"name": "先锋", "rarity": 3, "profession": "PIONEER"},
    }
    groups = group_operators(chars, info)
    assert [g["profession_cn"] for g in groups] == ["先锋", "医疗"]


def test_group_operators_includes_elite_and_level():
    chars = [{"charId": "a", "level": 90, "evolvePhase": 2, "potentialRank": 3}]
    info = {"a": {"name": "阿米娅", "rarity": 4, "profession": "CASTER"}}
    op = group_operators(chars, info)[0]["operators"][0]
    assert op["level"] == 90
    assert op["elite"] == 2
    assert op["potential"] == 3
    assert op["stars"] == 5
    assert op["avatar"].endswith("/char_avatar/a.png")


def test_find_operator_by_exact_name():
    chars = [{"charId": "c1", "level": 90, "evolvePhase": 2, "skills": [], "equip": []}]
    info = {"c1": {"name": "阿米娅", "rarity": 4, "profession": "CASTER"}}
    assert find_operator(chars, info, "阿米娅")["char_id"] == "c1"


def test_find_operator_is_case_insensitive_for_latin_names():
    chars = [{"charId": "c1", "level": 1, "evolvePhase": 0, "skills": [], "equip": []}]
    info = {"c1": {"name": "Amiya", "rarity": 4, "profession": "CASTER"}}
    assert find_operator(chars, info, "amiya") is not None


def test_find_operator_missing_returns_none():
    assert find_operator([], {}, "不存在") is None
    assert find_operator([], {}, "") is None


def test_find_operator_prefers_exact_over_substring():
    chars = [
        {"charId": "a", "level": 1, "evolvePhase": 0, "skills": [], "equip": []},
        {"charId": "b", "level": 1, "evolvePhase": 0, "skills": [], "equip": []},
    ]
    info = {
        "a": {"name": "阿米娅", "rarity": 4, "profession": "CASTER"},
        "b": {"name": "阿米娅·炎熔", "rarity": 5, "profession": "CASTER"},
    }
    assert find_operator(chars, info, "阿米娅")["char_id"] == "a"
    # a substring query still resolves
    assert find_operator(chars, info, "炎熔")["char_id"] == "b"


def test_find_operator_carries_skills_and_equip():
    chars = [
        {
            "charId": "c1",
            "level": 90,
            "evolvePhase": 2,
            "potentialRank": 5,
            "favorPercent": 200,
            "skills": [{"id": "skchr_amiya_3", "specializeLevel": 3}],
            "equip": [{"id": "uniequip_002_amiya", "level": 1}],
            "defaultSkillId": "skchr_amiya_3",
        }
    ]
    info = {"c1": {"name": "阿米娅", "rarity": 4, "profession": "CASTER"}}
    op = find_operator(chars, info, "阿米娅")
    assert op["favor"] == 200
    assert op["skills"][0]["specializeLevel"] == 3
    assert op["equip"][0]["id"] == "uniequip_002_amiya"
    assert op["default_skill_id"] == "skchr_amiya_3"


def test_build_roster_context_counts_owned_and_total():
    from core.operators import build_roster_context

    chars = [
        {"charId": "a", "level": 1, "evolvePhase": 0, "potentialRank": 0},
        {"charId": "b", "level": 1, "evolvePhase": 0, "potentialRank": 0},
    ]
    info = {
        "a": {"name": "A", "rarity": 3, "profession": "MEDIC"},
        "b": {"name": "B", "rarity": 5, "profession": "MEDIC"},
        "c": {"name": "C", "rarity": 5, "profession": "MEDIC"},
    }
    ctx = build_roster_context(group_operators(chars, info), info)
    assert ctx["owned"] == 2
    assert ctx["total"] == 3


def test_build_operator_context_resolves_skills_and_modules():
    from core.operators import build_operator_context

    operator = {
        "char_id": "c1",
        "name": "阿米娅",
        "profession_cn": "术师",
        "stars": 5,
        "level": 90,
        "elite": 2,
        "potential": 5,
        "favor": 200,
        "avatar": "avatar-url",
        "default_skill_id": "skchr_amiya_3",
        "skills": [
            {"id": "skchr_amiya_2", "specializeLevel": 0},
            {"id": "skchr_amiya_3", "specializeLevel": 3},
        ],
        "equip": [{"id": "uniequip_002_amiya", "level": 1}],
    }
    ctx = build_operator_context(operator, {"uniequip_002_amiya": {"name": "术师证章"}})
    assert ctx["favor_percent"] == 100
    assert ctx["skills"][1]["is_default"] is True
    assert ctx["skills"][1]["specialize"] == 3
    assert ctx["skills"][1]["icon"].endswith("/skill_icon/skill_icon_skchr_amiya_3.png")
    assert ctx["equips"][0]["name"] == "术师证章"
    assert ctx["portrait"].endswith("/char_portrait/c1_2.png")


def test_build_operator_context_falls_back_to_raw_module_id():
    from core.operators import build_operator_context

    operator = {
        "char_id": "c1",
        "name": "X",
        "skills": [],
        "equip": [{"id": "uniequip_999_x", "level": 3}],
        "default_skill_id": "",
    }
    ctx = build_operator_context(operator, None)
    assert ctx["equips"][0]["name"] == "uniequip_999_x"
    assert ctx["skills"] == []
