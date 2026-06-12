# test_zigzag.py —— ZigZag 拐点与切段合成数据测试（python3 test_zigzag.py）
import zigzag_segments as Z


def test_pivots_v_then_up():
    # 100→80(跌20%)→100(涨25%)，pct=0.15：应得 H@0, L@2
    high = [100, 90, 80, 90, 100]
    low  = [100, 90, 80, 90, 100]
    piv = Z.zigzag_pivots(high, low, 0.15)
    assert piv == [(0, "H"), (2, "L")], piv
    print("OK pivots_v_then_up")


def test_pivots_full():
    # 低100→高130(+30%)→低104(-20%)：从首根起先上后下
    high = [110, 120, 130, 120, 104]
    low  = [100, 110, 120, 110, 104]
    piv = Z.zigzag_pivots(high, low, 0.15)
    # 起点低候选@0(low100)，涨到130确认L@0、H@2，再回落到104(<130*0.85=110.5)确认H@2、L@4
    assert piv[0] == (0, "L"), piv
    assert (2, "H") in piv and (4, "L") in piv, piv
    print("OK pivots_full")


def test_segments():
    piv = [(0, "L"), (2, "H"), (4, "L")]
    segs = Z.segments_from_pivots(piv)
    assert segs == [(0, 2, "up"), (2, 4, "down")], segs
    print("OK segments")


def test_empty():
    assert Z.zigzag_pivots([], [], 0.15) == []
    assert Z.segments_from_pivots([]) == []
    print("OK empty")


if __name__ == "__main__":
    test_pivots_v_then_up()
    test_pivots_full()
    test_segments()
    test_empty()
    print("ALL OK")
