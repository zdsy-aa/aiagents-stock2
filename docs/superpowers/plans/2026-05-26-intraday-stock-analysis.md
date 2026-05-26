# 股票分析-分时（纯短线技术面）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把前端「股票分析」改名为「股票分析-日」，并在其下新增「股票分析-分时」——仅按分钟线（5min/30min 可选）做纯短线技术面 AI 分析。

**Architecture:** 复用现有 `StockAnalysisEngine.run_full_analysis` 流水线，给它加 `freq` 入参（分钟取数）+ 用 `enabled_analysts` 只开技术面；分钟数据走网关 route B 本地库（全市场已下载 5min/30min）→ TDX 降级。前端新增一个独立视图，复用现有结果渲染组件。不改动现有日线分析行为。

**Tech Stack:** Python 3.12、Streamlit、pandas、SQLite（route B 本地 K 线库）、现有 akshare_gateway 四级降级链。

---

## 文件结构

- `akshare_gateway.py` — 新增 `AKShareGateway.get_minute_kline()`（分钟取数：本地→TDX）。
- `stock_data.py` — 新增 `StockDataFetcher.get_minute_data()`（分钟 DataFrame → 标准 OHLCV）。
- `stock_analysis_engine.py` — `run_full_analysis` 加 `freq` 入参 + 基本面门控。
- `app.py` — 首页按钮改名、新增分时导航按钮与路由、新增 `display_intraday_analysis()` 视图。
- `tests/test_gateway_minute_kline.py`、`tests/test_minute_data.py`、`tests/test_engine_intraday.py` — 新增测试。

**测试约定：** 测试是可直接 `python3 tests/xxx.py` 运行的脚本（同 `tests/test_portfolio_db_regression.py`），用真实 host 本地库 `/home/tdxback/aiagents-stock/tdx-data/database/kline`（5528 只，样本 `600519` 含 DayKline/Minute5Kline/Minute30Kline）。因网关 singleton 在 import 时按 `LOCAL_DB_DIR` 定位本地库，测试必须在 **import 之前** 设该环境变量。

---

### Task 1: 网关分钟取数 `get_minute_kline`

**Files:**
- Modify: `akshare_gateway.py`（类 `AKShareGateway`，class 定义在 line 541；`call` 方法在 line 608）
- Test: `tests/test_gateway_minute_kline.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_gateway_minute_kline.py
"""网关分钟K线取数：route B 本地库优先。"""
import os

os.environ["LOCAL_DB_DIR"] = "/home/tdxback/aiagents-stock/tdx-data/database/kline"
os.environ.setdefault("LOCAL_DB_ENABLED", "true")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from akshare_gateway import akshare_gw


def test_get_minute_kline_local_30min():
    df = akshare_gw.get_minute_kline("600519", "30min", limit=240)
    assert df is not None and not df.empty
    assert list(df.columns)[:5] == ["日期", "开盘", "收盘", "最高", "最低"]
    assert len(df) <= 240
    # 分钟级时间戳应含多个不同的小时（非纯日期）
    assert df["日期"].dt.hour.nunique() > 1


def test_get_minute_kline_5min():
    df = akshare_gw.get_minute_kline("600519", "5min", limit=240)
    assert df is not None and not df.empty
    assert len(df) <= 240


if __name__ == "__main__":
    test_get_minute_kline_local_30min()
    test_get_minute_kline_5min()
    print("PASS: 网关分钟取数")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/tdxback/aiagents-stock && python3 tests/test_gateway_minute_kline.py`
Expected: FAIL — `AttributeError: 'AKShareGateway' object has no attribute 'get_minute_kline'`

- [ ] **Step 3: 写最小实现**

在 `akshare_gateway.py` 的 `class AKShareGateway` 内，紧跟 `call` 方法之后，新增：

```python
    def get_minute_kline(self, symbol, freq, limit=240):
        """获取分钟K线（route B 本地 → TDX；东财分钟接口被封，不走 AKTools/akshare）。

        freq: '5min' / '30min'（本地 _PERIOD_TO_TABLE 与 TDX _PERIOD_TO_TDX_TYPE 均支持）
        返回中文列 DataFrame（日期/开盘/收盘/最高/最低/成交量/成交额）或 None
        """
        if self.local.available:
            df = self.local.get_kline(symbol, kline_type=freq, limit=limit)
            if df is not None and not df.empty:
                return df
        if self.tdx.available:
            df = self.tdx.get_kline(symbol, kline_type=freq, limit=limit)
            if df is not None and not df.empty:
                return df
        return None
```

