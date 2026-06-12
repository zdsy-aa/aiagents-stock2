# tests/test_chanlun_ui_smoke.py
"""缠论选股页 AppTest 冒烟：切换两个模式不抛异常。不触真实本地源。"""
from streamlit.testing.v1 import AppTest


_SCRIPT = """
import streamlit as st
import chanlun_single
import pandas as pd

# 桩掉实时查询，避免依赖本地源
def _fake_query(code):
    df = pd.DataFrame({
        "signal_type": ["1买", "1卖"], "signal_date": ["2026-05-28", "2026-05-20"],
        "price": [10.0, 12.0], "stop_loss": [9.8, None],
        "reason": ["下跌段力度背驰；30m确认", "上涨段力度背驰；30m确认"],
        "level": ["日线", "日线"],
    }, columns=chanlun_single.KEEP_COLS)
    return True, df, "600519 全历史共 2 个缠论信号（含买卖点）"

chanlun_single.query_stock_signals = _fake_query
from chanlun_ui import display_chanlun_selector
display_chanlun_selector()
"""


def test_batch_mode_renders():
    at = AppTest.from_string(_SCRIPT).run()
    assert not at.exception
    # 默认批量模式：radio 存在且默认第一项
    assert at.radio[0].value == "批量选股"


def test_single_mode_renders_after_input():
    at = AppTest.from_string(_SCRIPT).run()
    at.radio[0].set_value("个股信号查询").run()
    assert not at.exception
    at.text_input[0].set_value("600519").run()
    assert not at.exception
    # 桩数据的 msg 出现在 info 中
    assert any("全历史共 2" in str(i.value) for i in at.info)
