# 稳定选股盘中化 + 4时点推送 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 🛡️稳定选股 在交易日 10:00/11:00/13:30/14:30 用"历史日K+当天实时bar"重算缠论买点并复核已有买点，出全量可入清单（高亮新出/变动）邮件推送，盘后管线零变化。

**Architecture:** 新增盘中管线与盘后并存：实时快照→注入今日bar→缠论盘中重算写独立库 `chanlun_signals_intraday.db`→daily_watchlist 盘中模式 union 盘后窗内信号、用实时价重算 entry_status→全量清单+高亮→宿主 crontab 提前~13min 触发、复用邮件基建。所有盘中行为由 `CHANLUN_INTRADAY` / `WL_INTRADAY` 环境变量开关，关闭时与现状逐字节一致。

**Tech Stack:** Python3, pandas, sqlite3, akshare_gateway(5级降级链), baostock, 容器内运行(agentsstock1), 宿主 crontab + bash, 纯 `python3 test_*.py` 断言测试(无pytest)。

设计依据：`docs/superpowers/specs/2026-06-10-intraday-stable-screening-design.md`

**约定（全程适用）：**
- 测试在容器跑：`docker exec -w /app/data/profit_mining agentsstock1 python3 <test_file>.py`，期望末行 `ALL OK`。
- 新测试文件沿用 `test_v2.py` 风格：`def test_*()` + `assert`，文件末 `if __name__ == "__main__":` 顺序调用并 `print("ALL OK")`。
- 每个 Task 末尾 commit，message 用中文 `feat/test/refactor(intraday): …`，结尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- 路径前缀：容器内 `/app/...`，宿主仓库 `/home/tdxback/aiagents-stock/...`。本计划写宿主相对路径（仓库根 = `/home/tdxback/aiagents-stock`）。

---

## Task 1: 实时bar注入 `inject_today_bar`

**Files:**
- Create: `data/profit_mining/intraday_quote.py`
- Test: `data/profit_mining/test_intraday_quote.py`

- [x] **Step 1: 写失败测试**

创建 `data/profit_mining/test_intraday_quote.py`：

```python
# test_intraday_quote.py —— 盘中实时bar注入/快照解析 断言测试（无pytest，python3直接跑）
import pandas as pd
import intraday_quote as IQ


def _df(dates, closes):
    idx = pd.to_datetime(dates)
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [100.0] * len(closes)}, index=idx)


def test_inject_appends_new_today_row():
    df = _df(["2026-06-08", "2026-06-09"], [10.0, 11.0])
    bar = {"Open": 11.2, "High": 11.9, "Low": 11.1, "Close": 11.5, "Volume": 500.0}
    out = IQ.inject_today_bar(df, bar, pd.Timestamp("2026-06-10"))
    assert len(out) == 3, len(out)
    assert out.index[-1] == pd.Timestamp("2026-06-10")
    assert out["Close"].iloc[-1] == 11.5
    assert len(df) == 2  # 入参不被改


def test_inject_overwrites_existing_today_row():
    df = _df(["2026-06-09", "2026-06-10"], [11.0, 11.3])
    bar = {"Open": 11.2, "High": 12.0, "Low": 11.1, "Close": 11.8, "Volume": 700.0}
    out = IQ.inject_today_bar(df, bar, pd.Timestamp("2026-06-10"))
    assert len(out) == 2, len(out)
    assert out["Close"].iloc[-1] == 11.8
    assert out["High"].iloc[-1] == 12.0


def test_inject_none_bar_passthrough():
    df = _df(["2026-06-09", "2026-06-10"], [11.0, 11.3])
    out = IQ.inject_today_bar(df, None, pd.Timestamp("2026-06-10"))
    assert out["Close"].iloc[-1] == 11.3
    assert len(out) == 2


if __name__ == "__main__":
    test_inject_appends_new_today_row()
    test_inject_overwrites_existing_today_row()
    test_inject_none_bar_passthrough()
    print("ALL OK")
```

- [x] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_intraday_quote.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'intraday_quote'`

- [x] **Step 3: 写最小实现**

创建 `data/profit_mining/intraday_quote.py`：

```python
# intraday_quote.py —— 盘中实时行情：取全市场快照 + 把"今日实时bar"拼到日K末尾。
#   供 chanlun 盘中重算 与 daily_watchlist 盘中模式 共用。
import pandas as pd

_COLS = ["Open", "High", "Low", "Close", "Volume"]


def inject_today_bar(df, bar, today):
    """把今日实时 bar 拼到标准 OHLCV df(index=日期) 末尾。
    bar={'Open','High','Low','Close','Volume'}；today=pd.Timestamp(当天)。
    末行已是今天→覆盖；否则追加。bar 为 None/空→原样返回。不改入参。"""
    if not bar:
        return df
    today = pd.Timestamp(today).normalize()
    row = {c: float(bar.get(c)) for c in _COLS if bar.get(c) is not None}
    if len(row) < len(_COLS):
        return df  # 字段不全，保守不注入
    out = df.copy()
    out.loc[today, _COLS] = [row[c] for c in _COLS]
    return out.sort_index()[_COLS]
```

- [x] **Step 4: 跑测试确认通过**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_intraday_quote.py`
Expected: `ALL OK`

- [x] **Step 5: 提交**

