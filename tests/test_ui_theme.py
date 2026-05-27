# tests/test_ui_theme.py
from ui_theme import THEME, build_theme_css


def test_theme_has_ashare_semantic_colors():
    # A股惯例：涨红跌绿
    assert THEME["up"] == "#f6465d"
    assert THEME["down"] == "#0ecb81"
    assert THEME["bg"] == "#0e1117"
    assert THEME["accent"] == "#22d3ee"


def test_build_theme_css_returns_style_block_with_tokens():
    css = build_theme_css()
    assert isinstance(css, str)
    assert css.strip().startswith("<style>")
    assert css.strip().endswith("</style>")
    # 关键 token 出现在 CSS 中
    for tok in (THEME["bg"], THEME["card"], THEME["border"], THEME["accent"]):
        assert tok in css
    # 卡片/区块标题工具类存在
    assert ".ftc-card" in css
    assert ".ftc-section" in css
