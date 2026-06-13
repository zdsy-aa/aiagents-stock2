# 「📋 当前策略」页 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在功能导航新增只读页「📋 当前策略」，按四类(选股/买卖/测试盈利/找共同点)集中展示每条策略的脚本名+中文解释+关键参数，并对 star_thresholds.json 等机器可读配置实时显示真值。

**Architecture:** 两个新文件——`strategy_catalog.py`(纯数据 CATALOG，事实来源) + `current_strategy_ui.py`(渲染 + 容错实时读取)。`app.py` 仅加导航按钮、clear 列表、dispatch 三处。复用 `stable_ui.PLANS` 避免方案文本双份。不改任何现有策略逻辑。

**Tech Stack:** Python 3 / Streamlit / pytest / Streamlit AppTest 无头冒烟测试。

---

## 文件结构

- **Create** `strategy_catalog.py` —— `CATALOG: list[dict]`，19 条策略，每条 `类别/名称/脚本/解释/关键参数/实时` 字段。
- **Create** `current_strategy_ui.py` —— `display_current_strategy()` + 三个容错实时读取函数(`_read_star_thresholds` / `_read_watchlist_stat` / `_read_commonality_latest`)。
- **Create** `tests/test_strategy_catalog.py` —— CATALOG 字段/类别合法性校验。
- **Modify** `app.py` —— 导航按钮、`show_current_strategy` 加入各 clear 列表、dispatch 分支。
- **Modify** `tests/test_ui_pages_smoke.py` —— 加 `show_current_strategy` 冒烟用例 + 四类标题断言。

---

## Task 1: strategy_catalog.py 数据模块 + 校验测试

**Files:**
- Create: `strategy_catalog.py`
- Test: `tests/test_strategy_catalog.py`

- [ ] **Step 1: 写失败测试**

`tests/test_strategy_catalog.py`:
```python
# tests/test_strategy_catalog.py
from strategy_catalog import CATALOG, CATEGORIES


def test_categories_constant():
    assert CATEGORIES == ["选股", "买入卖出", "测试盈利", "找共同点"]


def test_every_entry_well_formed():
    assert len(CATALOG) >= 18
    for e in CATALOG:
        assert e["类别"] in CATEGORIES, e
        assert e["名称"] and isinstance(e["名称"], str)
        assert e["脚本"] and isinstance(e["脚本"], list)
        assert all(isinstance(s, str) for s in e["脚本"])
        assert e["解释"] and isinstance(e["解释"], str)
        assert isinstance(e["关键参数"], list)
        for p in e["关键参数"]:
            assert isinstance(p, tuple) and len(p) == 3, (e["名称"], p)
        assert e["实时"] in (None, "plans", "star", "watchlist", "commonality"), e


def test_all_four_categories_present():
    present = {e["类别"] for e in CATALOG}
    assert present == set(CATEGORIES)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_strategy_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'strategy_catalog'`

- [ ] **Step 3: 写实现**

