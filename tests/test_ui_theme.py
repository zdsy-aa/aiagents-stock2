# tests/test_ui_theme.py
from ui_theme import THEME, build_theme_css
from ui_theme import pct_color, metric_card, badge, section_header
import plotly.graph_objects as go
from ui_theme import style_fig, candle_colors


def test_theme_has_ashare_semantic_colors():
    # A股惯例：涨红跌绿
    assert THEME["up"] == "#f6465d"
    assert THEME["down"] == "#0ecb81"
    assert THEME["bg"] == "#1e242e"
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


def test_pct_color_ashare_semantics():
    assert pct_color(2.3) == THEME["up"]      # 涨→红
    assert pct_color(-1.1) == THEME["down"]   # 跌→绿
    assert pct_color(0) == THEME["text_dim"]  # 平→灰


def test_metric_card_renders_value_and_colored_change():
    html = metric_card("收盘", "11.20", change_pct=2.3)
    assert "ftc-card" in html
    assert "收盘" in html and "11.20" in html
    assert THEME["up"] in html      # 涨幅染红
    assert "+2.3%" in html


def test_badge_and_section_header():
    assert "ftc-badge" in badge("买入", THEME["up"])
    assert "ftc-section" in section_header("技术面")
    assert "技术面" in section_header("技术面")


def test_candle_colors_ashare():
    inc, dec = candle_colors()
    assert inc == THEME["up"]    # 涨红
    assert dec == THEME["down"]  # 跌绿


def test_style_fig_applies_transparent_dark():
    fig = go.Figure()
    out = style_fig(fig)
    assert out is fig  # 原地返回
    assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert fig.layout.plot_bgcolor == "rgba(0,0,0,0)"
    assert fig.layout.font.color == THEME["text"]