- [ ] **Step 4: 运行确认通过**

Run: `cd /home/tdxback/aiagents-stock && python3 tests/test_gateway_minute_kline.py`
Expected: `PASS: 网关分钟取数`

- [ ] **Step 5: 提交**

```bash
git add akshare_gateway.py tests/test_gateway_minute_kline.py
git commit -m "feat(gateway): 新增 get_minute_kline 分钟K线取数（本地→TDX）"
```

---

### Task 2: 数据层 `get_minute_data`

**Files:**
- Modify: `stock_data.py`（类 `StockDataFetcher`；现有 `get_stock_data` 在 line 36、`_get_chinese_stock_data` 在 line 423、`calculate_technical_indicators` 在 line 525）
- Test: `tests/test_minute_data.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_minute_data.py
"""数据层分钟取数：返回标准 OHLCV（Date 索引），可直接算指标。"""
import os

os.environ["LOCAL_DB_DIR"] = "/home/tdxback/aiagents-stock/tdx-data/database/kline"
os.environ.setdefault("LOCAL_DB_ENABLED", "true")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from stock_data import StockDataFetcher


def test_get_minute_data_30min():
    f = StockDataFetcher()
    df = f.get_minute_data("600519", "30min", limit=240)
    assert isinstance(df, pd.DataFrame)
    assert df.index.name == "Date"
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        assert col in df.columns
    assert 0 < len(df) <= 240
    # 指标计算不报错
    enriched = f.calculate_technical_indicators(df)
    assert enriched is not None and not enriched.empty


if __name__ == "__main__":
    test_get_minute_data_30min()
    print("PASS: 数据层分钟取数")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/tdxback/aiagents-stock && python3 tests/test_minute_data.py`
Expected: FAIL — `AttributeError: 'StockDataFetcher' object has no attribute 'get_minute_data'`

- [ ] **Step 3: 写最小实现**

在 `stock_data.py` 的 `class StockDataFetcher` 内（紧跟 `_get_chinese_stock_data` 之后）新增：

```python
    def get_minute_data(self, symbol, freq, limit=240):
        """获取A股分钟K线，返回标准 OHLCV DataFrame（Date 索引）；失败返回 {"error": ...}。"""
        try:
            from akshare_gateway import akshare_gw
            df = akshare_gw.get_minute_kline(symbol, freq, limit=limit)
            if df is None or df.empty:
                return {"error": f"无法获取 {symbol} 的 {freq} 分钟数据"}
            df = df.rename(columns={
                '日期': 'Date', '开盘': 'Open', '收盘': 'Close',
                '最高': 'High', '最低': 'Low', '成交量': 'Volume'
            })
            df['Date'] = pd.to_datetime(df['Date'])
            df.set_index('Date', inplace=True)
            return df
        except Exception as e:
            return {"error": f"获取分钟数据失败: {str(e)}"}
```

> 注：`stock_data.py` 顶部已 `import pandas as pd`，无需新增 import。

- [ ] **Step 4: 运行确认通过**

Run: `cd /home/tdxback/aiagents-stock && python3 tests/test_minute_data.py`
Expected: `PASS: 数据层分钟取数`

- [ ] **Step 5: 提交**

```bash
git add stock_data.py tests/test_minute_data.py
git commit -m "feat(data): 新增 get_minute_data 分钟K线 → 标准OHLCV"
```

---

### Task 3: 引擎支持分钟分析 + 基本面门控

