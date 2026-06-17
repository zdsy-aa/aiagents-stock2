# 智策 大盘指数/涨跌家数/换手率 多源兜底 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给智策的大盘指数/涨跌家数/换手率取数加新浪/腾讯多源兜底，东财被封时不再空缺。

**Architecture:** 在 `sector_strategy_data.py` inline 加按序兜底（仿其已有「同花顺主+东财兜底」模式），每源用已存在的 `_call_with_timeout` 套硬超时。大盘指数链 腾讯→新浪→东财；涨跌家数链 新浪→东财；换手率 best-effort（东财板块短超时 enrichment + 缺失提示）。

**Tech Stack:** Python、akshare（新浪/东财源）、urllib（腾讯 qt.gtimg）、pandas；容器 agentsstock1。

**关键约束（已核对/实测 2026-06-17）：**
- `_call_with_timeout(func, timeout_sec)` 已存在于 `sector_strategy_data.py`（daemon 线程 join，超时/异常返回 None）。直接复用。
- 腾讯指数报文 `https://qt.gtimg.cn/q=sh000001,sz399001,sz399006`（gbk）：每行 `v_xxx="..."`，按 `~` 分割，**f[1]=名称, f[2]=代码, f[3]=最新价, f[31]=涨跌额, f[32]=涨跌幅**（实测 88 字段）。
- 新浪指数 `ak.stock_zh_index_spot_sina()`：列含 代码/名称/最新价/涨跌额/涨跌幅；名称含「上证指数/深证成指/创业板指」。
- 新浪全A `ak.stock_zh_a_spot()`：列含 代码/名称/涨跌幅（**无换手率**）；约 5527 行；东财 `stock_zh_a_spot_em` 同含「涨跌幅」列。
- 东财 `stock_zh_index_spot_em`/`stock_zh_a_spot_em`/`stock_board_industry_name_em` 属被封接口（flaky），仅作最后兜底/短超时尝试。
- develop on `main`；root 代码改动需 `docker compose build agentsstock` + `up -d agentsstock` recreate 生效。

---

## File Structure

| 文件 | 责任 |
|------|------|
| `sector_strategy_data.py`（改） | 加 `_try_sources`/`_breadth_from_spot`/`_parse_tencent_index`/`_get_index_quotes`；改 `_get_market_overview`、`_get_sector_performance` turnover enrichment、`format_data_for_ai` 换手率提示 |
| `tests/test_sector_data_multisource.py`（新） | 纯逻辑单测：广度统计/腾讯解析/源切换/换手率提示 |

---

## Task 1: 纯逻辑 helper（广度统计 + 腾讯指数解析）

**Files:**
- Modify: `sector_strategy_data.py`（加两个模块级纯函数，放在 `_call_with_timeout` 之后）
- Test: `tests/test_sector_data_multisource.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sector_data_multisource.py
"""智策多源兜底纯逻辑：涨跌家数统计 / 腾讯指数报文解析 / 源切换 / 换手率提示。"""
import pandas as pd

from sector_strategy_data import (
    _breadth_from_spot, _parse_tencent_index, _try_sources,
    SectorStrategyDataFetcher,
)


def test_breadth_from_spot_counts():
    df = pd.DataFrame({"涨跌幅": [9.6, 5.0, 0.0, -3.0, -9.6, 10.1, -10.2]})
    r = _breadth_from_spot(df)
    assert r["total_stocks"] == 7
    assert r["up_count"] == 3      # 9.6, 5.0, 10.1
    assert r["down_count"] == 3    # -3, -9.6, -10.2
    assert r["flat_count"] == 1    # 0.0
    assert r["limit_up"] == 2      # >=9.5: 9.6, 10.1
    assert r["limit_down"] == 2    # <=-9.5: -9.6, -10.2
    assert abs(r["up_ratio"] - round(3 / 7 * 100, 2)) < 1e-9


def test_breadth_from_spot_empty():
    assert _breadth_from_spot(pd.DataFrame({"涨跌幅": []}))["total_stocks"] == 0


def test_parse_tencent_index():
    raw = (
        'v_sh000001="1~上证指数~000001~4108.08~4091.89~4074.29~370668682~0~0~0.00~'
        + "~".join(["0"] * 21)  # 占位到 f[31]
        + '~16.19~0.40~' + "~".join(["0"] * 50) + '";\n'
    )
    # 构造保证 f[1]=上证指数 f[2]=000001 f[3]=4108.08 f[31]=16.19 f[32]=0.40
    fields = raw.split('="')[1].split('~')
    assert fields[1] == "上证指数" and fields[3] == "4108.08" and fields[31] == "16.19" and fields[32] == "0.40"
    out = _parse_tencent_index(raw)
    assert "000001" in out
    assert abs(out["000001"]["close"] - 4108.08) < 1e-6
    assert abs(out["000001"]["change_pct"] - 0.40) < 1e-6
    assert abs(out["000001"]["change"] - 16.19) < 1e-6


def test_parse_tencent_index_malformed_skipped():
    assert _parse_tencent_index("garbage no tilde") == {}


def test_try_sources_falls_through_and_returns_first_ok():
    calls = []
    def bad(): calls.append("bad"); raise RuntimeError("x")
    def empty(): calls.append("empty"); return None
    def good(): calls.append("good"); return "DATA"
    r = _try_sources([("bad", bad, 2), ("empty", empty, 2), ("good", good, 2)])
    assert r == "DATA"
    assert calls == ["bad", "empty", "good"]


def test_try_sources_all_fail_returns_none():
    assert _try_sources([("a", lambda: None, 2), ("b", lambda: (_ for _ in ()).throw(ValueError()), 2)]) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_sector_data_multisource.py -q`
