# test_swing_samples.py —— 起涨/起跌初期正样本窗口测试（拐点后 fwd 根）
import swing_samples as S


def test_windows():
    # 拐点 L@10, H@20, L@30 → 上涨段(10→20)取波谷10后含10的5根[10..14]；
    # 下跌段(20→30)取波峰20后含20的5根[20..24]
    up, down = S.windows_from_pivots([(10, "L"), (20, "H"), (30, "L")], fwd=4)
    assert up == [[10, 11, 12, 13, 14]], up
    assert down == [[20, 21, 22, 23, 24]], down
    print("OK windows")


def test_truncate_to_segment_end():
    # 上涨段 L@2 → H@5：[2,2+4]=[2..6] 但截到段终点5 → [2,3,4,5]
    up, down = S.windows_from_pivots([(2, "L"), (5, "H")], fwd=4)
    assert up == [[2, 3, 4, 5]], up
    print("OK truncate_to_segment_end")


def test_positive_windows_end2end():
    # 真实序列：先跌后涨再跌，验证 positive_windows 串起 zigzag
    high = [110, 100, 130, 120, 104]
    low = [100, 90, 120, 110, 104]
    up, down = S.positive_windows(high, low, 0.15, fwd=3)
    assert isinstance(up, list) and isinstance(down, list)
    print("OK end2end")


if __name__ == "__main__":
    test_windows()
    test_truncate_to_segment_end()
    test_positive_windows_end2end()
    print("ALL OK")
