import daily_watchlist as dw


# buy=10, stop=9.2, tp=13, premium=0.05 → 涨过阈值=10.5
BP, STOP, TP = 10.0, 9.2, 13.0


def test_enterable_within_pure_window():
    # gap<=1 且价格在区间内 → 可入
    assert dw.entry_status(0, 10.1, BP, STOP, TP) == "可入"
    assert dw.entry_status(1, 9.5, BP, STOP, TP) == "可入"


def test_tail_window_gap_two():
    # gap==2、价格仍在区间 → 尾窗
    assert dw.entry_status(2, 10.2, BP, STOP, TP) == "尾窗"


def test_past_window_gap_over_two():
    # gap>2、价格仍在区间 → 已过窗
    assert dw.entry_status(3, 10.2, BP, STOP, TP) == "已过窗"


def test_run_up_above_premium():
    # 收盘 > buy*1.05 → 已涨过(即便在纯窗口内)
    assert dw.entry_status(0, 10.6, BP, STOP, TP) == "已涨过"
    # 恰好 +5% 不算涨过(严格大于)
    assert dw.entry_status(0, 10.5, BP, STOP, TP) == "可入"


def test_stop_loss_breached():
    # 收盘 < 止损 → 已破止损
    assert dw.entry_status(1, 9.1, BP, STOP, TP) == "已破止损"


def test_take_profit_reached():
    # 收盘 >= 止盈 → 已止盈
    assert dw.entry_status(1, 13.0, BP, STOP, TP) == "已止盈"
    assert dw.entry_status(1, 13.5, BP, STOP, TP) == "已止盈"


def test_price_priority_over_window():
    # 破止损优先于已过窗(价格类先判)
    assert dw.entry_status(5, 9.0, BP, STOP, TP) == "已破止损"
    # 止盈优先于已过窗
    assert dw.entry_status(5, 13.2, BP, STOP, TP) == "已止盈"


def test_invalid_inputs_dash():
    assert dw.entry_status(-1, 10.1, BP, STOP, TP) == "—"
    assert dw.entry_status(0, None, BP, STOP, TP) == "—"
    assert dw.entry_status(0, 10.1, None, STOP, TP) == "—"


def test_custom_premium():
    # premium=0.10 → 阈值=11，10.8 仍可入
    assert dw.entry_status(0, 10.8, BP, STOP, TP, premium=0.10) == "可入"
    assert dw.entry_status(0, 11.1, BP, STOP, TP, premium=0.10) == "已涨过"
