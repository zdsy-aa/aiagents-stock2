# 整站 UI 升级：Clean SaaS 换肤 + 顶部导航布局 设计

2026-06-20。替换现行「浅色暖米白」主题，并把导航从「侧栏一堆按钮堆 expander」改为
「**顶部水平主导航（5 大类）+ 侧栏显示当前大类子页**」。目标：更现代、更合理、更便捷、更分明。

现状：UI 集中在 `ui_theme.py`（THEME 10 token + `build_theme_css()` + `inject_theme()` 在 app.py 调一次→全继承）；
导航在 `views/sidebar.py`（一长串 `st.button` 分组在 expander 里，无当前页高亮）；路由在 `views/page_router.py`
（按 `show_*` session_state 标志分派，本设计**不改路由**）。

## 目标
1. **换肤**：冷色浅白 SaaS 风（Linear/Notion 感），A股涨红跌绿+点睛色保留并调冷。
2. **顶部主导航**：主内容区顶端一排「分析 / 选股 / 策略 / 管理 / ⚙配置」，当前大类高亮。
3. **侧栏次级**：侧栏只显示「当前大类」的子页按钮，当前页高亮；底部保留系统状态/参数/配置。
4. 零第三方依赖（不引入 streamlit-option-menu 等）；页面内容/功能/路由逻辑全不动。

## 非目标（YAGNI）
- 不改任何页面的业务逻辑 / 数据 / 路由分派（`page_router.route_page` 不动）。
- 不引入第三方 UI 组件库（用原生 `st.columns`+`st.button`+CSS）。
- 不改 17 个页面各自内部布局。
- 不做响应式/移动端适配（桌面网页为主）。

## 配色（THEME token 替换）
| token | 现行 | 新（冷白 SaaS） |
|---|---|---|
| bg | #f7f5f0 | **#f8fafc** |
| panel | #fffdf9 | **#ffffff** |
| card | #ffffff | **#ffffff**（+柔和阴影） |
| border | #e6e0d4 | **#e2e8f0** |
| text | #2b2b2b | **#0f172a** |
| text_dim | #6b7280 | **#64748b** |
| accent | #0891b2 | **#2563eb**（SaaS 蓝） |
| up | #e5384e | **#e11d48**（A股红） |
| down | #0a9d63 | **#059669**（A股绿） |
| gold | #c98a00 | **#d97706** |

CSS 风格：卡片加柔和阴影 `0 1px 3px rgba(0,0,0,.06)`、圆角 12→10px、按钮/输入/表格/expander/tabs 统一冷灰描边+蓝选中、滚动条冷灰、字体 system-ui/Inter 栈、标题字重收紧。新增**顶部导航条样式**（横向排布、当前大类蓝色高亮）。

## 导航架构（核心）
**单一数据源 `views/nav_model.py`**（纯数据 + 纯函数，可单测）：
```
NAV = [ (category_name, category_icon, [ (page_label, show_flag_or_None, help), ... ]), ... ]
```
- 5 大类与子页归并：
  - **分析** 🔬：🏠股票分析-日(flag=None=首页) / ⏱️分时(show_intraday) / 📐缠论图解(show_chanlun_chart)
  - **选股** 🎯：主力(show_main_force)/低价擒牛(show_low_price_bull)/小市值(show_small_cap)/净利增长(show_profit_growth)/低估值(show_value_stock)/缠论选股(show_chanlun)/六脉(show_liumai)/缠论×六脉(show_combo)/稳定选股(show_stable)/📈起涨预测(show_qizhang)/📋当前策略(show_current_strategy)
  - **策略** 📊：智策板块(show_sector_strategy)/智瞰龙虎(show_longhubang)/新闻流量(show_news_flow)/宏观分析(show_macro_analysis)/宏观周期(show_macro_cycle)
  - **管理** 💼：持仓分析(show_portfolio)/AI盯盘(show_smart_monitor)/实时监测(show_monitor)/历史记录(show_history)
  - **配置** ⚙️：环境配置(show_config)
