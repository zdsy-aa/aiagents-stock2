# 深色 Fintech 全局 UI 升级 — 设计

- 日期：2026-05-27
- 项目：aiagents-stock（Streamlit 多智能体 A 股分析应用）
- 状态：已确认，待写实现计划

## 背景与目标

应用现为浅色 + 紫色渐变主题（`app.py` 顶部 53–277 行一大段自定义 `<style>`，`.streamlit/config.toml` 仅 `base="light"`），16 个页面经 `st.session_state.show_*` 路由、全在同一次 `app.py` run 内渲染。

**目标**：把全站升级为一套**深色专业 Fintech 设计系统**，所有页面统一继承；同时删除两个学习资源入口。用 frontend-design 的设计思路落地（刻意、有辨识度、避免通用「AI 风」）。

**关键约束（Streamlit）**：不能像普通网站自由写前端，可用手段=`.streamlit/config.toml` 主题 token + `st.markdown(unsafe_allow_html=True)` 注入 CSS + Plotly 图表模板。优先用官方 token，CSS 只补 token 覆盖不到处（跨版本更稳）。

**已确认决策**：① 视觉方向=深色专业 Fintech（深底 + 涨红跌绿 + 数据卡片）；② 范围=全局设计系统一次到位（非逐页 bespoke）；③ 涨跌遵循 A 股惯例**涨红跌绿**。

## 架构（两层主题 + 一个复用模块）

**新增 `ui_theme.py`**（单一职责：集中主题与可复用 UI 片段，便于全站一致、便于改）：
- `inject_theme()`：在 `app.py` 启动时调用**一次**，注入全局 CSS 设计系统（**替换**现有 53–277 行 CSS 块）。因 16 页同处一次 run，注入一次即全页继承。
- 组件辅助：`metric_card(...)`、`badge(...)`、`section_header(...)` 等，输出统一样式的 HTML 片段（供各页复用，替代零散内联 HTML）。
- `style_fig(fig, kind='kline'|'generic')`：给 Plotly 图套深色模板（透明底融入卡片、网格弱化、涨红跌绿）。

**`.streamlit/config.toml`**：`[theme] base="dark"` + token：
```toml
[theme]
base = "dark"
primaryColor = "#22d3ee"            # 交互强调色（青）
backgroundColor = "#0e1117"         # 页底
secondaryBackgroundColor = "#161b22"# 面板/侧栏
textColor = "#e6e9ef"
font = "sans serif"
```
（`[server]` 段 port=8503/address 保持不变。）

## 配色系统（token，A 股语义优先）

| 用途 | 值 |
|------|-----|
| 页底 / 面板 / 卡片 | `#0e1117` / `#161b22` / `#1c2330` |
| 边框 | `#2a2f3a` |
| 主文字 / 次文字 | `#e6e9ef` / `#9aa4b2` |
| 涨（A股惯例） | 红 `#f6465d` |
| 跌（A股惯例） | 绿 `#0ecb81` |
| 交互强调（按钮/链接/聚焦） | 青 `#22d3ee` |
| 点睛/高亮 | 金 `#f0b90b`（少量） |

强调色（青）刻意避开红绿语义；它是「最易调的旋钮」，后续可换。

## 组件规范（统一到 token）

- **指标卡**：深色卡片 + 细边框 + 圆角；数值按涨跌染色（涨红跌绿），标签用次文字色。
- **区块标题**：左侧强调色竖条 + 标题字重层级。
- **按钮**：主（青实心）/ 次（描边）/ 危险（红）三态；统一圆角、hover/active 反馈。
- **侧栏导航**：深色面板背景，当前项高亮。
- **`st.dataframe` / `st.tabs` / `st.expander` / `st.info|warning|error`**：覆盖到 token 配色与边框。
- **滚动条**：深色细滚动条。

## 图表（Plotly 深色）

经 `ui_theme.style_fig()` 统一处理，应用点：
- `app.py`：K 线图（`go.Figure` @1399，`st.plotly_chart` @1463）、成交量图（@1467/@1484）。
- `smart_monitor_kline.py`：K 线（@293 等 `go.Figure`）。
- `news_flow_ui.py`：词云 scatter（@226）、热度 bar（@711）等 `go.Figure`/`px`。

K 线蜡烛：涨 `#f6465d` / 跌 `#0ecb81`；图背景透明以融入深色卡片；网格线弱化为低对比。

## 全 16 页覆盖与验证

1. 全局注入自动覆盖所有 `show_*` 页（history/monitor/main_force/low_price_bull/small_cap/profit_growth/value_stock/sector_strategy/longhubang/smart_monitor/portfolio/news_flow/macro_analysis/macro_cycle/config/intraday + 默认首页）。
2. 审计并迁移零散内联浅色/写死颜色的 HTML（如评级卡 `<h3 style=...>`，约在 app.py 1505–1595 区）到 token/辅助函数。
3. **全量 AppTest 跑 16 页**确认 `at.exception` 为空（按既有无头测试法，容器 `agentsstock1` 内）；再抽查若干页视觉。
4. `docker compose up -d --build agentsstock` 部署后真实页面复验（线上=镜像烤入代码）。

## 顺带删除（用户要求）

- 「📺 学习视频合集」`st.expander`（`app.py` 516–525）整段删除。
- 「📺 新手必看干货」注释死代码（`app.py` 289）清掉。

## frontend-design 技能的使用

实现阶段用 frontend-design：重启 Claude Code 后作为技能调用，或直接读其 `SKILL.md` 按「刻意选定 bold 方向、精确执行、避免通用 AI 美学」的原则落地。本设计方向已体现该思路。

## 风险 / 取舍

- Streamlit 自定义 CSS 选择器依赖内部 DOM、跨版本可能脆 → 优先 config.toml token，CSS 仅补缺；选择器尽量用稳定的 `data-testid`。
- 深色下长篇分析文字对比度/可读性需校（次文字色不能过暗）。
- Plotly 透明底需确认在各页卡片背景下不发灰。

## 不做（YAGNI）

- 不做亮/暗主题切换开关（本期只做深色一套）。
- 不重构页面业务逻辑/路由结构（只动视觉层与上述两处删除）。
- 不引入新前端框架/构建链（纯 Streamlit + CSS + Plotly）。
- 不做多语言/响应式断点专门适配（沿用 Streamlit 默认 `layout="wide"`）。