```bash
git add data/profit_mining/intraday_quote.py data/profit_mining/test_intraday_quote.py
git commit -m "feat(intraday): 实时bar注入 inject_today_bar + 单测

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 实时快照 `_quote_to_bar` + `_parse_spot` + `fetch_market_snapshot`（TDX优先→akshare兜底）

**Files:**
- Modify: `data/profit_mining/intraday_quote.py`
- Test: `data/profit_mining/test_intraday_quote.py`

**数据源（用户拍板）：TDX 本地批量行情优先 → akshare 全市场快照兜底**（避东财 IP 封锁）。
- TDX 批量：`POST {akshare_gw.tdx.base_url}/api/batch-quote`，body `{"codes":[...]}`，返回 `data` 为行情列表，每条 `q`：`q["K"]["Open"/"High"/"Low"/"Close"]`=价格×1000、`q["TotalHand"]`=成交量(手，与本地日K `Volume` 同单位)、`q["Code"]`。`_quote_to_bar(q)` 把单条转 bar（停牌 Close<=0 / 缺字段→None），可单测。
- akshare 兜底：`akshare_gw.call("stock_zh_a_spot_em")` 全市场 DataFrame(中文列 代码/今开/最高/最低/最新价/成交量)，`_parse_spot` 转 `{code: bar}`，可单测。
- `fetch_market_snapshot(codes=None)` TDX 批量优先、akshare 仅补 TDX 取不到的票。已核对：`akshare_gw.call` 为网关统一入口、`akshare_gw.tdx.{base_url,available}` 存在、`/api/batch-quote` 见 `tdx-api/API_使用示例.py:89`。

- [x] **Step 1: 写失败测试（加到 test_intraday_quote.py，runner 也补调用）**

在 `test_intraday_quote.py` 的 runner 之前插入：

```python
def test_parse_spot_basic():
    spot = pd.DataFrame({
        "代码": ["600519", "000001", "300750"],
        "今开": [1700.0, 11.0, 200.0],
        "最高": [1720.0, 11.3, 205.0],
        "最低": [1695.0, 10.9, 199.0],
        "最新价": [1710.0, 11.2, 0.0],   # 300750 现价0 → 停牌/无效，应剔除
        "成交量": [3.0e5, 8.0e6, 1.0e5],
    })
    snap = IQ._parse_spot(spot)
    assert "600519" in snap and "000001" in snap
    assert "300750" not in snap, "现价<=0 应剔除"
    assert snap["600519"]["Close"] == 1710.0
    assert snap["000001"]["High"] == 11.3
    assert isinstance(list(snap.keys())[0], str) and len(list(snap.keys())[0]) == 6


def test_parse_spot_empty():
    assert IQ._parse_spot(None) == {}
    assert IQ._parse_spot(pd.DataFrame()) == {}


def test_quote_to_bar():
    q = {"Code": "000001", "TotalHand": 12345,
         "K": {"Open": 10000, "High": 10500, "Low": 9900, "Close": 10200}}
    bar = IQ._quote_to_bar(q)
    assert bar == {"Open": 10.0, "High": 10.5, "Low": 9.9, "Close": 10.2,
                   "Volume": 12345.0}, bar
    assert IQ._quote_to_bar({"K": {"Open": 0, "High": 0, "Low": 0, "Close": 0},
                             "TotalHand": 0}) is None   # 停牌 Close<=0
    assert IQ._quote_to_bar({"foo": 1}) is None          # 缺字段
```

在 runner（`if __name__`）里追加：

```python
    test_parse_spot_basic()
    test_parse_spot_empty()
    test_quote_to_bar()
```
（放在 `print("ALL OK")` 之前。）

- [x] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_intraday_quote.py`
Expected: FAIL — `AttributeError: module 'intraday_quote' has no attribute '_parse_spot'`

- [x] **Step 3: 写最小实现（加到 intraday_quote.py）**

在 `intraday_quote.py` 顶部 import 后加映射，并追加以下函数：

```python
import sys, logging
sys.path.insert(0, "/app")
logger = logging.getLogger(__name__)

# stock_zh_a_spot_em 中文列 → 标准列
_SPOT_MAP = {"今开": "Open", "最高": "High", "最低": "Low",
             "最新价": "Close", "成交量": "Volume"}


def _quote_to_bar(q):
    """TDX /api/quote|batch-quote 单条 q → 标准 bar；停牌(Close<=0)/缺字段→None。"""
    try:
        k = q["K"]
        close = float(k["Close"]) / 1000.0
        if close <= 0:
            return None
        return {"Open": float(k["Open"]) / 1000.0, "High": float(k["High"]) / 1000.0,
                "Low": float(k["Low"]) / 1000.0, "Close": close,
                "Volume": float(q.get("TotalHand", 0))}
    except (KeyError, TypeError, ValueError):
        return None


def _parse_spot(df):
    """全市场快照 DataFrame → {code(6位): {Open,High,Low,Close,Volume}}。
    现价<=0(停牌/无效)或字段缺失的票剔除。"""
    if df is None or len(df) == 0:
        return {}
    need = set(_SPOT_MAP) | {"代码"}
    if not need <= set(df.columns):
        return {}
    out = {}
    for _, r in df.iterrows():
        code = str(r["代码"]).zfill(6)
        try:
            bar = {std: float(r[zh]) for zh, std in _SPOT_MAP.items()}
        except (TypeError, ValueError):
            continue
        if bar["Close"] <= 0:
            continue
        out[code] = bar
    return out


def _tdx_batch_snapshot(codes, chunk=800):
    """TDX /api/batch-quote 批量取行情(优先源)。TDX 不可用 → {}。"""
    from akshare_gateway import akshare_gw
    import requests
    tdx = akshare_gw.tdx
    if not getattr(tdx, "available", False):
        return {}
    base = tdx.base_url.rstrip("/")
    out = {}
    for s in range(0, len(codes), chunk):
        batch = codes[s:s + chunk]
        try:
            r = requests.post(f"{base}/api/batch-quote", json={"codes": batch}, timeout=15)
            if r.status_code != 200:
                continue
            for q in (r.json().get("data") or []):
                code = str(q.get("Code", "")).zfill(6)[-6:]
                bar = _quote_to_bar(q)
                if code and bar:
                    out[code] = bar
        except Exception as e:
            logger.warning(f"[盘中快照] TDX 批量失败 {batch[0]}..: {type(e).__name__}: {str(e)[:60]}")
    return out


def fetch_market_snapshot(codes=None):
    """取实时快照 → {code(6位): bar}。TDX 批量优先，akshare 全市场快照兜底补 TDX 取不到的票。
    codes=None → 全市场(list_universe)。整体取不到返回 {}（调用方降级为纯历史）。"""
    if codes is None:
        from chanlun_universe import list_universe
        codes = [c for c, _, _ in list_universe()]
    codes = [str(c).zfill(6) for c in codes]
    if not codes:
        return {}
    out = _tdx_batch_snapshot(codes)          # 1) TDX 优先
    missing = [c for c in codes if c not in out]
    if missing:                                # 2) akshare 兜底补缺
        try:
            from akshare_gateway import akshare_gw
            sub = _parse_spot(akshare_gw.call("stock_zh_a_spot_em"))
        except Exception:
            sub = {}
        out.update({c: sub[c] for c in missing if c in sub})
    logger.info(f"[盘中快照] 取到 {len(out)}/{len(codes)} 只实时 bar")
    return out
```

