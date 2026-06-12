# 分维度共性挖掘 — 新增「行业」维度 设计

**日期**：2026-06-13
**关联**：`2026-06-12-grouped-param-mining-design.md`、`2026-06-12-fib-bbi-macd-commonality-design.md`
**状态**：设计定稿，待 review

## 背景与命题

前序分维度挖掘已证：**单套参数在全市场凑不出 ≥50% 共性**（双条件 AND 覆盖率上限 ~0.29；放松到 ≥50% 只剩松网角，lift 塌到 ~2、precision ~0.12）。已有维度（板块/市值/波动率）中波动率最强（低波动起涨 lift 4.63），市值微弱，板块温和。

**本次命题**：单套参数全市场不行，但**分到更细的子组后，某个子组 + 某套参数可能凑得出 >50% 共性**。新增**行业维度**继续验证；同时把"是否凑得出 >50%"做成显式的**达标视图**。

## 范围

- 维度：板块 / 市值 / 波动率 / **行业（新）**，全维度。
- 方案：A（斐波+MACD，3200组）+ B（BBI+MACD，400组）= 3600 组合全跑，买卖双向。
- 阈值：**>50%**（组内 coverage > 0.50 即"达标"）。

## 行业数据

- **源 = baostock `query_stock_industry()`**（证监会行业分类）。已是项目依赖、不走东财不被封。
- 实测：5529 行 / **84 个大类**（如 `C39计算机、通信和其他电子设备制造业`、`C27医药制造业`）；fields=`[updateDate, code, code_name, industry, industryClassification]`，行业字段在下标 3。
- **粒度 = 大类（84）+ 股票数 ≥30 门槛**：universe 内每个行业的股票数 ≥30 才赋标签，否则该股 → None（不进行业分组，仍计 ALL/板块/市值/波动率）。预计幸存 ~30-40 个大行业；小行业再被组级 seg≥3000 门槛二次滤掉。
- 股票池 = `events_labeled.csv` 去重 6 位码（同 universe）。

## 组件设计

### 1. 数据层 — `data/profit_mining/fetch_industry_snapshot.py`（新）
仿 `fetch_mktcap_snapshot.py` 契约。

- 输入：events universe 4415 码。
- 处理：baostock 登录 → `query_stock_industry()` 全量拉取 → `sh.600000`/`sz.000001` 前缀转 6 位 → 空行业字段跳过 → 只保留 universe 内的码。
- 输出：`stock_industry_snapshot.csv`，**契约 = `代码 / 行业 / 采集日期`**（代码 zfill6）。
- 容错：baostock 间歇失败重试 1 次；最终 0 行抛错（不静默写空表）；当天已存在则跳过（保留 fetch_mktcap 同款行为）。
- 运行：容器内（baostock 已装）；直连 baostock 不走 akshare gateway。

### 2. 分组层 — `data/profit_mining/group_dims.py`（改）
- 新增 `industry_group(industry)` → `f"行业={industry}"` 或 None（industry 为空/None → None）。
- 新增辅助：从行业映射 + 计数构造"幸存行业集"（≥30 只）；不在集合内的股票 industry → None。
- 行业归桶逻辑与板块同构（逐股单一标签），不引入新的窗口切分。

### 3. 挖掘层 — `data/profit_mining/mine_commonality.py`（改三处）
- `_group_ctx()`：懒加载 `industry_map`（读 `stock_industry_snapshot.csv` + 应用 ≥30 门槛）。
- `_proc` / `accumulate_stock(df, groups=...)`：`groups` 多带一个 `industry` 标签；在 `accumulate_stock` 内 append 到 `shared`（**整股复用同一窗口计数**，与 board/size 同路径，几乎零额外算量——不同于波动率的按拐点切窗）。
- `_dim_of(group)`：识别 `行业=` 前缀，归到"行业"维度。

### 4. 达标视图（>50%）+ 产物
每个维度产两类榜：

- **分组达标榜_{维度}_*.csv（新）**：组内 `coverage > 0.50` 的参数，按 coverage 降序 Top N。直接回答"哪个子组 + 哪套参数能凑出 >50% 共性"。列含 group / plan / side / pct / 参数 / coverage / lift / precision / 样本数。
- **分组uplift榜_{维度}_*.csv（保留现有）**：每组最优参数 + uplift（lift_group − lift_all，及 ratio）。
- **分组挖掘总览_*.md**：含行业维度结论。

产物落 `data/commonality_reports/`（gitignored）+ 拷归档 `/home/tdxback/report/*_<时间戳>.*`。

## 数据流

```
fetch_industry_snapshot.py (baostock) → stock_industry_snapshot.csv
                                              │
mine_commonality._group_ctx() 懒加载 industry_map(+≥30门槛)
                                              │
accumulate_stock(df, groups={board,size,vol_cuts,industry})  ← 每股
   行业=逐股单标签 → shared 计数复用
                                              │
finalize → coverage/lift/precision per (group,plan,side,pct,params)
                                              │
   ├─ write_grouped_reports → 分组uplift榜_行业_*.csv（现有逻辑，_dim_of 识别行业）
   └─ 达标榜筛选 coverage>0.50 → 分组达标榜_行业_*.csv（新）
```

## 算量

行业是最便宜维度（逐股单标签）。相比上次 11 组 ~30min，加 ~35 行业组估 **~40-50min @ NPROC10**，内存可控（向量化计数已优化）。先跑 500 股 checkpoint 估 ETA。

## 测试（TDD，python3 合成数据，容器内跑）

- `fetch_industry_snapshot`：`sh./sz.` 前缀→6位；空行业字段跳过；全空抛错；当天已存在跳过。
- `industry_group` + ≥30 门槛：满足/不满足门槛、空行业 → None。
- `accumulate_stock` 加行业组的**守恒校验**：各行业组计数之和 **≤** ALL（注意：因小行业=None，行业维度不必全覆盖 ALL，故是 ≤ 而非 ==，区别于板块/市值的 ==）。

## 收尾约定

- 研究脚本（features/mine_commonality 等）保持 untracked（CLAUDE.md 约定）。
- `fetch_industry_snapshot.py` 仿 `fetch_mktcap_snapshot.py` 先例：在 **main** 提交并 push stock2。
- 现行分支 = main（项目已改为 main 上开发）。
- 每个步骤随时更记忆。

## 不做（YAGNI）

- 不做申万/通达信行业（仅证监会大类）。
- 不做行业子级（门类/中类/小类切换）。
- 不改方案 A/B 的参数网格本身（沿用现有 3600 组大网格）。
- 不改全市场共性主榜（write_reports）逻辑。
