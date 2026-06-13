# 蓄势期特征共性挖掘（mine_setup_commonality）设计

2026-06-13。复用 mine_presetup 的「起涨前蓄势窗口 + 段级覆盖率」框架，但把信号库从动量类
（MACD金叉/BBI/斐波）换成**蓄势期特征**（低波动率收敛/缩量/箱体盘整/筹码集中），L1+L2 遍历，
找起涨前 **coverage>0.5 且 lift 显著>1** 的共性。

## 背景与动机
前一轮 mine_presetup 证明：动量信号（斐波回踩/BBI上穿/MACD金叉）在起涨前蓄势期 **lift≈1.0（零预测力）**——它们是突破之后才亮的滞后信号。本任务换用**蓄势期本身的特征**重挖，验证假设：低波动收敛/缩量/箱体/筹码集中等"蓄势态"特征，在起涨前是否真比基线更集中（lift>1）。

## 目标
- 信号库 = 蓄势期特征（4 类），L1 单信号 + L2 任意两两 AND。
- 窗口/口径完全复用 mine_presetup：zz6 起涨前蓄势窗口（近=[上一涨段起点,L] gap≤20 / 远=[L-7,L]，含波谷L、截止L无泄漏）、仅 buy 向、段级覆盖率（窗口内任一 bar 亮即该段命中）。
- 重点指标：**coverage>0.5 且 lift>1**（对照动量信号 lift≈1，看蓄势特征是否有真 edge）。
- **零回归**：不修改 mine_presetup.py / mine_commonality.py（仅 import 复用）。

## 信号库 `presetup_signals.py`（逐 bar 布尔 Series，参数化）
每个信号 = `(name:str, series_fn)`；series_fn(df[, ctx]) → 布尔 numpy 数组（长度 n）。NaN/不足回看的 bar 记 False。

**① 低波动率收敛 lowvol(win, q)** — 6 个：`win∈{10,20,30} × q∈{0.2,0.3}`
- ret = Close.pct_change(); v = ret.rolling(win).std();
- fires = v ≤ v.rolling(120, min_periods=40).quantile(q)（波动率跌到自身近 120 日低分位 = 收敛）。

**② 缩量 dryup(win, ratio)** — 4 个：`win∈{20,60} × ratio∈{0.7,0.8}`
- fires = Volume ≤ ratio × Volume.rolling(win).mean()。（无 Volume 列的股票该信号全 False。）

**③ 箱体盘整 box(win, width)** — 4 个：`win∈{20,30} × width∈{0.10,0.15}`
- rng = (HHV(Close,win) − LLV(Close,win)) / (LLV(Close,win)+1e-9);
- fires = rng ≤ width。（近 win 日价格振幅在窄带内 = 横盘箱体。）

**④ 筹码集中 chip(lo, hi)** — 3 个：`(50,80)`、`(60,85)`、`深度超跌(0,30)`
- 逐股用 `turnover_features.chip_series(df, turn)` 得逐 bar `获利盘`%（前 60 bar NaN→False）；
- fires = lo ≤ 获利盘 ≤ hi（前两档=筹码集中/锁仓；第三档 获利盘<30 = 深度超跌/套牢，蓄势底部特征）。
- 依赖该股 turnover 序列；缺失则该股 chip 类信号全 False（其余三类不受影响）。

**L1 合计 ≈ 17；L2 = 任意两两 AND** C(17,2)=136 → 总 ≈153 组合。signal 名用可读串（如 `lowvol_w20_q0.2`、`chip_50_80`）。

