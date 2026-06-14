# 回测执行精细化(起涨回测 v2) 设计

2026-06-14。现有回测(fwd_10_10 GBDT·每日top10·固定+10%/-5%/持10日·扣0.2%)年化+8%/Sharpe1.54/回撤-5%
但跑输强牛市上证-18.7%(63%被止损打出、赢家早砍)。本迭代试**更精细执行**(移动止盈/趋势退出/大盘择时),
6 配置横向对比,看能否把薄 edge 转成跑赢/正超额。模型打分不变,只改执行。

## 背景
回测 v1 证明模型有薄 edge 但固定止盈止损在强牛市跑输 β。诊断:+10%固定止盈砍掉赢家、-5%紧止损 63% 被打出。
本迭代不改模型/标签/选股分,只改**退出规则 + 择时仓位**,对比哪种执行最优。

## 目标
- 一次 GBDT(fwd_10_10) 打分(复用 v1 score_oos),所有配置共用 (date,code,score)。
- 6 配置(退出模式 × 择时)各跑回测,出 笔级 + 组合 + vs 上证超额,横向对比。

## 退出模式(simulate_trade 加 mode 开关)
- `fixed`(基准,现有):High≥+10% 止盈 / Low≤-5% 止损(同日取止损) / 持满 10 日收盘卖。
- `trailing`(移动止盈):**无固定止盈顶**;跟踪入场后**最高 High**,当 Low ≤ 峰值×(1-0.08)(回撤8%)→ 卖(卖价取该回撤位近似=峰值×0.92);硬止损 Low≤入场×0.95(-5%);**最大持有 30 日**收盘卖。同日同破硬止损与回撤→取硬止损(保守)。
- `trend`(趋势退出):**收盘 Close < MA10(收盘)** → 次类按当日收盘卖(以触发日收盘价计收益);硬止损 Low≤入场×0.95;最大持有 30 日。MA10 用该股自身收盘 10 日均线(入场后逐日判)。
- 所有模式:收益毛=出场价/入场(入场=t+1开盘);净=毛-0.2%成本。

## 大盘择时(run_backtest 选股 gate)
- 预算上证(index_sh000001)收盘 MA20。某交易日 **上证收盘 < 上证MA20 → 该日不开新仓**(已持仓仍按各自退出规则)。
- 配置可开/关此 gate。

## 配置矩阵(6,全跑)
| 配置 | 退出 mode | 择时 gate |
|------|-----------|-----------|
| C0_fixed | fixed | 否(=v1基准) |
| C1_trailing | trailing | 否 |
| C2_trend | trend | 否 |
| C3_fixed_timing | fixed | 是 |
| C4_trailing_timing | trailing | 是 |
| C5_trend_timing | trend | 是 |

## 评估
每配置:笔级(总笔数/胜率净>0/平均净/退出占比) + 组合(累计/年化/Sharpe/最大回撤,槽位法同v1) + vs 上证超额。
报告含 **6 配置横向对比表** + 结论(哪个最优、是否转正超额、移动止盈/趋势/择时各自效果)。

## 组件(扩 setup_backtest.py,不动其他)
- `simulate_trade(o,h,l,c, entry_idx, mode="fixed", tp=0.10, sl=-0.05, maxhold=10, cost=0.002, trail=0.08, ma=None)`:
  - mode="fixed":现逻辑不变(向后兼容,现有测试仍过)。
  - mode="trailing":maxhold 由调用方传 30;跟踪峰值 High,回撤 trail 触发;硬止损 sl。
  - mode="trend":需传 `ma`(该股 MA10 数组,与 o/h/l/c 等长);收盘<ma 触发;硬止损 sl;maxhold 30。
- `_ma(c, n)`:numpy 简单移动均线(用于 trend mode 预算 MA10)。
- `run_backtest(dates, codes, scores, mode="fixed", maxhold=10, timing=False, idx_ma=None)`:加 mode 透传 simulate_trade、timing gate(用 idx_ma:date→是否risk-off);trend mode 每股算 MA10 传入。
- `main()`:score_oos 一次 → 预算上证MA20(择时)→ 循环 6 配置 run_backtest+portfolio_curve+metrics → 写横向对比报告。
- 复用:score_oos/portfolio_curve/metrics/_bench_curve/_load_kline/_load_index_close(现有)。

## 测试(合成序列,追加到 test_setup_backtest.py)
- fixed mode 回归:现有 4 个 simulate_trade 测试仍过(默认 mode="fixed")。
- trailing:构造涨到 +15% 后回撤 8% → trailing 卖在峰值×0.92(毛≈+5.8%? 实际峰值/入场×0.92-1);先破硬止损 → 取硬止损。
- trend:收盘跌破 MA10 当日卖(给定 ma 数组);未破则持到 maxhold。
- 择时 gate:run_backtest 某日 risk-off 不开新仓(可小合成验证 select 被跳过)——或单测 timing 判定函数。

## 非目标(YAGNI)
- 不改模型/标签/选股分/特征。
- 不做参数寻优(trail/ma/maxhold 固定上述值)。
- 不做行业中性、不做放宽止损变体(本轮只这 3 类执行)。
- 不上线、不接前台。

## 数据依赖
setup_panel.npz(含codes,已建) + 本地日K(_load_kline) + index_sh000001.csv(基准+择时MA20)。