> 已核对外部依赖（无需实现时再确认）：`akshare_gw.call` 为网关统一入口（`akshare_gateway.py:668`）、`akshare_gw.tdx.base_url`/`.available` 存在（同文件 TDXClient）、`/api/batch-quote` 见 `tdx-api/API_使用示例.py:89-96`。

- [x] **Step 4: 跑测试确认通过**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_intraday_quote.py`
Expected: `ALL OK`

- [x] **Step 5: 提交**

```bash
git add data/profit_mining/intraday_quote.py data/profit_mining/test_intraday_quote.py
git commit -m "feat(intraday): 全市场快照解析 _parse_spot + fetch_market_snapshot

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: 交易日精筛 `is_cn_trading_day`

**Files:**
- Modify: `data/profit_mining/intraday_quote.py`
- Test: `data/profit_mining/test_intraday_quote.py`

crontab `1-5` 只滤周末；节假日用 akshare 交易日历精筛，取不到则退化为"工作日即交易日"。

- [x] **Step 1: 写失败测试（加到 test_intraday_quote.py）**

```python
def test_trading_day_weekday_fallback(monkey=None):
    # 交易日历不可用时：工作日→True，周末→False
    import intraday_quote as IQ2
    orig = IQ2._trade_cal_dates
    IQ2._trade_cal_dates = lambda: None          # 模拟取不到日历
    try:
        assert IQ2.is_cn_trading_day(pd.Timestamp("2026-06-10")) is True   # 周三
        assert IQ2.is_cn_trading_day(pd.Timestamp("2026-06-13")) is False  # 周六
    finally:
        IQ2._trade_cal_dates = orig


def test_trading_day_calendar_excludes_holiday():
    import intraday_quote as IQ2
    orig = IQ2._trade_cal_dates
    IQ2._trade_cal_dates = lambda: {pd.Timestamp("2026-06-10").normalize()}  # 只有10号是交易日
    try:
        assert IQ2.is_cn_trading_day(pd.Timestamp("2026-06-10")) is True
        assert IQ2.is_cn_trading_day(pd.Timestamp("2026-06-11")) is False   # 不在日历→非交易日
    finally:
        IQ2._trade_cal_dates = orig
```

runner 追加：

```python
    test_trading_day_weekday_fallback()
    test_trading_day_calendar_excludes_holiday()
```

- [x] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_intraday_quote.py`
Expected: FAIL — `AttributeError: ... has no attribute '_trade_cal_dates'`

- [x] **Step 3: 写最小实现（加到 intraday_quote.py）**

```python
def _trade_cal_dates():
    """返回近年交易日集合(set[pd.Timestamp normalize])，取不到返回 None。"""
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        return {pd.Timestamp(d).normalize() for d in df["trade_date"]}
    except Exception:
        return None


def is_cn_trading_day(today=None):
    """A股交易日判断：优先交易日历，失败退化为工作日(周一~周五)。"""
    today = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    cal = _trade_cal_dates()
    if cal is not None:
        return today in cal
    return today.weekday() < 5
```

- [x] **Step 4: 跑测试确认通过**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_intraday_quote.py`
Expected: `ALL OK`

- [x] **Step 5: 提交**

```bash
git add data/profit_mining/intraday_quote.py data/profit_mining/test_intraday_quote.py
git commit -m "feat(intraday): 交易日精筛 is_cn_trading_day(日历+工作日兜底)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: chanlun_batch 支持 live_bars 注入 + 独立库 + 盘中入口

**Files:**
- Modify: `chanlun_batch.py`（`_load`、`scan_codes`、`main`/入口）
- Test: `data/profit_mining/test_chanlun_intraday_load.py`

注入只在 `_load` 一处发生；`scan_codes` 透传 `live_bars`；入口按 `CHANLUN_INTRADAY=1` 取快照、写独立库。无开关时行为零变化。

- [x] **Step 1: 写失败测试（验证 _load 注入逻辑，mock 本地源）**

创建 `data/profit_mining/test_chanlun_intraday_load.py`：

```python
# 验证 chanlun_batch._load 在给定 live_bars 时把今日bar注入日K末尾。
import sys
sys.path.insert(0, "/app")
import pandas as pd
import chanlun_batch as CB


def test_load_injects_live_bar(monkeypatch=None):
    idx = pd.to_datetime(["2026-06-08", "2026-06-09"])
    fake = pd.DataFrame({"日期": idx, "开盘": [10, 11], "最高": [10, 11],
                         "最低": [10, 11], "收盘": [10, 11], "成交量": [100, 100]})

    # 替换本地源 get_kline
    from akshare_gateway import akshare_gw
    orig = akshare_gw.local.get_kline
    akshare_gw.local.get_kline = lambda *a, **k: fake.copy()
    try:
        bars = {"600519": {"Open": 11.2, "High": 11.9, "Low": 11.1,
                           "Close": 11.5, "Volume": 500.0}}
        df = CB._load("600519", "day", 500, live_bars=bars)
        assert df.index[-1] == pd.Timestamp("2026-06-10").normalize()
        assert df["Close"].iloc[-1] == 11.5
        # 不传 live_bars → 不注入
        df0 = CB._load("600519", "day", 500)
        assert df0.index[-1] == pd.Timestamp("2026-06-09")
    finally:
        akshare_gw.local.get_kline = orig


if __name__ == "__main__":
    test_load_injects_live_bar()
    print("ALL OK")
```

> 注意：测试假设"今天"是 2026-06-10。实现里 `_load` 用 `pd.Timestamp.now()` 取今天；若在别的日期跑此测试会失败——这是单测，按需把断言里的日期改成 `pd.Timestamp.now().normalize()` 动态比较（实现时若日期漂移用 `IQ.inject` 的 today 参数对齐）。稳妥写法见下：把断言改为 `assert df.index[-1] == pd.Timestamp.now().normalize()`。

- [x] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_chanlun_intraday_load.py`
Expected: FAIL — `_load() got an unexpected keyword argument 'live_bars'`

- [x] **Step 3: 改 `chanlun_batch.py`**

改 `_load`（约 19-27 行）为：

