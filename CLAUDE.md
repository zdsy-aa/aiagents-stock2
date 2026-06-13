# aiagents-stock 项目规则

## 分支策略（重要）

**以后只在 `main` 分支上开发。**

- 所有新功能、修复、研究代码一律提交到 `main`，不再新建/使用长期特性分支。
- 远程为 `stock2`（`git@github.com:zdsy-aa/aiagents-stock2.git`），`main` 跟踪 `stock2/main`。
- 由用户自行 `git push stock2 main`（除非用户明确要求代为推送）。
- 历史背景：曾长期在 `feat/liumai-and-combo-screening` 上开发，导致生产功能栈（六脉/组合/星级/盘中化/稳定选股/邮件改版）只在 feat、`main` 落后一大截。2026-06-12 已用 `git merge feat→main`（merge 062b8d6，零冲突）把整条栈合回 main，`main ≡ feat`。从此统一到 main，避免再次分叉。
- `feat/liumai-and-combo-screening` 视为历史分支，不再继续在其上开发。

## 约定

- 面向用户的输出一律用中文。
- 分析报告存 `/home/tdxback/report/` 并加 `_YYYYMMDD_HHMMSS` 时间戳后缀。
- `data/profit_mining/` 跟踪策略：**生产管线脚本入库**（被「📋 当前策略」页引用、或作为已入库下游脚本的上游依赖闭包：features.py / build_features*.py / events_export.py / event_registry.py / label_window.py / mine_combos*.py / mine_sell.py / walk_forward.py / mine_regime.py + 其测试，2026-06-13 修复跟踪断裂时入库）；纯探索/一次性实验脚本（backtest_*.py / portfolio_backtest*.py / eval_*.py / offset_sweep.py / refine_*.py 等）保持 untracked。判据：策略页/CLAUDE 文档引用到、或入库脚本 import 到的 → 入库；否则可不入库。
- 部署为 5 容器 docker；`./data` 挂载进容器即时生效，根目录代码（如 chanlun_batch.py）需重建镜像才生效。
