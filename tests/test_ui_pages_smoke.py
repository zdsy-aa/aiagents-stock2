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
    "show_main_force", "show_low_price_bull",
    "show_small_cap", "show_profit_growth", "show_value_stock", "show_sector_strategy",
    "show_longhubang", "show_news_flow",
    "show_macro_analysis", "show_macro_cycle", "show_config",
    "show_chanlun",
    "show_current_strategy",
    "show_qizhang",
    "show_docs_indicator",
    "show_docs_project",
    "show_docs_flow",
    "show_docs_scan",
    "show_mindmap",
]


@pytest.mark.parametrize("flag", PAGE_FLAGS)
def test_page_renders_without_exception(flag):
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state[flag] = True
    at.run()
    assert not at.exception, (flag, at.exception)


def test_current_strategy_page_shows_four_categories():
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state["show_current_strategy"] = True
    at.run()
    assert not at.exception, at.exception
    text = "\n".join(str(el.value) for el in at.markdown)
    for cat in ["选股", "买入卖出", "测试盈利", "找共同点"]:
        assert cat in text, cat
    assert "当前策略" in text


def test_home_shows_top_nav_categories():
    at = AppTest.from_file("app.py", default_timeout=180).run()
    assert at.exception is None or at.exception == []
    exp_labels = " ".join(e.label for e in at.sidebar.expander)
    btn_labels = " ".join(b.label for b in at.sidebar.button)
    for cat in ("分析", "选股", "策略", "配置", "文档"):
        assert cat in exp_labels
    # 管理模块已从网页删除
    assert "管理" not in exp_labels
    assert "持仓分析" not in btn_labels
    assert "历史记录" not in btn_labels
    # 已删除的分时分析/缠论图解不应出现
    assert "分时分析" not in btn_labels
    assert "缠论图解" not in btn_labels
    # 保留页在侧栏可见
    for lbl in ("股票分析-日", "主力选股", "环境配置"):
        assert lbl in btn_labels


def test_mindmap_page_renders():
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state["show_mindmap"] = True
    at.run()
    assert not at.exception, at.exception
    text = "\n".join(str(el.value) for el in at.markdown)
    assert "项目思维导图" in text
