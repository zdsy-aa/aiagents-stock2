# 整站 UI 升级：Clean SaaS 换肤 + 顶部导航布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 整站换肤为冷白 SaaS 风 + 把侧栏堆叠导航改为「顶部 5 大类水平导航 + 侧栏当前大类子页」，路由/功能不动。

**Architecture:** 改 `ui_theme.py` 色板与 CSS；新增 `views/nav_model.py`（大类→子页单源）+ `views/top_nav.py`（顶部导航）；改写 `views/sidebar.py`（按当前大类出子项、当前页高亮）；`app.py` 顶端调 `render_top_nav`。`page_router` 不变。

**Tech Stack:** Streamlit（原生 columns/button/primary 高亮）+ CSS，零第三方依赖。

**关键约束（已核对）：**
- `tests/test_ui_theme.py` **硬编码旧色值**（`THEME["up"]=="#e5384e"` 等）→ 换肤须同步改该断言（预期改动）。
- 现 `views/sidebar.py::render_sidebar()` 返回 `(api_key_status, period)`；底部「系统配置/状态/参数/帮助」段（约 251–322 行）须原样保留。
- 路由真相 = `show_*` session_state 标志（page_router 不动）；导航点击设标志、清其它即可（现有模式）。
- 全部 24 个页面标志：show_intraday/main_force/low_price_bull/small_cap/profit_growth/value_stock/chanlun/liumai/combo/stable/qizhang/chanlun_chart/current_strategy/sector_strategy/longhubang/news_flow/macro_analysis/macro_cycle/portfolio/smart_monitor/monitor/history/config（+ 首页=无标志）。
- 导航点击后 `st.rerun()` 保证顶部高亮/侧栏子项/内容一致刷新。
- develop on main；改 root/views → `docker compose build agentsstock`+`up -d agentsstock` recreate 生效。

---

## File Structure

| 文件 | 改动 |
|------|------|
| `ui_theme.py` | THEME 新色板 + build_theme_css（阴影/圆角/蓝 accent/primary 按钮/顶部导航样式） |
| `views/nav_model.py` | 新：NAV 大类→子页单源 + 纯函数 |
| `views/top_nav.py` | 新：render_top_nav（顶部 5 大类 + 页标题） |
| `views/sidebar.py` | 改写导航段为「当前大类子项+高亮」，保留底部系统段 |
| `app.py` | main() 顶端调 render_top_nav |
| `tests/test_ui_theme.py` | 改断言为新色值 |
| `tests/test_nav_model.py` | 新：nav_model 纯函数单测 |
| `tests/test_ui_pages_smoke.py` | 不变（全页回归保护）；新增首页含 5 大类断言 |

---

## Task 1: ui_theme 换肤（色板 + CSS）

**Files:** Modify `ui_theme.py`、`tests/test_ui_theme.py`

- [ ] **Step 1: 改 test_ui_theme.py 的色值断言（先失败）**