```python
def _load(symbol: str, kind: str, limit: int, live_bars=None):
    """经本地源取标准 OHLCV（索引=日期）；无数据返回 None。
    live_bars={code:bar} 且本品种有今日实时bar时，把今日bar注入日K末尾(盘中模式)。"""
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type=kind, limit=limit)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    if live_bars and kind == "day":
        import sys as _sys
        _sys.path.insert(0, "/app/data/profit_mining")
        import intraday_quote as IQ
        code = str(symbol)[-6:].zfill(6)
        df = IQ.inject_today_bar(df, live_bars.get(code), pd.Timestamp.now().normalize())
    return df
```

改 `scan_codes` 签名与对 `_load` 的调用：把 `def scan_codes(codes, db, scan_date=None, days=7, name_board=None)` 改为 `def scan_codes(codes, db, scan_date=None, days=7, name_board=None, live_bars=None)`，并把内部 `df_day = _load(code, "day", 500)` 改为 `df_day = _load(code, "day", 500, live_bars=live_bars)`（若还有分钟/周线 `_load` 调用，不传 live_bars，仅日线注入）。

- [x] **Step 4: 跑测试确认通过**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_chanlun_intraday_load.py`
Expected: `ALL OK`

- [x] **Step 5: 加盘中入口**

在 `chanlun_batch.py` 的 `main()`（或 `__main__` 块）顶部加盘中分支。定位 `main()` 里构造 `ChanlunSignalDB(...)` 与调用 `scan_codes(...)` 处，改为：

```python
    import os, sys
    intraday = os.getenv("CHANLUN_INTRADAY") == "1"
    live_bars = None
    db_file = os.path.join(DATA_DIR, "chanlun_signals.db")
    if intraday:
        sys.path.insert(0, "/app/data/profit_mining")
        import intraday_quote as IQ
        live_bars = IQ.fetch_market_snapshot()
        db_file = os.path.join(DATA_DIR, "chanlun_signals_intraday.db")
        logger.info(f"[缠论盘中] 实时快照 {len(live_bars)} 只，写独立库 {db_file}")
    db = ChanlunSignalDB(db_file)
    # …原有 universe 枚举…
    n = scan_codes(codes, db, scan_date=scan_date, name_board=name_board, live_bars=live_bars)
```

> 用 `ChanlunSignalDB(db_file)` 时确认其构造支持自定义路径；若默认无参，实现时给它加可选 `path` 参数（与 `base_db`/`DATA_DIR` 一致），盘后默认不变。

- [x] **Step 6: 冒烟（小批，确认入口不报错、写独立库）**

Run:
```
docker exec -w /app -e CHANLUN_INTRADAY=1 agentsstock1 python3 -c "import chanlun_batch as C; C.main()" 2>&1 | tail -5
docker exec agentsstock1 ls -la /app/data/chanlun_signals_intraday.db
```
Expected: 日志出现 `[缠论盘中] 实时快照 N 只`，独立库文件存在；`/app/data/chanlun_signals.db` 未被改动（mtime 不变）。

- [x] **Step 7: 提交**

```bash
git add chanlun_batch.py data/profit_mining/test_chanlun_intraday_load.py
git commit -m "feat(intraday): chanlun_batch 支持 live_bars 注入+独立盘中库+CHANLUN_INTRADAY入口

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: daily_watchlist 信号 union 复核 `load_signals`

**Files:**
- Modify: `data/profit_mining/daily_watchlist.py`（抽出取信号逻辑为 `load_signals`）
- Test: `data/profit_mining/test_daily_watchlist_union.py`

- [x] **Step 1: 写失败测试（用临时 sqlite 构造两库）**

创建 `data/profit_mining/test_daily_watchlist_union.py`：

```python
import sqlite3, tempfile, os
import daily_watchlist as dw

_DDL = ("CREATE TABLE signals(code TEXT,name TEXT,board TEXT,signal_type TEXT,"
        "signal_date TEXT,buy_price REAL,scan_date TEXT)")


def _mkdb(path, rows, scan_date):
    c = sqlite3.connect(path); c.execute(_DDL)
    for r in rows:
        c.execute("INSERT INTO signals VALUES(?,?,?,?,?,?,?)",
                  (r[0], r[1], r[2], r[3], r[4], r[5], scan_date))
    c.commit(); c.close()


def test_union_dedup_intraday_priority():
    d = tempfile.mkdtemp()
    post = os.path.join(d, "post.db"); intra = os.path.join(d, "intra.db")
    # 盘后库：A 信号(窗内 06-09) 和 B(超窗 06-01，应被剔)
    _mkdb(post, [("600519", "贵州茅台", "主板", "1买", "2026-06-09", 1700.0),
                 ("000002", "万科", "主板", "1买", "2026-06-01", 10.0)], "2026-06-09")
    # 盘中库：A 同 code 同日(盘中优先) + 新出 C
    _mkdb(intra, [("600519", "贵州茅台", "主板", "1买", "2026-06-09", 1705.0),
                  ("300750", "宁德时代", "创业板", "2买", "2026-06-10", 200.0)], "2026-06-10")

    rows = dw.load_signals(post_db=post, intraday_db=intra,
                           today="2026-06-10", window_days=2)
    keyed = {(r["code"], r["signal_date"]): r for r in rows}
    assert ("600519", "2026-06-09") in keyed
    assert keyed[("600519", "2026-06-09")]["buy_price"] == 1705.0, "盘中优先"
    assert ("300750", "2026-06-10") in keyed, "盘中新出应纳入"
    assert ("000002", "2026-06-01") not in keyed, "超窗(>2交易日)盘后信号应剔除"


if __name__ == "__main__":
    test_union_dedup_intraday_priority()
    print("ALL OK")
```

- [x] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_daily_watchlist_union.py`
Expected: FAIL — `AttributeError: module 'daily_watchlist' has no attribute 'load_signals'`

- [x] **Step 3: 实现 `load_signals`（加到 daily_watchlist.py）**

在 `main()` 之前加：

```python
def _recent_trade_days(today, n):
    """返回 today 及其前 n 个自然日内的日期字符串集合(粗口径窗，配合 entry_status 精判)。"""
    t = pd.Timestamp(today)
    # 用自然日 *2 兜住周末，entry_status 再按交易日 gap 精判
    return {(t - pd.Timedelta(days=k)).strftime("%Y-%m-%d") for k in range(0, n * 2 + 3)}


