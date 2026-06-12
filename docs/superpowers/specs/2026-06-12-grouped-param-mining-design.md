# 分维度参数挖掘（Grouped Param Mining）设计

- 日期：2026-06-12
- 作者：Claude + 用户
- 背景模块：`data/profit_mining/`（方案A/B 涨跌前期共性挖掘）

## 1. 目标与动机

现状：一套参数网格对**全市场**所有股票统一评估，得到全市场口径的 coverage / lift /
precision。问题是——一套参数在全市场反应平平（lift≈1.x），但很可能在**某个子群**里
显著增强（lift 跳升）。本设计在现有全市场挖掘之上**增加分组维度**，找出
「哪套参数在哪个分组里好、比全市场强多少」。

核心产出（头条指标）：每（维度×组×side）的**最优参数 + 对全市场的 lift 提升 uplift**。

非目标（本轮不做，YAGNI）：
- 行业维度（组多、样本碎，推迟）。
- 维度交叉（板块×市值×波动率），本轮只做**边际式**（每维度独立切）。
- 样本外/分年验证（独立的后续工作）。
- 只评估全市场 Top-K 参数的省算法（会漏掉「全市场平平、组内强」的参数，与目标冲突）。

## 2. 分组维度（边际式，共 10 组 + ALL 基线）

| 维度 | 组数 | 取值 | 数据来源 | 口径 |
|------|------|------|----------|------|
| 板块 | 4 | 沪主板/深主板/中小板/创业板 | `events_labeled.csv` 的 `板块` 列（现成） | 按股，点-in-time 严谨 |
| 市值 | 3 | 小/中/大盘 | akshare 全市场快照拉取 | 按股；**当前快照近似**，对老事件有漂移+幸存者偏差（报告注明） |
| 波动率 | 3 | 低/中/高 | K线计算 `vol20=mean((H−L)/C,20)` | **按事件**：每个信号拐点 bar 的 vol20 落桶，同股不同时点可落不同桶，点-in-time 严谨 |

- 历史数据里板块仅含上述 4 类（无科创板/北交所）。
- `ALL` 组 = 全市场基线，保留用作 uplift 分母，等于现有的全市场榜。

## 3. 方案选择

**采用方案1：扩展 `accumulate_stock`，一遍过同时累加 ALL + 各分组。**

理由：信号 `sig` 每股每 (plan,params,side) 只算一次，被该股所属各组共享；分组只增加
**轻量的字典累加**，不增加信号计算，运行时间仍十几分钟级。

否决方案2（按组过滤股票池跑 N 遍）：板块/市值要 N× 运行时间，且**波动率按事件无法靠
过滤股票池实现**（它是股票内时变的）。
否决方案3（只评估全市场 Top-K 参数）：会漏掉「全市场平平、组内强」的参数，与目标直接冲突。

## 4. 分桶口径与标定

桶边界先用一个轻量标定 pass 算好、固化进 `group_buckets.json`，保证可复现。

- **板块**：直接用 events 字段，无需标定。
- **市值**：拉一次 akshare 快照存 `stock_mktcap_snapshot.csv` → 全市场总市值**三分位**得小/中/大盘切点；一股一桶。
- **波动率**：标定 pass 遍历全股，在每个事件拐点 bar 取 `vol20` → 全市场分布**三分位**得低/中/高切点；主 pass 里每个事件按其拐点 vol20 落桶。

`group_buckets.json` 结构：`{市值:{cuts:[c1,c2],counts:[..]}, 波动率:{cuts:[c1,c2],counts:[..]}, 标定时间}`。

**边界与缺失处理（消歧）：**
- 市值快照查不到该股（退市/次新/快照缺）→ 该股**不参与市值分组**（仍计入 ALL / 板块 / 波动率）。市值榜会注明被纳入股票数。
- 波动率 `vol20` 用 `rolling(20)`；事件拐点 bar 不足 20 根历史 → `min_periods` 允许用现有根数算出的振幅均值落桶（不丢事件），与标定 pass 同一算法保持一致。
- 三分位归桶统一用「左闭右开 + 最高桶含上界」，标定与主 pass 共用同一函数，避免边界不一致。

## 5. 数据结构与累加键

- **现状键**：`(plan, side, pct, params)` → `[seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all]`
- **新键**：`(group, plan, side, pct, params)`，`group ∈ {"ALL","板块=创业板",...,"市值=小盘",...,"波动率=高",...}`

每股分组成员身份：
- 板块、市值：整股级，一个标签，该股**所有窗口**进对应组。
- 波动率：事件级，同股不同窗口可进不同 vol 桶。

