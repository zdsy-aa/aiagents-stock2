import swing_samples as SW

def _seg(pivots):
    return SW.Z.segments_from_pivots(pivots)

def test_far_branch_no_prev_up():
    # 单个上涨段: L@10 -> H@20。无上一涨段 -> 远分支 [10-7, 10]
    pivots = [(10, "L"), (20, "H")]
    wins = SW.presetup_windows_from_pivots(pivots, near_n=20, far=7)
    assert wins == [list(range(3, 11))], wins   # [L-7 .. L] 含L, 共8根

def test_far_branch_clip_negative():
    pivots = [(3, "L"), (15, "H")]               # L=3, L-7<0 -> 截到0
    wins = SW.presetup_windows_from_pivots(pivots, near_n=20, far=7)
    assert wins == [list(range(0, 4))], wins

def test_near_branch_prev_cycle():
    # 上涨段1: L0@0->H0@10; 下降段 H0@10->L1@25(gap=25-10=15<=20 近);
    # 上涨段2: L1@25->H1@40。 seg2 窗口 = [L0=0 .. L1=25] 含L1
    pivots = [(0, "L"), (10, "H"), (25, "L"), (40, "H")]
    wins = SW.presetup_windows_from_pivots(pivots, near_n=20, far=7)
    # seg1(L0): 无上一涨段 -> 远 [0-7截0 .. 0] = [0]
    # seg2(L1=25): 近 -> [0 .. 25]
    assert wins[0] == [0], wins[0]
    assert wins[1] == list(range(0, 26)), wins[1]

def test_near_falls_to_far_when_gap_big():
    # gap=30>20 -> seg2 走远分支 [25-7 .. 25]
    pivots = [(0, "L"), (10, "H"), (40, "L"), (55, "H")]
    wins = SW.presetup_windows_from_pivots(pivots, near_n=20, far=7)
    assert wins[1] == list(range(33, 41)), wins[1]

if __name__ == "__main__":
    test_far_branch_no_prev_up(); test_far_branch_clip_negative()
    test_near_branch_prev_cycle(); test_near_falls_to_far_when_gap_big()
    print("ALL presetup_windows OK")