**Files:**
- Modify: `stock_analysis_engine.py`（`run_full_analysis` 在 line 18；技术面取数在 line 39-44；无条件 `get_financial_data` 在 line 47）
- Test: `tests/test_engine_intraday.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_engine_intraday.py
"""引擎分钟分析：freq 时走 get_minute_data，且 fundamental 关闭时不调 get_financial_data。"""
import os

os.environ["LOCAL_DB_DIR"] = "/home/tdxback/aiagents-stock/tdx-data/database/kline"
os.environ.setdefault("LOCAL_DB_ENABLED", "true")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock
from stock_analysis_engine import StockAnalysisEngine


def test_intraday_uses_minute_data_and_skips_fundamental():
    engine = StockAnalysisEngine()

    # 桩掉 LLM / 网络，保持测试 hermetic
    engine.fetcher.get_stock_info = MagicMock(return_value={"symbol": "600519", "name": "贵州茅台"})
    engine.fetcher.get_financial_data = MagicMock(return_value={})
    engine.agents.run_multi_agent_analysis = MagicMock(return_value={"technical": {}})
    engine.agents.comprehensive_discussion = MagicMock(return_value={})
    engine.agents.deepseek_client = MagicMock()
    engine.agents.deepseek_client.final_decision = MagicMock(return_value={"decision": "观望"})

    # spy 分钟取数（仍调真实实现）
    real_get_minute = engine.fetcher.get_minute_data
    engine.fetcher.get_minute_data = MagicMock(side_effect=real_get_minute)

    result = engine.run_full_analysis(
        "600519", period="30min", freq="30min",
        enabled_analysts={"technical": True, "fundamental": False, "fund_flow": False,
                          "risk": False, "sentiment": False, "news": False},
    )

    engine.fetcher.get_minute_data.assert_called_once()
    engine.fetcher.get_financial_data.assert_not_called()
    assert result["final_decision"] == {"decision": "观望"}


if __name__ == "__main__":
    test_intraday_uses_minute_data_and_skips_fundamental()
    print("PASS: 引擎分钟分析 + 基本面门控")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/tdxback/aiagents-stock && python3 tests/test_engine_intraday.py`
Expected: FAIL — `TypeError: run_full_analysis() got an unexpected keyword argument 'freq'`

- [ ] **Step 3: 写最小实现**

3a. 修改 `run_full_analysis` 签名（line 18-19）：

```python
    def run_full_analysis(self, symbol: str, period: str = "1y",
                          enabled_analysts: Optional[Dict[str, bool]] = None,
                          freq: Optional[str] = None) -> Dict[str, Any]:
```

3b. 把技术面取数块（现 line 39-44）改为：

```python
        # 2. 技术面：历史数据 + 最新指标（freq 非空走分钟线）
        if freq:
            stock_data = self.fetcher.get_minute_data(symbol, freq, limit=240)
        else:
            stock_data = self.fetcher.get_stock_data(symbol, period)
        indicators = {}
        if isinstance(stock_data, pd.DataFrame) and not stock_data.empty:
            enriched = self.fetcher.calculate_technical_indicators(stock_data)
            indicators = self.fetcher.get_latest_indicators(enriched)
```

3c. 把无条件的基本面取数（现 line 47 `financial_data = self.fetcher.get_financial_data(symbol)`）改为受门控：

```python
        # 3. 基本面（受 fundamental 门控；纯技术面/分时分析跳过，亦绕开东财资金流报错）
        financial_data = None
        if enabled_analysts.get('fundamental'):
            financial_data = self.fetcher.get_financial_data(symbol)
```

> 注：`stock_analysis_engine.py` 顶部已 `import pandas as pd`。`enabled_analysts` 在 line 27-31 已有默认全开逻辑，日线调用（不传 freq、不传 enabled_analysts）行为完全不变。

- [ ] **Step 4: 运行确认通过**

Run: `cd /home/tdxback/aiagents-stock && python3 tests/test_engine_intraday.py`
Expected: `PASS: 引擎分钟分析 + 基本面门控`

- [ ] **Step 5: 回归——确认日线测试/导入不破**

Run: `cd /home/tdxback/aiagents-stock && LOCAL_DB_DIR=/home/tdxback/aiagents-stock/tdx-data/database/kline python3 -c "from stock_analysis_engine import StockAnalysisEngine; StockAnalysisEngine(); print('engine import OK')"`
Expected: `engine import OK`

- [ ] **Step 6: 提交**

```bash
git add stock_analysis_engine.py tests/test_engine_intraday.py
git commit -m "feat(engine): run_full_analysis 支持 freq 分钟分析 + 基本面门控"
```

---

### Task 4: 前端——首页改名 + 分时导航按钮 + 路由

