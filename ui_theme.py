# ui_theme.py
"""深色 Fintech 全局设计系统：主题色板、全局 CSS、可复用组件、Plotly 深色模板。
全站 16 页同处一次 Streamlit run，启动调一次 inject_theme() 即全继承。"""

THEME = {
    "bg":        "#1e242e",   # 页底（中度提亮 slate）
    "panel":     "#272e3a",   # 面板/侧栏
    "card":      "#313a48",   # 卡片
    "border":    "#3f4856",
    "text":      "#f0f3f8",   # 主文字
    "text_dim":  "#b4bdca",   # 次文字
    "up":        "#f6465d",   # 涨（A股红）
    "down":      "#0ecb81",   # 跌（A股绿）
    "accent":    "#22d3ee",   # 交互强调（青）
    "gold":      "#f0b90b",   # 点睛
}


def build_theme_css() -> str:
    """返回完整 <style> 字符串（纯函数，便于测试）。"""
    t = THEME
    return f"""<style>
/* ===== 深色 Fintech 设计系统 ===== */
.stApp {{ background: {t['bg']}; color: {t['text']}; }}
section[data-testid="stSidebar"] {{ background: {t['panel']}; border-right: 1px solid {t['border']}; }}
h1, h2, h3, h4 {{ color: {t['text']}; }}
p, span, label, li {{ color: {t['text']}; }}
.stCaption, [data-testid="stCaptionContainer"] {{ color: {t['text_dim']} !important; }}

/* 卡片 */
.ftc-card {{
    background: {t['card']}; border: 1px solid {t['border']}; border-radius: 12px;
    padding: 16px 18px; margin: 8px 0;
}}
.ftc-card .ftc-label {{ color: {t['text_dim']}; font-size: 0.8rem; }}
.ftc-card .ftc-value {{ color: {t['text']}; font-size: 1.5rem; font-weight: 700; }}

/* 区块标题：左侧强调色竖条 */
.ftc-section {{
    border-left: 4px solid {t['accent']}; padding-left: 10px; margin: 18px 0 8px;
    font-size: 1.15rem; font-weight: 700; color: {t['text']};
}}

/* 徽章 */
.ftc-badge {{ display:inline-block; padding:2px 10px; border-radius:999px; font-size:0.8rem; font-weight:600; }}

/* 涨跌语义色工具类 */
.ftc-up {{ color: {t['up']}; }}
.ftc-down {{ color: {t['down']}; }}

/* 遗留内联HTML类（app.py 顶部标题栏 + 智能体/决策/风险卡）深色重定义 */
.top-nav {{
    background: linear-gradient(135deg, {t['panel']} 0%, {t['card']} 100%);
    padding: 1.4rem 2rem; border-radius: 14px; margin-bottom: 1.5rem;
    border: 1px solid {t['border']}; border-left: 4px solid {t['accent']};
}}
.nav-title {{ font-size: 2rem; font-weight: 800; color: {t['text']}; text-align: center; margin: 0; letter-spacing: 1px; }}
.nav-subtitle {{ text-align: center; color: {t['text_dim']}; font-size: 0.95rem; margin-top: 0.5rem; font-weight: 300; }}
.agent-card {{
    background: {t['card']}; padding: 1.3rem; border-radius: 12px; margin: 1rem 0;
    border: 1px solid {t['border']}; border-left: 4px solid {t['accent']};
}}
.decision-card {{
    background: {t['card']}; padding: 1.6rem; border-radius: 12px; margin: 1.2rem 0;
    border: 1px solid {t['border']}; border-left: 4px solid {t['accent']};
}}
.warning-card {{
    background: {t['card']}; padding: 1.3rem; border-radius: 12px; margin: 1rem 0;
    border: 1px solid {t['border']}; border-left: 4px solid {t['gold']};
}}

/* 按钮 */
.stButton > button {{
    background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 8px;
}}
.stButton > button:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}

/* 输入 / 选择框 */
[data-testid="stMetric"], .stDateInput, .stTextInput, .stSelectbox {{ color: {t['text']}; }}

/* 表格 */
[data-testid="stDataFrame"] {{ border: 1px solid {t['border']}; border-radius: 8px; }}

/* expander / tabs */
[data-testid="stExpander"] {{ border: 1px solid {t['border']}; border-radius: 10px; background: {t['panel']}; }}
.stTabs [data-baseweb="tab-list"] {{ border-bottom: 1px solid {t['border']}; }}
.stTabs [aria-selected="true"] {{ color: {t['accent']}; }}

/* 滚动条 */
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-thumb {{ background: {t['border']}; border-radius: 6px; }}
::-webkit-scrollbar-track {{ background: {t['bg']}; }}
</style>"""


import streamlit as st


def pct_color(pct: float) -> str:
    """按 A股惯例：涨红跌绿，平灰。"""
    if pct > 0:
        return THEME["up"]
    if pct < 0:
        return THEME["down"]
    return THEME["text_dim"]


def metric_card(label: str, value: str, change_pct: float | None = None) -> str:
    """返回一个深色指标卡 HTML。change_pct 给定时按涨跌染色。"""
    change_html = ""
    if change_pct is not None:
        sign = "+" if change_pct > 0 else ""
        change_html = (
            f'<div style="color:{pct_color(change_pct)};font-weight:600;">'
            f'{sign}{change_pct}%</div>'
        )
    return (
        f'<div class="ftc-card">'
        f'<div class="ftc-label">{label}</div>'
        f'<div class="ftc-value">{value}</div>'
        f'{change_html}</div>'
    )


def badge(text: str, color: str) -> str:
    return (
        f'<span class="ftc-badge" '
        f'style="background:{color}22;color:{color};border:1px solid {color}55;">{text}</span>'
    )


def section_header(title: str) -> str:
    return f'<div class="ftc-section">{title}</div>'


def inject_theme():
    """在 app.py 启动时调用一次，注入全局深色设计系统。"""
    st.markdown(build_theme_css(), unsafe_allow_html=True)


def candle_colors():
    """K线蜡烛：涨红跌绿（A股）。返回 (increasing, decreasing)。"""
    return THEME["up"], THEME["down"]


def style_fig(fig, kind: str = "generic"):
    """给 Plotly 图套深色模板：透明底融入卡片、网格弱化、深色字。原地修改并返回。"""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=THEME["text"]),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    fig.update_xaxes(gridcolor=THEME["border"], zerolinecolor=THEME["border"])
    fig.update_yaxes(gridcolor=THEME["border"], zerolinecolor=THEME["border"])
    if kind == "kline":
        inc, dec = candle_colors()
        for tr in fig.data:
            if tr.type == "candlestick":
                tr.increasing.line.color = inc
                tr.increasing.fillcolor = inc
                tr.decreasing.line.color = dec
                tr.decreasing.fillcolor = dec
    return fig
