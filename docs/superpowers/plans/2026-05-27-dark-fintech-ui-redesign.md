# 深色 Fintech 全局 UI 升级 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Streamlit A 股应用全站升级为一套深色专业 Fintech 设计系统（深底 + 涨红跌绿 + 数据卡片），并删除「学习视频合集」与「新手必看干货」两处。

**Architecture:** 新增 `ui_theme.py` 集中「全局 CSS 注入 + 可复用组件 HTML + Plotly 深色模板」；`.streamlit/config.toml` 设暗色 base + token 让原生组件自动变深；`app.py` 启动调一次 `inject_theme()` 替换原 53–277 行紫渐变 CSS；K线/量及其它 Plotly 图统一过 `style_fig()`。16 页同处一次 run，注入一次即全继承。

**Tech Stack:** Streamlit 1.57、Plotly、纯 CSS（`st.markdown(unsafe_allow_html=True)`）、pytest + `streamlit.testing.v1.AppTest`（容器 `agentsstock1` 内跑）。

**Spec:** `docs/superpowers/specs/2026-05-27-dark-fintech-ui-redesign-design.md`

---

## 执行约定（重要）

- 本项目惯例：在 `main` 上工作，**运行代码=镜像烤入的代码**，改完源文件需 `docker compose up -d --build agentsstock` 才对线上网页生效。开发期验证用 AppTest：`docker cp` 改过的文件进 `/app` 后在容器内跑 pytest（AppTest 是新 python 进程读新代码）。
- 测试在容器 `agentsstock1` 内跑：`docker exec agentsstock1 sh -c "cd /app && python3 -m pytest <file> -v"`。**前置**：容器内需有 pytest，若无先 `docker exec agentsstock1 python3 -m pip install -q pytest`。
- 每个 task 改完源文件后，先 `docker cp` 进容器再跑测试；测试绿了再 commit。
- 不用 worktree（沿用项目 main 工作习惯）。

## 文件结构

| 文件 | 职责 |
|------|------|
| `ui_theme.py`（新建） | `THEME`(色板dict)、`build_theme_css()`(纯函数返回CSS串)、`inject_theme()`、组件 `metric_card/badge/section_header`、`pct_color()`、`style_fig()` |
| `.streamlit/config.toml`（改） | `[theme] base="dark"` + token |
| `app.py`（改） | 删 53–277 CSS 块→`inject_theme()`；删「学习视频合集」(516–525)/「新手必看」(289)；K线/量过 `style_fig`；评级卡内联 HTML 迁移 |
| `smart_monitor_kline.py`（改） | K线图过 `style_fig` |
| `news_flow_ui.py`（改） | 各 Plotly 图过 `style_fig` |
| `tests/test_ui_theme.py`（新建） | ui_theme 纯函数单测 |
| `tests/test_ui_pages_smoke.py`（新建） | 16 页 AppTest 无异常 + 两处删除已生效 |

---

### Task 1: ui_theme.py — 色板 + build_theme_css()

**Files:**
- Create: `ui_theme.py`
- Test: `tests/test_ui_theme.py`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_theme.py -v"`
（先 `docker cp tests/test_ui_theme.py agentsstock1:/app/tests/`）
Expected: FAIL — `ModuleNotFoundError: No module named 'ui_theme'`

- [ ] **Step 3: 写最小实现**

```python
# ui_theme.py
"""深色 Fintech 全局设计系统：主题色板、全局 CSS、可复用组件、Plotly 深色模板。
全站 16 页同处一次 Streamlit run，启动调一次 inject_theme() 即全继承。"""

THEME = {
    "bg":        "#0e1117",   # 页底
    "panel":     "#161b22",   # 面板/侧栏
    "card":      "#1c2330",   # 卡片
    "border":    "#2a2f3a",
    "text":      "#e6e9ef",   # 主文字
    "text_dim":  "#9aa4b2",   # 次文字
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp ui_theme.py agentsstock1:/app/ui_theme.py && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_theme.py -v"`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add ui_theme.py tests/test_ui_theme.py
git commit -m "feat(ui): 深色Fintech色板与全局CSS build_theme_css"
```

---

### Task 2: ui_theme.py — 组件 pct_color / metric_card / badge / section_header

**Files:**
- Modify: `ui_theme.py`
- Test: `tests/test_ui_theme.py`

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 tests/test_ui_theme.py
from ui_theme import pct_color, metric_card, badge, section_header


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_ui_theme.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_theme.py -v"`
Expected: FAIL — `ImportError: cannot import name 'pct_color'`

