# 六脉神剑选股 + 选股板块重构 + 缠论×六脉组合策略 设计

日期：2026-05-30
分支：`feat/liumai-and-combo-screening`
参考：六脉神剑通达信公式 `/home/tdxback/llll.txt`

## 背景与目标

在「🎯 选股板块」中：
1. 新增**六脉神剑选股**单独页（每日批量落库，前台只读 + 手动重算）。
2. 把选股板块重构为两组：**单策略选股**（主力选股 / 低价擒牛 / 小市值 / 净利增长 / 低估值 / 缠论选股 / 六脉神剑）与**组合策略选股**。
3. 组合策略新增 **缠论×六脉神剑**：当出现缠论买入信号、且其信号日 **±3 交易日**窗口内出现六脉神剑 **5 红以上**（六维多头数≥5）即选中。每日定时跑，前台可手动刷新。

均不改动现有策略与缠论批量链路。

## 用户已确认的关键决策

- 六脉单独页选中条件：**最新交易日 六维多头数 ≥ 5**。
- 组合「前后 3 天」：**±3 交易日**窗口。
- 组合的缠论买入信号源：**复用批量库** `chanlun_signals.db` 最新批次买点。
- 六脉单独页数据：**每日批量扫全池落库**，前台只读 + 手动重算。

## 名词与口径

- 六维：MACD / KDJ / RSI / LWR / BBI / MTM，每维「多头」记 1「红」。
- 多头数 = 六维多头之和（0–6）。「5 红以上」= 多头数 ≥ 5。
- 加权得分 = MACD×20 + KDJ×15 + RSI×15 + LWR×10 + BBI×20 + MTM×20（满分 100）。
- 状态：≥70 强势 / 40–70 偏多 / 20–40 震荡 / ≤20 偏空。

## 隔离性原则

- 新增模块独立成文件；不改 `chanlun_*`、`low_price_bull_*` 等现有策略代码。
- 组合策略只**读** `chanlun_signals.db`（经现有 `ChanlunSignalDB`），不写。
- app.py 仅做导航分组 + 两个新 `show_*` 路由的添加，现有按钮逻辑不动。

---

## 组件设计

### 1. `liumai_engine.py`（纯函数，零 IO，零 Streamlit）

输入标准日线 DataFrame（列 Open/High/Low/Close/Volume，索引升序）。实现通达信语义：

- 通达信 `SMA(X,N,M) = (M*X + (N-M)*前值SMA)/N`（递归，首值取首个有效 X），单独实现 `_tdx_sma(series, n, m)`。
- `EMA` 用 `series.ewm(span=N, adjust=False).mean()`。`MA` 用 `rolling(N).mean()`。
- 六维布尔（逐根 Series）：
  - MACD：快=EMA(C,8)-EMA(C,13)，信号=EMA(快,5)，多头=快>信号。
  - KDJ：RSV=(C-LLV(L,8))/(HHV(H,8)-LLV(L,8))*100，K=SMA(RSV,3,1)，D=SMA(K,3,1)，多头=K>D。
  - RSI：短=SMA(MAX(C-REF(C,1),0),5,1)/SMA(ABS(C-REF(C,1)),5,1)*100，长同 13；多头=短>长。
  - LWR：原=(-(HHV(H,13)-C))/(HHV(H,13)-LLV(L,13))*100，K=SMA(原,3,1)，D=SMA(K,3,1)，多头=K>D。
  - BBI：(MA3+MA6+MA12+MA24)/4，多头=C>BBI。
  - MTM：变化=C-REF(C,1)，短=100*EMA(EMA(变化,5),3)/EMA(EMA(ABS(变化),5),3)，长同 13/8；多头=短>长。

公开接口：

```python
DIMS = ["MACD", "KDJ", "RSI", "LWR", "BBI", "MTM"]
_WEIGHTS = {"MACD": 20, "KDJ": 15, "RSI": 15, "LWR": 10, "BBI": 20, "MTM": 20}

def compute_flags(df) -> pd.DataFrame:
    """返回逐根六维多头布尔 DataFrame（列=DIMS，索引=df.index）。"""

def bull_count_series(df) -> pd.Series:
    """逐根多头数（0-6），索引=df.index。组合策略按日期窗口取值用。"""

def score_of(flags_row) -> int:
    """单根六维布尔 → 加权得分。"""

def state_of(score: int) -> str:
    """得分 → 强势/偏多/震荡/偏空。"""

def latest_snapshot(df) -> Optional[dict]:
    """最新一根快照：{signal_date, bull_count, score, state, MACD..MTM(各bool)}；
    df 过短(<30 根)返回 None。"""
```

数据不足（<30 根，确保各指标预热）时 `latest_snapshot` 返回 None，`bull_count_series` 返回空 Series。

### 2. `liumai_signal_db.py`（继承 `BaseDatabase`）

表 `liumai_signals`：

