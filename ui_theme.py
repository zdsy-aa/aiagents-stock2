# ui_theme.py
"""深色 Fintech 全局设计系统：主题色板、全局 CSS、可复用组件、Plotly 深色模板。
全站 16 页同处一次 Streamlit run，启动调一次 inject_theme() 即全继承。"""

THEME = {
    "bg":        "#f8fafc",   # 冷调极浅灰页底（slate-50）
    "panel":     "#ffffff",   # 面板/侧栏纯白
    "card":      "#ffffff",   # 卡片纯白
    "border":    "#e2e8f0",   # 冷灰边框（slate-200）
    "text":      "#0f172a",   # 主文字（近黑冷调，slate-900）
    "text_dim":  "#64748b",   # 次文字（slate-500）
    "up":        "#e11d48",   # 涨（A股红，rose-600）
    "down":      "#059669",   # 跌（A股绿，emerald-600）
    "accent":    "#1d4ed8",   # 交互强调（靛蓝 blue-700，深稳重）
    "gold":      "#d97706",   # 点睛（amber-600）
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
    background: {t['card']}; border: 1px solid {t['border']}; border-radius: 10px;
    padding: 14px 16px; margin: 8px 0;
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
/* 顶部品牌条（精简单行） */
.top-nav {{
    background: {t['panel']}; padding: 0.5rem 0.9rem; border-radius: 8px; margin-bottom: 0.6rem;
    border: 1px solid {t['border']}; border-left: 3px solid {t['accent']};
}}
.nav-title {{ font-size: 1.15rem; font-weight: 800; color: {t['text']}; letter-spacing: .5px; }}
.nav-subtitle {{ color: {t['text_dim']}; font-size: 0.85rem; font-weight: 400; }}
.agent-card {{
    background: {t['card']}; padding: 1.1rem; border-radius: 8px; margin: 0.8rem 0;
    border: 1px solid {t['border']}; border-left: 3px solid {t['accent']};
}}
.decision-card {{
    background: {t['card']}; padding: 1.3rem; border-radius: 8px; margin: 1rem 0;
    border: 1px solid {t['border']}; border-left: 3px solid {t['accent']};
}}
.warning-card {{
    background: {t['card']}; padding: 1.1rem; border-radius: 8px; margin: 0.8rem 0;
    border: 1px solid {t['border']}; border-left: 3px solid {t['gold']};
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

/* === SaaS 精修 === */
.ftc-card {{ box-shadow: 0 1px 3px rgba(15,23,42,.06); border-radius: 10px; }}
/* primary 按钮=蓝底白字（顶部当前大类 / 侧栏当前页高亮） */
.stButton > button[kind="primary"] {{
    background: {t['accent']}; color: #fff; border: 1px solid {t['accent']};
}}
.stButton > button[kind="primary"]:hover {{ filter: brightness(1.08); color: #fff; }}
.stButton > button[kind="secondary"] {{
    background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']};
}}
.stButton > button[kind="secondary"]:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
/* 顶部导航条 */
.topnav-bar {{ border-bottom: 1px solid {t['border']}; margin-bottom: 4px; }}
.topnav-title {{ font-size: 1.4rem; font-weight: 800; color: {t['text']}; margin: 6px 0 12px; }}
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
        template="plotly_white",
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