`strategy_catalog.py`:
```python
# strategy_catalog.py —— 「当前策略」页的事实来源：四类全部策略的脚本名+中文解释+关键可调参数。
# 只读文档；改某条策略时顺手维护这里。关键参数=(参数名, 所在文件, 现值/说明)，指明"改哪"。
# 实时字段：None / "plans"(引stable_ui.PLANS) / "star"(读star_thresholds.json) /
#           "watchlist"(读每日清单) / "commonality"(读共性挖掘最近产物)。

CATEGORIES = ["选股", "买入卖出", "测试盈利", "找共同点"]

CATALOG = [
    # ───────────── 选股策略 · 量化研究栈 ─────────────
    {
        "类别": "选股", "名称": "🌀 缠论选股",
        "脚本": ["chanlun_selector.py", "chanlun_batch.py", "chanlun_engine.py", "chanlun_ui.py"],
        "解释": "多级别缠论买点筛选：日线本级别 + 30分钟次级别确认。读 chanlun_signals.db 最新批次"
                "（每日收盘后 chanlun_batch 预计算），识别 1买/2买/3买，给买入参考价、止损位与缠论卖点。",
        "关键参数": [
            ("买点类型判定", "chanlun_engine.py", "笔/线段/中枢→1买/2买/3买逻辑"),
            ("次级别确认级别", "chanlun_engine.py", "30分钟"),
            ("批量范围与调度", "chanlun_batch.py", "扫描股票池、近N交易日窗口、每日20:00"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🔱 六脉神剑",
        "脚本": ["liumai_selector.py", "liumai_engine.py", "liumai_batch.py"],
        "解释": "六维指标(MACD/KDJ/RSI/LWR/BBI/MTM)多头共振，选最新多头数≥5(5红以上)。读 liumai_signals.db 最新批次。",
        "关键参数": [
            ("多头数门槛 min_bull", "liumai_selector.py get_picks", "默认 5(5红以上)"),
            ("六维多空判定", "liumai_engine.py", "各维指标公式与红绿灯"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🔗 缠论×六脉",
        "脚本": ["combo_selector.py", "combo_batch.py", "combo_signal_db.py"],
        "解释": "组合策略——缠论买点 ±3 交易日内出现六脉神剑 5红以上。读 combo_signals.db，取两套各自优势的交集。",
        "关键参数": [
            ("时间窗 ±N交易日", "combo_batch.py", "默认 ±3"),
            ("六脉红灯门槛", "combo_batch.py", "≥5红"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🛡️ 稳定选股",
        "脚本": ["stable_ui.py", "daily_watchlist.py"],
        "解释": "经 walk-forward 样本外验证的稳健买卖规则(抄底/抢筹/过热顶/强势顶)，融入全量信号库共性结论。"
                "每日20:00缠论批量后自动生成当日清单；买卖方案详见『买入卖出』类。",
        "关键参数": [
            ("买卖方案文本", "stable_ui.py PLANS/NOTES", "三方案+纪律"),
            ("选股规则 A∪B", "daily_watchlist.py", "A 极限抄底+量比≥1.3 / B 尖刺金叉"),
        ],
        "实时": "watchlist",
    },
    # ───────────── 选股策略 · AI智能体栈 ─────────────
    {
        "类别": "选股", "名称": "💰 主力选股",
        "脚本": ["main_force_selector.py", "main_force_ui.py"],
        "解释": "用 pywencai(同花顺问财)取主力资金净流入前100名，再按市值/资金等做智能筛选。",
        "关键参数": [
            ("市值区间", "main_force_selector.py get_main_force_stocks", "min_market_cap / max_market_cap"),
            ("回溯天数", "main_force_selector.py get_main_force_stocks", "days_ago / start_date"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🐂 低价擒牛",
        "脚本": ["low_price_bull_strategy.py", "low_price_bull_selector.py"],
        "解释": "低价高成长股，基于 MA 均线择时的量化买卖策略。",
        "关键参数": [
            ("最大持股数 max_stocks", "low_price_bull_strategy.py", "默认 4"),
            ("个股最大仓位 max_position_per_stock", "low_price_bull_strategy.py", "0.4(4成)"),
            ("持股周期 holding_period", "low_price_bull_strategy.py", "5 天"),
            ("单日最大买入 max_daily_buy", "low_price_bull_strategy.py", "2"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "📊 小市值策略",
        "脚本": ["small_cap_selector.py", "small_cap_ui.py"],
        "解释": "pywencai 问财筛选：总市值≤50亿、营收增速≥10%、净利增速≥100%、沪深A股、非ST/非创业板/非科创板，按总市值由小到大。",
        "关键参数": [
            ("筛选 query", "small_cap_selector.py get_small_cap_stocks", "市值/增速门槛"),
            ("返回数 top_n", "small_cap_selector.py get_small_cap_stocks", "默认 5"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "📈 净利增长",
        "脚本": ["profit_growth_selector.py", "profit_growth_ui.py"],
        "解释": "pywencai 问财：净利润同比增速≥10%、深圳A股、非科创/非创业、非ST，按成交额由小到大。",
        "关键参数": [
            ("筛选 query", "profit_growth_selector.py get_profit_growth_stocks", "净利增速门槛/市场"),
            ("返回数 top_n", "profit_growth_selector.py get_profit_growth_stocks", "默认 5"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "💎 低估值策略",
        "脚本": ["value_stock_selector.py", "value_stock_strategy.py", "value_stock_ui.py"],
        "解释": "价值投资筛选——PE≤20、PB≤1.5、股息率≥1%、资产负债率≤30%、非ST/非科创/非创业，按流通市值由小到大；"
                "配套 RSI 超买 + 持股周期择时策略。",
        "关键参数": [
            ("选股 query", "value_stock_selector.py get_value_stocks", "PE/PB/股息/负债门槛"),
            ("择时参数", "value_stock_strategy.py", "holding_period=30 / rsi_overbought=70"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🐉 智瞰龙虎(龙虎榜)",
        "脚本": ["longhubang_data.py", "longhubang_scoring.py", "longhubang_engine.py", "longhubang_agents.py"],
        "解释": "龙虎榜深度分析与 AI 评分：抓龙虎榜数据→多维评分→AI智能体解读生成报告。偏分析型而非纯量化选股。",
        "关键参数": [
            ("评分维度/权重", "longhubang_scoring.py", "席位/资金/连板等"),
            ("数据抓取", "longhubang_data.py", "龙虎榜数据源"),
        ],
        "实时": None,
    },
    # ───────────── 买入卖出策略 ─────────────
    {
        "类别": "买入卖出", "名称": "🛒 稳定选股买卖方案",
        "脚本": ["stable_ui.py"],
        "解释": "抄底(核心A：缠论买点+极限抄底+量比≥1.3+机构净买) / 抢筹(核心B：1买+尖刺金叉) / 稳定组合(A∪B)；"
                "卖点=过热顶(均线全多头/连板)或强势顶(相对强弱≥5+六脉红灯+MA20上行)/+25~30%移动止盈。均经样本外验证。",
        "关键参数": [
            ("三方案与买卖说明", "stable_ui.py PLANS", "买点/卖点/胜率口径"),
            ("纪律/适用条件", "stable_ui.py NOTES", "适用市场/反向过滤/仓位预期"),
        ],
        "实时": "plans",
    },
    {
        "类别": "买入卖出", "名称": "📉 卖点共性挖掘",
        "脚本": ["mine_sell.py"],
        "解释": "缠论卖点共同特征挖掘(复用 mine_combos 评分器)，标签=好卖点(卖后跌≥4%)，找最能预示该卖的信号组合；结论反哺稳定选股『强势顶』卖点。",
        "关键参数": [
            ("好卖点阈值", "mine_sell.py", "卖后跌≥4%"),
            ("卖点分组", "mine_sell.py", "全部/1卖/2卖/3卖"),
        ],
        "实时": None,
    },
    {
        "类别": "买入卖出", "名称": "🟢 每日清单·可入与止盈损",
        "脚本": ["daily_watchlist.py"],
        "解释": "工程化每日选股：对最近缠论买点应用稳定组合 A∪B 规则输出当日清单；含可入状态(可入/尾窗/已过窗/已涨过/已破止损/已止盈)、实时价判定与星级排序。",
        "关键参数": [
            ("入选规则", "daily_watchlist.py", "A∪B + 大盘SID≤2 + 剔除获利盘>70%"),
            ("可入/止盈损判定", "daily_watchlist.py", "价格类优先于窗口类"),
        ],
        "实时": "watchlist",
    },
    # ───────────── 测试盈利策略 ─────────────
    {
        "类别": "测试盈利", "名称": "⭐ 星级分档(样本外胜率)",
        "脚本": ["star_calibrate.py", "star_thresholds.json"],
        "解释": "全历史1买信号回测『合成分→样本外胜率』，给核心(5★)/精选两层各定固定星级阈值(诚实降档)，星级=样本外验证胜率差。产出 star_thresholds.json，纯标准库。",
        "关键参数": [
            ("胜率/大涨阈值", "star_thresholds.json win_thresh/bigrise_thresh", "4% / 10%"),
            ("训练-测试切分", "star_thresholds.json train_end/oos", "2023末 / 2024~2025.10"),
            ("特征权重与 cuts", "star_calibrate.py + json tiers", "各档星级阈值"),
        ],
        "实时": "star",
    },
    {
        "类别": "测试盈利", "名称": "🔁 滚动样本外检验",
        "脚本": ["walk_forward.py"],
        "解释": "训练段挖规则、测试段纯验证，量化样本内偏差；规则=L1/L2/L3 条件组合，训练段内胜率最高(满足支持度)→测试未来段，防过拟合。",
        "关键参数": [
            ("训练/测试最小支持", "walk_forward.py", "SUP_TRAIN=200 / SUP_TEST=30"),
            ("三联 TopK", "walk_forward.py", "TOPK_TRIPLE=16"),
        ],
        "实时": None,
    },
    # ───────────── 找共同点策略 ─────────────
    {
        "类别": "找共同点", "名称": "🔍 共性挖掘(方案A/B)",
        "脚本": ["mine_commonality.py"],
        "解释": "涨跌前期共性挖掘——逐股累加每个信号在 ±窗口 内的命中→覆盖率/提升度/精确度→报告；找盈利买卖点的共同特征(按提升度排序)。",
        "关键参数": [
            ("窗口 W / offset", "build_features.py / mine_commonality.py", "±2 窗口"),
            ("排序口径", "mine_commonality.py", "覆盖率/提升度/精确度"),
        ],
        "实时": "commonality",
    },
    {
        "类别": "找共同点", "名称": "🧩 信号组合挖掘",
        "脚本": ["mine_combos.py", "mine_combos_v2.py"],
        "解释": "在 signal_features.csv 上生成 L1单/L2两两/L3三联/L5 测试方案，向量化算覆盖率/提升度/胜率并排序出榜。",
        "关键参数": [
            ("盈利覆盖门槛 COVER_MIN", "mine_combos.py", "0.70"),
            ("进榜最小支持 SUPPORT_MIN", "mine_combos.py", "50"),
            ("三联 TopK", "mine_combos.py", "TOPK_TRIPLE=18"),
        ],
        "实时": None,
    },
    {
        "类别": "找共同点", "名称": "🏗️ 特征/信号库构建",
        "脚本": ["build_features.py", "build_features_v2.py", "features.py"],
        "解释": "逐股加载日K+大盘，对每信号 ±2 窗口算布尔特征→signal_features.csv(防泄漏)，是挖掘的输入。",
        "关键参数": [
            ("盈利标签阈值 WIN_THRESH", "build_features.py", "4.0%"),
            ("窗口偏移 OFFSET", "build_features.py", "±2"),
            ("原子信号定义", "features.py", "信号库集合"),
        ],
        "实时": None,
    },
    {
        "类别": "找共同点", "名称": "📐 分维度参数挖掘",
        "脚本": ["group_dims.py", "test_group_dims.py", "mine_regime.py", "surface_l3.py", "calibrate_buckets.py"],
        "解释": "按波动率/市值/行业/板块把样本分桶，找各子组起涨前 uplift 最强的信号(达标榜>50%共性)。已知结论：低波动起涨 lift 最强。",
        "关键参数": [
            ("分桶维度与 cuts", "group_dims.py / calibrate_buckets.py", "波动率/市值/行业/板块"),
            ("达标共性阈值", "mine_regime.py / 分维度脚本", ">50%"),
        ],
        "实时": None,
    },
]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_strategy_catalog.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add strategy_catalog.py tests/test_strategy_catalog.py
git commit -m "feat(current-strategy): 策略目录数据模块 strategy_catalog.py + 校验测试"
```

