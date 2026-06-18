# 缠论图解 + 未来3天条件信号 页 设计

2026-06-18。新增网页：输入股票代码 → 画缠论日线 K 线图，标注**中枢 / 所有买点 / 卖点**；
在图上向后扩出**未来 3 个交易日的「决策区」**，把触发各类买卖点所需的**关键价位画成横线**，
图下方文字逐条说明「若某未来交易日满足某价格条件 → 出现某买/卖点信号」。

复用现有缠论引擎 `chanlun_engine.analyze_one(df) -> ChanResult`（已暴露 `pivots`[中枢 ZG/ZD/GG/DD/i_start/i_end]
与 `points`[TradePoint: kind/i/price/note]）。前端用 Streamlit + plotly（app.py 既有技术栈）。

## 目标
- 输入任一 A 股代码 → 取本地日K → 缠论分析 → plotly 蜡烛图标注中枢矩形 + 买卖点 markers（hover 显示理由）。
- 图上向后扩 3 个交易日为阴影「决策区」，叠加关键价位横线（中枢 ZG/ZD、最近 1买/1卖 价、前低/前高）。
- 图下逐条文字条件：6 类买卖点各给「关键价位 + 触发表述」；1买/1卖含 MACD 背驰，标注「近似/需确认」。
- 全只读、不下单、不发邮件、不接选股。

## 非目标（YAGNI）
- 不接 30 分钟次级别（仅日线本级别，保图清晰）。
- 不做实时盘中刷新（取本地日K最新批）。
- 节假日不特判（未来交易日仅用 `is_cn_trading_day` 跳周末；偶遇节假日日期标注略有偏差，可接受）。
- 不编造未来虚拟 OHLC（决策区只画阈值横线与阴影，不画假 K 线）。
- 不改 chanlun_engine（只读其 ChanResult）。

## 架构 / 组件
新文件 `chanlun_chart_ui.py`（root），函数：
- `display_chanlun_chart()`：Streamlit 页面入口——输入框 + 分析按钮 → 取数 → 分析 → 画图 → 文字条件 + 免责。
- `_next_trading_days(last_date, n=3) -> list[date]`：从最后 bar 日期起，用 `intraday_quote.is_cn_trading_day` 推后 n 个交易日。
- `build_chart(df, result, future_days)`：组装 plotly Figure（蜡烛 + 中枢矩形 + 买卖点 markers + 关键价位 hline + 决策区 vrect）。
- `forward_conditions(result, df) -> list[dict]`：基于当前 ChanResult 反推各类买卖点关键价位与条件文本。

数据流：
```
代码输入 → mine_commonality._load_kline(code) 取日K(取最近 120 根)
        → chanlun_engine.analyze_one(df) → ChanResult
        → forward_conditions(result, df)  → 条件列表
        → build_chart(...) → plotly 图  +  st 渲染条件文字
```

## 图形标注（build_chart，plotly）
- **蜡烛图**：最近 120 根日K（go.Candlestick，x=日期）。
- **中枢**：每个 `Pivot` 画半透明矩形（add_shape rect：x0=日期[i_start], x1=日期[i_end], y0=ZD, y1=ZG），标注 ZG/ZD 数值。
- **买卖点**：`points` 按 kind 上色——买点(1/2/3买)红色▲在低侧、卖点蓝/绿▼在高侧；hover 文本=kind+note(理由)。
- **关键价位横线**（add_hline，延伸贯穿到决策区）：最近中枢 ZG/ZD；最近未配对 1买/1卖 价；近端前低/前高。
- **决策区**：x 轴在末根后扩 3 个交易日，用 add_vrect 画阴影 + 顶部标注「未来3日决策区（无真实K线）」。

## 未来条件逻辑（forward_conditions，核心）
基于当前结构取关键价位，逐类生成 `{signal, direction, level_price, text, confidence}`：
- **3买**：`level = 最近中枢.ZG`。文本「若价站上 ZG={level} 后回踩不破 → 3买（中枢突破）」，confidence=明确。
- **3卖**：`level = 最近中枢.ZD`。「若跌破 ZD={level} 后反抽不破 → 3卖」，明确。
- **2买**：`level = 最近 1买 price`（存在最近 1买 时）。「若回踩不破 1买低点 {level} → 2买」，明确。
- **2卖**：`level = 最近 1卖 price`（存在时）。「若反弹不破 1卖高点 {level} → 2卖」，明确。
- **1买**：`level = 近端前低`（最近一个向下笔/段低点）。「若跌破前低 {level} 且下跌力度较前段衰减(MACD 底背驰) → 1买」，confidence=**近似/需背驰确认**。
- **1卖**：`level = 近端前高`，对称，**近似/需确认**。
- 仅在对应结构存在时输出该条（如无中枢则跳过 3买/3卖）；每条附「最早可能日期 = 未来第1交易日」。

## 错误处理 / 边界
- 代码无效 / 本地无 K 线 / 不足分析（<60 根）：页面提示「无数据或样本不足」，不抛异常。
- 无中枢 / 无 1买1卖：对应条件项跳过，不报错；至少展示已有的中枢与买卖点标注。
- `_load_kline` 列约定：DatetimeIndex + Open/High/Low/Close（与现有缠论/回测一致）。

## 测试
- `forward_conditions`：构造合成 `ChanResult`（含一个 Pivot ZG/ZD + 一个 1买 TradePoint）+ 合成 df，断言 3买/3卖 取 ZG/ZD、2买 取 1买 price、1买 取前低，且无中枢时不产 3买/3卖。
- `_next_trading_days`：给定一个周五日期，断言跳过周末返回下周一/二/三（monkeypatch 或真实 is_cn_trading_day）。
- 页面渲染冒烟纳入 `tests/test_ui_pages_smoke.py`（参数化加 `show_chanlun_chart`，空输入/无代码下渲染不崩）。
- 图形函数 `build_chart` 返回 plotly Figure 不崩（合成 df+result 冒烟，断言 isinstance go.Figure）。

## 上线 / 影响面
- 新增 `chanlun_chart_ui.py`（root，烤进镜像）+ `views/sidebar.py` 加「📐 缠论图解」按钮 + `views/page_router.py` 加 `show_chanlun_chart` 分派 + 冒烟标志。
- 改 root 代码：`docker compose build agentsstock` + `up -d agentsstock` recreate 才在网页生效。
- develop on main，用户自行 push stock2。

## 免责（页面显式）
缠论为结构化技术判断，非投资建议；「未来条件」是基于当前结构的推演，实际需后续 K 线走出确认；
1买/1卖 的背驰条件为近似提示，不保证成立。
