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


def test_bin_volratio():
    assert sc.bin_volratio("0.9") == 0
    assert sc.bin_volratio("1.5") == 1
    assert sc.bin_volratio("2.3") == 2


def test_bin_relstr_lower_is_better():
    # 相对强弱越低(越超跌)档位越高
    assert sc.bin_relstr("-6") == 2
    assert sc.bin_relstr("-3") == 1
    assert sc.bin_relstr("-0.5") == 0


def test_feature_values_keys_and_levels():
    row = {"极限抄底": "1", "中枢极限底": "0", "中枢底部回升": "1",
           "量比": "1.5", "相对强弱": "-6"}
    fv = sc.feature_values(row)
    assert fv == {"极限抄底": 1.0, "中枢极限底": 0.0, "中枢底部回升": 1.0,
                  "量比": 1, "相对强弱": 2}


def test_fit_weights_positive_signal():
    # 极限抄底=1 全胜、=0 全负 → 权重应为正且约等于 1.0
    rows = []
    for _ in range(50):
        rows.append({"fv": {"极限抄底": 1.0}, "win": 1})
        rows.append({"fv": {"极限抄底": 0.0}, "win": 0})
    w = sc.fit_weights(rows, ["极限抄底"])
    assert w["极限抄底"] > 0.9


def test_fit_weights_no_signal_zero_weight():
    # 特征恒为0 → 无对照组 → 权重 0
    rows = [{"fv": {"极限抄底": 0.0}, "win": 1} for _ in range(20)]
    w = sc.fit_weights(rows, ["极限抄底"])
    assert w["极限抄底"] == 0.0


def test_score_row_weighted_sum():
    w = {"极限抄底": 0.2, "量比": 0.1}
    fv = {"极限抄底": 1.0, "量比": 2}
    assert abs(sc.score_row(fv, w) - (0.2 * 1.0 + 0.1 * 2)) < 1e-9