- [ ] **Step 3: 实现（追加到 ui_theme.py 末尾）**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp ui_theme.py agentsstock1:/app/ui_theme.py && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_theme.py -v"`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add ui_theme.py tests/test_ui_theme.py
git commit -m "feat(ui): metric_card/badge/section_header/pct_color/inject_theme"
```

---

### Task 3: ui_theme.py — style_fig() Plotly 深色模板

**Files:**
- Modify: `ui_theme.py`
- Test: `tests/test_ui_theme.py`

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 tests/test_ui_theme.py
import plotly.graph_objects as go
from ui_theme import style_fig, candle_colors


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_ui_theme.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_theme.py -v"`
Expected: FAIL — `ImportError: cannot import name 'style_fig'`

- [ ] **Step 3: 实现（追加到 ui_theme.py 末尾）**

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp ui_theme.py agentsstock1:/app/ui_theme.py && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_theme.py -v"`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```bash
git add ui_theme.py tests/test_ui_theme.py
git commit -m "feat(ui): style_fig 给 Plotly 套深色模板+涨红跌绿蜡烛"
```

---

### Task 4: .streamlit/config.toml 暗色 token

**Files:**
- Modify: `.streamlit/config.toml`

- [ ] **Step 1: 写实现（整文件覆盖）**

```toml
[theme]
base = "dark"
primaryColor = "#22d3ee"
backgroundColor = "#0e1117"
secondaryBackgroundColor = "#161b22"
textColor = "#e6e9ef"
font = "sans serif"

[server]
port = 8503
address = "127.0.0.1"
```

- [ ] **Step 2: 校验**

Run: `python3 -c "import tomllib; d=tomllib.load(open('.streamlit/config.toml','rb')); assert d['theme']['base']=='dark' and d['theme']['primaryColor']=='#22d3ee' and d['server']['port']==8503; print('config OK')"`
Expected: `config OK`

- [ ] **Step 3: Commit**

```bash
git add .streamlit/config.toml
git commit -m "feat(ui): config.toml 切暗色 base + token"
```

---

### Task 5: app.py — 接入 inject_theme，删除原紫渐变 CSS 块

**Files:**
- Modify: `app.py`（删除 51–277 的 `# 自定义CSS样式 - 专业版` 注释起、到 `""", unsafe_allow_html=True)` @277 的整个 `st.markdown("""<style>...</style>""")` 块；在 import 段加 `from ui_theme import inject_theme, style_fig, metric_card, badge, section_header`；在 `st.set_page_config(...)`（36–41）之后调用 `inject_theme()`）

- [ ] **Step 1: 写删除/接入（编辑步骤，非新代码块）**

1. 在 app.py 顶部 import 区（`import plotly.express as px` 之后）加一行：
   ```python
   from ui_theme import inject_theme, style_fig, metric_card, badge, section_header
   ```
2. 删除从 `# 自定义CSS样式 - 专业版`（51 行）到 `""", unsafe_allow_html=True)`（277 行）的整段（即 `st.markdown("""<style> ... </style>""", unsafe_allow_html=True)`）。
3. 在 `st.set_page_config(...)` 闭合括号（41 行）之后、`show_current_model_info` 定义之前，加：
   ```python
   # 注入深色 Fintech 全局设计系统（全站 16 页同一次 run 内继承）
   inject_theme()
   ```

- [ ] **Step 2: AppTest 确认首页可渲染、无异常**

