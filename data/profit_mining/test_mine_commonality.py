# test_mine_commonality.py —— 计数与聚合测试
import numpy as np
import mine_commonality as M


def test_count_for_signal():
    # 8根，信号在 idx 3,7 触发；窗口[[1,2,3],[5,6]]
    sig = [False, False, False, True, False, False, False, True]
    windows = [[1, 2, 3], [5, 6]]
    seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all = \
        M.count_for_signal(sig, windows)
    assert seg_total == 2
    assert seg_hit == 1                 # 仅窗口1命中(idx3)
    assert bars_pos == 5                # {1,2,3,5,6}
    assert fires_pos == 1               # idx3 在正样本，idx7 不在
    assert fires_all == 2
    assert bars_all == 8
    print("OK count_for_signal")


def test_count_out_of_range_window():
    sig = [True, False, False]
    windows = [[-1, 0]]                  # -1 越界忽略
    seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all = \
        M.count_for_signal(sig, windows)
    assert seg_hit == 1 and bars_pos == 1 and fires_pos == 1
    print("OK count_out_of_range")


def test_finalize_and_rank():
    # 两个key累加计数 → 覆盖率/提升度/精确度
    counts = {
        ("ALL", "A", "buy", 0.15, (20, 0.618, 0.01, 12, 26, 9)):
            [7, 10, 8, 40, 20, 1000],     # cover 0.7, rate_pos .2, rate_all .02 → lift 10
        ("ALL", "A", "buy", 0.15, (10, 0.5, 0.01, 12, 26, 9)):
            [5, 10, 1, 40, 50, 1000],     # cover 0.5 → 被滤
    }
    rows = M.finalize(counts)
    assert len(rows) == 2
    assert all(r["group"] == "ALL" for r in rows)
    kept = M.filter_rank(rows, cover_min=0.70)
    assert len(kept) == 1, kept
    r = kept[0]
    assert abs(r["coverage"] - 0.7) < 1e-9
    assert abs(r["lift"] - 10.0) < 1e-6, r["lift"]
    assert abs(r["precision"] - 8 / 20) < 1e-9
    assert r["plan"] == "A" and r["side"] == "buy" and r["pct"] == 0.15
    print("OK finalize_and_rank")


def test_uplift_rows():
    # 同参数: ALL lift=2, 某组 lift=4 → uplift=2, ratio=2
    params = (20, 0.618, 0.01, 12, 26, 9)
    counts = {
        ("ALL", "A", "buy", 0.2, params): [6, 10, 30, 100, 100, 5000],
        ("板块=创业板", "A", "buy", 0.2, params): [8, 10, 60, 100, 100, 2000],
    }
    rows = M.finalize(counts)
    enriched = M.attach_uplift(rows)
    grp = [r for r in enriched if r["group"] == "板块=创业板"][0]
    assert "lift_all" in grp and "uplift" in grp and "uplift_ratio" in grp
    allrow = [r for r in enriched if r["group"] == "ALL"][0]
    assert abs(grp["lift_all"] - allrow["lift"]) < 1e-9
    assert abs(grp["uplift"] - (grp["lift"] - allrow["lift"])) < 1e-9
    print("OK uplift_rows")


def test_accumulate_stock():
    import pandas as pd
    # 造一段足够长、含明显涨跌的K线
    base = list(range(20, 60)) + list(range(60, 20, -1))   # 上后下
    c = [float(x) for x in base]
    df = pd.DataFrame({"Open": c, "High": [x + 1 for x in c],
                       "Low": [x - 1 for x in c], "Close": c,
                       "Volume": [1000.0] * len(c)},
                      index=pd.date_range("2020-01-01", periods=len(c), freq="D"))
    counts = M.accumulate_stock(df, pcts=(0.15,))
    # 至少应有 方案A/B × buy/sell × 0.15 的若干 key，计数为6元list
    assert any(k[0] == "ALL" and k[1] == "A" and k[2] == "buy" and k[3] == 0.15 for k in counts), list(counts)[:3]
    sample = next(iter(counts.values()))
    assert len(sample) == 6
    print("OK accumulate_stock")


def test_accumulate_stock_grouped_conservation():
    import pandas as pd
    import numpy as np
    base = list(range(20, 60)) + list(range(60, 20, -1))
    c = [float(x) for x in base]
    df = pd.DataFrame({"Open": c, "High": [x + 1 for x in c],
                       "Low": [x - 1 for x in c], "Close": c,
                       "Volume": [1000.0] * len(c)},
                      index=pd.date_range("2020-01-01", periods=len(c), freq="D"))
    groups = {"board": "板块=创业板", "size": "市值=小盘", "vol_cuts": [0.01, 0.03]}
    counts = M.accumulate_stock(df, pcts=(0.15,), groups=groups)
    # 1) 板块/市值组的 6 元计数应与 ALL 完全一致(单股全归入这两组)
    all_keys = [k for k in counts if k[0] == "ALL"]
    assert all_keys, "应有 ALL 键"
    for ak in all_keys:
        bk = ("板块=创业板",) + ak[1:]
        sk = ("市值=小盘",) + ak[1:]
        assert counts[bk] == counts[ak], (ak, counts[bk], counts[ak])
        assert counts[sk] == counts[ak], (ak, counts[sk], counts[ak])
    # 2) 波动率三桶的窗口计数(idx0-3)之和 == ALL 的窗口计数
    for ak in all_keys:
        agg = [0, 0, 0, 0]
        for lab in ("波动率=低", "波动率=中", "波动率=高"):
            vk = (lab,) + ak[1:]
            if vk in counts:
                for i in range(4):
                    agg[i] += counts[vk][i]
        assert agg == counts[ak][:4], (ak, agg, counts[ak][:4])
    print("OK accumulate_stock_grouped_conservation")


