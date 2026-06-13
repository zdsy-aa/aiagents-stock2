import numpy as np, pandas as pd
import presetup_signals as PSig

def _df(close, vol=None):
    c = pd.Series(close, dtype=float)
    return pd.DataFrame({"Open": c, "High": c*1.01, "Low": c*0.99, "Close": c,
                         "Volume": pd.Series(vol if vol is not None else [1.0]*len(c))})

def test_box_fires_on_flat_not_on_trend():
    flat = _df([10.0]*40)                      # 完全横盘 -> 箱体应亮
    trend = _df([10.0 + i for i in range(40)]) # 单调上行 -> 箱体不亮
    bf = PSig.sig_box(flat, 20, 0.10)
    tf = PSig.sig_box(trend, 20, 0.10)
    assert bf[-1] == True and tf[-1] == False, (bf[-1], tf[-1])

def test_dryup_fires_on_low_volume():
    vol = [100.0]*30 + [10.0]*10               # 后段缩量
    d = _df([10.0]*40, vol=vol)
    f = PSig.sig_dryup(d, 20, 0.8)
    assert f[-1] == True, f[-1]
    # 无 Volume 列 -> 全 False
    d2 = _df([10.0]*40); d2 = d2.drop(columns=["Volume"])
    assert PSig.sig_dryup(d2, 20, 0.8).sum() == 0

def test_lowvol_fires_when_std_compresses():
    # 前段大波动,后段几乎不动 -> 后段低波动应亮
    noisy = [10.0 + (2.0 if i % 2 else -2.0) for i in range(80)]
    calm = [20.0 + 0.001*(i % 2) for i in range(80)]
    d = _df(noisy + calm)
    f = PSig.sig_lowvol(d, 20, 0.3)
    assert f[-1] == True, f[-1]

def test_chip_band_and_none():
    profit = np.array([np.nan]*60 + [55.0, 90.0, 20.0])
    f = PSig.sig_chip(profit, 50, 80)
    assert f[-3] == True and f[-2] == False and f[-1] == False
    assert PSig.sig_chip(None, 50, 80) is None

def test_l1_specs_and_l2_pairs():
    names = [s[0] for s in PSig.L1_SPECS]
    assert len(names) == 17 and len(set(names)) == 17, len(names)
    pairs = PSig.l2_pairs(names)
    assert len(pairs) == 17*16//2, len(pairs)

if __name__ == "__main__":
    test_box_fires_on_flat_not_on_trend(); test_dryup_fires_on_low_volume()
    test_lowvol_fires_when_std_compresses(); test_chip_band_and_none()
    test_l1_specs_and_l2_pairs()
    print("ALL presetup_signals OK")
