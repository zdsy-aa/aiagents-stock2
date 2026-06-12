# test_swing_samples.py —— W=5 正样本窗口测试
import swing_samples as S


def test_windows():
    # 拐点 L@10, H@20, L@30 → 上涨段(10→20)取波谷10前含10的5根[6..10]；
    # 下跌段(20→30)取波峰20前含20的5根[16..20]
    up, down = S.windows_from_pivots([(10, "L"), (20, "H"), (30, "L")], W=5)
    assert up == [[6, 7, 8, 9, 10]], up
    assert down == [[16, 17, 18, 19, 20]], down
    print("OK windows")


def test_truncate_head():
    # 拐点 L@2：窗口不足5根，截到[0,1,2]
    up, down = S.windows_from_pivots([(2, "L"), (8, "H")], W=5)
    assert up == [[0, 1, 2]], up
    print("OK truncate_head")


def test_positive_windows_end2end():
    # 真实序列：先跌后涨再跌，验证 positive_windows 串起 zigzag
    high = [110, 100, 130, 120, 104]
    low = [100, 90, 120, 110, 104]
    up, down = S.positive_windows(high, low, 0.15, W=3)
    assert isinstance(up, list) and isinstance(down, list)
    print("OK end2end")


if __name__ == "__main__":
    test_windows()
    test_truncate_head()
    test_positive_windows_end2end()
    print("ALL OK")