- 纯函数：
  - `all_flags()` → 所有 show_* flag 列表（用于"清其它"）。
  - `flag_to_category(flag)` → flag 所属大类名；None/未知 → "分析"。
  - `current_category()` → 读 session_state 现有 show_* 标志，返回当前大类（无标志=分析）。
  - `category_pages(cat)` → 该大类子页列表。
  - `category_default_flag(cat)` → 该大类第一个子页的 flag（点大类时落地页）。

**`views/top_nav.py::render_top_nav()`**（主区顶端）：
- 一排 `st.columns(5)`，每列一个 `st.button(f"{icon} {cat}", type=...)`：当前大类 `type="primary"`（蓝高亮），其余 `type="secondary"`。
- 点某大类 → 清所有 `show_*` 标志 + 设该大类 `category_default_flag`（None 则停在首页）→ rerun。
- 顶端再渲染当前页标题（`st.markdown` 页名，分明）。

**`views/sidebar.py::render_sidebar()`**（改写）：
- 顶部 logo/标题。
- 渲染 `current_category()` 的子页按钮：当前页 `type="primary"`、其余 secondary；点子页=设该 flag+清其它（沿用现有清单逻辑，改为 `all_flags()` 统一清）。
- 底部保留：系统配置（API 状态/模型）、系统状态面板、分析参数（period 选择）、帮助。
- 返回 `(api_key_status, period)` 不变。

**`app.py::main()`**：在 `render_sidebar()` 之后、`route_page()` 之前，于主区顶端调 `render_top_nav()`；其余不变（route_page 仍按 flag 分派）。

## 数据流 / 当前页判定
- 当前页 = 现有 `show_*` 标志（page_router 不变）；大类 = `current_category()` 从标志反推。
- 顶部高亮当前大类、侧栏出当前大类子项、侧栏高亮当前页——三者都由现有标志驱动，**无需新增导航状态**。

## 错误处理 / 边界
- 无任何 show_* 标志（首页）→ 大类=分析、侧栏出分析子项、内容=日线主页（render_analysis_home）。
- 点大类落地页 flag=None（分析）→ 清空标志回首页。
- nav_model 是唯一归并来源；新增页面只在 NAV 加一行即自动进顶部/侧栏（可维护性）。

## 测试
- `views/nav_model.py` 纯函数单测：flag_to_category 正确归类（含 show_chanlun_chart→分析、show_qizhang→选股 等）、current_category 默认"分析"、all_flags 覆盖全部 17 页标志、category_default_flag 取首项。
- `ui_theme.build_theme_css()` 返回含新色值（断言含 `#2563eb`/`#0f172a`），且为合法 `<style>`（沿用现有 ui_theme 测试若有）。
- `tests/test_ui_pages_smoke.py`：**全 17 页（含 show_chanlun_chart/show_qizhang 等）经 app.py 渲染仍无异常**（顶部导航+侧栏改造后路由不变，回归保护）。
- 新增冒烟：默认首页（无 flag）渲染含顶部 5 大类导航文本。

## 上线 / 影响面
- 改 `ui_theme.py` + 新增 `views/nav_model.py`/`views/top_nav.py` + 改 `views/sidebar.py` + 改 `app.py`（顶端加一行）。
- 改 root/views 代码 → `docker compose build agentsstock` + `up -d agentsstock` recreate 才在网页生效。
- **真机预览迭代**：实现后在 8503 网页看真实效果，逐项微调色值/圆角/阴影/导航间距。
- develop on main，用户自行 push stock2。

## 风险
- 顶部水平导航为 Streamlit 自制（columns+button+CSS），是本次最大改动（中高风险）；靠 test_ui_pages_smoke 全页回归 + 真机预览兜底。
- 路由与页面内容零改动 → 功能不受影响，最坏只是样式/导航需微调。
