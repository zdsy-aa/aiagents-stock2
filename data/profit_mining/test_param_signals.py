# test_param_signals.py —— 参数化信号合成数据测试
import pandas as pd
import param_signals as P


def _df(o, h, l, c):
    n = len(c)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c,
                         "Volume": [1000.0] * n}, index=idx)


def test_macd_golden_dead():
    # 构造先跌后涨：DIF 上穿 DEA 处应有金叉
    c = [10, 9.5, 9, 9.2, 9.6, 10.2, 10.8, 11.5]
    df = _df(c, c, c, c)
    g = P.macd_golden(df, 5, 10, 3)
    d = P.macd_dead(df, 5, 10, 3)
    assert g.sum() >= 1, g.tolist()
    assert (g & d).sum() == 0          # 金叉死叉互斥
    print("OK macd_golden_dead")


def test_fib_support_hold():
    # 近N=4 高=110 低=100，range=10，ratio0.5→support=105。
    # 末根 low=104(<=105*1.01=106.05 触及) 且 close=106(>=105) → 回踩企稳成立
    df = _df([105]*5, [110, 108, 106, 107, 106],
             [100, 103, 104, 104, 104], [108, 106, 105, 106, 106])
    sig = P.fib_support_hold(df, N=4, ratio=0.5, band=0.01)
    assert bool(sig.iloc[-1]) is True, sig.tolist()
    print("OK fib_support_hold")


def test_bbi_cross_up_down():
    c = [10, 10, 10, 10, 9, 9, 9.5, 11, 12]
    df = _df(c, c, c, c)
    up = P.bbi_cross_up(df, (2, 3, 4, 5))
    dn = P.bbi_cross_down(df, (2, 3, 4, 5))
    assert up.sum() >= 1, up.tolist()
    assert (up & dn).sum() == 0
    print("OK bbi_cross")


def test_combiners_and_grids():
    c = [10, 9.5, 9, 9.2, 9.6, 10.2, 10.8, 11.5, 12.0, 12.5]
    df = _df(c, [x + 0.5 for x in c], [x - 0.5 for x in c], c)
    a = P.plan_a_signal(df, 4, 0.5, 0.02, 5, 10, 3, "buy")
    b = P.plan_b_signal(df, (2, 3, 4, 5), 5, 10, 3, "buy")
    assert a.dtype == bool and b.dtype == bool
    assert len(P.PLAN_A_GRID) == 144, len(P.PLAN_A_GRID)
    assert len(P.PLAN_B_GRID) == 12, len(P.PLAN_B_GRID)
    print("OK combiners_grids")


if __name__ == "__main__":
    test_macd_golden_dead()
    test_fib_support_hold()
    test_bbi_cross_up_down()
    test_combiners_and_grids()
    print("ALL OK")
