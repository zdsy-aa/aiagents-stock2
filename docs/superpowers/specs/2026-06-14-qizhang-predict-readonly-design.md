# 起涨预测 只读展示 + 日调度（方案A）设计

2026-06-14。回测 v2 研究产物（GBDT fwd_10_10 打分 → C4 移动止盈+大盘择时，OOS 超额 +6.3%/年化 +21%/
Sharpe 3.27/回撤 -3.1%）现仅活在 `data/profit_mining/` 离线脚本，不接任何生产。本方案把 C4 策略变成
**每天自动更新、前台只读、自我验证战绩**的观察页，先 paper-tracking 攒跨行情真实样本，再决定是否进一步上线。

## 目标
- 每日收盘后自动：重训 GBDT（扩展窗）→ 给当日 bar 打分 → 产出 top-10 候选 → 落库。
- 对已到期的历史候选回填 realized 结果（C4 移动止盈退出收益），聚合成随时间生长的实盘外战绩。
- 前台新建只读页展示：醒目免责+诚实局限、C4 回测结论、今日候选、战绩表。
- **明确不做**：不下单、不发邮件、不进选股邮件、不碰实盘（纯观察）。

## 非目标（YAGNI）
- 不下单 / 不发邮件 / 不并入每日选股邮件或 daily_watchlist。
- 不做参数寻优（trail=8%、MA20、TOPN=10、H/X 固定为回测口径）。
- 不改回测脚本本身（setup_backtest/setup_modeling 只复用、不改逻辑）。
- 不对接 miniqmt（空壳不碰）。
- 不做多策略对比（只 C4 单策略）。

## 架构（仿 chanlun-updater sidecar 范式）
```
qizhang-updater (新 docker sidecar, 复用 aiagents-stock-app 镜像, 每日 20:30 CST)
  └─ qizhang_schedule.sh  (GNU date 定时 + 交易日门控 + flock 防叠跑, 仿 chanlun_schedule.sh)
       └─ python3 qizhang_batch.py:
            1. build_panel()          复用 setup_modeling, _universe()~4415 码 + route B 本地K线 _load_kline
            2. 训练 GBDT(扩展窗)       全部 valid-label 行(label=fwd_10_10), 截至有完整标签的最近 bar
            3. 给"今日 bar"打分         → select_topn(TOPN=10) 候选
            4. C4 大盘择时 gate        上证收盘 < 上证 MA20 → 当日 risk-off, 不产候选(记 gate 状态)
            5. 写 daily_picks          落库 data/qizhang_picks.db
            6. realized 回填           对已到期历史候选, simulate_trade(mode="trailing") 算 C4 退出收益
qizhang_predict_ui.py (只读页, @st.cache_data ttl=1800)
  ← app.py 侧栏「选股板块」新增「📈 起涨预测(观察中)」按钮 + views/page_router.py 加 show_qizhang 分派
```
调度时序：kline-updater 18:00 增量更新本地K线 → chanlun-updater 20:00 → **qizhang-updater 20:30**（确保本地K线已是最新）。

## 数据落库 `data/qizhang_picks.db`（新建，继承 BaseDatabase）
三张表，主键/口径如下（具体列在实现计划阶段以代码为准，此处定契约）：

- **daily_picks**（每日候选，scan_date 当日落库）
  - `scan_date TEXT`（交易日 YYYY-MM-DD）, `code TEXT`, `name TEXT`, `score REAL`,
    `rank INTEGER`（1..N）, `entry_ref_price REAL`（次日开盘参考价，回填或留空）,
    `riskoff INTEGER`（0/1，当日大盘择时是否避险）, `created_at TEXT`
  - 唯一约束 (scan_date, code)。
- **realized**（到期后回填，每候选一行）
  - `scan_date TEXT`, `code TEXT`, `exit_date TEXT`, `holding_days INTEGER`,
    `realized_return REAL`（C4 移动止盈净收益，扣 0.2% 成本，同回测口径）,
    `hit_10pct INTEGER`（持有窗内是否触及 +10%）, `exit_reason TEXT`（止损/移动止盈/到期）,
    `bench_return REAL`（同持有期上证涨跌幅）
  - 唯一约束 (scan_date, code)。
- **run_meta**（每次跑一行，可观测/调试）
  - `scan_date TEXT PRIMARY KEY`, `model_train_rows INTEGER`, `train_end_date TEXT`,
    `sh_ma20_gate INTEGER`（当日是否 risk-off）, `status TEXT`（ok/failed）, `created_at TEXT`