Expected: FAIL（`ImportError: cannot import name '_breadth_from_spot'`）

- [ ] **Step 3: 实现三个模块级函数**（加到 `sector_strategy_data.py` 中 `_call_with_timeout` 定义之后）

```python
def _try_sources(sources):
    """按序尝试 (label, callable, timeout_sec)，第一个返回非空(非 None、非空 DataFrame/dict)即用。

    每源用 _call_with_timeout 套硬超时；异常/超时/空 → 试下一个；全失败返回 None。
    """
    import logging as _lg
    log = _lg.getLogger(__name__)
    for label, fn, timeout_sec in sources:
        r = _call_with_timeout(fn, timeout_sec)
        empty = (r is None) or (hasattr(r, "empty") and r.empty) or (isinstance(r, (dict, list)) and len(r) == 0)
        if not empty:
            log.info("    [多源] 命中: %s", label)
            return r
        log.info("    [多源] 跳过(空/超时): %s", label)
    return None


def _breadth_from_spot(df):
    """全A快照 df(含'涨跌幅'列) -> 涨跌家数/涨停跌停 统计 dict。"""
    out = {}
    if df is None or df.empty or "涨跌幅" not in df.columns:
        out["total_stocks"] = 0
        return out
    pct = pd.to_numeric(df["涨跌幅"], errors="coerce").dropna()
    total = len(pct)
    up = int((pct > 0).sum()); down = int((pct < 0).sum()); flat = total - up - down
    out.update({
        "total_stocks": total, "up_count": up, "down_count": down, "flat_count": flat,
        "up_ratio": round(up / total * 100, 2) if total else 0,
        "limit_up": int((pct >= 9.5).sum()), "limit_down": int((pct <= -9.5).sum()),
    })
    return out


def _parse_tencent_index(raw_text):
    """腾讯 qt.gtimg 指数报文 -> {code: {close, change_pct, change}}。
    每行 v_xxx="名称~代码~最新价~...~涨跌额~涨跌幅~..."；f[1]名 f[2]码 f[3]最新 f[31]涨跌额 f[32]涨跌幅。"""
    out = {}
    for line in str(raw_text).strip().split("\n"):
        if "~" not in line or '="' not in line:
            continue
        try:
            payload = line.split('="', 1)[1].rstrip('";')
            f = payload.split("~")
            if len(f) <= 32:
                continue
            out[f[2]] = {"close": float(f[3]), "change": float(f[31]), "change_pct": float(f[32])}
        except (ValueError, IndexError):
            continue
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_sector_data_multisource.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add sector_strategy_data.py tests/test_sector_data_multisource.py
git commit -m "feat(sector): 多源兜底纯逻辑(涨跌家数统计/腾讯指数解析/源切换)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 大盘指数多源链 `_get_index_quotes`

**Files:**
- Modify: `sector_strategy_data.py`（加 `_get_index_quotes` 方法 + 三个取数源闭包）
- Test: `tests/test_sector_data_multisource.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
def test_get_index_quotes_uses_tencent_first(monkeypatch):
    f = SectorStrategyDataFetcher()
    # 桩腾讯源：直接返回三指数
    monkeypatch.setattr(f, "_index_from_tencent", lambda: {
        "sh_index": {"code": "000001", "name": "上证指数", "close": 4108.08, "change_pct": 0.4, "change": 16.19},
        "sz_index": {"code": "399001", "name": "深证成指", "close": 15745.0, "change_pct": 0.5, "change": 70.0},
        "cyb_index": {"code": "399006", "name": "创业板指", "close": 4107.0, "change_pct": 0.6, "change": 20.0},
    })
    # 新浪/东财不应被调用
    monkeypatch.setattr(f, "_index_from_sina", lambda: (_ for _ in ()).throw(AssertionError("不应走新浪")))
    q = f._get_index_quotes()
    assert q["sh_index"]["close"] == 4108.08
    assert q["cyb_index"]["code"] == "399006"