---

## Task 2: current_strategy_ui.py 渲染 + 容错实时读取

**Files:**
- Create: `current_strategy_ui.py`
- Test: `tests/test_current_strategy_live.py`

实时读取函数从模块级常量取路径，便于测试 monkeypatch。每个都 try/except 容错。

- [ ] **Step 1: 写失败测试**

`tests/test_current_strategy_live.py`:
```python
# tests/test_current_strategy_live.py
import json
import current_strategy_ui as M


def test_star_read_ok(tmp_path, monkeypatch):
    p = tmp_path / "star.json"
    p.write_text(json.dumps({
        "win_thresh": 4.0, "bigrise_thresh": 10.0,
        "train_end": "2023-12-31", "oos": ["2024-01-01", "2025-10-31"],
        "tiers": {"核心": {"n_stars": 5}, "精选": {"n_stars": 2}},
    }), encoding="utf-8")
    monkeypatch.setattr(M, "STAR_THRESH", str(p))
    out = M._read_star_thresholds()
    assert out["ok"] is True
    assert "4" in out["text"] and "核心" in out["text"]


def test_star_read_missing_is_graceful(monkeypatch):
    monkeypatch.setattr(M, "STAR_THRESH", "/no/such/file.json")
    out = M._read_star_thresholds()
    assert out["ok"] is False
    assert out["text"]  # 有回退文案，不抛异常


def test_watchlist_stat_missing_is_graceful(monkeypatch):
    monkeypatch.setattr(M, "WATCHLIST", "/no/such/file.csv")
    out = M._read_watchlist_stat()
    assert out["ok"] is False and out["text"]


def test_commonality_latest_missing_is_graceful(monkeypatch):
    monkeypatch.setattr(M, "COMMONALITY_DIR", "/no/such/dir")
    out = M._read_commonality_latest()
    assert out["ok"] is False and out["text"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_current_strategy_live.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'current_strategy_ui'`

