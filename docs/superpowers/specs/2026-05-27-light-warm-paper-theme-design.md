# 浅色「暖米白/纸质」主题 — 设计

- 日期：2026-05-27
- 项目：aiagents-stock（Streamlit 多智能体 A 股分析应用）
- 状态：已确认，待实现
- 关联：取代前序深色 Fintech 主题（spec `2026-05-27-dark-fintech-ui-redesign-design.md` / 已上线 main@`4e23338`）

## 背景与目标

深色主题上线后，用户反馈希望整体改回浅色，且「纯白太刺眼」，要求柔和不刺眼的白（米白/纸质）。**取消主题切换方案**（曾短暂讨论），只做这一套浅色。

因前序深色主题已把样式集中到 `ui_theme.py` 的 `THEME` dict + token 驱动的 `build_theme_css()` / `style_fig()`，本次只需**整体替换色板 + 切 config base + 几处写死值**，无需改架构、布局、路由、组件结构。

## 色板（暖米白/纸质，THEME）

| token | 值 | 说明 |
|---|---|---|
| bg | `#f7f5f0` | 暖米白页底 |
| panel | `#fffdf9` | 侧栏/面板（近白） |
| card | `#ffffff` | 卡片纯白 |
| border | `#e6e0d4` | 暖灰边框 |
| text | `#2b2b2b` | 主文字（深灰，非纯黑） |
| text_dim | `#6b7280` | 次文字 |
| up（涨） | `#e5384e` | A股红，白底加深 |
| down（跌） | `#0a9d63` | A股绿，白底加深（原 `#0ecb81` 在白上发飘） |
| accent | `#0891b2` | 强调青蓝（原 `#22d3ee` 在白上几乎不可见） |
| gold | `#c98a00` | 点睛/风险，白底加深 |

涨红跌绿/强调/金均为白底做了对比度加深，保留 A 股语义。

## 改动点（全走现有 token，面小）

1. **`ui_theme.py`**：`THEME` → 上表；`style_fig()` 的 Plotly 模板 `plotly_dark → plotly_white`（transparent 底/grid 走 token 自动跟随）；蜡烛色经 `candle_colors()` 自动变深红/深绿。
2. **`.streamlit/config.toml`**：`base="light"`、backgroundColor `#f7f5f0`、secondaryBackgroundColor `#fffdf9`、textColor `#2b2b2b`、primaryColor `#0891b2`。
3. **`monitor_manager.py`**：写死卡片色 → 白卡 `#ffffff` / 边框 `#e6e0d4` / 阴影改淡 `rgba(0,0,0,0.06)`。
4. **`app.py`**：成交量柱 `marker_color='lightblue'` → `#0891b2`（浅底上 lightblue 发白看不清）。
5. **`tests/test_ui_theme.py`**：`test_theme_has_ashare_semantic_colors` 的 `bg/accent/up/down` 字面断言 → 新值（其余测试走 token，不改）。

`build_theme_css` 的卡片/区块标题竖条/按钮 hover/表格/expander/tabs/滚动条/遗留类（top-nav/agent/decision/warning）全是 token 驱动，自动变浅，无需逐条改。

## 验证

容器 `agentsstock1` 内 `pytest tests/`（16 页 AppTest + ui_theme + 删除验证）全绿（pytest 非烤入，重建后需先 `pip install -q pytest`）→ `docker compose up -d --build agentsstock` 部署 healthy → 浏览器抽查：白底不刺眼、红涨绿跌在浅底清晰、K线/量图在白卡上清晰、侧栏/表格/expander 统一浅色。

## 不做（YAGNI）

- 不做亮/暗主题切换开关（用户决定只留浅色一套）。
- 不改布局/路由/业务逻辑/组件结构。
- 不引入新依赖。
- 全仓非 UI 的浅色残留（邮件模板 notification_service、PDF 生成器 pdf_generator/main_force_pdf_generator）本就该浅底，不动。

## 风险 / 取舍

- 因 config base 与注入 CSS 同为浅色（不像之前强行浅覆盖深 base），原生控件天然一致，无 portal 弹层色差问题。
- 透明底 Plotly 在白卡上需确认不发灰（plotly_white 模板已是白底体系）。
- 需全仓 grep 现行深色字面值（`#1e242e/#272e3a/#313a48/#3f4856/#f0f3f8/#b4bdca` 及旧 `#22d3ee` 等）确认无遗漏的写死处。
