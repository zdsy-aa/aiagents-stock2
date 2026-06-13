import swing_samples as SW

def test_tight_single_segment():
    pivots = [(30, "L"), (50, "H")]
    w = SW.presetup_windows_from_pivots(pivots, tight_k=5)
    assert w == [list(range(25, 31))], w   # [L-5 .. L] 含L, 6根

def test_tight_clip_negative():
    pivots = [(3, "L"), (15, "H")]
    w = SW.presetup_windows_from_pivots(pivots, tight_k=5)
    assert w == [list(range(0, 4))], w     # L-5<0 截到0

def test_tight_ignores_prev_cycle():
    # 两上涨段; 紧窗口每段都是 [L-K, L], 与上一段无关(不跨周期)
    pivots = [(0, "L"), (10, "H"), (25, "L"), (40, "H")]
    w = SW.presetup_windows_from_pivots(pivots, tight_k=5)
    assert w[0] == [0], w[0]                # L0=0: [0-5截0..0]
    assert w[1] == list(range(20, 26)), w[1]  # L1=25: [20..25]

def test_tight_none_equals_adaptive():
    # tight_k=None(默认) 必须与现有自适应输出完全一致(回归保护)
    pivots = [(0, "L"), (10, "H"), (25, "L"), (40, "H")]
    assert (SW.presetup_windows_from_pivots(pivots, tight_k=None)
            == SW.presetup_windows_from_pivots(pivots))

if __name__ == "__main__":
    test_tight_single_segment(); test_tight_clip_negative()
    test_tight_ignores_prev_cycle(); test_tight_none_equals_adaptive()
    print("ALL tight_window OK")
