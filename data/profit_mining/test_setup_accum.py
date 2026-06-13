import numpy as np, pandas as pd
import mine_setup_commonality as MS
import swing_samples as SW

def _df(n=160):
    base = [10.0]*60 + [10.0 + 0.5*i for i in range(40)] + [30.0]*(n-100)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    c = pd.Series(base[:n], dtype=float, index=idx)
    return pd.DataFrame({"Open": c, "High": c*1.01, "Low": c*0.99,
                         "Close": c, "Volume": pd.Series([100.0]*n, index=idx)}, index=idx)

def test_accumulate_keys_levels_and_segtotal():
    df = _df()
    counts = MS.accumulate_setup(df, "000001", turn=None)  # 无turn -> chip全False但仍计
    assert counts, "应有计数"
    levels = {k[1] for k in counts}
    assert levels == {"L1", "L2"}, levels
    for k, v in counts.items():
        g, level, side, pct, name = k
        assert g == "ALL" and side == "buy" and pct == 0.06
        assert isinstance(name, str) and len(v) == 6
    # seg_total = 蓄势窗口数
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), 0.06)
    n_up = len(SW.presetup_windows_from_pivots(piv))
    assert next(iter(counts.values()))[1] == n_up, (next(iter(counts.values()))[1], n_up)

def test_l2_is_and_of_l1():
    # L2 命中段数 <= 各自 L1 命中段数(AND 单调)
    df = _df()
    counts = MS.accumulate_setup(df, "000001", turn=None)
    l1 = {k[4]: v for k, v in counts.items() if k[1] == "L1"}
    l2 = {k[4]: v for k, v in counts.items() if k[1] == "L2"}
    assert l2, "应有L2"
    name2, v2 = next(iter(l2.items()))
    a, b = name2.split(" & ")
    assert v2[0] <= l1[a][0] and v2[0] <= l1[b][0], (v2[0], l1[a][0], l1[b][0])

if __name__ == "__main__":
    test_accumulate_keys_levels_and_segtotal(); test_l2_is_and_of_l1()
    print("ALL setup_accum OK")
