# 起涨前蓄势窗口共性挖掘（mine_presetup）设计

2026-06-13。共性挖掘的新窗口变体：在所有 ≥6% 的上涨段，取**起涨前的蓄势窗口**为正样本，
按方案 A/B 遍历所有参数，找 **>50% 段级共性**。与现有"拐点后 [L,L+4] 起涨初期"变体并存，互不影响。

## 背景与动机
现有 `mine_commonality.py` 的正样本窗口是**拐点后 [L, L+4]**（起涨/起跌初期，刻画"转折之后金叉/回踩已发生"）。
本变体反向：刻画**突破启动之前的蓄势/铺垫期**有什么共同信号，用于"起涨前"预判。
示例：1–10 号在低价区浮动 <1%，10 号起涨到 20 号翻倍，21 号回落 → 关注 **11 号以前（含 10 号=波谷 L）** 的共性。

## 目标
- 仅 **buy 向**（上涨段起涨前；不做下跌段对称）。
- 仅 **zz6**（ZigZag pct=6%，捕捉所有 ≥6% 摆动；更大涨幅是其子集）。
- 段级覆盖率：找 `coverage > 0.5` 的方案 A/B 参数组合；并出"最佳可达 Top30"兜底。
- **零回归**：现有 `mine_commonality.py` 及其报告完全不动（独立新脚本 + 独立产物）。

## 窗口定义（核心，buy 向，仅 up 段）
对 zz6 切出的每个上涨段（波谷 `L` → 波峰 `H`，涨幅 ≥6%）：
- 记上一个上涨段终点为 `H_prev`，上一涨段起点为 `L_prev`；`H_prev → L` 的中间下降段长度 `gap`（交易日，= L_idx − H_prev_idx）。
- **近（`gap ≤ N`，默认 N=20）**：蓄势窗口 = `[L_prev_idx, L_idx]`（含 L，覆盖"上一涨段+下降段"整段）。
- **远 / 无上一涨段（`gap > N` 或序列开头）**：窗口 = `[L_idx − FAR, L_idx]`（默认 FAR=7，突破前 7 根 + L，含 L）。
- 窗口一律**截止于 L**（波谷=起涨点），全部 bar 在上涨之前，无未来泄漏。
- 窗口需有足够前置 bar 供信号自身回看（斐波 N / MACD slow+signal）；不足则该信号在该段记为"未命中"（不报错）。

`N`、`FAR` 为模块常量，可调。

## 覆盖率 / 共性口径（段级，复用现有定义）
- 每个上涨段 = 1 个样本；蓄势窗口内**任一根 bar 触发**该信号组合 → 该段命中。
- `coverage = seg_hit / seg_total`（段级，与现有 mine_commonality 同口径）。
- `lift`、`precision` 沿用现有定义（正样本命中率 ÷ 全体 bar 基线命中率；防伪过滤"哪都亮"的信号）。
- 主榜：`coverage > 0.5` 按 lift 排序；另出"最佳可达 Top30"（按 lift，不卡覆盖率）保证非空。

## 信号与参数网格
复用 `param_signals`：
- 方案 A = 斐波那契回踩企稳（N × ratio∈{.382,.5,.618,.786} × band）× MACD 金叉。
- 方案 B = BBI（cross 上穿 / above 站上）× MACD。
- 全参数网格遍历，逐组合在每段蓄势窗口上评估。

## 组件
1. `swing_samples.py` 新增 `presetup_windows_from_pivots(pivots, near_n=20, far=7)` → 返回 up 段的蓄势窗口列表（buy 向）。纯计算，复用 `zigzag_segments`。
2. **新脚本 `mine_presetup.py`**：
   - 池 = events_labeled.csv 去重股票（≈4417，与 mine_commonality 同源）。
   - 逐股本地 K 线（复用 build_features_v2 同款读取）→ zz6 拐点 → presetup 窗口 → 对每个方案 A/B 参数组合累加 seg_hit/seg_total + bar 基线 → finalize（coverage/lift/precision）。
   - 多进程 `NPROC`（默认 8/10）。
   - 输出 `data/commonality_reports/`：`方案A_起涨前蓄势_zz6_{ts}.csv`、`方案B_起涨前蓄势_zz6_{ts}.csv`、各自"最佳可达"、横向对比 `起涨前蓄势_横向对比_{ts}.md`。
3. 不改 `mine_commonality.py`。

## 测试（合成序列，无 pytest 用 `python3 test_*.py` 或加入 tests/）
- `presetup_windows_from_pivots`：
  - 近场景：构造两个上涨段、中间短下降段（gap≤N）→ 窗口 = `[L_prev, L]` 且含 L。
  - 远场景：gap>N → 窗口 = `[L-FAR, L]`（长度 FAR+1，含 L）。
  - 序列开头无上一段 → 走远分支（前 FAR 根，不越界到负索引则截断）。
  - 窗口不越过 L（无泄漏）。
- 段级覆盖率：构造"全段命中/半数命中"小样本，验证 coverage 分母=段数、任一 bar 亮即命中。

## 非目标（YAGNI）
- 不做 sell 向 / 下跌段起跌前。
- 不做 zz10/15/20（仅 zz6）。
- 不动现有"拐点后"挖掘、不做分维度（板块/市值/行业）分组——先把基础版跑通。

## 数据依赖（保留勿删，见 DATA_FILES.md）
events_labeled.csv（股票池）+ 本地 TDX 日 K。不依赖 features_v2.csv / turnover.csv。
