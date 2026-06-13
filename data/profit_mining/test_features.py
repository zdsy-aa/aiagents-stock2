# test_features.py —— 合成数据断言测试（无pytest，python3直接跑）
import numpy as np
import pandas as pd
import features as F


def _df(close, high=None, low=None, vol=None):
    n = len(close)
    high = high if high is not None else [c * 1.01 for c in close]
    low = low if low is not None else [c * 0.99 for c in close]
    vol = vol if vol is not None else [1000.0] * n
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                         "Close": close, "Volume": vol}, index=idx)


def test_price_form():
    up = _df(list(np.linspace(10, 30, 250)))
    f = F.price_form_features(up)
    assert f["多头排列"].iloc[-1] == 1
    assert f["斐波全多头"].iloc[-1] == 1
    assert f["站上MA233"].iloc[-1] == 1
    print("OK price_form")


def test_volume():
    df = _df(list(np.linspace(10, 12, 40)), vol=[1000.0] * 39 + [5000.0])
    f = F.volume_features(df)
    assert f["放量"].iloc[-1] == 1 and f["量比大于2"].iloc[-1] == 1 and f["价涨量增"].iloc[-1] == 1
    print("OK volume")


def test_classic_runs():
    df = _df(list(10 + np.sin(np.linspace(0, 12, 120))))
    f = F.classic_indicators(df)
    for col in ["MACD_DIF大于0", "BOLL收上中轨", "KDJ金叉态", "RSI6大于50"]:
        assert col in f.columns
        assert set(f[col].dropna().unique()) <= {0, 1}
    print("OK classic")


def test_wyckoff_liumai_run():
    df = _df(list(10 + np.sin(np.linspace(0, 20, 200))),
             vol=list(1000 + 500 * np.cos(np.linspace(0, 20, 200))))
    w = F.wyckoff_features(df)
    lm = F.liumai_features(df)
    for col in ["威科夫得分大于4", "威科夫B3弹簧", "黄金柱", "中枢上方"]:
        assert col in w.columns
    for col in ["六脉红灯大于5", "六脉6红首发"]:
        assert col in lm.columns
    print("OK wyckoff+liumai")


def test_index_and_rel():
    idx_up = _df(list(np.linspace(3000, 3600, 80)))
    st = F.index_state(idx_up)
    assert st["大盘状态ID"].iloc[-1] == 1 and st["SID小于等于2"].iloc[-1] == 1
    stock = pd.Series(np.linspace(10, 14, 80), index=idx_up.index)
    rs = F.relative_strength(stock, idx_up["Close"])
    assert rs["相对强弱大于0"].iloc[-1] == 1
    print("OK index+rel")


def test_window_or_at():
    s = pd.Series([0] * 45); s.iloc[37] = 1
    assert F.window_or_at(s, 39, 2) == 1
    assert F.window_or_at(s, 42, 2) == 0
    assert F.window_or_at(s, 0, 2) == 0
    print("OK window_or_at")


def test_tdx_extra():
    df = _df(list(10 + np.sin(np.linspace(0, 20, 200))),
             vol=list(1000 + 500 * np.cos(np.linspace(0, 20, 200))))
    t = F.tdx_extra_features(df, code="000001")
    for col in ["火箭信号", "回马枪", "纳财", "极限抄底", "中枢进机会区",
                "中枢上穿中轴", "摇钱树", "主力启动", "超短打板"]:
        assert col in t.columns, col
        assert set(t[col].dropna().unique()) <= {0, 1}, col
    print(f"OK tdx_extra ({t.shape[1]} 信号列)")


def test_assemble():
    df = _df(list(10 + np.sin(np.linspace(0, 12, 250))),
             vol=list(1000 + 300 * np.cos(np.linspace(0, 12, 250))))
    ff = F.assemble_feature_frame(df, None, None, code="300001")
    for col in ["多头排列", "放量", "MACD金叉态", "威科夫B3弹簧", "六脉红灯大于5",
                "偏多共振", "火箭信号", "中枢进机会区", "极限抄底"]:
        assert col in ff.columns, col
    print(f"OK assemble ({ff.shape[1]} 特征列)")


def run_all():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ALL FEATURE TESTS PASSED")


if __name__ == "__main__":
    run_all()