def test_get_index_quotes_falls_to_sina_when_tencent_empty(monkeypatch):
    f = SectorStrategyDataFetcher()
    monkeypatch.setattr(f, "_index_from_tencent", lambda: {})        # 腾讯空
    monkeypatch.setattr(f, "_index_from_sina", lambda: {
        "sh_index": {"code": "000001", "name": "上证指数", "close": 4083.86, "change_pct": -0.2, "change": -8.0},
    })
    q = f._get_index_quotes()
    assert q["sh_index"]["close"] == 4083.86
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_sector_data_multisource.py -k index_quotes -q`
Expected: FAIL（`AttributeError: _get_index_quotes`）

- [ ] **Step 3: 实现 `_index_from_tencent` / `_index_from_sina` / `_index_from_em` / `_get_index_quotes`**（加为 `SectorStrategyDataFetcher` 方法）

```python
    _INDEX_MAP = [("sh_index", "000001", "上证指数"),
                  ("sz_index", "399001", "深证成指"),
                  ("cyb_index", "399006", "创业板指")]

    def _index_from_tencent(self):
        import urllib.request
        raw = urllib.request.urlopen(
            "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006", timeout=8).read().decode("gbk")
        parsed = _parse_tencent_index(raw)   # {code: {close,change,change_pct}}
        out = {}
        for key, code, name in self._INDEX_MAP:
            if code in parsed:
                out[key] = {"code": code, "name": name, **parsed[code]}
        return out

    def _index_from_sina(self):
        df = ak.stock_zh_index_spot_sina()
        if df is None or df.empty:
            return {}
        out = {}
        for key, code, name in self._INDEX_MAP:
            hit = df[df["名称"] == name]
            if not hit.empty:
                r = hit.iloc[0]
                out[key] = {"code": code, "name": name,
                            "close": float(r.get("最新价", 0)),
                            "change_pct": float(r.get("涨跌幅", 0)),
                            "change": float(r.get("涨跌额", 0))}
        return out

    def _index_from_em(self):
        out = {}
        for key, code, name in self._INDEX_MAP:
            try:
                df = ak.stock_zh_index_spot_em(symbol="上证系列指数") if key == "sh_index" else None
            except Exception:
                df = None
            # 东财接口形态多变，作最后兜底：能拿到就填，拿不到跳过
            if df is not None and not df.empty:
                hit = df[df.get("名称", "") == name] if "名称" in df.columns else df.iloc[0:0]
                if not hit.empty:
                    r = hit.iloc[0]
                    out[key] = {"code": code, "name": name,
                                "close": float(r.get("最新价", 0)),
                                "change_pct": float(r.get("涨跌幅", 0)),
                                "change": float(r.get("涨跌额", 0))}
        return out

    def _get_index_quotes(self):
        """大盘指数多源链：腾讯(0.3s)→新浪(1.2s)→东财(兜底)。返回 {sh_index,sz_index,cyb_index} 部分/全部。"""
        return _try_sources([
            ("腾讯指数", self._index_from_tencent, 8),
            ("新浪指数", self._index_from_sina, 15),
            ("东财指数", self._index_from_em, 6),
        ]) or {}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_sector_data_multisource.py -k index_quotes -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add sector_strategy_data.py tests/test_sector_data_multisource.py