## 累加与口径（复用 mine_presetup 模式）
- 单股：zz6 拐点 → `SW.presetup_windows_from_pivots` 蓄势窗口；每个 L1/L2 信号 → 逐 bar 布尔 → cumsum → 每窗口命中数 wf；seg_hit=count_nonzero(wf)、seg_total=#窗口、fires_pos=Σwf、bars_pos=Σ窗口长、fires_all=Σsig、n。
- counts key=("ALL", level, "buy", 0.06, signal_name)，level∈{"L1","L2"}，signal_name 为可读串；6 元组值同 mine_commonality。
- **finalize / filter_rank 复用 mine_commonality**（对该 key 元组通用，仅按 coverage/lift 计算与排序）：coverage=seg_hit/seg_total；lift=(fires_pos/bars_pos)/(fires_all/n)；precision=fires_pos/fires_all。
- **不复用 `_write_board`/`_expand_params`**（它们按方案A/B 参数元组硬编码，蓄势信号的"params"是名字串，不兼容）→ 本任务自带轻量 CSV 写入器（列：level, signal, seg_hit, seg_total, coverage, rate_all, lift, precision）。
- 近窗口按构造与上一段重叠 → bars_pos/fires_pos 含重复计，**coverage 段级精确、lift 近似**（同 mine_presetup，注释说明）。

## turnover 处理（筹码类）
- 主进程在 Pool fork 前，把 turnover.csv 读成 `turn_by_code: {code: pd.Series(turn% indexed by 日期)}`，存模块全局（仿 turnover_features 的 `_TG`，COW 共享、不 pickle）。
- worker 内：chip 类信号取 `turn_by_code.get(code)`；无则 chip 信号全 False。
- 信号计算顺序：先算三类纯 K 线信号（不需 turn），chip 类按需算 chip_series（较重，每股一次，缓存 获利盘 序列跨参数复用）。

## 组件
1. `presetup_signals.py`（新）：4 类 series_fn + `L1_SIGNALS`（list[(name, fn)]）+ `l2_pairs(L1名列表)`。纯函数，可单测。
2. `mine_setup_commonality.py`（新）：
   - `_load_turn_by_code()`（读 turnover.csv → dict，fork 前调用，存全局）。
   - `accumulate_setup(df, code)`（单股 L1+L2 seg 级累加；import `_win_arrays` 逻辑同 mine_presetup，或自含同款）。
   - `_write_setup_reports(rows, out_dir, ts)`（自带：主榜 coverage>0.5 + 最佳可达 Top30 + 横向对比 md；列含 level/signal/指标）。
   - `main()`：池=`mine_commonality._universe()`；逐股 `mine_commonality._load_kline`；多进程 NPROC；finalize；写报告。
3. 复用（import，不改）：`swing_samples.presetup_windows_from_pivots`、`mine_commonality.{finalize, filter_rank, _load_kline, _universe}`、`turnover_features.chip_series`、`features` 的 HHV/LLV/MA/STD。（**不复用** `_write_board`/`_expand_params`。）

## 交付（产物落 data/commonality_reports/，归档 report/）
- `蓄势特征_共性_zz6_{ts}.csv`（coverage>0.5 主榜，L1+L2 混排，按 lift 降序）
- `蓄势特征_最佳可达_zz6_{ts}.csv`（不卡覆盖率，按 lift Top30）
- `蓄势特征_横向对比_{ts}.md`（L1 各类代表 + L2 最佳；显式标注"是否有 coverage>0.5 且 lift>1 的组合"）

## 测试（合成序列，python3 test_*.py）
- `presetup_signals`：构造低波动段/缩量段/窄箱体/已知获利盘的 df，验证各 series_fn 在应亮处 True、应灭处 False；L2 = 两 L1 的 AND。
- chip：用 turnover_features.chip_series 在合成 turn 上验证 获利盘 单调性 + chip 信号 band 判定。
- accumulate：合成有上涨段的 df，验证 seg_total=#蓄势窗口、seg 级命中语义、L1/L2 键齐全。

## 非目标（YAGNI）
- 不做 sell 向、不做 zz10/15/20（仅 buy/zz6）。
- 不做 L3+。
- 不挖 wyckoff_features 内部 积累SC（筹码用 chip_series 获利盘分档即可）。
- 不做分维度（板块/市值/行业）分组。

## 数据依赖（保留勿删，见 DATA_FILES.md）
events_labeled.csv（池，经 _universe）+ 本地 TDX 日 K + turnover.csv（筹码类）。