def load_signals(post_db=SIGDB, intraday_db=None, today=None, window_days=2, scan_date=None):
    """取候选买点：盘中库今日新信号 ∪ 盘后库窗内信号(signal_date 距今 ≤window_days*交易日)。
    按 (code, signal_date) 去重，盘中库优先。返回 list[dict(code,name,board,signal_type,signal_date,buy_price)]。
    intraday_db=None → 仅盘后(scan_date 那批)，等价旧行为。"""
    today = today or pd.Timestamp.now().strftime("%Y-%m-%d")
    keep = _recent_trade_days(today, window_days)
    merged = {}

    def _pull(path, only_recent):
        c = sqlite3.connect(path); c.row_factory = sqlite3.Row
        sd = c.execute("SELECT MAX(scan_date) FROM signals").fetchone()[0]
        rs = c.execute("SELECT code,name,board,signal_type,signal_date,buy_price FROM signals "
                       "WHERE scan_date=? AND signal_type IN ('1买','2买','3买')", (sd,)).fetchall()
        c.close()
        for r in rs:
            if only_recent and r["signal_date"] not in keep:
                continue
            merged[(str(r["code"]).zfill(6), r["signal_date"])] = dict(r)

    _pull(post_db, only_recent=intraday_db is not None)
    if intraday_db and os.path.exists(intraday_db):
        _pull(intraday_db, only_recent=False)   # 盘中库后写=覆盖=优先
    return list(merged.values())
```

> 旧 `main()` 里直接 `con.execute("SELECT ... FROM signals WHERE scan_date=? ...")` 的那段（96-100 行）改为调用 `rows = load_signals(scan_date=sd)`（盘后路径，`intraday_db=None`，行为等价）。`r["code"]` 等键访问改为 dict 访问（`load_signals` 已返回 dict）。

- [x] **Step 4: 跑测试确认通过 + 回归 entry 测试**

Run:
```
docker exec -w /app/data/profit_mining agentsstock1 python3 test_daily_watchlist_union.py
docker exec -w /app/data/profit_mining agentsstock1 python3 test_daily_watchlist_entry.py
```
Expected: 两个都 `ALL OK`（entry 测试若用 pytest 风格无 runner，则 `python3 -m pytest test_daily_watchlist_entry.py -q`）。

- [x] **Step 5: 提交**

```bash
git add data/profit_mining/daily_watchlist.py data/profit_mining/test_daily_watchlist_union.py
git commit -m "feat(intraday): daily_watchlist 抽出 load_signals(盘中∪盘后窗内,盘中优先)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 变化高亮 `mark_changes`

**Files:**
- Modify: `data/profit_mining/daily_watchlist.py`
- Test: `data/profit_mining/test_daily_watchlist_changes.py`

- [x] **Step 1: 写失败测试**

创建 `data/profit_mining/test_daily_watchlist_changes.py`：

```python
import daily_watchlist as dw


def _row(code, status):
    return {"股票代码": code, "可入状态": status, "精选": "", "星级": "", "量比": 1.0,
            "买点类型": "1买", "命中规则": "A抄底", "资金确认": "", "中枢底部": ""}


def test_mark_new_and_changed():
    prev = [_row("600519", "尾窗"), _row("000001", "可入")]
    cur = [_row("600519", "可入"),     # 尾窗→可入 = 变动
           _row("000001", "可入"),     # 不变
           _row("300750", "可入")]     # 上轮没有 = 新出
    out = dw.mark_changes(cur, prev)
    m = {r["股票代码"]: r["变化标记"] for r in out}
    assert m["300750"] == "🆕新出", m
    assert m["600519"] == "⤴变动", m
    assert m["000001"] == "", m
    # 高亮(新出/变动)置顶
    assert out[0]["股票代码"] in ("300750", "600519")
    assert out[-1]["股票代码"] == "000001"


def test_mark_first_run_no_prev():
    cur = [_row("600519", "可入")]
    out = dw.mark_changes(cur, None)
    assert out[0]["变化标记"] == ""   # 首轮无上轮→不打标


if __name__ == "__main__":
    test_mark_new_and_changed()
    test_mark_first_run_no_prev()
    print("ALL OK")
```

- [x] **Step 2: 跑测试确认失败**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_daily_watchlist_changes.py`
Expected: FAIL — `has no attribute 'mark_changes'`

- [x] **Step 3: 实现 `mark_changes`（加到 daily_watchlist.py）**

```python
_ENTERABLE = {"可入", "尾窗"}
_GOODER = {"可入": 2, "尾窗": 1}   # 变好判定：分值升高


def mark_changes(cur, prev):
    """对当前行打 变化标记 列：上轮不存在=🆕新出；可入状态变好(尾窗→可入/新转可入)=⤴变动。
    高亮(新出/变动)置顶，其余维持原顺序。prev=None(首轮)→全不打标。返回新列表。"""
    pmap = {r["股票代码"]: r.get("可入状态", "") for r in (prev or [])}
    for r in cur:
        code, st = r["股票代码"], r.get("可入状态", "")
        if prev is None:
            r["变化标记"] = ""
        elif code not in pmap:
            r["变化标记"] = "🆕新出" if st in _ENTERABLE else ""
        else:
            up = _GOODER.get(st, 0) > _GOODER.get(pmap[code], 0)
            r["变化标记"] = "⤴变动" if (up and st in _ENTERABLE) else ""
    hi = [r for r in cur if r["变化标记"]]
    lo = [r for r in cur if not r["变化标记"]]
    return hi + lo
```

- [x] **Step 4: 跑测试确认通过**

Run: `docker exec -w /app/data/profit_mining agentsstock1 python3 test_daily_watchlist_changes.py`
Expected: `ALL OK`

- [x] **Step 5: 提交**

```bash
git add data/profit_mining/daily_watchlist.py data/profit_mining/test_daily_watchlist_changes.py
git commit -m "feat(intraday): mark_changes 标记新出/变动并置顶+单测

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: daily_watchlist 盘中模式接线（WL_INTRADAY）

**Files:**
- Modify: `data/profit_mining/daily_watchlist.py`（`main`、`_load`、输出）

把前面零件接进主流程，仅当 `WL_INTRADAY=1` 生效；无开关时盘后行为不变。

- [x] **Step 1: 改 `_load` 接受注入**

`_load(code)`（39-44 行）改为：

```python
def _load(code, live_bars=None):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=600)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()[["Open", "High", "Low", "Close", "Volume"]]
    if live_bars:
        import intraday_quote as IQ
        df = IQ.inject_today_bar(df, live_bars.get(str(code).zfill(6)), pd.Timestamp.now().normalize())
    return df
```

