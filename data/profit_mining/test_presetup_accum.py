import numpy as np, pandas as pd
import mine_presetup as MP

def _df(n=120):
    # 构造有明显 zz6 上涨段的合成K线: 前低位震荡, 后台阶上行
    base = [10.0]*40 + [10.0 + 0.5*i for i in range(40)] + [30.0]*40
    close = pd.Series(base[:n])
    return pd.DataFrame({"Open": close, "High": close*1.01,
                         "Low": close*0.99, "Close": close})

def test_accumulate_keys_and_shape():
    df = _df()
    counts = MP.accumulate_presetup(df)
    assert counts, "应有计数"
    for k, v in counts.items():
        group, plan, side, pct, params = k
        assert group == "ALL" and side == "buy" and pct == 0.06
        assert plan in ("A", "B")
        assert len(v) == 6 and v[1] >= 1   # seg_total>=1
        break

def test_seg_total_equals_num_up_segments():
    df = _df()
    counts = MP.accumulate_presetup(df)
    import swing_samples as SW
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), 0.06)
    n_up = len(SW.presetup_windows_from_pivots(piv))
    any_v = next(iter(counts.values()))
    assert any_v[1] == n_up, (any_v[1], n_up)

if __name__ == "__main__":
    test_accumulate_keys_and_shape(); test_seg_total_equals_num_up_segments()
    print("ALL presetup_accum OK")