Run:
```bash
docker cp ui_theme.py agentsstock1:/app/ui_theme.py && docker cp app.py agentsstock1:/app/app.py
docker exec agentsstock1 sh -c "cd /app && python3 -c \"
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('app.py', default_timeout=120).run()
print('exception:', at.exception)
assert not at.exception
print('HOME OK')\""
```
Expected: `exception: []` 然后 `HOME OK`

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat(ui): app.py 接入 inject_theme，移除旧紫渐变CSS块"
```

---

### Task 6: app.py — 删除「学习视频合集」与「新手必看干货」

**Files:**
- Modify: `app.py`（删 516–525 的 `with st.expander("📺 学习视频合集"):` 整块；删 289 的注释行）
- Test: `tests/test_ui_pages_smoke.py`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `docker cp tests/test_ui_pages_smoke.py agentsstock1:/app/tests/ && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_pages_smoke.py -v"`
Expected: FAIL — `assert "学习视频合集" not in text`（当前仍在）

- [ ] **Step 3: 实现删除**

1. 删除 app.py 289 行整行（`#    st.info("📺 **新手必看干货**...")` 注释死代码）。
2. 删除 516–525 行整块：
   ```python
           # 学习资源
           with st.expander("📺 学习视频合集"):
               st.markdown("""
               **📢 B站干货合集**
               ...
               - 🧠 [投资认知提升合集](...)
               """)
   ```
   （含其上方 `# 学习资源` 注释行；注意保持周围缩进与逻辑结构完整。）

- [ ] **Step 4: 跑测试确认通过**

Run: `docker cp app.py agentsstock1:/app/app.py && docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_pages_smoke.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_ui_pages_smoke.py
git commit -m "feat(ui): 删除学习视频合集与新手必看干货入口"
```

---

### Task 7: app.py — K线/量图过 style_fig，评级卡内联HTML迁移

**Files:**
- Modify: `app.py`（K线 `st.plotly_chart(fig...)` @1463 前、量图 @1484 前各插 `style_fig`；评级卡内联 `<h3 style=...>` 区，约 1505–1595，迁移到深色 token）

- [ ] **Step 1: 应用 style_fig（编辑步骤）**

1. K 线：在 `st.plotly_chart(fig, use_container_width=True, ...)`（@1463）这一行**之前**插入：
   ```python
   fig = style_fig(fig, kind="kline")
   ```
2. 成交量：在 `st.plotly_chart(fig_volume, ...)`（@1484）**之前**插入：
   ```python
   fig_volume = style_fig(fig_volume, kind="generic")
   ```

- [ ] **Step 2: 迁移写死浅色的内联 HTML**

Run（先找出所有内联写死浅色/黑白的 HTML）：
```bash
grep -n 'background:#fff\|background: #fff\|color:#000\|color: #000\|background-color:#f\|#ffffff\|#f0f2f6' app.py
```
对每处：把写死的浅底/黑字改为深色 token（背景 `#1c2330`、文字 `#e6e9ef`、次文字 `#9aa4b2`、边框 `#2a2f3a`），评级展示优先改用 `metric_card()`/`badge()`。例如评级卡 `<h3 style="text-align:center;">{rating_color} {rating}</h3>` 这类居中标题：保留结构、确保未写死浅色即可（emoji 评级圆点在深色下正常）。grep 无结果则本步无改动。

- [ ] **Step 3: AppTest 分析相关页无异常**