`main()` 里 `df = _load(code)` 改为 `df = _load(code, live_bars=LIVE_BARS)`（`LIVE_BARS` 见下）。

- [x] **Step 2: 改 `main()` 头部：读开关、取快照、定路径**

在 `main()` 开头（`_refresh_index()` 之前）加：

```python
    INTRADAY = os.getenv("WL_INTRADAY") == "1"
    LIVE_BARS = None
    INTRA_DB = "/app/data/chanlun_signals_intraday.db"
    slot = os.getenv("WL_SLOT", pd.Timestamp.now().strftime("%H%M"))   # 时段标签，用于文件名
    if INTRADAY:
        import intraday_quote as IQ
        LIVE_BARS = IQ.fetch_market_snapshot()
        print(f"[盘中选股] WL_INTRADAY=1，实时快照 {len(LIVE_BARS)} 只，时段 {slot}", flush=True)
```

把取信号那行（Task5 已改为 `rows = load_signals(scan_date=sd)`）在盘中分支替换为：

```python
    if INTRADAY:
        today = pd.Timestamp.now().strftime("%Y-%m-%d")
        rows = load_signals(post_db=SIGDB, intraday_db=INTRA_DB, today=today, window_days=2)
        sd = today
    else:
        sd = sys.argv[1] if len(sys.argv) > 1 else None  # 维持旧默认(MAX(scan_date))
        rows = load_signals(scan_date=sd)
        if sd is None:
            sd = max((r.get("scan_date") for r in rows), default=pd.Timestamp.now().strftime("%Y-%m-%d"))
```

> `entry_status` 的 `close_scan` 已经用 `df` 末根 bar（盘中模式下 = 注入的实时bar），无需另改——实时价天然进入可入判定。`gap` 用交易日 index 差，注入今日bar后 j 指向今天，逻辑自洽。

- [x] **Step 3: 改输出：盘中写独立目录 + latest 指针 + 高亮**

定位写文件段（241-245 行）。在排序后、写文件前插入高亮，并按模式选路径：

```python
    if INTRADAY:
        intra_dir = f"{HISTDIR}/intraday"
        os.makedirs(intra_dir, exist_ok=True)
        # 读本交易日上一轮快照做对比
        import glob as _g
        prevs = sorted(_g.glob(f"{intra_dir}/每日自选股清单_{sd}_*.csv"))
        prev_rows = None
        if prevs:
            import csv as _csv
            with open(prevs[-1], encoding="utf-8-sig") as f:
                prev_rows = list(_csv.DictReader(f))
        out = mark_changes(out, prev_rows)
        cols = ["变化标记"] + cols           # 高亮列置首
        paths = [f"{intra_dir}/每日自选股清单_{sd}_{slot}.csv",
                 f"{intra_dir}/每日自选股清单_latest.csv"]
    else:
        os.makedirs(HISTDIR, exist_ok=True)
        paths = [OUT, f"{HISTDIR}/每日自选股清单_{sd}.csv"]
```

把原来的 `for path in (OUT, f"{HISTDIR}/每日自选股清单_{sd}.csv"):` 改为 `for path in paths:`。（`变化标记` 列只在盘中存在；盘后 `cols` 不含它。）

- [x] **Step 4: 冒烟（盘中模式跑一次）**

Run:
```
docker exec -w /app -e WL_INTRADAY=1 -e WL_SLOT=TEST agentsstock1 python3 -u /app/data/profit_mining/daily_watchlist.py 2>&1 | tail -8
docker exec agentsstock1 ls -la /app/data/profit_mining/watchlist_history/intraday/
docker exec agentsstock1 head -1 /app/data/profit_mining/watchlist_history/intraday/每日自选股清单_latest.csv
```
Expected: 出清单、独立目录有 `_TEST.csv` 与 `_latest.csv`，首行列以 `变化标记` 开头；`每日自选股清单.csv`(盘后latest) 未被改动。

- [x] **Step 5: 回归（盘后模式行为不变）**

Run: `docker exec -w /app agentsstock1 python3 -u /app/data/profit_mining/daily_watchlist.py 2>&1 | tail -3`
Expected: 正常出盘后清单，写 `每日自选股清单.csv`，列与改动前一致（无 `变化标记`）。

- [x] **Step 6: 提交**

```bash
git add data/profit_mining/daily_watchlist.py
git commit -m "feat(intraday): daily_watchlist 盘中模式(WL_INTRADAY:实时bar+union+高亮+独立输出)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: push_watchlist 支持 --slot + 高亮区

**Files:**
- Modify: `ops/push_watchlist.py`（参数、subject、render_html 高亮区）

- [x] **Step 1: 加 `--slot` 参数解析**

在 `main()` 的参数循环里（`elif a == "--out":` 之后）加：

```python
        elif a == "--slot":
            slot = args[i + 1]; i += 2
```

并在循环前初始化 `slot = None`（与 `to_override, dry, ...` 同行声明）。

- [x] **Step 2: 盘中 subject + 高亮统计**

定位 `subject = f"【每日选股】{scan} 精选{nSel}只(核心{nCore}) / 共{n}只"`，改为：

```python
    if slot:
        nNew = sum(1 for r in rows if r.get("变化标记", "").startswith("🆕"))
        nChg = sum(1 for r in rows if r.get("变化标记", "").startswith("⤴"))
        subject = f"🛡️盘中选股 {scan} {slot} 时段 / 新出{nNew} 变动{nChg} / 共{n}只"
    else:
        subject = f"【每日选股】{scan} 精选{nSel}只(核心{nCore}) / 共{n}只"
```

- [x] **Step 3: 顶部免责区(已定) + 本时段新增/变动区注入正文**

`render_html(rows)` 返回 `body`。盘中(slot)时在最上方先拼**醒目免责区**（用户拍板：盘中信号为临时态、收盘前可能消失），再拼"本时段新增/变动"概览（有高亮行才拼）。在 `subject` 计算后、`if out_html:` 之前加：

```python
    if slot:
        disclaimer = (
            '<div style="background:#fdecea;border-left:4px solid #d9534f;padding:12px 16px;'
            'border-radius:4px;margin-bottom:12px;font-size:14px;color:#a33;line-height:1.7;">'
            '⚠️ <b>盘中临时态提示</b>：本清单基于<b>未收盘实时 bar</b>，信号为<b>临时态</b>，'
            '随价格变动/收盘后可能消失，仅供盘中参考，非投资建议。</div>')
        hi = [r for r in rows if r.get("变化标记", "")]
        banner = ""
        if hi:
            items = "".join(
                f"<li>{html.escape(r['变化标记'])} <b>{html.escape(str(r.get('股票名称','')))}</b>"
                f" {html.escape(str(r.get('股票代码','')))} · {html.escape(str(r.get('可入状态','')))}"
                f" · {html.escape(str(r.get('买点类型','')))}</li>"
                for r in hi)
            banner = (f"<h3>本时段新增/变动（{len(hi)}）</h3><ul>{items}</ul><hr>")
        body = disclaimer + banner + body   # 免责区永远置顶