def test_accumulate_stock_no_groups_only_all():
    import pandas as pd
    base = list(range(20, 60)) + list(range(60, 20, -1))
    c = [float(x) for x in base]
    df = pd.DataFrame({"Open": c, "High": [x + 1 for x in c],
                       "Low": [x - 1 for x in c], "Close": c,
                       "Volume": [1000.0] * len(c)},
                      index=pd.date_range("2020-01-01", periods=len(c), freq="D"))
    counts = M.accumulate_stock(df, pcts=(0.15,))     # groups=None
    assert all(k[0] == "ALL" for k in counts), "无 groups 时只应有 ALL 键"
    print("OK accumulate_stock_no_groups_only_all")


def test_write_reports(tmpdir_path="/tmp/mc_test_out"):
    import os, glob, shutil
    shutil.rmtree(tmpdir_path, ignore_errors=True)
    os.makedirs(tmpdir_path, exist_ok=True)
    rows = [
        {"group": "ALL", "plan": "A", "side": "buy", "pct": 0.15, "params": (20, 0.618, 0.01, 12, 26, 9),
         "seg_hit": 7, "seg_total": 10, "coverage": 0.7, "rate_all": 0.02,
         "lift": 10.0, "precision": 0.4},
        # coverage 0.3 < 0.70：达标主榜应排除它，但最佳可达榜仍应收录
        {"group": "ALL", "plan": "B", "side": "sell", "pct": 0.10, "params": ((3, 6, 12, 24), "above", 12, 26, 9),
         "seg_hit": 3, "seg_total": 10, "coverage": 0.3, "rate_all": 0.03,
         "lift": 5.0, "precision": 0.3},
    ]
    paths = M.write_reports(rows, out_dir=tmpdir_path, ts="20260612_000000")
    csvs = glob.glob(os.path.join(tmpdir_path, "*.csv"))
    md = glob.glob(os.path.join(tmpdir_path, "*.md"))
    assert len(csvs) >= 1 and len(md) == 1, (csvs, md)
    # A买点达标主榜应含 N/ratio/band/fast 展开列
    head = open([p for p in csvs if "方案A" in p and "上涨前共性" in p][0],
                encoding="utf-8-sig").readline()
    assert "ratio" in head and "coverage" in head, head

    def _rows(path):
        return open(path, encoding="utf-8-sig").read().splitlines()
    # 达标主榜(coverage≥0.70)：A买1行数据，B卖(cov0.3)应空
    a_main = [p for p in csvs if "方案A" in p and "上涨前共性" in p][0]
    b_main = [p for p in csvs if "方案B" in p and "下跌前共性" in p][0]
    assert len(_rows(a_main)) == 2, _rows(a_main)          # 表头+1
    assert len(_rows(b_main)) == 1, _rows(b_main)          # 仅表头(无达标)
    # 最佳可达榜：即便 cov<0.70 也应收录 B卖那条
    b_best = [p for p in csvs if "方案B" in p and "下跌前最佳可达" in p][0]
    assert len(_rows(b_best)) == 2, _rows(b_best)          # 表头+1
    bhead = _rows(b_best)[0]
    assert "form" in bhead and "periods" in bhead, bhead   # 形态列(上穿/收上)已落地
    assert "above" in _rows(b_best)[1], _rows(b_best)[1]
    print("OK write_reports")


def _synth_df_ind(n=300, seed=1):
    import pandas as pd, numpy as np
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                         "Close": close, "Volume": rng.integers(1e5, 1e6, n)})


def test_accumulate_stock_industry():
    df = _synth_df_ind()
    out = M.accumulate_stock(df, groups={"board": None, "size": None,
                                         "vol_cuts": None, "industry": "行业=测试业"})
    ind_keys = [k for k in out if k[0] == "行业=测试业"]
    assert ind_keys, "应出现 行业=测试业 的 key"
    # 单股全归该行业 → 行业组 seg_hit == 同参 ALL seg_hit（≤ 的等号情形）
    for k in ind_keys:
        allk = ("ALL",) + k[1:]
        assert out[k][0] == out[allk][0], (k, out[k], out[allk])
    # industry=None 不产行业组
    out2 = M.accumulate_stock(df, groups={"board": None, "size": None,
                                          "vol_cuts": None, "industry": None})
    assert not any(k[0].startswith("行业=") for k in out2)
    print("OK accumulate_stock_industry")


def test_dim_of_industry():
    assert M._dim_of("行业=C39计算机") == "行业"
    print("OK dim_of_industry")


if __name__ == "__main__":
    test_count_for_signal()
    test_count_out_of_range_window()
    test_finalize_and_rank()
    test_uplift_rows()
    test_accumulate_stock()
    test_accumulate_stock_grouped_conservation()
    test_accumulate_stock_no_groups_only_all()
    test_write_reports()
    test_accumulate_stock_industry()
    test_dim_of_industry()
    print("ALL OK")