## 候选生成口径（实现计划阶段细化）
- **每日重训扩展窗**：每天用截至昨日（有完整 fwd_10_10 标签）的全部行重训 GBDT，给"今日 bar"打分。
  代价已知：每日重建全市场 panel + 训练较重（分钟级）；模型每日微变 → paper-track 口径有轻微漂移，
  但符合"看真实跨行情表现"的目标，接受。
- **N=10**（同回测 TOPN）。
- **risk-off 日（上证收盘 < 上证 MA20）不产候选、也不进战绩**（严格等同 C4 回测口径）；run_meta 记 gate 状态，页面显示避险提示。
- realized 回填只对 **non-riskoff** 候选；用 `setup_backtest.simulate_trade(mode="trailing", maxhold=30, trail=0.08, sl=-0.05, cost=0.002)`，入场 = scan_date 次日开盘，与 C4 回测同口径。

## 页面四段（qizhang_predict_ui.py）
1. **顶部免责（醒目）**：paper-tracking 观察、非投资建议；**诚实局限直接写在页上**——Sharpe 受槽位法影响偏高、
   单一牛市 OOS 非跨周期 walk-forward、未含涨跌停/停牌不可成交与滑点。
2. **C4 回测结论（静态）**：OOS 超额 +6.3%/年化 +21%/Sharpe 3.27/回撤 -3.1% + 上证同期 +33.5% 对照
   （固化为常量或读归档报告 md，避免运行期依赖离线产物）。
3. **今日候选**：top-10（code/name/score/rank/次日开盘参考价）；risk-off 日显示「大盘择时避险，今日不开新仓」。
4. **实盘外战绩表（随时间生长）**：累计候选数、已到期数、胜率（realized_return>0）、命中 +10% 率、
   C4 平均净收益、paper 期累计收益 vs 上证、退出原因分布。realized 不足时显示「样本积累中（需 ≥10 交易日到期）」。

## 错误处理 / 边界
- **交易日门控**：非交易日 schedule 跳过（仿现有 chanlun_schedule.sh）。
- **flock 防叠跑**：单实例锁，避免上次未跑完叠跑。
- **失败兜底**：数据源/panel/训练任一失败 → run_meta status=failed，不写当日候选；页面显示「今日未更新（最近成功：<日期>）」。
- **首次上线**：realized 表为空 → 战绩段显示「样本积累中」。
- **DB 不存在**：页面读取处容错（无库/空库显示空态，不抛异常）。

## 测试
- `qizhang_batch` 纯逻辑单测（不联网、合成数据）：top-N 选取、risk-off gate 判定、realized 回填用合成K线
  验证与 `simulate_trade(trailing)` 口径一致。
- `qizhang_picks_db` round-trip 单测（仿 tests/test_*_db.py，临时库 + 合成数据，save→get）。
- 页面渲染冒烟纳入 `tests/test_ui_pages_smoke.py`（参数化加 `show_qizhang` 标志，空库下不崩）。

## 复用 vs 新增
- **复用**：`setup_modeling.build_panel / fit_gbdt / _subsample_train / col_median / fill_na`、
  `mine_commonality._universe / _load_kline`、`setup_backtest.simulate_trade / select_topn / _riskoff_days / score 口径`、
  `base_db.BaseDatabase`、chanlun-updater 调度范式。
- **新增**：`qizhang_batch.py`、`qizhang_schedule.sh`、`qizhang_picks_db.py`、`qizhang_predict_ui.py`、
  docker-compose `qizhang-updater` 服务、app.py 侧栏按钮 + views/page_router.py 路由接线 + test 冒烟标志。

## 数据依赖
- 本地日K（route B `_load_kline`，tdx-data:ro）+ `index_sh000001`（基准+择时 MA20）+ `_universe()` 票池。
- 写 `data/qizhang_picks.db` / `data/qizhang_update.log`（挂载即时生效，符合 data/ bind-mount 约定）。

## 上线说明
- 根目录新增 .py（qizhang_batch/qizhang_picks_db/qizhang_predict_ui）+ app.py 改动需**重建镜像**才对用户与 sidecar 生效；
  data/ 下产物挂载即时生效。
- sidecar `qizhang-updater` 复用主镜像（与 chanlun-updater 同思路），healthcheck disable，restart unless-stopped。
- 首次可手动 `docker exec qizhang-updater python3 /app/qizhang_batch.py` 跑一次验证端到端。
