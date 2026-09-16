from core import assets


def test_char_avatar_url():
    assert (
        assets.char_avatar("char_002_amiya")
        == "https://torappu.prts.wiki/assets/char_avatar/char_002_amiya.png"
    )


def test_char_portrait_defaults_to_elite_two():
    assert (
        assets.char_portrait("char_002_amiya")
        == "https://torappu.prts.wiki/assets/char_portrait/char_002_amiya_2.png"
    )
    assert assets.char_portrait("char_002_amiya", 1).endswith(
        "/char_portrait/char_002_amiya_1.png"
    )


def test_skill_icon_url():
    assert (
        assets.skill_icon("skchr_amiya_3")
        == "https://torappu.prts.wiki/assets/skill_icon/skill_icon_skchr_amiya_3.png"
    )