- [ ] **Step 3: 写实现**

`current_strategy_ui.py`:
```python
# current_strategy_ui.py —— 「📋 当前策略」只读页：按四类集中展示策略脚本名+中文解释+关键参数。
# C方案：对机器可读配置(star_thresholds.json/每日清单/共性产物)实时读真值，全部 try/except 容错。
import os
import glob
import json
import streamlit as st

from strategy_catalog import CATALOG, CATEGORIES

# 容器内路径(与 stable_ui 一致；宿主机/无文件时实时读取优雅回退为"—")
STAR_THRESH = "/app/data/profit_mining/star_thresholds.json"
WATCHLIST = "/app/data/profit_mining/每日自选股清单.csv"
COMMONALITY_DIR = "/app/data/commonality_reports"


def _read_star_thresholds():
    """读 star_thresholds.json，返回 {ok, text}。失败优雅回退。"""
    try:
        with open(STAR_THRESH, "r", encoding="utf-8") as f:
            d = json.load(f)
        tiers = "、".join(f"{k}({v.get('n_stars','?')}★)" for k, v in d.get("tiers", {}).items())
        oos = d.get("oos", ["?", "?"])
        text = (f"胜率口径 ≥{d.get('win_thresh','?')}% / 大涨 ≥{d.get('bigrise_thresh','?')}%；"
                f"训练截止 {d.get('train_end','?')}，样本外 {oos[0]}~{oos[-1]}；分层：{tiers or '—'}")
        return {"ok": True, "text": text}
    except Exception as e:
        return {"ok": False, "text": f"— (未读到 star_thresholds.json：{type(e).__name__})"}


def _read_watchlist_stat():
    """读每日自选股清单的候选数与更新时间，返回 {ok, text}。"""
    try:
        if not os.path.exists(WATCHLIST):
            raise FileNotFoundError(WATCHLIST)
        import pandas as pd
        df = pd.read_csv(WATCHLIST, encoding="utf-8-sig", dtype=str)
        import datetime
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(WATCHLIST)).strftime("%Y-%m-%d %H:%M")
        return {"ok": True, "text": f"最新清单 {len(df)} 只候选，更新于 {mt}"}
    except Exception as e:
        return {"ok": False, "text": f"— (暂无每日清单：{type(e).__name__})"}


def _read_commonality_latest():
    """列出共性挖掘最近一次产物(按文件名时间戳)，返回 {ok, text}。"""
    try:
        files = glob.glob(os.path.join(COMMONALITY_DIR, "*"))
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            raise FileNotFoundError(COMMONALITY_DIR)
        latest = max(files, key=os.path.getmtime)
        import datetime
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(latest)).strftime("%Y-%m-%d %H:%M")
        return {"ok": True, "text": f"最近产物 {os.path.basename(latest)}（{mt}）"}
    except Exception as e:
        return {"ok": False, "text": f"— (暂无共性挖掘产物：{type(e).__name__})"}


def _render_live(key):
    """按 entry['实时'] 渲染实时区块。"""
    if key == "star":
        st.caption("🔢 实时阈值：" + _read_star_thresholds()["text"])
    elif key == "watchlist":
        st.caption("🔢 实时清单：" + _read_watchlist_stat()["text"])
    elif key == "commonality":
        st.caption("🔢 结论新鲜度：" + _read_commonality_latest()["text"])
    elif key == "plans":
        try:
            import pandas as pd
            from stable_ui import PLANS
            st.dataframe(pd.DataFrame(PLANS)[["方案", "买点", "卖点"]],
                         width="stretch", hide_index=True)
        except Exception as e:
            st.caption(f"— (未读到稳定方案：{type(e).__name__})")


def _render_entry(e):
    with st.expander(e["名称"], expanded=False):
        st.markdown("**承载脚本**：" + " ".join(f"`{s}`" for s in e["脚本"]))
        st.markdown(e["解释"])
        if e["关键参数"]:
            st.markdown("**关键可调参数**：")
            for name, where, val in e["关键参数"]:
                st.markdown(f"- **{name}** — `{where}`：{val}")
        if e["实时"]:
            _render_live(e["实时"])


def display_current_strategy():
    st.markdown('<div class="ftc-section">📋 当前策略</div>', unsafe_allow_html=True)
    st.caption("只读总览：集中查看全部 选股/买入卖出/测试盈利/找共同点 策略的承载脚本与中文说明，"
               "方便识别后自行决定修改——改完告诉我(脚本名)，由我改代码并重跑验证。前台不在线编辑。")
    for cat in CATEGORIES:
        items = [e for e in CATALOG if e["类别"] == cat]
        st.markdown(f"#### 🗂️ {cat}策略（{len(items)}）")
        for e in items:
            _render_entry(e)
        st.divider()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_current_strategy_live.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add current_strategy_ui.py tests/test_current_strategy_live.py
git commit -m "feat(current-strategy): 渲染页 current_strategy_ui.py + 容错实时读取"
```