```sql
CREATE TABLE IF NOT EXISTS liumai_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL, name TEXT, board TEXT,
    signal_date TEXT NOT NULL,
    bull_count INTEGER, score INTEGER, state TEXT,
    macd INTEGER, kdj INTEGER, rsi INTEGER, lwr INTEGER, bbi INTEGER, mtm INTEGER,
    scan_date TEXT NOT NULL,
    UNIQUE(code, scan_date)
)
```

方法（对齐 `ChanlunSignalDB` 风格）：`init_tables`、`upsert_signals(rows)`（ON CONFLICT(code,scan_date) DO UPDATE）、`get_latest_signals()`、`list_scan_dates()`、`get_signals_by_scan_date(d)`、`clear_scan(d)`。db_path 默认 `liumai_signals.db`。

### 3. `liumai_batch.py`

```python
def scan_codes(codes, db, scan_date=None, name_board=None) -> int:
    """逐 code 经 akshare_gw.local 取日线(limit 300)，算 latest_snapshot，
    多头数≥5 者组装行写库。返回写入条数。复用 chanlun_batch._load 同款加载。"""

def main():
    """日调度入口：clear_scan(today) → 扫 list_universe() 全池 → 落库 → 日志。
    手动：docker exec agentsstock1 python3 /app/liumai_batch.py"""
```

加载复用 `chanlun_batch._load(symbol, "day", 300)`（已是标准 OHLCV、索引=日期）。

### 4. `liumai_selector.py`

```python
KEEP_COLS = ["code","name","board","signal_date","bull_count","score","state",
             "macd","kdj","rsi","lwr","bbi","mtm"]
DISPLAY_NAMES = {... 中文表头：多头数/得分/状态/各维红绿 ...}

class LiumaiSelector:
    def get_picks(self, min_bull=5, scan_date=None) -> Tuple[bool, df, msg]:
        # 读最新或指定批次，过滤 bull_count>=min_bull，按 bull_count desc, score desc
    def list_dates(self) -> List[str]
```

六维 flag 在展示层渲染为 🔴/⚪（多头红、空头白）。

### 5. `liumai_ui.py`

```python
def display_liumai_selector():
    # 标题 + caption(说明六脉口径与"最新多头数≥5")
    # 🔄 立即重算按钮：st.spinner 同步跑 liumai_batch.scan_codes(全池) → clear cache → st.rerun
    # 读 LiumaiSelector().get_picks() → st.info(msg) → st.dataframe(中文表头)
```

缓存 `@st.cache_data(ttl=1800)` 包装只读查询。

### 6. `combo_signal_db.py`（继承 `BaseDatabase`）

表 `combo_signals`：

```sql
CREATE TABLE IF NOT EXISTS combo_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL, name TEXT, board TEXT,
    chanlun_type TEXT, chanlun_date TEXT, buy_reason TEXT,
    liumai_date TEXT, liumai_bull_count INTEGER, liumai_score INTEGER,
    scan_date TEXT NOT NULL,
    UNIQUE(code, chanlun_date, scan_date)
)
```

方法：`init_tables`、`upsert_signals`、`get_latest_signals`、`list_scan_dates`、`get_signals_by_scan_date`、`clear_scan`。db_path 默认 `combo_signals.db`。

### 7. `combo_batch.py`

```python
_WINDOW = 3  # ±3 交易日

def scan(chanlun_db, combo_db, scan_date=None) -> int:
    """读 chanlun_db.get_latest_signals() 的买点(1买/2买/3买)；
    按 code 分组，逐 code 加载日线、bull_count_series；
    对每个缠论买点：取其 signal_date 在日线索引上的位置 i，检查 [i-3, i+3]
    交易日窗口内 bull_count.max()，≥5 则命中，记录该窗口内首个达标日期与多头数；
    命中行写 combo_db。返回写入条数。"""

def main():
    """日调度入口(须在 chanlun_batch 之后跑)：clear_scan(today) → scan → 日志。
    手动：docker exec agentsstock1 python3 /app/combo_batch.py"""
```

要点：
- 缠论买点 `signal_date` 是字符串日期；在该 code 日线索引中定位最近交易日下标；window 用下标 ±3 切片（自然覆盖"±3 交易日"，遇停牌按已有交易日算）。
- 若 signal_date 不在日线索引（数据缺失），该买点跳过。
- 同一 code 多个缠论买点分别判定，各自成行。

### 8. `combo_selector.py` + `combo_ui.py`

```python
# combo_selector.py
KEEP_COLS = ["code","name","board","chanlun_type","chanlun_date","buy_reason",
             "liumai_date","liumai_bull_count","liumai_score"]
DISPLAY_NAMES = {...中文...}
class ComboSelector:
    def get_picks(self, scan_date=None) -> Tuple[bool, df, msg]
    def list_dates(self) -> List[str]
```