实现要点（保住「信号只算一次」）：
- 信号 `sig`、累积和 `csum` 仍每股每 (plan,params,side) 只算一次。
- `tally` 接收一组「窗口结构」`[(group_label, starts, ends, seg_total, bars_pos), ...]`：
  - 板块/市值整股复用同一份 `starts/ends`，对同一 `csum` 向量化计数一次，结果分别 `_merge`
    进 `ALL`、`板块=X`、`市值=Y`（同一份数字累加进 3 个键，零额外信号计算）。
  - 波动率在 `_win_arrays` 阶段按拐点 vol20 把该股窗口**预切成 ≤3 个子集**
    （`starts_lo/ends_lo`…），对同一 `csum` 分别做 3 次区间和，累加进 `波动率=低/中/高`。
- 内存：键数 ≈ 11组 × 3600 × 2 side × 3 pct ≈ 237k 个 6-int 列表 ≈ 几十 MB/worker，可控。

新增/改动函数：
- `_load_groups(df, code)` → 该股 `板块`、`市值桶`、按 pct 预切的波动率窗口子集。
- `accumulate_stock` 的 `tally` 改为遍历窗口结构列表。
- `out` 键加 `group` 前缀；`finalize` / `write_reports` 按 group 分文件。

## 6. uplift 计算、样本门槛与报告

**uplift（头条）**：对每 `(group,plan,side,pct,params)`，查同 `(plan,side,pct,params)` 的 `ALL` 组 `lift_all`：
- `uplift = lift_group − lift_all`（绝对）
- `uplift_ratio = lift_group / lift_all`（相对倍数）
- 主排序：**uplift 绝对值降序**。

**样本门槛（防噪声/防 lift 爆表）**：
- 组级：`seg_total_group ≥ 3000`，不足标 `low_sample_flag` 且不进主榜。
- 行级：`fires_all_group ≥ 300`，不足则剔除（避免少量点火 lift 假高）。
- 阈值定为配置常量，跑完看分布可微调。

**输出文件**（`data/commonality_reports/`，归档到 `/home/tdxback/report/` 带 `_<ts>` 后缀）：
- `分组uplift榜_板块_<ts>.csv` / `_市值_<ts>.csv` / `_波动率_<ts>.csv`：各组 Top30 按 uplift 降序、过门槛。
  - 列：`group, plan, side, pct, <参数列>, seg_total, coverage, lift_group, lift_all, uplift, uplift_ratio, precision, low_sample_flag`
- `分组挖掘总览_<ts>.md`：每（维度×组×side）一行最优参数 + lift_group + vs全市场 + uplift + 覆盖 + 样本；高亮 **uplift_ratio ≥ 1.3** 的「分组显著增强」条目。
- 全市场 ALL 榜照旧出（等于现有那套），与分组榜互不影响。

头条结论形态（示例，跑完真填）：
> `fib N20/0.5/0.01/8-17-9` 全市场 lift 1.4，但在创业板组 lift 2.6（uplift +1.2，1.9×）。

## 7. 执行流程

```
fetch_mktcap_snapshot.py   (一次/已存在则跳过)
        ↓ stock_mktcap_snapshot.csv
calibrate_buckets.py       (~1-2min, 无信号计算)
        ↓ group_buckets.json
mine_commonality.py        (主跑, NPROC=10, ~12-15min)
  _proc(code): df=_load_kline; 板块=events查表; 市值桶=快照+cuts;
               每pct窗口按拐点vol20切3子集; accumulate_stock 累加 ALL+板块+市值+波动率
        ↓
  finalize + uplift(查ALL基线) + 样本门槛
        ↓
  写 分组uplift榜_{板块,市值,波动率}_<ts>.csv + 分组挖掘总览_<ts>.md (+ ALL榜照旧)
```

容器/挂载：`agentsstock1`（或 `chanlun-updater`）挂载 host 的 `data/`，改 host 的 `.py` 即生效；
脚本路径 `/app/data/profit_mining/`。市值快照拉取若被东财限流，失败退出并提示走代理/重试。

## 8. 校验

扩展 `_verify_opt.py`，新增分组守恒断言（在几只股上跑）：
- 板块各组计数之和 == ALL 组计数（每个 6 元计数器逐项相等）。
- 市值各组计数之和 == ALL 组计数。
- 波动率三桶计数之和 == ALL 组计数。
这一举抓出分组逻辑的漏算/重算 bug。沿用本轮已验证的「优化版 vs 参考实现逐键比对」手段保证 ALL 组本身仍与原实现一致。

## 9. 产物清单（归档 `/home/tdxback/report/`）

- `stock_mktcap_snapshot.csv`、`group_buckets.json`
- `分组uplift榜_板块_<ts>.csv` / `_市值_<ts>.csv` / `_波动率_<ts>.csv`
- `分组挖掘总览_<ts>.md`
- 运行日志 `grouped_mining_<ts>.log`

预计耗时：标定 ~2min + 主跑 ~12–15min。