git commit -m "feat(sector): 大盘指数多源链 _get_index_quotes(腾讯→新浪→东财)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `_get_market_overview` 接入指数链 + 涨跌家数新浪兜底

**Files:**
- Modify: `sector_strategy_data.py`（重写 `_get_market_overview` 两段）

- [ ] **Step 1: 替换 `_get_market_overview` 实现**（保持返回结构不变）

```python
    def _get_market_overview(self):
        """获取市场总体情况（涨跌家数多源:新浪→东财；大盘指数多源:腾讯→新浪→东财）。"""
        try:
            overview = {}
            # 涨跌家数/涨停：新浪全A → 东财全A
            spot = _try_sources([
                ("新浪全A", ak.stock_zh_a_spot, 40),
                ("东财全A", ak.stock_zh_a_spot_em, 8),
            ])
            if spot is not None and not spot.empty:
                overview.update(_breadth_from_spot(spot))

            # 大盘指数：腾讯 → 新浪 → 东财
            overview.update(self._get_index_quotes())
            return overview
        except Exception as e:
            logger.error(f"    获取市场概况失败: {e}")
            return {}
```

- [ ] **Step 2: 语法检查 + 全量纯逻辑测试仍过**

Run:
```bash
python3 -c "import ast; ast.parse(open('sector_strategy_data.py').read()); print('syntax OK')"
python3 -m pytest tests/test_sector_data_multisource.py tests/test_sector_data_vectorize.py -q
```
Expected: `syntax OK` + 全 PASS（vectorize 既有测试不受影响——它 monkeypatch `_safe_request`，本任务未改 `_get_sector_performance` 主链）

- [ ] **Step 3: Commit**

```bash
git add sector_strategy_data.py
git commit -m "feat(sector): _get_market_overview 接多源(涨跌家数新浪兜底+指数链)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: 板块换手率 best-effort enrichment + AI 提示

**Files:**
- Modify: `sector_strategy_data.py`（`_get_sector_performance` 末尾加 turnover enrichment；`format_data_for_ai` 加缺失提示）
- Test: `tests/test_sector_data_multisource.py`（追加提示测试）

- [ ] **Step 1: 追加失败测试**

```python
def test_format_includes_turnover_missing_note_when_all_zero():
    f = SectorStrategyDataFetcher()
    txt = f.format_data_for_ai({
        "success": True,
        "sectors": {"银行": {"change_pct": 1.0, "turnover": 0, "top_stock": "A",
                            "top_stock_change": 2.0, "up_count": 5, "down_count": 1}},
    })
    assert "板块换手率本次暂缺" in txt


def test_format_no_turnover_note_when_present():
    f = SectorStrategyDataFetcher()
    txt = f.format_data_for_ai({
        "success": True,
        "sectors": {"银行": {"change_pct": 1.0, "turnover": 3.5, "top_stock": "A",
                            "top_stock_change": 2.0, "up_count": 5, "down_count": 1}},
    })
    assert "板块换手率本次暂缺" not in txt
```

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_sector_data_multisource.py -k turnover -q`
Expected: FAIL

- [ ] **Step 3a: `_get_sector_performance` 末尾（`return sectors` 前）加 best-effort enrichment**

在 `_get_sector_performance` 构造好 `sectors` dict、`return` 之前插入：

```python
        # best-effort 板块换手率回填：主源(同花顺)无换手率→试东财板块接口(短超时);拿不到保持 0
        if sectors and all(v.get("turnover", 0) in (0, None) for v in sectors.values()):
            try:
                em = _call_with_timeout(lambda: ak.stock_board_industry_name_em(), 15)
                if em is not None and not em.empty and "板块名称" in em.columns and "换手率" in em.columns:
                    tmap = dict(zip(em["板块名称"], pd.to_numeric(em["换手率"], errors="coerce")))
                    for name, v in sectors.items():
                        if name in tmap and pd.notna(tmap[name]):
                            v["turnover"] = float(tmap[name])
                    logger.info("    [换手率] 东财板块回填成功")
            except Exception as e:
                logger.info(f"    [换手率] 回填跳过: {e}")
```