**Files:**
- Modify: `app.py`（首页按钮 line 301；其清除列表 line 303-304；默认主界面起点 `# 主界面` 在 line 598）

- [ ] **Step 1: 首页按钮改名 + 清除列表加 show_intraday**

把 line 301 的按钮 label 由 `"🏠 股票分析"` 改为 `"🏠 股票分析-日"`（key `nav_home` 不变）：

```python
        if st.button("🏠 股票分析-日", width='stretch', key="nav_home", help="返回首页，进行单只股票的日线深度分析"):
```

并在其清除列表（line 303-304）末尾加入 `'show_intraday'`：

```python
            for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                       'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull', 'show_news_flow', 'show_macro_cycle', 'show_macro_analysis', 'show_value_stock', 'show_intraday']:
```

- [ ] **Step 2: 在首页按钮块之后（line 308 的 `st.markdown("---")` 之前）新增分时导航按钮**

```python
        # ⏱️ 分时分析（纯短线技术面）
        if st.button("⏱️ 股票分析-分时", width='stretch', key="nav_intraday", help="仅按分钟线做纯短线技术面分析"):
            st.session_state.show_intraday = True
            for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                        'show_sector_strategy', 'show_longhubang', 'show_portfolio',
                        'show_low_price_bull', 'show_small_cap', 'show_profit_growth',
                        'show_value_stock', 'show_news_flow', 'show_macro_analysis',
                        'show_macro_cycle', 'show_smart_monitor']:
                if key in st.session_state:
                    del st.session_state[key]
```

- [ ] **Step 3: 新增路由（作为最后一个 `show_*` 判断，放在 line 598 `# 主界面` 之前）**

```python
    # 检查是否显示分时分析（放在所有 show_* 之后、默认日线主界面之前）
    if 'show_intraday' in st.session_state and st.session_state.show_intraday:
        display_intraday_analysis()
        return

```

> 放在最后保证：从分时视图点其它导航按钮时（即使个别按钮未清 show_intraday），对应视图仍优先显示；而点「股票分析-日」会清掉 show_intraday 回到默认日线视图。

- [ ] **Step 4: 语法检查**

Run: `cd /home/tdxback/aiagents-stock && python3 -m py_compile app.py && echo "app.py 语法 OK"`
Expected: `app.py 语法 OK`
（注：此时 `display_intraday_analysis` 尚未定义，py_compile 只查语法不查名字解析，OK；该函数在 Task 5 定义。）

- [ ] **Step 5: 提交**

```bash
git add app.py
git commit -m "feat(ui): 股票分析改名为-日 + 新增分时导航按钮与路由"
```

---

### Task 5: 前端——`display_intraday_analysis()` 视图

**Files:**
- Modify: `app.py`（在结果渲染组件附近新增函数，如 `display_final_decision` 在 line 1516、`display_batch_analysis_results` 在 line 1641；建议加在 line 1640 附近）

- [ ] **Step 1: 新增视图函数**

在 `app.py` 中（建议紧跟 `display_final_decision` 函数之后）新增：

```python
def display_intraday_analysis():
    """股票分析-分时：仅按分钟线做纯短线技术面分析。"""
    st.markdown("## ⏱️ 股票分析-分时")
    st.caption("仅基于分钟线的纯短线技术面分析（跳过基本面 / 资金面 / 新闻 / 情绪）")

    col1, col2 = st.columns([2, 1])
    with col1:
        symbol = st.text_input("股票代码", placeholder="6位A股代码，如 600519", key="intraday_symbol")
    with col2:
        freq_label = st.radio("分钟粒度", ["5分钟", "30分钟"], index=1,
                              horizontal=True, key="intraday_freq")
    freq = {"5分钟": "5min", "30分钟": "30min"}[freq_label]

    if st.button("🚀 开始分析", type="primary", key="intraday_run") and symbol:
        symbol = symbol.strip()
        with st.spinner(f"正在按 {freq_label}线 分析 {symbol} ..."):
            try:
                from stock_analysis_engine import StockAnalysisEngine
                engine = StockAnalysisEngine()
                result = engine.run_full_analysis(
                    symbol, period=freq, freq=freq,
                    enabled_analysts={'technical': True, 'fundamental': False,
                                      'fund_flow': False, 'risk': False,
                                      'sentiment': False, 'news': False},
                )
            except Exception as e:
                st.error(f"分析失败：{e}")
                return

        stock_data = result.get("stock_data")
        if not isinstance(stock_data, pd.DataFrame) or stock_data.empty:
            st.error("无法获取分钟数据（本地库与 TDX 均无该票数据）")
            return

        name = result.get("stock_info", {}).get("name", "")
        st.success(f"✅ {name} {symbol} · {freq_label}线 分析完成")
        display_agents_analysis(result.get("agents_results", {}))
        display_team_discussion(result.get("discussion_result", {}))
        display_final_decision(result.get("final_decision", {}), result.get("stock_info", {}),
                               result.get("agents_results"), result.get("discussion_result"))
```

