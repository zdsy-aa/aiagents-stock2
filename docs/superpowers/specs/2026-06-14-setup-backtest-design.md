# 起涨打分模型回测 设计

2026-06-14。用最佳配置(fwd_10_10 GBDT, OOS AUC0.679/lift1.88)在 OOS(2024-01~2025-10)按模型分选股、
固定持有+止盈止损,算**扣成本收益曲线 vs 上证**,看是否真可用(比 AUC/lift 更接近实战)。

## 背景
打分模型 v2 证明:多因子 GBDT 在 fwd_10_10(后10日涨≥10%)有 OOS AUC0.68/lift1.88。但 AUC/lift 不等于
可交易收益。本回测把"模型分"落成具体交易(选股/入场/止盈止损/成本),出净值曲线+对比基准,判断实战价值。

## 前提改动
`setup_panel.npz` 当前缺 code。`setup_modeling` 的 `_panel_proc`/`build_panel` **加 codes 列**(向后兼容,
main 不读 codes 不受影响);重建 panel 一次,使每行 (X, Y, date, **code**) 可定位股票。

## 策略(已与用户确认)
- **打分**:载 panel → 训练集(date≤2023-12-31)上重训 GBDT(标签=fwd_10_10,沿用 v2 的中位填充/负样本下采样R5)→ 给 OOS(2024-01-01~2025-10-31) 每个 bar 打分 → 信号集 (date, code, score)。
- **选股**:每交易日按 score 降序取 **top-N=10** 只等权;**同一 code 持仓中不重复买**(已持则跳过该日该票)。
- **入场**:信号日 t 收盘出信号 → **t+1 开盘**买入(防当日前视)。
- **退出**(买入后逐日 OHLC,先到先执行):① High ≥ entry×1.10 → +10% 止盈;② Low ≤ entry×0.95 → −5% 止损;③ 持满 **10** 个交易日 → 当日收盘卖。(同一日内若同时触止盈与止损,**保守取止损**。)
- **成本**:每笔往返扣 **0.2%**(佣金+印花税+滑点近似),从该笔净收益中减。
- **基准**:上证指数(index_sh000001)同期累计收益。

## 收益/组合口径
- **笔级**:每笔交易记录 (code, 入场日, 出场日, 毛收益, 净收益=毛−0.2%, 退出原因∈{止盈,止损,到期})。统计:笔数、胜率(净>0)、平均净收益、收益分布、三类退出占比。
- **组合级(等权日度净值)**:可用资金均分到当日活跃持仓;每笔从入场到出场按其个股日收益贡献。简化口径:按"槽位法"——固定 `SLOTS`(=N×maxhold=100 槽,近似满仓上限),每笔占 1 槽资金;日净值 = 各活跃笔当日浮动盈亏加权。产出日度净值序列。
- 指标:累计收益、年化、Sharpe(日收益年化,无风险=0)、最大回撤;对比上证:超额累计、超额年化。

## 组件
1. `setup_modeling.py`:`_panel_proc` 返回加 `codes`(np.full(n, code));`build_panel` 收集并 `np.savez(... codes=...)`。**仅此小改**,main/评估不变。
2. `setup_backtest.py`(新):
   - `score_oos(panel)`:载 panel,fwd_10_10 列,train mask 重训 GBDT(复用 setup_modeling.fit_gbdt/_subsample_train/col_median/fill_na),OOS 打分 → 结构化 (dates[], codes[], scores[]) 仅 OOS 有效行。
   - `simulate_trade(ohlc, entry_idx, tp=0.10, sl=-0.05, maxhold=10, cost=0.002)`:纯函数,给某股 OHLC(numpy O/H/L/C) 与入场行 entry_idx(=t+1),按规则算 (exit_idx, gross, net, reason)。entry=open[entry_idx]。可单测。
   - `run_backtest(dates, codes, scores, topn=10, ...)`:逐日选 top-N、去重在持、对每笔取该股 kline(缓存 _load_kline)定位 t+1→simulate_trade,汇总 trades。
   - `portfolio_curve(trades, oos_dates, slots=100)`:槽位法日度净值。
   - `metrics(curve, bench_curve)`:笔级+组合级指标。
   - `main()`:score→run→curve→metrics→写报告。
3. 复用:setup_modeling(fit_gbdt/_subsample_train/col_median/fill_na/time_split_mask)、mine_commonality._load_kline、_load_index_close。不动其他脚本。

## 交付
- 报告 `起涨回测_{ts}.md`:策略参数、笔级统计、组合净值指标(累计/年化/Sharpe/回撤)、对比上证超额、退出原因分布、结论(扣成本后是否跑赢基准/是否可用)。
- `起涨回测_净值_{ts}.csv`(日期,策略净值,上证净值)+ `起涨回测_逐笔_{ts}.csv`。归档 report/。

## 测试(合成序列,python3 test_*.py)
- `simulate_trade`:构造入场后某日 High 破 +10% → 止盈、净=+10%−0.2%;某日 Low 破 −5% → 止损;横盘到第10日 → 到期收盘价收益;同日同破止盈止损 → 取止损。
- 成本扣减正确(net=gross−cost)。
- `run_backtest` 选股:合成 (date,code,score) 验证每日取分最高 N、在持去重。
- `metrics`:已知净值序列验证 累计/最大回撤 数值。

## 非目标(YAGNI)
- 不做参数寻优(就 N=10/TP10/SL5/hold10/cost0.2%)。
- 不做 logistic 对比、不做其他标签(只 fwd_10_10 GBDT)。
- 不含停牌/涨跌停不可成交的精细撮合(用 t+1 开盘近似;涨跌停限制作为已知局限注明)。
- 不上线、不接前台。

## 数据依赖
setup_panel.npz(加code后) + 本地日K(_load_kline,退出模拟) + index_sh000001.csv(基准)。
