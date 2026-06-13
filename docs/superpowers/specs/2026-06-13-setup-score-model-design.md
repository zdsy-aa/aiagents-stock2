# 起涨预测多因子打分模型 设计

2026-06-13。从"布尔信号共性"(已证起涨前 lift≈1 无效)转向**监督学习**:逐 bar 用 ~25 个连续特征
(蓄势+动量+经典)预测"起涨",两种标签 × 两种模型对比,时间切分 OOS,看弱信号**组合后**是否有
AUC/top-decile lift 的 edge。

## 任务框架
- 样本 = (股票, bar t)。特征 x(t) 只用 ≤t 的数据(防泄漏)。标签 y(t) 用 t 之后的未来(仅标签可用未来)。
- 训练分类器 P(起涨|x(t));时间切分 OOS 评估。

## 两种标签(都做,各训一套模型对比)
- **y_fwd(前向收益)**:`max(High[t+1 : t+H]) / Close[t] - 1 >= X` → 1。H=20 交易日,X=6%。标准、可交易("当下买,未来H日内能否涨X%")。末尾不足 H 根的 bar 丢弃(无完整未来)。
- **y_zz(ZigZag窗口)**:t ∈ 某 zz6 上涨段波谷 L 的 [L-K, L] → 1。K=10。与挖掘线一致。zz6 拐点用 swing_samples/zigzag_segments。

## 特征(~25 连续值,全部 ≤t,用 features.py 算子直接算连续量,不用其布尔输出)
- **蓄势**:收益率STD(20)的近120日分位、量比 Vol/MA(Vol,20)、量比 Vol/MA(Vol,60)、箱体幅 (HHV(C,20)-LLV(C,20))/LLV、(HHV(C,60)-LLV(C,60))/LLV、获利盘%、套牢盘%(chip_series,需turnover;缺失填NaN→中位数)
- **动量/经典**:MACD柱 bar=DIF-DEA、MACD柱斜率(bar-bar.shift)、RSI(14)、KDJ的K、(C-MA5)/MA5、(C-MA20)/MA20、(C-MA60)/MA60、相对大盘强弱(个股20日涨幅-大盘20日涨幅)、ATR(14)/C、近20日涨幅、近60日涨幅、距年内高位 (C-HHV(C,250))/HHV、距年内低位 (C-LLV(C,250))/LLV、换手率(turn,缺NaN)
- 约 22-25 列。所有 rolling 用 min_periods 保证只用历史;NaN(回看不足/缺turnover)在训练前按列中位数填充(用**训练集**中位数填充训练与OOS,防泄漏)。

## 样本与切分
- 全市场 4417 股(events 池)全历史逐 bar。预计 ~1500-2000 万行 × ~25 列。
- **时间切分(防泄漏)**:训练 = bar 日期 ≤ 2023-12-31;**OOS = 2024-01-01 ~ 2025-10-31**(沿用 star_calibrate 口径)。在切分日期前后不混样本。
- 标准化(logistic 用):均值/方差只用**训练集**统计,套用到 OOS。
- 类别不均衡:logistic 用 class_weight(按正负比);GBDT 用 scale_pos_weight。
- **内存/速度控制**:面板存 **float32**(~2GB)。**训练集**负样本下采样(保留全部正样本 + R 倍负样本,R=5,固定随机种子)以限内存/时长;**OOS 评估用全量 OOS bar**(不采样,保证 AUC/lift 诚实)。下采样后仍用 class_weight 校正基线。

## 两种模型(都做)
- **纯 numpy logistic**:L2 正则、特征标准化、批量梯度下降(或 mini-batch);出每特征权重(标准化后→可比的因子重要性)。零新依赖。
- **lightgbm GBDT**:容器 `pip install lightgbm` + 加入 requirements.txt;默认参数+早停;出 feature_importance。
  - 若 lightgbm 安装失败(网络/wheel)→ 降级:跳过 GBDT,仅 logistic,报告注明。
- 共 **2 标签 × 2 模型 = 4 次训练**。

## 评估(全部在 OOS)
- **AUC**(主):有无 edge,0.5=无,>0.55 才值得关注。
- **lift@top-decile**:OOS 按模型分排序,前 10% bar 的实际正样本率 ÷ OOS 基线正样本率(可交易性)。
- **logistic 权重 / GBDT importance**:哪些因子有用(正/负贡献)。

## 组件
1. `setup_modeling.py`(新):
   - `build_panel(codes, ...)`:逐股算 ~25 连续特征 + y_fwd + y_zz + 日期,拼全市场面板(numpy 数组 + 列名 + 日期 + code)。多进程。落 `setup_panel.npz`(或分块)避免重算。
   - `time_split(panel, train_end, oos_start, oos_end)`:按日期切。
   - `fit_logistic(X, y, l2, ...)` / `predict_logistic`:纯 numpy。
   - `fit_gbdt(X, y)`(lightgbm,容错 import)。
   - `evaluate(y_true, score)` → AUC + lift@top-decile。
   - `main()`:build/load panel → 4 训练 → 评估 → 写报告。
2. 复用(import,不改):features.py 算子(MA/EMA/STD/HHV/LLV/TR/relative_strength/index_state)、turnover_features.chip_series、swing_samples/zigzag(y_zz)、mine_commonality._load_kline/_universe。
3. **不动**现有挖掘脚本(mine_commonality/mine_presetup/mine_setup_commonality)。

## 交付
- `setup_panel.npz`(特征/标签面板,gitignore,登记 DATA_FILES)。
- 报告 `起涨打分模型_评估_{ts}.md`:**4 单元 AUC 表**(logistic/GBDT × y_fwd/y_zz)+ 各 top-decile lift + 因子权重/重要性 Top + 结论(组合后是否有 edge;对照单点 lift≈1)。归档 report/。
- 各模型系数/重要性 CSV。

## 测试(合成序列,python3 test_*.py)
- 特征无泄漏:构造序列,验证 feature[t] 不依赖 >t 的值(对未来插入异常值,feature[t] 不变)。
- 标签正确:构造已知前向收益(y_fwd)与已知 zz6 段(y_zz),验证标签命中位置。
- logistic:在线性可分合成数据上 AUC→~1;退化(全同标签)不崩。
- AUC/lift 函数:已知排序的合成 score/label,AUC 与 lift@decile 数值正确。
- time_split:训练/OOS 按日期无重叠、无跨界。

## 非目标(YAGNI)
- 不做超参搜索/交叉验证网格(GBDT 默认+早停,logistic 固定 l2)。
- 不做特征选择自动化(固定 ~25 列)。
- 不上线前台、不做实盘信号(纯研究评估)。
- 不改现有挖掘脚本。

## 数据依赖(保留勿删,见 DATA_FILES.md)
events_labeled.csv(池) + 本地日K + turnover.csv(获利盘/换手) + 上证指数 index_sh000001.csv(相对强弱)。均已就绪。