```python
# combo_ui.py
def display_combo_selector():
    # 标题 + caption(说明组合口径：缠论买点 ±3 交易日内六脉≥5红)
    # 🔄 立即刷新按钮：st.spinner 同步跑 combo_batch.scan(chanlun_db, combo_db) → clear cache → rerun
    # 读 ComboSelector().get_picks() → st.info → st.dataframe
```

### 9. 导航重构 `app.py`

在「🎯 选股板块」expander 内：
- 加 `st.markdown("**单策略选股**")` 小标题，其后是现有 6 个按钮 + 新增 `🔱 六脉神剑`(key=`nav_liumai`, 置 `show_liumai`)。
- 加 `st.markdown("**组合策略选股**")` 小标题 + `🔗 缠论×六脉`(key=`nav_combo`, 置 `show_combo`)。
- 各按钮的"清理其他 show_ 标志"沿用现有写法；新增标志 `show_liumai` / `show_combo` 纳入彼此与缠论按钮的清理集。
- 页面路由区（现有 `show_chanlun` 分支 `app.py:382-384` 之后）增加两个**同构独立 if 块**（现有写法是独立 `if`，非 elif 链）：

```python
if 'show_liumai' in st.session_state and st.session_state.show_liumai:
    from liumai_ui import display_liumai_selector
    display_liumai_selector()

if 'show_combo' in st.session_state and st.session_state.show_combo:
    from combo_ui import display_combo_selector
    display_combo_selector()
```

### 10. 定时调度

沿用缠论 chanlun-updater 日调度（cron / 容器定时 `docker exec`）。每日收盘后**按序**执行：

```
python3 /app/chanlun_batch.py   # 先：当日缠论买点
python3 /app/liumai_batch.py    # 再：当日六脉≥5红
python3 /app/combo_batch.py     # 后：读当日缠论买点做组合(依赖前者)
```

三脚本均可单独 `docker exec` 手动触发；前台六脉页 / 组合页的 🔄 按钮做即时重算（同步、带 spinner）。调度配置变更（cron/compose）在实现说明中给出，不在本仓库代码内强制。

## 数据流

```
[日调度]
 chanlun_batch → chanlun_signals.db
 liumai_batch  → (list_universe → _load 日线 → liumai_engine.latest_snapshot → 多头数≥5) → liumai_signals.db
 combo_batch   → (chanlun_signals.db 最新买点 → 按code _load 日线 → bull_count_series →
                  缠论日±3交易日窗口内 max≥5 命中) → combo_signals.db

[前台]
 六脉页:  LiumaiSelector.get_picks → st.dataframe ；🔄 → liumai_batch.scan_codes 同步重算
 组合页:  ComboSelector.get_picks  → st.dataframe ；🔄 → combo_batch.scan 同步重算
```

## 错误处理

| 情况 | 行为 |
|------|------|
| 某 code 无数据/日线<30 根 | batch 内 try 跳过该 code（同 chanlun_batch 风格），不中断全批 |
| liumai/combo 库为空（未跑批） | selector 返回 (False,None,"暂无…批量扫描尚未运行")，UI 显示 st.info |
| 组合：chanlun 最新批次无买点 | scan 写 0 条；UI 提示"暂无缠论买点，无法形成组合信号" |
| 组合：缠论 signal_date 不在该股日线索引 | 跳过该买点 |
| 手动重算按钮执行异常 | try 包裹，st.error 友好提示，不崩页面 |

## 测试策略

- `liumai_engine`（纯函数，手工 K 线锚定）：
  - 单调强上涨序列 → 六维全多、多头数=6、得分=100、状态=强势。
  - 单调下跌 → 多头数低、状态偏空。
  - `_tdx_sma` 递归值与手算核对（小序列）。
  - 数据不足(<30 根) → `latest_snapshot` 返回 None。
- `combo_batch.scan`（monkeypatch `_load` 与 chanlun_db）：
  - 构造某 code 缠论买点 + 其 ±3 交易日内 bull_count≥5 → 命中 1 条。
  - 买点附近 bull_count<5 → 不命中。
  - chanlun 无买点 → 返回 0。
- `liumai_signal_db` / `combo_signal_db`：临时库 upsert→get_latest→list_dates 往返（对齐 `test_chanlun_signal_db` 风格）。
- selector：临时库 seed → get_picks 过滤/排序/空库提示。
- UI：AppTest 无头冒烟（桩掉 selector + batch），验证页面渲染与 🔄 按钮存在、不抛异常。

## 不做（YAGNI）

- 不画六脉神剑指标图（仅表格 + 🔴/⚪ 红绿灯列）。
- 不做组合策略的多策略可配置（本期固定 缠论×六脉、±3 交易日、≥5 红）。
- 不在本仓库内改 cron/compose 配置文件（仅文档说明调度顺序）；脚本可手动/被现有调度器调用。
- 不改动六脉之外的现有单策略实现。
