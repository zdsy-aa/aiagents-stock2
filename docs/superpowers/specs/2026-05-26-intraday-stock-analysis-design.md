# 股票分析改名（-日）+ 新增「股票分析-分时」（纯短线技术面） — 设计

- 日期：2026-05-26
- 项目：aiagents-stock
- 状态：已确认，待写实现计划

## 背景与目标

前端「🏠 股票分析」是一条完整的多智能体流水线（技术面[日线] + 基本面 + 季报 + 资金面 +
情绪 + 新闻 + 风险 → 讨论 → 决策），由 `StockAnalysisEngine.run_full_analysis(symbol, period)` 驱动。

目标：
1. 把「股票分析」改名为「**股票分析-日**」（仍是现有日线分析，行为不变）。
2. 其下新增「**股票分析-分时**」：**只按分钟线做纯短线技术面分析**（跳过基本面/季报/新闻/资金面/情绪），
   粒度支持 **5min 与 30min（页面可选）**。

## 关键事实（探查结论）

- 数据能力已具备：网关 `akshare_gateway.AKShareGateway`（实例 `akshare_gw`，含 `.local` 本地库 /
  `.tdx` 四级降级）的 `LocalDBClient.get_kline(symbol, kline_type, limit, ...)` 支持分钟表
  （`_PERIOD_TO_TABLE`: `'5min'→Minute5Kline`、`'30min'→Minute30Kline`…），route B 本地库对
  **全 A 股已下载 5min + 30min**。
- 但 `data_source_manager.get_stock_hist_data` 写死 `period="daily"`，且网关 `call('stock_zh_a_hist_min_em')`
  写死 `kline_type='1min'`——分钟能力没暴露到上层。
- 东财分钟接口 `stock_zh_a_hist_min_em` 在本机被 IP 封锁（`BLOCKED_EM_FUNCS`），故分钟取数走
  **本地 → TDX**，不走 AKTools/akshare。
- `get_kline` 返回中文列 DataFrame（日期/开盘/收盘/最高/最低/成交量/成交额），分钟/小时保留完整时间戳。
- 引擎 `run_full_analysis` 已支持 `enabled_analysts` 门控；但第 47 行 `get_financial_data` 是
  **无条件调用**（需改为受 `fundamental` 门控，纯技术面才真不拉基本面）。
- 导航：`🏠 股票分析` 是默认首页视图（清空所有 `show_*` 标志即回到它），其余功能各设 `show_X` 标志。

## 改动清单（按层）

### 1. 网关 `akshare_gateway.py`
新增 `AKShareGateway.get_minute_kline(symbol, freq, limit)`：
- `freq ∈ {'5min','30min'}`。
- 先 `self.local.get_kline(symbol, kline_type=freq, limit=limit)`（route B 本地，全市场已有）；
  返回空再 `self.tdx.get_kline(symbol, kline_type=freq, limit=limit)`。
- 不走 AKTools/akshare（东财分钟被封）。返回中文列 DataFrame 或 None。

### 2. 数据层 `stock_data.py`
新增 `StockDataFetcher.get_minute_data(symbol, freq, limit)`：
- 调 `akshare_gw.get_minute_kline`，把中文列重命名为 `Date/Open/High/Low/Close/Volume`、
  `Date` 转 datetime 并设为索引（与现有 `_get_hk_stock_data` 同款转换）。
- 返回的 DataFrame 直接可喂给现有 `calculate_technical_indicators`（指标算法与周期无关）。
- 取不到返回 `{"error": ...}`（与现有 `_get_chinese_stock_data` 一致的失败约定）。

### 3. 引擎 `stock_analysis_engine.py`
`run_full_analysis(symbol, period="1y", enabled_analysts=None, freq=None)`：
- 新增 `freq: Optional[str] = None`。`freq` 非空时，技术面数据改用
  `self.fetcher.get_minute_data(symbol, freq, limit)`（limit 见下）而非 `get_stock_data`。
- 落库 `period` 标签用 `freq`（如 `"30min"`）以区分日线分析。
- 把第 47 行 `financial_data = self.fetcher.get_financial_data(symbol)` 改为受
  `enabled_analysts.get('fundamental')` 门控（默认 enabled_analysts 仍全开，日线行为不变）。
  附带收益：纯技术面分时分析不再触发 #3 的东财资金流 RemoteDisconnected。

### 4. 前端 `app.py`
- 首页按钮 label `🏠 股票分析` → `🏠 股票分析-日`（key `nav_home` 不变，清除逻辑不变，仅 label）。
- 其正下方新增按钮 `⏱️ 股票分析-分时`（key `nav_intraday`）→ 设 `st.session_state.show_intraday=True`，
  并清除其它 `show_*`。
- 把 `show_intraday` 加入各导航按钮（含 `nav_home`）的清除列表，沿用现有 `show_portfolio` 同款模式，
  确保切换到任何其它视图时分时视图被关闭。
- 新增路由块（与其它 `show_*` 同级）：`if show_intraday: display_intraday_analysis(); return`。
- 新增 `display_intraday_analysis()`：
  - 股票代码输入 + 粒度单选（`5分钟`→`5min` / `30分钟`→`30min`）+「开始分析」按钮。
  - 调 `StockAnalysisEngine().run_full_analysis(symbol, period=freq, freq=freq,
    enabled_analysts={'technical': True, 'fundamental': False, 'fund_flow': False,
    'risk': False, 'sentiment': False, 'news': False})`。
  - 复用现有结果渲染组件展示技术面 + AI 短线决策（不新造可视化）。

## 数据流（分时）
代码 + 粒度 → `run_full_analysis(freq)` → `get_minute_data` → 网关 `get_minute_kline`（本地→TDX）
→ `calculate_technical_indicators`（分钟 bar）→ 技术面 Agent → 讨论 → 短线决策 → 渲染。

## 关键默认值（不暴露给用户，YAGNI）
- bar 数 `limit`：`5min → 240`（≈5 交易日）、`30min → 240`（≈30 交易日），
  够算 MA60 等指标 + 近期上下文。

## 错误处理
- 本地无该票分钟库 → 网关自动降级 TDX；都失败 → `get_minute_data` 返回 error，视图提示
  「无法获取分钟数据」，不崩。
- 分时分析跳过基本面/资金面/新闻/情绪，天然不触发 #3 的东财报错。

## 测试
- 引擎单测：`run_full_analysis(symbol, freq='30min', enabled_analysts={'technical':True,其余False})`
  用真实本地库返回结果，且断言 **未调用** `get_financial_data`（桩/spy 验证门控）。
- 数据层单测：`get_minute_data('600519','30min',240)` 返回含 `Date/Open/High/Low/Close/Volume`
  的 DataFrame、行数 ≤ limit、索引为含分钟的 datetime。
- 网关单测：`get_minute_kline('600519','5min',240)` 命中本地库返回非空、列为中文 OHLCV。
- 部署后页面手测：5min / 30min 各跑一只票，结果正常渲染；「股票分析-日」行为不变。

## 不做（YAGNI）
- 分钟级的基本面/资金面/新闻接入。
- 1min / 15min / 60min 粒度（本地未下载，后续需要再加，网关 `_PERIOD_TO_TABLE` 已留映射）。
- 分时专属图表可视化（先复用现有渲染）。
- 改动现有日线分析的任何行为。
