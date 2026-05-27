# 缠论选股 — 设计

- 日期：2026-05-27
- 项目：aiagents-stock（Streamlit 多智能体 A 股分析应用）
- 状态：已确认，待写实现计划
- 关联架构：16/17 页 `show_*` 路由、各选股功能 `*_selector.py + *_ui.py` 模式、本地 route B K 线库（见 `aiagents-stock-git-and-analysis` / `aiagents-stock-deployment` 记忆）

## 背景与目标

在「选股板块」下新增**缠论选股**页：扫全市场，选出**最近 7 个交易日内**出现缠论买点（一买/二买/三买）的股票，并对每只给出**缠论卖点（一卖/二卖/三卖）与止损**作为离场参考。

**已确认关键决策**：
1. **算法严格度**：严格多级别缠论（用户在了解「简化版 vs 严格版」区别后明确选严格版）。
2. **级别**：本级别 = 日线，次级别 = 30 分钟。
3. **买点**：一买、二买、三买全做。
4. **卖点**：原始缠论 一卖、二卖、三卖（引擎一并识别），每只股附止损位 + 离场条件。
5. **数据源**：**仅 TDX 本地库** `tdx-data/database/kline/<code>.db`（表 `DayKline` + `Minute30Kline`）。无任何网络 / akshare / 东财。
6. **扫描方式**：每日批量预计算 + 落库，页面只读（秒开）。
7. **信号窗口**：最近 7 个交易日。
8. **股票池**：本地库全市场（~5532）；**排除**科创板（`688`/`689`）、北交所（`8`/`4`/`920` 开头）、ST/\*ST；保留沪深主板（`60`/`000`）、中小板（`002`）、创业板（`300`）。数据不足以构成笔/中枢的跳过。

## 缠论算法（严格多级别，本级别=日线 / 次级别=30分钟）

引擎对一段 OHLCV 顺序计算：

1. **包含关系处理**：相邻 K 线高低被包含时按方向合并（向上取高高、向下取低低），得到「无包含」序列。
2. **分型**：在无包含序列上识别顶分型（中间 K 线最高）/ 底分型（中间 K 线最低）。
3. **笔**：顶底分型交替、且中间至少满足缠论笔的间隔约束（独立 K 线数）连成「笔」，处理笔的成立与破坏。
4. **线段**：用特征序列 + 缺口规则把笔划分为线段（严格版核心难点之一）。
5. **中枢**：连续重叠的线段（次级别走势）构成中枢，记录 `ZG`（中枢上沿）/`ZD`（中枢下沿）/`GG`/`DD`；处理中枢的延伸 / 扩展 / 新生；递归到次级别。
6. **背驰**：趋势（≥2 个同向中枢）末端，比较该段与前一同向段力度（MACD 黄白线 + 红绿柱面积），并结合 30 分钟次级别背驰确认。

**买卖点定义（6 类）**：
- **一买**：下跌趋势末端，日线底背驰 + 30 分钟次级别底背驰确认。
- **二买**：一买后次级别上涨，再回踩**不破一买低点**、且 30 分钟回踩不创新低。
- **三买**：价格向上突破中枢（站上 `ZG`）后，次级别回抽**不跌破中枢上沿 `ZG`** 的低点（确认中枢支撑）。
- **一卖**：上涨趋势末端，日线顶背驰 + 30 分钟次级别顶背驰确认。
- **二卖**：一卖后次级别反弹**不创新高**、力度衰竭。
- **三卖**：价格向下跌破中枢（跌穿 `ZD`）后，次级别反抽**不站上中枢下沿 `ZD`** 的高点（确认中枢压制）。

1/2 类靠**背驰 + 前低/前高关系**，3 类靠**中枢突破后回抽不破边沿**。

## 架构（职责单一的单元，可独立测试）

| 单元 | 职责 / 接口 | 依赖 |
|---|---|---|
| `chanlun_engine.py`（新，核心） | 纯函数：`analyze(df_day, df_30m) -> ChanResult`（含分型/笔/线段/中枢列表 + 买卖点列表）。子函数 `merge_inclusion / find_fractals / build_strokes / build_segments / build_pivots / detect_divergence / detect_trade_points`。无 Streamlit / 无 IO。 | pandas、numpy |
| `chanlun_signal_db.py`（新） | `chanlun_signals.db` 落库，沿用 `BaseDatabase.conn()` 风格。表 `signals(code, name, board, signal_type, signal_date, buy_price, stop_loss, exit_rule, level, scan_date)`；方法 `upsert_signals / get_recent_signals(days) / clear_scan(scan_date)`。 | base_db |
| `chanlun_batch.py`（新，批量入口） | 收盘后跑：枚举本地 `kline/*.db` → 按股票池规则过滤 → 读日线+30分钟 → `engine.analyze` → 取最近 7 交易日买点（附对应卖点/止损）→ 写库。记录进度/耗时/失败计数到日志。 | engine、signal_db、codes.db（取名/判 ST） |
| `chanlun_selector.py`（新） | `get_chanlun_picks(days=7, types=...) -> (ok, DataFrame, msg)`，读库过滤，对齐其它 `*_selector.py` 返回三元组。 | signal_db |
| `chanlun_ui.py`（新） | `display_chanlun_selector()`：结果列表（代码/名称/板块/买点类型/信号日期/买入参考价/止损位/卖点离场条件）；可选缠论标注 K 线图（笔/中枢/买卖点）。 | selector、ui_theme、(可选)plotly |
| `app.py`（改） | 加 `show_chanlun` 标志 + 侧栏「🌀 缠论选股」按钮（归入「选股板块」）+ 路由段 `if show_chanlun: display_chanlun_selector(); return`，套路同其余选股页；并入清空其它 `show_*` 的导航逻辑。 | chanlun_ui |