把 `test_theme_has_ashare_semantic_colors` 改为：
```python
def test_theme_has_ashare_semantic_colors():
    assert THEME["up"] == "#e11d48"       # 涨红
    assert THEME["down"] == "#059669"     # 跌绿
    assert THEME["bg"] == "#f8fafc"       # 冷白页底
    assert THEME["accent"] == "#2563eb"   # SaaS 蓝
```
并把 `test_build_theme_css_returns_style_block_with_tokens` 末尾追加：
```python
    assert "topnav" in css  # 顶部导航样式存在
```

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_ui_theme.py -q`
Expected: FAIL（旧色值断言不符）

- [ ] **Step 3: 改 THEME 色板**（ui_theme.py 顶部 THEME dict）

```python
THEME = {
    "bg":        "#f8fafc",   # 冷调极浅灰页底
    "panel":     "#ffffff",   # 面板/侧栏纯白
    "card":      "#ffffff",   # 卡片纯白
    "border":    "#e2e8f0",   # 冷灰边框
    "text":      "#0f172a",   # 主文字（近黑冷调）
    "text_dim":  "#64748b",   # 次文字
    "up":        "#e11d48",   # 涨（A股红）
    "down":      "#059669",   # 跌（A股绿）
    "accent":    "#2563eb",   # 交互强调（SaaS 蓝）
    "gold":      "#d97706",   # 点睛
}
```

- [ ] **Step 4: build_theme_css 追加/调整 CSS**

在 `build_theme_css()` 的 `</style>` 之前追加（卡片阴影、圆角、primary 按钮、顶部导航条样式）：
```python
/* === SaaS 精修 === */
.ftc-card {{ box-shadow: 0 1px 3px rgba(15,23,42,.06); border-radius: 10px; }}
/* primary 按钮=蓝底白字（顶部当前大类/侧栏当前页高亮） */
.stButton > button[kind="primary"] {{
    background: {t['accent']}; color: #fff; border: 1px solid {t['accent']};
}}
.stButton > button[kind="primary"]:hover {{ filter: brightness(1.08); color:#fff; }}
.stButton > button[kind="secondary"] {{
    background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']};
}}
.stButton > button[kind="secondary"]:hover {{ border-color: {t['accent']}; color: {t['accent']}; }}
/* 顶部导航条容器（render_top_nav 用 columns，套一层标识） */
.topnav-bar {{ border-bottom: 1px solid {t['border']}; margin-bottom: 4px; }}
.topnav-title {{ font-size: 1.4rem; font-weight: 800; color: {t['text']}; margin: 6px 0 12px; }}
```
（将 `.ftc-card` 原 border-radius 若已有则以新值为准；其余既有规则保留。）

- [ ] **Step 5: 跑确认通过**

Run: `python3 -m pytest tests/test_ui_theme.py -q`
Expected: PASS（全绿）

- [ ] **Step 6: Commit**

```bash
git add ui_theme.py tests/test_ui_theme.py
git commit -m "feat(ui): 换肤冷白SaaS色板 + 卡片阴影/primary按钮/顶部导航样式

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: views/nav_model.py 大类→子页单源

**Files:** Create `views/nav_model.py`、Test `tests/test_nav_model.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_nav_model.py
from views.nav_model import (NAV, all_flags, flag_to_category, current_category,
                             category_pages, category_default_flag)


def test_all_flags_covers_pages():
    flags = all_flags()
    for f in ("show_intraday", "show_qizhang", "show_chanlun_chart", "show_config", "show_history"):
        assert f in flags
    assert None not in flags


def test_flag_to_category():
    assert flag_to_category("show_qizhang") == "选股"
    assert flag_to_category("show_chanlun_chart") == "分析"
    assert flag_to_category("show_sector_strategy") == "策略"
    assert flag_to_category("show_portfolio") == "管理"
    assert flag_to_category("show_config") == "配置"
    assert flag_to_category("unknown") == "分析"


def test_current_category_from_state():
    assert current_category({}) == "分析"
    assert current_category({"show_qizhang": True}) == "选股"
    assert current_category({"show_longhubang": True}) == "策略"


def test_category_pages_and_default():
    names = [c for c, _, _ in NAV]
    assert names == ["分析", "选股", "策略", "管理", "配置"]
    assert category_default_flag("分析") is None         # 首页
    assert category_default_flag("配置") == "show_config"
```

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_nav_model.py -q`
Expected: FAIL（无 views.nav_model）

- [ ] **Step 3: 实现 views/nav_model.py**

```python
# views/nav_model.py
"""导航单源：大类 → 子页(标签, show_flag, help)。驱动顶部导航与侧栏；路由仍用 show_* 标志。"""

# (category, icon, [(label, show_flag 或 None=首页, help)])
NAV = [
    ("分析", "🔬", [
        ("🏠 股票分析-日", None, "返回首页，单只股票日线深度分析"),
        ("⏱️ 分时分析", "show_intraday", "仅按分钟线做纯短线技术面分析"),
        ("📐 缠论图解", "show_chanlun_chart", "缠论中枢/买卖点图 + 未来3天触发条件"),
    ]),
    ("选股", "🎯", [
        ("💰 主力选股", "show_main_force", "主力资金流向选股"),
        ("🐂 低价擒牛", "show_low_price_bull", "低价高成长筛选"),
        ("📊 小市值", "show_small_cap", "小盘高成长筛选"),
        ("📈 净利增长", "show_profit_growth", "净利润增长稳健筛选"),
        ("💎 低估值", "show_value_stock", "低PE+低PB+高股息+低负债"),
        ("🌀 缠论选股", "show_chanlun", "多级别缠论买点筛选"),
        ("🔱 六脉神剑", "show_liumai", "六维多头共振≥5红"),
        ("🔗 缠论×六脉", "show_combo", "缠论买点±3日内六脉5红"),
        ("🛡️ 稳定选股", "show_stable", "样本外验证的稳健买卖策略"),
        ("📈 起涨预测", "show_qizhang", "起涨C4策略 paper-tracking 观察"),
        ("📋 当前策略", "show_current_strategy", "全部策略脚本与说明只读总览"),
    ]),
    ("策略", "📊", [
        ("🎯 智策板块", "show_sector_strategy", "AI板块策略分析"),
        ("🐉 智瞰龙虎", "show_longhubang", "龙虎榜深度分析"),
        ("📰 新闻流量", "show_news_flow", "新闻流量监测与短线指导"),
        ("🌏 宏观分析", "show_macro_analysis", "宏观数据×行业映射×标的"),
        ("🧭 宏观周期", "show_macro_cycle", "康波×美林时钟×政策"),
    ]),
    ("管理", "💼", [
        ("📊 持仓分析", "show_portfolio", "投资组合分析与定时跟踪"),
        ("🤖 AI盯盘", "show_smart_monitor", "DeepSeek自动盯盘决策"),
        ("📡 实时监测", "show_monitor", "价格监控与预警"),
        ("📖 历史记录", "show_history", "查看历史分析记录"),
    ]),
    ("配置", "⚙️", [
        ("⚙️ 环境配置", "show_config", "系统设置与API配置"),
    ]),
]


def all_flags():
    """全部非空 show_* 标志（用于清其它页）。"""
    return [flag for _, _, pages in NAV for (_, flag, _) in pages if flag]


def flag_to_category(flag):
    """标志所属大类；未知/None → '分析'。"""
    for cat, _, pages in NAV:
        for (_, f, _) in pages:
            if f == flag:
                return cat
    return "分析"


def current_category(state=None):
    """据当前 session_state 的 show_* 标志反推大类；无标志=分析。state 可注入(测试)。"""
    if state is None:
        import streamlit as st
        state = st.session_state
    for flag in all_flags():
        if state.get(flag):
            return flag_to_category(flag)
    return "分析"


def category_pages(cat):
    for c, _, pages in NAV:
        if c == cat:
            return pages
    return []


def category_default_flag(cat):
    """大类落地页 = 首个子页的 flag（分析→None=首页）。"""
    pages = category_pages(cat)
    return pages[0][1] if pages else None
```

- [ ] **Step 4: 跑确认通过**

Run: `python3 -m pytest tests/test_nav_model.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add views/nav_model.py tests/test_nav_model.py
git commit -m "feat(ui): nav_model 大类→子页单源 + 纯函数(归类/当前大类/落地页)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: views/top_nav.py 顶部导航

**Files:** Create `views/top_nav.py`

无独立单测（依赖 st）；由 Task 5 UI 冒烟 + Task 6 端到端覆盖。

- [ ] **Step 1: 实现 views/top_nav.py**

```python
# views/top_nav.py
"""顶部水平主导航：5 大类 + 当前页标题。点大类→落地其首个子页(分析=首页)。"""
import streamlit as st

from views.nav_model import NAV, all_flags, current_category, category_default_flag


def _go(flag):
    for f in all_flags():
        st.session_state.pop(f, None)
    if flag:
        st.session_state[flag] = True
    st.rerun()


def render_top_nav():
    """主区顶端渲染 5 大类导航 + 当前页标题。"""
    cur = current_category()
    st.markdown('<div class="topnav-bar"></div>', unsafe_allow_html=True)
    cols = st.columns(len(NAV))
    for i, (cat, icon, _pages) in enumerate(NAV):
        with cols[i]:
            if st.button(f"{icon} {cat}", key=f"topnav_{cat}", width='stretch',
                         type=("primary" if cat == cur else "secondary")):
                _go(category_default_flag(cat))

    # 当前页标题（分明）
    title = "🏠 股票分析-日"
    for _, _, pages in NAV:
        for label, flag, _ in pages:
            if flag and st.session_state.get(flag):
                title = label
    st.markdown(f'<div class="topnav-title">{title}</div>', unsafe_allow_html=True)
```

- [ ] **Step 2: 语法检查**

Run: `python3 -c "import ast; ast.parse(open('views/top_nav.py').read()); print('syntax OK')"`
Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
git add views/top_nav.py
git commit -m "feat(ui): 顶部水平主导航 render_top_nav(5大类+当前页标题,primary高亮)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 改写 views/sidebar.py 导航段（当前大类子项 + 高亮）

**Files:** Modify `views/sidebar.py`

- [ ] **Step 1: 替换 render_sidebar 的导航段**（保留底部系统配置/状态/参数/帮助段不动）

把 `render_sidebar()` 中 `with st.sidebar:` 内、从首个导航按钮起到「系统配置」`st.markdown("### ⚙️ 系统配置")` 之前的**整段导航**（即旧的首页/分时按钮 + 三个 expander + 历史/配置按钮）替换为：

```python
    from views.nav_model import current_category, category_pages, all_flags

    api_key_status = False
    period = "1y"
    with st.sidebar:
        st.markdown("### 📈 智投 · 导航")
        cat = current_category()
        st.caption(f"当前分类：{cat}")
        for label, flag, help_txt in category_pages(cat):
            # 当前页(或首页 flag=None 且无任何标志) 高亮为 primary
            is_active = (st.session_state.get(flag) if flag
                         else not any(st.session_state.get(f) for f in all_flags()))
            if st.button(label, width='stretch', key=f"side_{flag or 'home'}",
                         help=help_txt, type=("primary" if is_active else "secondary")):
                for f in all_flags():
                    st.session_state.pop(f, None)
                if flag:
                    st.session_state[flag] = True
                st.rerun()

        st.markdown("---")
        # ===== 以下系统配置/状态/参数/帮助段保持原样 =====
```

（即：删掉旧的一长串 nav 按钮 + 三个 expander，换成上面这段「按当前大类出子项」；`st.markdown("### ⚙️ 系统配置")` 起的原有底部段一字不改保留，直到 `return api_key_status, period`。）

- [ ] **Step 2: 语法检查 + 现有 nav/theme 测试不回退**

Run:
```bash
python3 -c "import ast; ast.parse(open('views/sidebar.py').read()); print('syntax OK')"
python3 -m pytest tests/test_nav_model.py tests/test_ui_theme.py -q
```
Expected: `syntax OK` + PASS

- [ ] **Step 3: Commit**

```bash
git add views/sidebar.py
git commit -m "feat(ui): 侧栏改为当前大类子项+当前页primary高亮(保留系统配置段)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: app.py 接顶部导航 + 全页冒烟回归

**Files:** Modify `app.py`、`tests/test_ui_pages_smoke.py`

- [ ] **Step 1: app.py main() 顶端调 render_top_nav**

在 `app.py` 顶部 import 区加 `from views.top_nav import render_top_nav`；在 `main()` 内 `render_sidebar()` 之后、`route_page()` 之前插入：
```python
    # 顶部水平主导航（5 大类 + 当前页标题）
    render_top_nav()
```

- [ ] **Step 2: test_ui_pages_smoke.py 加首页含大类断言**

在文件末尾追加：
```python
def test_home_shows_top_nav_categories():
    at = AppTest.from_file("app.py", default_timeout=180).run()
    assert at.exception is None or at.exception == []
    btn_labels = " ".join(b.label for b in at.button)
    for cat in ("分析", "选股", "策略", "管理"):
        assert cat in btn_labels
```

- [ ] **Step 3: 跑 UI 冒烟全量（全页路由不回退 + 首页大类）**

Run: `python3 -m pytest tests/test_ui_pages_smoke.py -q`
Expected: PASS（全 17 页参数化 + 首页大类 + 既有用例全过；顶部导航/侧栏改造后路由不变）

- [ ] **Step 4: Commit**

```bash
git add app.py tests/test_ui_pages_smoke.py
git commit -m "feat(ui): app.py 接入顶部导航 + 首页大类冒烟

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 全量回归 + 重建镜像 + 真机预览

**Files:** 无（构建+验证）

- [ ] **Step 1: 全量回归**

Run: `python3 -m pytest tests/ -q`
Expected: 全绿（基线 290 + nav_model + 首页大类；0 failed，已知 news_flow 偶发可单独重跑）

- [ ] **Step 2: 重建镜像 + recreate**

Run:
```bash
docker compose build agentsstock
docker compose up -d agentsstock
```
Expected: 构建成功 + agentsstock1 healthy。

- [ ] **Step 3: AppTest 渲染若干页确认无异常 + 顶部大类在**

Run:
```bash
docker exec -w /app agentsstock1 python3 -c "
from streamlit.testing.v1 import AppTest
for flag in [None, 'show_qizhang', 'show_chanlun_chart', 'show_sector_strategy', 'show_config']:
    at = AppTest.from_file('app.py', default_timeout=180)
    if flag: at.session_state[flag] = True
    at.run()
    labels = ' '.join(b.label for b in at.button)
    ok = all(c in labels for c in ['分析','选股','策略','管理'])
    print(flag or 'home', 'exception:', at.exception, '| 顶部大类全在:', ok)
"
```
Expected: 每行 `exception: None`（或空）+ `顶部大类全在: True`；无 traceback。

- [ ] **Step 4: 真机预览（交付给用户）**

提示用户在 8503 网页查看新 UI（顶部 5 大类导航 + 冷白 SaaS 配色 + 侧栏当前大类子项 + 当前页高亮），逐项收集微调意见（色值/圆角/阴影/导航间距/分类归并），按反馈迭代。

- [ ] **Step 5: 无代码改动则跳过 commit。**

---

## Self-Review

**1. Spec 覆盖**
- 换肤冷白 SaaS 色板 + CSS 精修 → Task 1 ✅
- 顶部 5 大类水平导航(当前大类高亮) → Task 3 render_top_nav + Task 5 接入 ✅
- 侧栏当前大类子项 + 当前页高亮 → Task 4 ✅
- nav_model 单源 + 路由不动 → Task 2；page_router 未列改动 ✅
- 零第三方依赖（原生 columns/button/primary）→ 全程 ✅
- 测试（nav_model 纯函数 / theme 新色 / 全页冒烟回归 / 首页大类）→ Task 1/2/5 ✅
- 真机预览迭代 → Task 6 Step4 ✅

**2. Placeholder 扫描**：无 TBD/TODO；Task 4 用「替换整段导航、保留底部段」描述（必要的结构化改写说明，配合实读源码定位），非占位。

**3. 一致性**：nav_model 的 all_flags/current_category/category_pages/category_default_flag 在 top_nav(Task3)/sidebar(Task4) 调用签名一致；THEME 新色（Task1）被 test_ui_theme(Task1) 断言一致；primary 高亮机制（Task1 CSS）↔ top_nav/sidebar 用 type="primary"（Task3/4）一致；show_* 标志全集与 page_router 既有分派一致（路由不动）。