> 注：`app.py` 已 `import streamlit as st`、`import pandas as pd`；`display_agents_analysis`/`display_team_discussion`/`display_final_decision` 均已存在且签名匹配上面调用（见 line 1470 / 1503 / 1516）。

- [ ] **Step 2: 语法检查**

Run: `cd /home/tdxback/aiagents-stock && python3 -m py_compile app.py && echo "app.py 语法 OK"`
Expected: `app.py 语法 OK`

- [ ] **Step 3: 全量测试回归**

Run: `cd /home/tdxback/aiagents-stock && python3 tests/test_gateway_minute_kline.py && python3 tests/test_minute_data.py && python3 tests/test_engine_intraday.py && python3 tests/test_portfolio_db_regression.py`
Expected: 四个测试均打印各自的 `PASS:`

- [ ] **Step 4: 提交**

```bash
git add app.py
git commit -m "feat(ui): 新增 display_intraday_analysis 分时分析视图"
```

---

### Task 6: 部署与人工验证（与 bug#2 一起重建）

> 本任务不写代码，是上线步骤。按既定顺序，功能#1 完成后连同 bug#2（已修复的 `portfolio_db.py`）一起重建。

- [ ] **Step 1: 重建主应用镜像**

Run: `cd /home/tdxback/aiagents-stock && docker compose up -d --build agentsstock`
Expected: `agentsstock1` 重建并健康（其余容器不动）。

- [ ] **Step 2: 网页端人工验证**

- [ ] 侧边栏「🏠 股票分析-日」存在，点击进入日线分析，行为与改名前一致。
- [ ] 其下「⏱️ 股票分析-分时」存在；点击进入分时视图。
- [ ] 分时视图：输入 `600519`，分别选 5分钟 / 30分钟 各跑一次，结果正常渲染（技术面 + 团队讨论 + 决策），无报错。
- [ ] 「📊 持仓分析」→ 分析历史不再报 `get_latest_analysis_history` AttributeError（bug#2 验证）。

---

## Self-Review

**Spec coverage：**
- 改名「股票分析-日」→ Task 4 Step 1 ✅
- 新增「股票分析-分时」按钮 + 路由 → Task 4 Step 2/3 ✅
- 分时视图（5min/30min 可选、纯技术面）→ Task 5 ✅
- 网关分钟取数（本地→TDX）→ Task 1 ✅
- 数据层分钟 → OHLCV → Task 2 ✅
- 引擎 freq 入参 + 基本面门控（顺带绕开 #3）→ Task 3 ✅
- bar limit 默认 240 → Task 3 Step 3b（`limit=240`）+ Task 5 调用 ✅
- 错误处理（无数据降级/提示）→ Task 2（error 返回）+ Task 5（st.error）✅
- 测试（引擎门控 / 数据层 / 网关）→ Task 1/2/3 测试 ✅
- 不改日线行为 → Task 3 默认参数保持、Task 4 仅加不改 ✅

**Placeholder 扫描：** 无 TBD/TODO；每个代码步骤均含完整代码与可运行命令。

**类型/签名一致性：** `get_minute_kline(symbol, freq, limit=240)`（Task1）↔ `get_minute_data` 调用（Task2）↔ `run_full_analysis(..., freq=...)`（Task3）↔ 视图调用（Task5）一致；渲染组件签名与现有定义一致。

**YAGNI：** 不接分钟级基本面/资金面/新闻；不加 1/15/60min；不做分时专属图表。
