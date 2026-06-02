import star_calibrate as sc


def test_is_trap_dapan_bull():
    # 大盘多头 → 陷阱(精选层失效)
    assert sc.is_trap({"大盘多头": "1", "相对强弱": "-3"}) is True


def test_is_trap_relstr_nonneg():
    # 相对强弱 >= 0 → 陷阱(超跌反弹转强反失效)
    assert sc.is_trap({"大盘多头": "0", "相对强弱": "0.5"}) is True


def test_is_trap_false():
    assert sc.is_trap({"大盘多头": "0", "相对强弱": "-4"}) is False


def test_reconstruct_tier_core():
    # 1买 + 非陷阱 + 量能金叉 → 核心
    row = {"买点类型": "1买", "大盘多头": "0", "相对强弱": "-4", "量能金叉": "1"}
    assert sc.reconstruct_tier(row) == "核心"


def test_reconstruct_tier_refined():
    # 1买 + 非陷阱 + 无量能金叉 → 精选
    row = {"买点类型": "1买", "大盘多头": "0", "相对强弱": "-4", "量能金叉": "0"}
    assert sc.reconstruct_tier(row) == "精选"


def test_reconstruct_tier_none_when_not_first_buy():
    row = {"买点类型": "2买", "大盘多头": "0", "相对强弱": "-4", "量能金叉": "1"}
    assert sc.reconstruct_tier(row) is None


def test_reconstruct_tier_none_when_trap():
    row = {"买点类型": "1买", "大盘多头": "1", "相对强弱": "-4", "量能金叉": "1"}
    assert sc.reconstruct_tier(row) is None


def test__f_edge_cases():
    assert sc._f("") == 0.0
    assert sc._f(None) == 0.0
    assert sc._f("abc") == 0.0
    assert sc._f("3.5") == 3.5
    assert sc._f("", default=-1.0) == -1.0
    # 'nan'/'inf' 是合法浮点字面量，按设计透传(不返回 default)
    import math
    assert math.isnan(sc._f("nan"))