```

> `render_html` 内部生成的全量表保持不变；免责区永远置顶，高亮区附加其下。`html` 模块已在文件顶部 import。Step 4 干跑应额外断言含 `盘中临时态提示`。

- [x] **Step 4: 干跑验证（用 Task7 冒烟产出的盘中 latest）**

Run:
```
docker exec -w /app agentsstock1 python3 /app/ops/push_watchlist.py \
  --csv /app/data/profit_mining/watchlist_history/intraday/每日自选股清单_latest.csv \
  --slot 10:00 --dry --out /tmp/intraday_preview.html
docker exec agentsstock1 sh -c "grep -c '盘中选股' /tmp/intraday_preview.html; grep -c '本时段新增/变动' /tmp/intraday_preview.html"
```
Expected: `[--dry] 主题: 🛡️盘中选股 … 10:00 时段 …`；预览 HTML 含标题与（若有高亮）"本时段新增/变动"区。

- [x] **Step 5: 提交**

```bash
git add ops/push_watchlist.py
git commit -m "feat(intraday): push_watchlist 支持 --slot(盘中主题)+本时段新增/变动高亮区

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: 盘中编排脚本 `ops/intraday_watchlist_and_mail.sh`

**Files:**
- Create: `ops/intraday_watchlist_and_mail.sh`

- [x] **Step 1: 写脚本**

创建 `ops/intraday_watchlist_and_mail.sh`（参照 `daily_watchlist_and_mail.sh`，加交易日门控、盘中开关）：

```bash
#!/bin/bash
# 盘中稳定选股+推送：宿主 crontab 在 09:47/10:47/13:17/14:17 提前~13min 触发。
# 用法: intraday_watchlist_and_mail.sh <时段标签如 10:00>
# 流程: 交易日门控 → 缠论盘中重算(独立库) → daily_watchlist 盘中清单(实时价+高亮) → 发邮件。
# crontab(宿主): 47 9 * * 1-5 .../intraday_watchlist_and_mail.sh 10:00 >> /home/tdxback/report/intraday_watchlist_mail.log 2>&1
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SLOT="${1:-$(date +%H:%M)}"
HHMM=$(echo "$SLOT" | tr -d ':')
OPS="/home/tdxback/aiagents-stock/ops"
INTRA_LATEST="/app/data/profit_mining/watchlist_history/intraday/每日自选股清单_latest.csv"

# -1) 并发锁(已定)：抢不到说明上一轮还在跑 → 直接退出，不与上一轮叠跑抢资源
exec 9>/tmp/intraday_watchlist.lock
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 上一轮仍在运行(未获锁)，跳过 slot=$SLOT"; exit 0
fi

echo "[$(date '+%F %T')] === 盘中选股 $SLOT 开始 ==="

# 0) 交易日门控(容器内判，复用 intraday_quote.is_cn_trading_day)
if ! docker exec -w /app/data/profit_mining agentsstock1 python3 -c \
     "import intraday_quote as IQ,sys; sys.exit(0 if IQ.is_cn_trading_day() else 1)"; then
  echo "[$(date '+%F %T')] 非交易日，跳过"; exit 0
fi

# 1) 缠论盘中重算(写独立库;失败仅用盘后库复核)
if docker exec -w /app -e CHANLUN_INTRADAY=1 agentsstock1 python3 -u /app/chanlun_batch.py; then
  echo "[$(date '+%F %T')] 缠论盘中重算完成"
else
  echo "[$(date '+%F %T')] ⚠ 缠论盘中重算失败(仅复核盘后已有买点)"
fi

# 2) 盘中清单(实时价+union+高亮)
if docker exec -w /app -e WL_INTRADAY=1 -e WL_SLOT="$HHMM" agentsstock1 \
     python3 -u /app/data/profit_mining/daily_watchlist.py; then
  echo "[$(date '+%F %T')] 盘中清单已更新"
else
  echo "[$(date '+%F %T')] ⚠ 盘中清单生成失败(用上一轮清单继续发)"
fi

# 3) 发邮件(读盘中 latest，主题带时段)
if docker exec -w /app agentsstock1 python3 /app/ops/push_watchlist.py \
     --csv "$INTRA_LATEST" --slot "$SLOT"; then
  echo "[$(date '+%F %T')] 邮件已发送"
else
  echo "[$(date '+%F %T')] ⚠ 邮件发送失败"
fi
echo "[$(date '+%F %T')] === 盘中选股 $SLOT 完成 ==="
```

- [x] **Step 2: 赋可执行权限**

Run: `chmod +x /home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh`

- [x] **Step 3: 端到端干跑（--dry 不真发信）**

临时把脚本第 3 步的 push 命令手动加 `--dry --out /tmp/it.html` 跑一遍，或直接验证前两步 + push --dry：
```
SLOT=10:00 bash -c 'docker exec -w /app -e WL_INTRADAY=1 -e WL_SLOT=1000 agentsstock1 python3 -u /app/data/profit_mining/daily_watchlist.py >/tmp/wl.log 2>&1; tail -3 /tmp/wl.log'
docker exec -w /app agentsstock1 python3 /app/ops/push_watchlist.py --csv "/app/data/profit_mining/watchlist_history/intraday/每日自选股清单_latest.csv" --slot 10:00 --dry
```
Expected: 清单生成、push `--dry` 打印盘中主题，无异常。

- [x] **Step 4: 提交**

