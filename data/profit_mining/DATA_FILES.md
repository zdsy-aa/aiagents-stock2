# profit_mining 数据/中间文件清单（打标登记）

**保留策略（用户准则 2026-06-13）**：本目录下脚本用到的数据文件与中间产物，
**只要对应功能还在，就保留、不删除**；需要刷新时**重新生成覆盖（更新）**，不要删。
只有当对应功能/脚本被移除时，其专属数据文件才可删。新增数据文件请在此登记。

（这些 `.csv/.json` 是 gitignore 的本地数据，不入库；本清单入库以作"打标"。）

## 输入 / 原始数据（外部抓取或一次性准备，缺了要重抓）
| 文件 | 生产脚本 | 主要消费方 | 说明 |
|------|---------|-----------|------|
| `labels.csv` | （历史准备） | fetch_turnover.py / build_features* | 信号股票代码与盈利标签来源 |
| `index_sh000001.csv` | （历史准备） | build_features_v2.py (IDXCSV) | 上证指数日K，算大盘状态特征 |
| `turnover.csv` | fetch_turnover.py (baostock) | turnover_features.py | 信号股全历史换手率 |
| `turnover_by_year/` | fetch_turnover_yearly.py | （换手率重建源） | 分年换手率，重建 turnover 用 |
| `stock_mktcap_snapshot.csv` | fetch_mktcap_snapshot.py (腾讯) | group_dims.py / calibrate_buckets.py | 市值快照(分维度挖掘) |
| `stock_industry_snapshot.csv` | fetch_industry_snapshot.py | group_dims.py | 行业快照(分维度挖掘) |

## 管线中间产物（由上游脚本生成，被下游挖掘消费）
| 文件 | 生产脚本 | 主要消费方 | 说明 |
|------|---------|-----------|------|
| `events_labeled.csv` | events_export.py | build_features_v2.py | 12组买卖点+30日窗口标签 |
| `features_v2.csv` | build_features_v2.py | mine_combos_v2 系挖掘 | 每事件±2窗口全量信号特征(V2) |
| `signal_features.csv` | build_features.py | mine_combos.py / mine_sell.py / walk_forward.py 等(8处) | 防泄漏布尔特征矩阵 |
| `sell_features.csv` | chanlun_sell_pipeline.py | mine_sell 系 | 卖点特征 |
| `turnover_signal.csv` | turnover_features.py | 多处(7) | 换手率衍生信号 |
| `forward_stats.csv` | build_forward_stats.py | 回测/统计 | 前向收益统计 |
| `scores_all_combos.csv` | mine_combos.py | walk_forward.py | L1/L2/L3 组合全量评分 |

> 报告产物(commonality_reports/，按时间戳归档，保留)：
> - mine_commonality.py → `方案AB_共性横向对比_*.md` + `方案{A/B}_{上涨前/下跌前}{共性/最佳可达}_zz{6/10/15/20}_*.csv` + 分组榜（拐点后[L,L+4]变体）
> - mine_presetup.py → `起涨前蓄势_横向对比_*.md` + `方案{A/B}_起涨前蓄势{,最佳可达}_zz6_*.csv`（起涨前蓄势窗口×动量信号变体）
> - mine_setup_commonality.py → `蓄势特征_横向对比_*.md` + `蓄势特征_{共性,最佳可达}_zz6_*.csv`（起涨前蓄势窗口×蓄势期特征 L1/L2 变体）
> - 紧窗口变体: mine_presetup.py / mine_setup_commonality.py 支持 `TIGHT_K` env(=K)→窗口改为[L-K,L],产物名加 `_tightK{K}`(默认不设=自适应)

## 标定/产物 JSON（固化阈值，前台/调度读取）
| 文件 | 生产脚本 | 主要消费方 | 说明 |
|------|---------|-----------|------|
| `group_buckets.json` | calibrate_buckets.py | mine_commonality.py | 波动率/市值三分位切点 |
| `star_thresholds.json` | star_calibrate.py | daily_watchlist.py / stable_ui.py | 核心/精选层星级阈值 |

## 前台交付产物（每日刷新）
| 文件 | 生产脚本 | 说明 |
|------|---------|------|
| `每日自选股清单.csv` | daily_watchlist.py | 当日稳定选股清单(前台/邮件) |

> 注：`commonality_reports/` 下的挖掘报告（`方案AB_共性横向对比_*.md` 等）按时间戳归档，
> 同样保留；研究报告另拷 `/home/tdxback/report/`。
> 可删的"垃圾"仅限：`__pycache__/`、`*.pyc`、编辑器残留、一次性校验脚手架（如曾经的 `_verify_opt.py`）。