Run:
```bash
docker cp app.py agentsstock1:/app/app.py
docker exec agentsstock1 sh -c "cd /app && python3 -c \"
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('app.py', default_timeout=120).run()
assert not at.exception, at.exception
print('HOME OK')\""
```
Expected: `HOME OK`

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat(ui): app.py K线/量图深色化 + 内联浅色HTML迁移"
```

---

### Task 8: smart_monitor_kline.py / news_flow_ui.py — 图表深色化

**Files:**
- Modify: `smart_monitor_kline.py`、`news_flow_ui.py`

- [ ] **Step 1: 应用 style_fig（编辑步骤）**

1. `smart_monitor_kline.py`：顶部加 `from ui_theme import style_fig`；在每个返回/渲染 `go.Figure` 前（如 @293 构造的 K线 fig，函数 return 之前）加 `fig = style_fig(fig, kind="kline")`（空图 `_create_empty_figure` 用 `kind="generic"`）。
2. `news_flow_ui.py`：顶部加 `from ui_theme import style_fig`；每处 `st.plotly_chart(fig, ...)`（@139/@252/@714/@886 等）之前对该 fig 调 `fig = style_fig(fig, kind="generic")`。

- [ ] **Step 2: AppTest smart_monitor / news_flow 页无异常**

Run:
```bash
docker cp smart_monitor_kline.py agentsstock1:/app/smart_monitor_kline.py && docker cp news_flow_ui.py agentsstock1:/app/news_flow_ui.py
docker exec agentsstock1 sh -c "cd /app && python3 -c \"
from streamlit.testing.v1 import AppTest
for flag in ('show_smart_monitor','show_news_flow'):
    at = AppTest.from_file('app.py', default_timeout=180)
    at.session_state[flag] = True
    at.run()
    assert not at.exception, (flag, at.exception)
    print(flag, 'OK')\""
```
Expected: `show_smart_monitor OK` / `show_news_flow OK`（news_flow 加载较慢，超时给足）

- [ ] **Step 3: Commit**

```bash
git add smart_monitor_kline.py news_flow_ui.py
git commit -m "feat(ui): 盯盘K线/新闻流图表深色化"
```

---

### Task 9: 全 16 页 AppTest 回归 + 部署 + 视觉抽查

**Files:**
- Test: `tests/test_ui_pages_smoke.py`（补全页遍历）

- [ ] **Step 1: 补全 16 页遍历测试**

```python
# 追加到 tests/test_ui_pages_smoke.py
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
```

- [ ] **Step 2: 跑全量 AppTest + 既有回归**

Run:
```bash
docker cp tests/test_ui_pages_smoke.py agentsstock1:/app/tests/
docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/test_ui_pages_smoke.py tests/test_ui_theme.py -v"
docker exec agentsstock1 sh -c "cd /app && python3 -m pytest tests/ -q"
```
Expected: 全 pass（16 页 + ui_theme 7 + 删除 1 + 既有 22 无回归）

- [ ] **Step 3: 部署到线上**

Run: `docker compose up -d --build agentsstock`
Expected: 重建成功、`agentsstock1` 变 healthy（`docker inspect -f '{{.State.Health.Status}}' agentsstock1` → healthy）

- [ ] **Step 4: 视觉抽查**

打开 `http://<host>:8503`：确认深色生效、涨红跌绿、K线图深色融入卡片、侧栏/表格/expander 深色统一、「学习视频合集」已消失。如有写死浅色残留，回到对应 task 修。

- [ ] **Step 5: Commit（如步骤4有补修）**

```bash
git add -A && git commit -m "feat(ui): 全16页深色回归通过并部署"
```

---

## Self-Review（plan vs spec）

- **主题机制（config token + 全局CSS注入）** → Task 1/2/4/5 ✓
- **配色 token（涨红跌绿/强调青）** → Task 1（THEME）、Task 3（蜡烛）✓
- **组件规范（卡片/徽章/区块标题/按钮/侧栏/表格/expander/tabs/滚动条）** → Task 1（CSS）+ Task 2（组件）✓
- **Plotly 深色（app.py / smart_monitor_kline / news_flow_ui）** → Task 3/7/8 ✓
- **全16页覆盖 + AppTest 验证** → Task 9 ✓
- **删除学习视频合集 + 新手必看** → Task 6 ✓
- **frontend-design 思路** → 体现在配色/组件/对比度取舍（实现期可重启调用技能复核）
- 占位符扫描：无 TBD；唯一「按 grep 结果迁移」处给了具体命令+映射规则+示例，非空泛。
- 命名一致性：`inject_theme/build_theme_css/style_fig/metric_card/badge/section_header/pct_color/candle_colors/THEME` 全程一致。
