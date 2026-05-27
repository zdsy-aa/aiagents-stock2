# tests/test_ui_pages_smoke.py
from streamlit.testing.v1 import AppTest


def _home_text():
    at = AppTest.from_file("app.py", default_timeout=120).run()
    assert not at.exception, at.exception
    # 收集所有 markdown / 文本元素
    chunks = []
    for el in at.markdown:
        chunks.append(str(el.value))
    return "\n".join(chunks)


def test_learning_video_section_removed():
    text = _home_text()
    assert "学习视频合集" not in text
    assert "新手必看干货" not in text
    # 加固：expander 内的 B站合集内容与链接也应消失
    assert "B站干货合集" not in text
    assert "股票知识讲解合集" not in text
    assert "投资认知提升合集" not in text


import pytest

PAGE_FLAGS = [
    "show_history", "show_monitor", "show_main_force", "show_low_price_bull",
    "show_small_cap", "show_profit_growth", "show_value_stock", "show_sector_strategy",
    "show_longhubang", "show_smart_monitor", "show_portfolio", "show_news_flow",
    "show_macro_analysis", "show_macro_cycle", "show_config", "show_intraday",
]


@pytest.mark.parametrize("flag", PAGE_FLAGS)
def test_page_renders_without_exception(flag):
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state[flag] = True
    at.run()
    assert not at.exception, (flag, at.exception)
