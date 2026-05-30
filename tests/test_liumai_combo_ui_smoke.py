# tests/test_liumai_combo_ui_smoke.py
"""六脉/组合页 AppTest 冒烟: 桩掉 selector 与 batch, 验证渲染与 🔄 按钮不抛异常。"""
import pandas as pd
from streamlit.testing.v1 import AppTest


_LIUMAI_SCRIPT = """
import pandas as pd
import liumai_selector, liumai_batch
from liumai_selector import KEEP_COLS

def _fake_get_picks(self, min_bull=5, scan_date=None):
    df = pd.DataFrame([{
        "code": "600000", "name": "浦发", "board": "深主板", "signal_date": "2026-05-29",
        "bull_count": 6, "score": 100, "state": "强势", "macd": 1, "kdj": 1, "rsi": 1,
        "lwr": 1, "bbi": 1, "mtm": 1,
    }], columns=KEEP_COLS)
    return True, df, "扫描批次 2026-05-29, 共 1 只(多头数≥5)"

liumai_selector.LiumaiSelector.get_picks = _fake_get_picks
liumai_batch.scan_codes = lambda *a, **k: 1
from liumai_ui import display_liumai_selector
display_liumai_selector()
"""


def test_liumai_renders():
    at = AppTest.from_string(_LIUMAI_SCRIPT).run()
    assert not at.exception
    assert any("共 1 只" in str(i.value) for i in at.info)
    assert len(at.button) >= 1       # 🔄 重算按钮存在