---

## Task 3: app.py 集成（导航按钮 / clear 列表 / dispatch）

**Files:**
- Modify: `app.py`（导航按钮区约 line 168-175；各 clear 列表；dispatch 约 line 438）

- [ ] **Step 1: 加导航按钮（在「🛡️ 稳定选股」按钮块之后）**

在 `app.py` 中找到稳定选股按钮块（约 line 168-175，结尾是 `'show_chanlun', 'show_liumai', 'show_combo']:` 后的 del 循环），紧随其后插入：
```python
            if st.button("📋 当前策略", width='stretch', key="nav_current_strategy", help="集中查看全部 选股/买卖/测试盈利/找共同点 策略的脚本与中文说明（只读，便于识别后决定修改）"):
                st.session_state.show_current_strategy = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_liumai', 'show_combo', 'show_stable']:
                    if key in st.session_state:
                        del st.session_state[key]
```

- [ ] **Step 2: 把 'show_current_strategy' 加进『🏠 股票分析-日』与『⏱️ 股票分析-分时』两个按钮的 clear 列表**

在 `app.py` line 78 的列表(以 `'show_stable']` 结尾)，把结尾改为同时含本标志：
```python
                       'show_chanlun', 'show_liumai', 'show_combo', 'show_stable', 'show_current_strategy']:
```
在 line 89 的列表(同样以 `'show_stable']` 结尾)，同样改为：
```python
                        'show_chanlun', 'show_liumai', 'show_combo', 'show_stable', 'show_current_strategy']:
```

