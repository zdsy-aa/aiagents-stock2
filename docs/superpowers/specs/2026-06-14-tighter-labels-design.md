# 收紧标签迭代（起涨打分模型 v2）设计

2026-06-14。当前 y_fwd(后20日≥6%) base 0.61 偏松、OOS AUC 0.63 分离温和。收紧预测目标(更高涨幅/更短窗口/超额)
看 AUC/lift 能否放大。**特征不变(21列)**,只改/加标签集,重训对比。沿用 setup_modeling 全套基建。

## 背景
起涨打分模型 v1(2026-06-14)已证:多因子组合在 y_fwd(6%/20日)有真实弱 edge(AUC0.63/lift1.31),
但目标太易(base0.61)。本迭代收紧标签:目标越难、base 越低,看模型分离度(AUC/lift)是否提升。
y_zz(ZigZag对照,已知自洽假象)本轮不跑。

## 目标
- 4 组前向标签对比,各跑 logistic + lightgbm GBDT(共 8 评估),同一特征面板、同一时间切分。
- 看每组的 base rate、OOS AUC、lift@top-decile,判断"收紧目标是否放大 edge"。

## 4 组标签
| 名 | 定义 | 备注 |
|----|------|------|
| `fwd_6_20` | 后20日内 max(High[t+1:t+20])/Close[t]-1 ≥ 0.06 | 基准(v1现有口径) |
| `fwd_10_10` | 后10日内 max(High[t+1:t+10])/Close[t]-1 ≥ 0.10 | 更高更短 |
| `fwd_10_20` | 后20日内 max(High[t+1:t+20])/Close[t]-1 ≥ 0.10 | 更高 |
| `excess_10_20` | (Close[t+20]/Close[t]) - (Idx[t+20]/Idx[t]) ≥ 0.10 | **close-to-close 点对点超额**,剔大盘β,大盘=上证index_sh000001 |
- 前 3 用 `label_fwd(df,H,X)`(max-High 口径,复用)。`excess_10_20` 新增 `label_excess(df, idx_close, H=20, X=0.10)`:个股 H 日 close-to-close 收益 − 对齐的大盘 H 日 close-to-close 收益 ≥ X → 1;末尾不足 H 根或大盘对齐缺失 → NaN。idx_close 用 `_load_index_close()` reindex(df.index).ffill()。

## 特征 / 切分 / 模型 / 评估
- 特征:**完全不变**(setup_features.compute_features 21列)。
- 时间切分:训练≤2023-12-31 / OOS 2024-01-01~2025-10-31(不变)。
- 预处理/模型/评估:沿用 v1(中位填充&标准化只用训练统计;float32面板;训练负样本下采样R=5;OOS全量;logistic class_weight + GBDT;AUC + lift@top-decile + 权重/importance)。
- y_zz 不参与。

## 改动
1. `setup_features.py`:**新增** `label_excess(df, idx_close, H=20, X=0.10)`(close-to-close 超额,返回 float numpy 0/1/NaN)。`label_fwd` 不动。
2. `setup_modeling.py`:
   - **标签集配置** `LABELS`(name → (kind, params)),kind∈{"fwd","excess"}。
   - `_panel_proc`:算 21 特征 + 4 标签 → 标签矩阵 `Y[n,4]`(列序=LABELS),连同 dates。
   - `build_panel`:存 `setup_panel.npz`:X[float32], Y[n,4,float32], label_names, dates。
   - `main`:载/建面板 → 对 4 列标签各 `_run_one`(label_name 取自 label_names) → 报告。
   - **去掉 y_zz 相关**(yz 不再算/存/评)。
   - 报告 `起涨打分模型v2_评估_{ts}.md`:4 标签 × (logistic/GBDT) AUC+lift 表 + base rate + 因子;结论(收紧后 edge 是否放大)。
3. **不动**其他脚本。旧 `setup_panel.npz`(v1,yf/yz) 结构变了 → main 检测列数不符则重建(或直接重建:删旧panel)。

## 测试(合成序列,python3 test_*.py)
- `test_setup_features.py` 追加 `test_label_excess`:构造个股大涨而大盘平 → excess=1;个股跟随大盘涨 → excess=0;末尾不足H → NaN。
- panel 标签矩阵:_panel_proc 返回 Y 形状 [n,4]、列序与 LABELS 一致(可在 build_panel 冒烟/小测验证,或 main limit 冒烟看4标签段都出)。

## 非目标(YAGNI)
- 不改特征、不改时间切分、不改模型超参。
- 不跑 y_zz。
- 不做 H/X 更大网格(就这 4 组)。

## 数据依赖
events_labeled.csv(池) + 本地日K + turnover.csv(特征) + index_sh000001.csv(相对强弱特征 & excess标签大盘)。均就绪。