```bash
git add ops/intraday_watchlist_and_mail.sh
git commit -m "feat(intraday): 盘中编排脚本(交易日门控+缠论盘中重算+清单+推送)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: 全量回归 + 既有未提交改动纳入 + spec 状态

**Files:**
- Modify: 工作区既有未提交改动（`app.py` nav_stable、`chanlun_schedule.sh`、`daily_watchlist.py` 扫描日价、`requirements.txt` baostock）一并审阅提交

- [x] **Step 1: 跑既有测试套件确认无回归**

Run:
```
docker exec -w /app/data/profit_mining agentsstock1 python3 test_v2.py
docker exec -w /app/data/profit_mining agentsstock1 python3 test_features.py
docker exec -w /app/data/profit_mining agentsstock1 python3 test_intraday_quote.py
docker exec -w /app/data/profit_mining agentsstock1 python3 test_chanlun_intraday_load.py
docker exec -w /app/data/profit_mining agentsstock1 python3 test_daily_watchlist_union.py
docker exec -w /app/data/profit_mining agentsstock1 python3 test_daily_watchlist_changes.py
```
Expected: 全部 `ALL OK`。

- [x] **Step 2: 提交既有未提交改动（盘后导航/调度/列/依赖）**

```bash
git add app.py chanlun_schedule.sh requirements.txt
git commit -m "feat(stable): 🛡️稳定选股接入前台导航+盘后调度顺带生成清单+baostock依赖

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
（`daily_watchlist.py` 的"扫描日价"列改动已随前面盘中任务一起提交，无需重复。）

- [x] **Step 3: AppTest 无头渲染稳定选股页（沿用既有方法）**

Run:
```
docker exec -w /app agentsstock1 python3 -c "
from streamlit.testing.v1 import AppTest
at = AppTest.from_function(lambda: __import__('stable_ui').display_stable_selector()).run()
print('exception=', at.exception); print('dataframes=', len(at.dataframe))
"
```
Expected: 无 exception，渲染出方案表 + 选股清单 dataframe。

- [x] **Step 4: 标记 spec 完成状态（在计划文件勾选）**

确认本计划所有 Task 勾选完成；spec 与 plan 已落 `docs/superpowers/`。

- [x] **Step 5: 提交计划勾选状态**

```bash
git add docs/superpowers/plans/2026-06-10-intraday-stable-screening.md
git commit -m "docs(intraday): 标记实施计划完成

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: 上线（运维，需用户在宿主执行）

> 这些步骤改动生产/对外，**需在用户确认并具备容器环境时执行**，不在代码评审范围。

- [ ] **Step 1: 拉起容器并重建镜像（让导航等改动对用户可见）**

```bash
cd /home/tdxback/aiagents-stock && sudo docker compose up -d --build
```

- [ ] **Step 2: 容器内手动跑一次盘中全链冒烟**

```bash
/home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh 10:00
```
Expected: 日志走完交易日门控→重算→清单→邮件；收到主题 `🛡️盘中选股 … 10:00 时段` 的邮件。

- [ ] **Step 3: 安装宿主 crontab 4 条**

`crontab -e` 加（注意 chanlun-updater 盘后 20:00 与本盘中库互不影响）：
```
47 9  * * 1-5 /home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh 10:00 >> /home/tdxback/report/intraday_watchlist_mail.log 2>&1
47 10 * * 1-5 /home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh 11:00 >> /home/tdxback/report/intraday_watchlist_mail.log 2>&1
17 13 * * 1-5 /home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh 13:30 >> /home/tdxback/report/intraday_watchlist_mail.log 2>&1
17 14 * * 1-5 /home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh 14:30 >> /home/tdxback/report/intraday_watchlist_mail.log 2>&1
```

- [ ] **Step 4: 次交易日核验**

核验 4 个时段邮件按时到达、内容含全量清单 + 本时段新增/变动；`intraday_watchlist_mail.log` 无报错。

---

## 自评清单（写计划后自查，已过）

- **Spec 覆盖**：实时bar注入(T1)、快照(T2)、交易日(T3)、缠论盘中重算独立库(T4)、union复核(T5)、高亮(T6)、盘中接线(T7)、推送slot+高亮区(T8)、编排+门控(T9)、回归+既有改动+上线(T10/11) — 对应 spec §4.1-4.6/§5/§6/§7 全覆盖。
- **零变化保证**：T4/T5/T7 均强调无 `*_INTRADAY` 开关时盘后逐字节不变，T7-Step5 与 T10-Step1 显式回归。
- **类型/命名一致**：`inject_today_bar(df,bar,today)`、`fetch_market_snapshot()→{code:bar}`、`_parse_spot`、`is_cn_trading_day`、`load_signals(post_db,intraday_db,today,window_days,scan_date)`、`mark_changes(cur,prev)→加"变化标记"列`、`WL_INTRADAY/CHANLUN_INTRADAY/WL_SLOT`、独立库 `chanlun_signals_intraday.db`、盘中输出 `watchlist_history/intraday/` — 全计划一致。
- **外部依赖点（已核对，无需实现时再查）**：① 网关入口 `akshare_gw.call`（`akshare_gateway.py:668`）+ TDX 批量 `akshare_gw.tdx.base_url/.available` + `/api/batch-quote`（`tdx-api/API_使用示例.py:89`）✓；② `ChanlunSignalDB(db_path)` 构造支持自定义库名，裸名落 `data/` 目录（`chanlun_signal_db.py:16`+`base_db.py:17`），故 `ChanlunSignalDB("chanlun_signals_intraday.db")`→`data/chanlun_signals_intraday.db` ✓；③ 现有 `test_daily_watchlist_entry.py` 为纯 `assert` 风格非 pytest，直接 `python3` 跑 ✓。
- **挂载约束（实现关键）**：仅 `./data:/app/data` 挂载——`data/profit_mining/*` 与 `daily_watchlist.py` 改动容器内即时生效；**`chanlun_batch.py` 在 `/app` 根烤进镜像**，T4 开发期测试前须 `docker cp chanlun_batch.py agentsstock1:/app/chanlun_batch.py`，最终随 T11 重建镜像生效。
- **用户拍板 4 决策全部落地**：① 实时源「TDX 批量优先→akshare 兜底」= T2 `fetch_market_snapshot`（已纠正原 akshare 优先版）；② flock 防叠跑 = T9 脚本 `flock -n 9`，抢不到即 `exit 0`；③ 邮件顶部醒目免责「盘中临时态」= T8-Step3 `disclaimer` 永久置顶；④ 6-03 未提交改动随本次上线 = T10/T11 提交+重建镜像。