说明：其余页(缠论/六脉/组合/稳定)的 clear 列表互不含对方的完整集，残留标志靠 dispatch 顺序兜底；本页 dispatch 放在最后(见 Step 4)，且首页/分时按钮已显式清除，足以避免抢占。无需逐一改全部列表。

- [ ] **Step 3: 加 dispatch 分支（在稳定选股 dispatch 之后、show_intraday 之前，约 line 438-440）**

找到：
```python
    if 'show_stable' in st.session_state and st.session_state.show_stable:
        from stable_ui import display_stable_selector
        display_stable_selector()
        return
```
在其后插入：
```python
    # 检查是否显示「当前策略」只读总览页
    if 'show_current_strategy' in st.session_state and st.session_state.show_current_strategy:
        from current_strategy_ui import display_current_strategy
        display_current_strategy()
        return
```

- [ ] **Step 4: 跑现有冒烟测试确保未破坏首页**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_ui_pages_smoke.py -k learning_video -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add app.py
git commit -m "feat(current-strategy): app.py 接入导航按钮/clear列表/dispatch"
```

---

## Task 4: AppTest 冒烟测试

**Files:**
- Modify: `tests/test_ui_pages_smoke.py`

- [ ] **Step 1: 把 show_current_strategy 加入 PAGE_FLAGS 并新增四类标题断言**

在 `tests/test_ui_pages_smoke.py` 的 `PAGE_FLAGS` 列表末尾加 `"show_current_strategy",`，并在文件末尾追加：
```python
def test_current_strategy_page_shows_four_categories():
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state["show_current_strategy"] = True
    at.run()
    assert not at.exception, at.exception
    text = "\n".join(str(el.value) for el in at.markdown)
    for cat in ["选股", "买入卖出", "测试盈利", "找共同点"]:
        assert cat in text, cat
    assert "当前策略" in text
