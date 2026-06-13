# 紧窗口变体（起涨前 [L-K, L]）设计

2026-06-13。把起涨前蓄势窗口从"近=整个上一周期"改成紧贴突破的固定小窗口 `[L-K, L]`（K∈{5,10}），
对动量(mine_presetup)与蓄势(mine_setup_commonality)两套挖掘各重跑一遍，检验紧窗口下是否出现
**coverage>0.5 且 lift>1**（此前 lift≈1 疑为大"近"窗口稀释的人为产物）。

## 背景与动机
前两轮(动量/蓄势)在起涨前窗口都得 lift≈1。诊断：自适应"近"窗口 `[上一涨段起点, L]` 跨整个上一周期(30-60+根)，
大窗口里"任一bar触发"使覆盖率虚高、lift 被稀释趋近全局频率(≈1)，**失去对"集中度"的分辨力**。
紧窗口 `[L-K, L]`(K 很小)才是"起涨前 K 天有无共性"的诚实检验。

## 目标
- 给窗口函数加**紧窗口模式**：每个上涨段窗口 = `[max(0, L-K), L]`(含波谷L、截止L无泄漏、忽略近/远自适应)。
- K∈{5,10} 各跑；对**动量(mine_presetup 方案A/B)** 与 **蓄势(mine_setup_commonality L1+L2)** 各重跑 → 共 4 次跑。
- 口径不变：zz6、buy 向、段级覆盖率；重点看 coverage>0.5 且 lift>1。
- **向后兼容/零回归**：紧窗口为**可选模式**，默认(不设)仍是现有自适应窗口；mine_commonality.py(原拐点后)不动。

## 改动
**① `swing_samples.presetup_windows_from_pivots(pivots, near_n=20, far=7, tight_k=None)`**
- `tight_k=None`(默认)：**行为完全不变**(现有近/远自适应)。
- `tight_k=K`(int)：每个上涨段(L→H)窗口 = `list(range(max(0, L-K), L+1))`(含L)，不分近/远。
- 现有调用 `presetup_windows_from_pivots(piv, NEAR_N, FAR)` 不传 tight_k → 默认 None → 不受影响。

**② `mine_presetup.py` / `mine_setup_commonality.py` 读环境变量 `TIGHT_K`**
- 模块顶部：`TIGHT_K = int(os.getenv("TIGHT_K")) if os.getenv("TIGHT_K") else None`。
- 调窗口处改为 `SW.presetup_windows_from_pivots(piv, NEAR_N, FAR, tight_k=TIGHT_K)`。
- 输出文件名加后缀：`TIGHT_K` 设了 → `_tightK{K}`，否则空串。即：
  - mine_presetup：`方案{A/B}_起涨前蓄势{,最佳可达}_zz6{suffix}_{ts}.csv` + `起涨前蓄势_横向对比{suffix}_{ts}.md`。
  - mine_setup_commonality：`蓄势特征_{共性,最佳可达}_zz6{suffix}_{ts}.csv` + `蓄势特征_横向对比{suffix}_{ts}.md`。
- 不设 `TIGHT_K` → suffix 空 → 文件名与现有一致，行为不变。

**③ mine_commonality.py 不动。**

## 运行
容器 agentsstock1 内，各跑一遍（NPROC=10，全市场）：
- `TIGHT_K=5  python3 mine_presetup.py`
- `TIGHT_K=10 python3 mine_presetup.py`
- `TIGHT_K=5  python3 mine_setup_commonality.py`
- `TIGHT_K=10 python3 mine_setup_commonality.py`
（mine_setup_commonality 需先加载 396M turnover，首条进度前数十秒。）

## 测试（合成序列，python3 test_*.py）
- 新增 `test_tight_window.py`：
  - `presetup_windows_from_pivots(pivots, tight_k=5)`：单上涨段 L@30 → 窗口 == `list(range(25, 31))`(含L,6根)；L@3,tight_k=5 → `list(range(0,4))`(负索引截0)。
  - 多上涨段：每段窗口都是 `[L-K, L]`，与上一段无关(不再跨周期)。
  - `tight_k=None` → 与现有自适应一致(回归保护：同一 pivots 下 tight_k=None 的输出 == 原 `presetup_windows_from_pivots(pivots)`)。

## 非目标（YAGNI）
- 不改口径(仍 zz6/buy/段级)、不加新信号、不改 mine_commonality。
- 不做 K 的更大网格(只 5/10)。

## 数据依赖
同前(events_labeled.csv 池 + 本地日K + turnover.csv 供蓄势 chip)；均已就绪(保留勿删,见 DATA_FILES.md)。