（注：`_get_sector_performance` 实际变量名以源码为准——若板块 dict 不叫 `sectors`、列名不叫 `板块名称`，按实际改；实现阶段先读该方法确认。）

- [ ] **Step 3b: `format_data_for_ai` 板块段后加换手率缺失提示**

在 `format_data_for_ai` 中处理完 `data.get("sectors")` 后追加：

```python
        # 板块换手率整体缺失(全 0)提示，防 AI 据 0 误判量能
        secs = data.get("sectors") or {}
        if secs and all((v.get("turnover", 0) in (0, None)) for v in secs.values()):
            text_parts.append("""
【数据说明】本次板块换手率暂缺（数据源未取到），请勿据换手率判断板块量能；其余量化数据正常。
""")
```

- [ ] **Step 4: 跑确认通过 + 全量纯逻辑**

Run: `python3 -m pytest tests/test_sector_data_multisource.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: Commit**

```bash
git add sector_strategy_data.py tests/test_sector_data_multisource.py
git commit -m "feat(sector): 板块换手率best-effort回填(东财短超时)+缺失时AI提示

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 全量回归 + 重建镜像 + 容器端到端验证

**Files:** 无（构建+验证）

- [ ] **Step 1: 全量回归**

Run: `python3 -m pytest tests/ -q`
Expected: 全绿（基线 272 passed 之上 +多源新测；0 failed/1 skipped）

- [ ] **Step 2: 重建镜像并 recreate**

Run:
```bash
docker compose build agentsstock
docker compose up -d agentsstock
```
Expected: 构建成功 + agentsstock1 healthy（等 `docker inspect -f '{{.State.Health.Status}}' agentsstock1` = healthy）

- [ ] **Step 3: 容器内端到端验证多源真能取到**

Run:
```bash
docker exec -w /app agentsstock1 python3 -c "
from sector_strategy_data import SectorStrategyDataFetcher
f=SectorStrategyDataFetcher()
ov=f._get_market_overview()
print('指数:', {k:ov.get(k,{}).get('close') for k in ['sh_index','sz_index','cyb_index']})
print('涨跌家数:', ov.get('up_count'), '/', ov.get('down_count'), '总', ov.get('total_stocks'))
"
```
Expected: 三个指数 close 均为非空数字（来自腾讯/新浪，东财被封也能出）；涨跌家数非空。无 traceback。

- [ ] **Step 4: Commit（如有 DATA/文档微调；代码已在前序 commit）**

无新增代码改动则跳过；否则：
```bash
git commit -am "chore(sector): 多源兜底端到端验证通过(重建镜像)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec 覆盖**
- 大盘指数 腾讯→新浪→东财 → Task 2 `_get_index_quotes` + Task 3 接入 ✅
- 涨跌家数 新浪→东财 + 从涨跌幅列算 → Task 1 `_breadth_from_spot` + Task 3 `_try_sources` ✅
- 换手率 best-effort + 缺失提示 → Task 4 ✅
- 复用 `_call_with_timeout` 套超时 → `_try_sources`/enrichment 均用 ✅
- 不动 gateway/资金流向主链 → 仅改 overview + turnover enrichment ✅
- 纯逻辑单测不联网 → Task 1/2/4 用合成数据+monkeypatch ✅
- 重建镜像+recreate 生效 → Task 5 ✅

**2. Placeholder 扫描**：Task 3a 标注「变量名/列名以源码为准」——实现阶段先读 `_get_sector_performance` 确认 sectors 变量名与东财列名（`板块名称`/`换手率`），非占位是必要的实读校验；其余步骤均含完整代码。

**3. 一致性**：`_try_sources`(Task1) 被 Task2/3 调用签名一致；`_breadth_from_spot`(Task1)→Task3 调用一致；`_get_index_quotes`(Task2)→Task3 调用一致；`_parse_tencent_index`(Task1)→`_index_from_tencent`(Task2) 一致；返回结构 {sh_index/sz_index/cyb_index} 与现有 `format_data_for_ai` 读取键一致。