```

- [ ] **Step 2: 跑测试确认通过**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_ui_pages_smoke.py -k "current_strategy" -v`
Expected: PASS（参数化的 `show_current_strategy` 用例 + `test_current_strategy_page_shows_four_categories` 均通过）

- [ ] **Step 3: 跑全套 UI 冒烟确保无回归**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_ui_pages_smoke.py -v`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add tests/test_ui_pages_smoke.py
git commit -m "test(current-strategy): AppTest 冒烟 + 四类标题断言"
```

---

## Task 5: 收尾验证

- [ ] **Step 1: 跑三套相关测试**

Run: `cd /home/tdxback/aiagents-stock && python3 -m pytest tests/test_strategy_catalog.py tests/test_current_strategy_live.py tests/test_ui_pages_smoke.py -v`
Expected: 全部 PASS

- [ ] **Step 2: 提醒部署**

向用户说明：根目录新增/改动代码(strategy_catalog.py / current_strategy_ui.py / app.py)需**重建镜像**才在容器对用户可见(项目惯例)；并由用户自行 `git push stock2 main`。

---

## 自查记录

- **Spec 覆盖**：§2集成→Task3；§3.1数据→Task1；§3.2渲染→Task2；§4四类全部收录→Task1 CATALOG(19条)；§5实时数值→Task2三函数+_render_live；§6测试→Task1/2/4。全覆盖。
- **占位符**：无 TBD/TODO；所有代码步骤含完整代码。
- **类型一致**：实时键集合 `{None,"plans","star","watchlist","commonality"}` 在 catalog 校验、`_render_live`、各读取函数间一致；`_read_*` 均返回 `{ok,text}`；常量名 `STAR_THRESH/WATCHLIST/COMMONALITY_DIR` 在实现与测试 monkeypatch 间一致。
