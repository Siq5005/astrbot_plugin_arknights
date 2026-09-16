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


def test_secretary_portrait_defaults_to_elite_one():
    from core.assets import secretary_portrait

    skin = "char_1012_skadi2#2"
    # the default is uniform elite one, regardless of the outfit worn
    assert secretary_portrait("char_1012_skadi2", skin).endswith(
        "/char_portrait/char_1012_skadi2_1.png"
    )
    assert secretary_portrait("char_1012_skadi2", skin, "elite1").endswith("_1.png")
    assert secretary_portrait("char_1012_skadi2", skin, "elite2").endswith("_2.png")
    # the skin mode follows the worn outfit
    assert secretary_portrait("char_1012_skadi2", skin, "skin").endswith("_2.png")
    assert secretary_portrait(
        "char_1012_skadi2", "char_1012_skadi2#1", "skin"
    ).endswith("_1.png")


def test_secretary_portrait_random_pool_is_limited_to_real_artwork():
    import random

    from core.assets import secretary_portrait

    seen = {
        secretary_portrait(
            "char_1012_skadi2", "char_1012_skadi2#2", "random", random.Random(i)
        )
        for i in range(30)
    }
    assert seen
    assert all(url.endswith(("_1.png", "_2.png")) for url in seen)
    assert len(seen) == 2  # both promotion portraits appear

    # a named outfit joins the pool
    with_skin = {
        secretary_portrait(
            "char_002_amiya", "char_002_amiya@winter#1", "random", random.Random(i)
        )
        for i in range(40)
    }
    assert any("skin/" in url for url in with_skin)
    assert any("char_portrait" in url for url in with_skin)


def test_secretary_portrait_handles_missing_operator():
    from core.assets import secretary_portrait

    assert secretary_portrait("", "x") == ""
    assert secretary_portrait("char_002_amiya", "").endswith("char_002_amiya_1.png")
