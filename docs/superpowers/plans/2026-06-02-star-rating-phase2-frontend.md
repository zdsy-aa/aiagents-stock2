# 星级分级 · 阶段二落地前台 Implementation Plan

> 执行方式：控制器(本会话)直接实现 + 直接验证；改动与阶段一脚本/现有 daily_watchlist/stable_ui 紧耦合。

**Goal:** 把阶段一固化的 `star_thresholds.json` 用到每日清单：`daily_watchlist.py` 给当日核心/精选候选打星(新增 星级/预估胜率/大涨率 列)，`stable_ui.py` 醒目展示，口径与训练完全一致。

**Architecture:** 在 `star_calibrate.py` 加一个**服务端打星helper**(`load_thresholds`+`assign_star`)，复用同一套 `feature_values/score_row/assign_bucket`，保证训练/线上口径一致。`daily_watchlist` 仅负责把信号时点特征装成 dict 调用它。`stable_ui` 仅展示。星级只对 `1买` 非陷阱候选(即现有 refine=★★核心/★精选)生效。

## Task A — star_calibrate.py 加服务端打星 helper（TDD）
- `load_thresholds(path=THRESH_OUT)`：读 json。
- `assign_star(tier, row, thresholds)`：用该层 weights+cuts，对 `feature_values(row)` 算分→`assign_bucket`→返回 `(star:int, est_win, bigrise, n_stars)`。
- 单测：构造小 thresholds(核心5档/精选2档简化)，验证高分→高星、低分→低星、est_win 取对应档 oos_win。
- 提交。

## Task B — daily_watchlist.py 打星（additive 列）
- 顶部 `import star_calibrate as SC`；`main()` 开头 `STARS = SC.load_thresholds()` 包 try/except(缺失→None，降级不打星)。
- 循环内 refine 确定后，若 `refine` 非空：tier=核心/精选；装 `star_row`(极限抄底/中枢极限底/中枢底部回升 用 `F.window_or_at(...,i,2)`；量比 `vf["量比"].iloc[i]`；相对强弱 `rs_i`)→`SC.assign_star`→`星级=f"{tier}{'★'*star}"`、`预估胜率`、`大涨率`。
- `out.append` 增 3 键；`cols` 末尾追加 `星级/预估胜率/大涨率`(additive，不动既有列序，保护 export/push 下游)。
- 排序在层主键后插入 `-星级数`(层内高星优先)。
- 验证：离线 parity——对 `signal_features.csv` 训练段/样本外重算 star 分布，应与 `star_thresholds.json` 各档 n 吻合。

## Task C — stable_ui.py 展示
- 显示清单时把 `星级` 列移到最前(若存在)；加 caption 解释星级口径(核心5★：★≈68%→★★★★★≈85%；精选2★：★≈73%/★★≈81%；样本外验证、非保证)。
- AppTest 无头渲染通过、无异常。

## Task D — 验证 & 提交
- pytest 全绿；离线 parity 通过；AppTest 通过。提交。

## 完成定义
当日清单出现 `星级/预估胜率/大涨率`；核心最高5★、精选最高2★；排序层主键+星内倒序；stable_ui 正常展示并有口径说明；训练/线上同一套打分函数(无口径漂移)。
