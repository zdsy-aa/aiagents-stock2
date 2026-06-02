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


def test_assign_bucket_by_cuts():
    # cuts=[10,20] → score<10:档0, 10<=score<20:档1, >=20:档2
    assert sc.assign_bucket(5, [10, 20]) == 0
    assert sc.assign_bucket(10, [10, 20]) == 1
    assert sc.assign_bucket(25, [10, 20]) == 2


def test_fit_buckets_clean_5_monotone():
    # 构造分数与胜率严格单调的数据 → 应分满 5 档
    scored = []
    for star in range(5):              # star 0..4 → 胜率 0.2..0.6
        wr = 0.2 + 0.1 * star
        for j in range(300):
            win = 1 if j < int(300 * wr) else 0
            scored.append((float(star), win, 0))
    scored.sort(key=lambda x: x[0])
    n, cuts, stats = sc.fit_buckets(scored, max_stars=5, min_n=200)
    assert n == 5
    wins = [s["train_win"] for s in stats]
    assert all(wins[i] <= wins[i + 1] + 1e-9 for i in range(4))


def test_fit_buckets_honest_downgrade_on_small_sample():
    # 仅 300 样本、min_n=200 → 最多 1 档(2 档需 400)
    scored = [(float(i), i % 2, 0) for i in range(300)]
    scored.sort(key=lambda x: x[0])
    n, cuts, stats = sc.fit_buckets(scored, max_stars=5, min_n=200)
    assert n == 1
    assert cuts == []


def test_fit_buckets_downgrade_when_not_monotone():
    # 5 档会非单调，但合并到 2 档单调 → 应降到能单调的最大档数(<5)
    scored = []
    pattern = [0.5, 0.1, 0.5, 0.1, 0.6]   # 5 等频段胜率(非单调)
    for seg, wr in enumerate(pattern):
        for j in range(300):
            scored.append((float(seg), 1 if j < int(300 * wr) else 0, 0))
    scored.sort(key=lambda x: x[0])
    n, cuts, stats = sc.fit_buckets(scored, max_stars=5, min_n=200)
    assert n < 5
    wins = [s["train_win"] for s in stats]
    assert all(wins[i] <= wins[i + 1] + 1e-9 for i in range(len(wins) - 1))


def test_eval_buckets_oos_winrate_and_bigrise():
    # 2 档：低分档 win=0、大涨=0；高分档 win=1、大涨=1
    oos = [(0.0, 0, 0)] * 100 + [(5.0, 1, 1)] * 100
    cuts = [2.5]
    out = sc.eval_buckets(oos, cuts)
    assert out[0]["star"] == 1 and out[0]["n"] == 100
    assert abs(out[0]["oos_win"] - 0.0) < 1e-9
    assert out[1]["star"] == 2 and abs(out[1]["oos_win"] - 1.0) < 1e-9
    assert abs(out[1]["oos_bigrise"] - 1.0) < 1e-9


def test_eval_buckets_empty_bucket_none():
    oos = [(0.0, 0, 0)] * 50    # 全落最低档，高档为空
    out = sc.eval_buckets(oos, [2.5])
    assert out[1]["n"] == 0 and out[1]["oos_win"] is None


def test_parse_signal_row():
    raw = {"买点类型": "1买", "信号日期": "2024-03-01", "区间涨跌幅": "7.5",
           "极限抄底": "1", "中枢极限底": "0", "中枢底部回升": "0",
           "量比": "1.5", "相对强弱": "-6", "量能金叉": "1", "大盘多头": "0"}
    p = sc.parse_signal_row(raw)
    assert p["tier"] == "核心"
    assert p["win"] == 1          # 7.5 >= 4
    assert p["bigwin"] == 0       # 7.5 < 10
    assert p["date"] == "2024-03-01"


def test_split_train_oos():
    rows = [{"date": "2022-05-01"}, {"date": "2024-06-01"},
            {"date": "2025-12-01"}, {"date": "2026-01-01"}]
    train, oos = sc.split_train_oos(rows)
    assert [r["date"] for r in train] == ["2022-05-01"]
    assert [r["date"] for r in oos] == ["2024-06-01"]   # 2025-12/2026 在 OOS 窗外被排除


def test_collapse_cuts():
    cuts = [0.1, 0.2, 0.3, 0.4]   # 5 分位(4 切点)
    # 降为 2 档 → 只保留最高 1 个切点(顶分位 vs 其余)
    assert sc.collapse_cuts(cuts, 2) == [0.4]
    # 降为 3 档 → 保留最高 2 个切点
    assert sc.collapse_cuts(cuts, 3) == [0.3, 0.4]
    # target>=档数 → 全保留(不降)
    assert sc.collapse_cuts(cuts, 5) == [0.1, 0.2, 0.3, 0.4]
    # 1 档 → 无切点
    assert sc.collapse_cuts(cuts, 1) == []
    # 空切点(已是1档) → 仍空
    assert sc.collapse_cuts([], 2) == []


def _fake_thresholds():
    # 核心5档(cuts 4个)、精选2档(cut 1个)的简化阈值，权重让"极限抄底"主导分数
    return {"tiers": {
        "核心": {"n_stars": 5, "weights": {"极限抄底": 1.0, "量比": 0.1},
                 "cuts": [0.05, 0.15, 0.5, 0.9],
                 "stars": [{"star": i + 1, "oos_win": 0.6 + 0.05 * i,
                            "oos_bigrise": 0.4 + 0.05 * i} for i in range(5)]},
        "精选": {"n_stars": 2, "weights": {"极限抄底": 1.0},
                 "cuts": [0.5],
                 "stars": [{"star": 1, "oos_win": 0.73, "oos_bigrise": 0.6},
                           {"star": 2, "oos_win": 0.81, "oos_bigrise": 0.71}]}}}


def test_assign_star_core_high_and_low():
    th = _fake_thresholds()
    # 极限抄底=1,量比≥2(档2) → 分=1.0+0.1*2=1.2 ≥0.9 → 顶档 5★
    hi = {"极限抄底": "1", "中枢极限底": "0", "中枢底部回升": "0", "量比": "2.5", "相对强弱": "-1"}
    star, ew, br, n = sc.assign_star("核心", hi, th)
    assert star == 5 and n == 5 and abs(ew - 0.8) < 1e-9
    # 全0特征 → 分=0 <0.05 → 1★
    lo = {"极限抄底": "0", "中枢极限底": "0", "中枢底部回升": "0", "量比": "0.5", "相对强弱": "-1"}
    star2, ew2, _, _ = sc.assign_star("核心", lo, th)
    assert star2 == 1 and abs(ew2 - 0.6) < 1e-9


def test_assign_star_refined_two_bands():
    th = _fake_thresholds()
    # 精选: 极限抄底=1 → 分=1.0 ≥0.5 → ★★(顶档)
    top = {"极限抄底": "1", "中枢极限底": "0", "中枢底部回升": "0", "量比": "0.5", "相对强弱": "-1"}
    star, ew, br, n = sc.assign_star("精选", top, th)
    assert star == 2 and n == 2 and abs(ew - 0.81) < 1e-9
    # 极限抄底=0 → 分=0 <0.5 → ★(基础档)
    base = {"极限抄底": "0", "中枢极限底": "0", "中枢底部回升": "0", "量比": "0.5", "相对强弱": "-1"}
    star2, ew2, _, _ = sc.assign_star("精选", base, th)
    assert star2 == 1 and abs(ew2 - 0.73) < 1e-9