## 数据流

`chanlun_batch`（每日）→ 读 TDX 本地 `DayKline`+`Minute30Kline` + `codes.db`(名称/ST) → `chanlun_engine.analyze` → 最近 7 交易日买卖点 → `chanlun_signal_db.upsert` → `chanlun_signals.db`。
页面：`chanlun_ui` → `chanlun_selector.get_chanlun_picks` → 读 `chanlun_signals.db` → 列表展示。页面**不**触发重算（秒开）。

## 调度（piggyback 现有 scheduler）

现有 `kline-updater` sidecar 每日 18:00 更新日线（见记忆）。缠论批量需 Python+pandas+引擎+本地数据，宜在 agentsstock 容器环境跑。**推荐**：日线更新成功后串联触发 `python3 chanlun_batch.py`。具体 wiring（新增 cron / 扩展 sidecar 在更新成功后 `docker exec` 触发 / 独立 compose 服务）在实现计划里定，默认「kline 更新成功 → 触发缠论批量」。批量需读 30 分钟数据，注意与线上 Streamlit 的 SQLite 读不冲突（只读，无写锁问题）。

## 卖出条件（随每只选中股给出）

- **止损（硬）**：跌破买点最低价（一买=底分型最低；二买=回踩低点；三买=回抽低点/中枢上沿 `ZG`）。
- **离场（缠论卖点）**：出现对应级别 **一卖/二卖/三卖**（顶背驰 / 反弹不创新高 / 跌破中枢后反抽不破 `ZD`），或跌破最近中枢下沿。
- 结果列：`buy_price` / `stop_loss`（具体价） + `exit_rule`（文字化缠论离场条件）。

## 测试策略（严格缠论无「标准答案」→ 用构造序列锚定行为）

- **引擎单测**（重点）：手工构造小型 K 线序列，逐步验证 `merge_inclusion`（包含合并方向）、`find_fractals`（顶/底分型位置）、`build_strokes`（笔成立/破坏）、`build_pivots`（中枢 `ZG`/`ZD` 区间）、`detect_divergence`（背驰判定）、`detect_trade_points`（6 类买卖点在已知结构上正确触发）。
- **链路测**：`chanlun_signal_db` 读写 + `clear_scan`；`chanlun_selector` 近 7 交易日过滤；`chanlun_ui` 走 AppTest（`show_chanlun` 页无异常），纳入页面回归（16→17 页）。
- **批量测**：小股票池（3~5 只本地票）跑 `chanlun_batch` 端到端，校验落库行为 + 股票池过滤（科创/北交/ST 被排除）。
- **真实抽查**：挑几只近期已知明显日线底背驰的票，人工核对引擎买点判定。
- 测试在容器 `agentsstock1` 内 `pytest`（pytest 非烤入需先 `pip install -q pytest`）。

## 不做（YAGNI）

- 不做盘中实时信号（只每日批量）。
- 不做多于「日线 + 30 分钟」的级别组合。
- 不做自动交易 / 历史回测 / 胜率统计。
- 不引入新第三方依赖（缠论引擎自实现，纯 pandas/numpy）。
- 不用任何网络数据源（严格只读 TDX 本地库）。
- 不在页面端触发全市场重算（只读库）。

## 风险 / 取舍

- **严格缠论歧义大**：线段划分（特征序列 vs 笔破坏）、严格背驰判定无统一标准，不同实现结果不一致；引擎是工程大头，靠构造序列单测锚定行为，真实信号需人工复核（选股=初筛漏斗，非下单信号）。
- **批量耗时**：全市场 ~5532 ×（日线+30分钟）多级别计算，单线程估 5~18 分钟；放收盘后批量可接受，必要时多进程并行（实现计划评估）。
- **30 分钟数据完整性**：已抽样 300/300 本地库均有 `Minute30Kline`（~2 年）；批量时对个别数据不足者跳过并记日志。
- **次新股 / 数据过短**：笔/中枢算不出的跳过，不报错。
