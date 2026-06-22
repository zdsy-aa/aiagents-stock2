# 智策财经新闻 多源真实新闻链 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把智策财经新闻从「财联社→东财」扩成 5 源真实新闻链，任一源活着即拿到真新闻，全失败才空。

**Architecture:** `sector_strategy_data.py` 加通用归一化器 `_news_normalize`（候选列名映射，不依赖各源精确列名）+ `_news_chain`（逐源 `_call_with_timeout` 取首个非空）；重写 `_get_financial_news` 走 5 源链。复用现成 `_call_with_timeout`。

**Tech Stack:** akshare 真实新闻接口（cls/sina/ths/futu/em）+ pandas；零新依赖。

**关键约束（已核对）：**
- `_call_with_timeout(func, timeout_sec)` 已存在（daemon 线程硬超时，返回 None 表失败）。
- 现 `_get_financial_news`（约 454–499 行）：cls 主 + em 备，已有 `hasattr(ak, fn)` 防御 + try/except。
- 已知列：cls=标题/内容/发布日期/发布时间；em=标题/摘要/发布时间/链接；sina/ths/futu 列名未知 → 用候选列名映射（不猜死）。
- 归一化目标：`{title, content, publish_time, source}`，content 截断 200 字。
- 纯函数（_news_normalize/_news_chain）host 可测；akshare 调用经 _call_with_timeout。
- develop on main；改 root → `docker compose build agentsstock`+`up -d agentsstock` recreate（与 #1 分开一次构建）。

---

## File Structure

| 文件 | 改动 |
|------|------|
| `sector_strategy_data.py` | 加 `_news_normalize`/`_news_chain`；重写 `_get_financial_news` 5 源链 |
| `tests/test_sector_news_multisource.py` | 新：归一化器 + 多源链选取单测 |

---

## Task 1: 多源新闻链（归一化 + 链 + 重写 _get_financial_news）

**Files:**
- Modify: `sector_strategy_data.py`
- Test: `tests/test_sector_news_multisource.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sector_news_multisource.py
"""智策财经新闻多源链：列名归一化 + 逐源取首个非空。"""
import pandas as pd

from sector_strategy_data import _news_normalize, _news_chain


def test_normalize_cls_style():
    df = pd.DataFrame([{"标题": "A大涨", "内容": "正文" * 80, "发布日期": "2026-06-22", "发布时间": "09:30"}])
    out = _news_normalize(df, "财联社")
    assert out[0]["title"] == "A大涨"
    assert out[0]["source"] == "财联社"
    assert len(out[0]["content"]) <= 200
    assert out[0]["publish_time"]  # 取到 发布时间 或 发布日期


def test_normalize_em_style():
    df = pd.DataFrame([{"标题": "B消息", "摘要": "摘要内容", "发布时间": "2026-06-22 10:00", "链接": "u"}])
    out = _news_normalize(df, "东财")
    assert out[0]["title"] == "B消息"
    assert out[0]["content"] == "摘要内容"
    assert out[0]["publish_time"] == "2026-06-22 10:00"


def test_normalize_empty_and_missing_cols():
    assert _news_normalize(pd.DataFrame(), "x") == []
    assert _news_normalize(None, "x") == []
    # 缺列不崩：只有标题
    out = _news_normalize(pd.DataFrame([{"标题": "只有标题"}]), "y")
    assert out[0]["title"] == "只有标题" and out[0]["content"] == ""


def test_news_chain_picks_first_nonempty():
    calls = []
    def empty(): calls.append("e"); return pd.DataFrame()
    def good(): calls.append("g"); return pd.DataFrame([{"标题": "命中", "内容": "x"}])
    def never(): calls.append("n"); return pd.DataFrame([{"标题": "不该到"}])
    rows = _news_chain([("源1", empty), ("源2", good), ("源3", never)], timeout=5)
    assert rows[0]["title"] == "命中" and rows[0]["source"] == "源2"
    assert calls == ["e", "g"]   # 命中即停，源3 不调


def test_news_chain_all_fail_returns_empty():
    assert _news_chain([("a", lambda: None), ("b", lambda: pd.DataFrame())], timeout=5) == []
```

- [ ] **Step 2: 跑确认失败**

Run: `python3 -m pytest tests/test_sector_news_multisource.py -q`
Expected: FAIL（无 `_news_normalize`/`_news_chain`）

- [ ] **Step 3: 实现 `_news_normalize` + `_news_chain`**（加在 `sector_strategy_data.py` 模块级，`_call_with_timeout` 之后）

```python
_NEWS_TITLE_KEYS = ["标题", "title", "新闻标题"]
_NEWS_CONTENT_KEYS = ["内容", "摘要", "content", "正文", "summary"]
_NEWS_TIME_KEYS = ["发布时间", "时间", "datetime", "发布日期", "ctime", "date"]


def _news_normalize(df, source, n=150):
    """任一新闻源 df → 统一 [{title, content, publish_time, source}]。按候选列名映射,缺列容错。"""
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for row in df.head(n).to_dict("records"):
        def pick(keys):
            for k in keys:
                v = row.get(k)
                if v is not None and str(v).strip():
                    return str(v).strip()
            return ""
        title = pick(_NEWS_TITLE_KEYS)
        content = pick(_NEWS_CONTENT_KEYS)
        t = pick(_NEWS_TIME_KEYS)
        if title or content:
            out.append({"title": title, "content": content[:200], "publish_time": t, "source": source})
    return out


def _news_chain(sources, timeout=25):
    """sources=[(label, callable)]; 逐源 _call_with_timeout 取 df→归一化,首个非空即返回;全失败 []。"""
    for label, fn in sources:
        df = _call_with_timeout(fn, timeout)
        rows = _news_normalize(df, label)
        if rows:
            return rows
    return []
```

- [ ] **Step 4: 重写 `_get_financial_news`**（替换现有方法体）

```python
    def _get_financial_news(self):
        """多源真实新闻链：财联社→新浪→同花顺→富途→东财，逐源硬超时取首个非空。"""
        order = [("财联社", "stock_info_global_cls"), ("新浪", "stock_info_global_sina"),
                 ("同花顺", "stock_info_global_ths"), ("富途", "stock_info_global_futu"),
                 ("东财", "stock_info_global_em")]
        sources = [(label, getattr(ak, name)) for label, name in order if hasattr(ak, name)]
        rows = _news_chain(sources)
        if rows:
            logger.info("    ✓ 财经新闻 %d 条（源: %s）", len(rows), rows[0]["source"])
        else:
            logger.info("    财经新闻全源未取到，留空")
        return rows
```

- [ ] **Step 5: 跑确认通过 + 语法**

Run:
```bash
python3 -c "import ast; ast.parse(open('sector_strategy_data.py').read()); print('syntax OK')"
python3 -m pytest tests/test_sector_news_multisource.py -q
```
Expected: `syntax OK` + PASS（5 passed）

- [ ] **Step 6: Commit**

```bash
git add sector_strategy_data.py tests/test_sector_news_multisource.py
git commit -m "feat(sector): 财经新闻多源真实链(财联社→新浪→同花顺→富途→东财)+列名归一化

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 全量回归 + 重建镜像 + 容器端到端

**Files:** 无（构建+验证）

- [ ] **Step 1: 全量回归**

Run: `python3 -m pytest tests/ -q`
Expected: 全绿（基线 297 之上 +新闻多源 5；0 failed/1 skipped；news_flow 页偶发可单独重跑）

- [ ] **Step 2: 重建镜像 + recreate**（确认 #1 的构建已结束后再开始，避免叠跑）

Run:
```bash
docker compose build agentsstock
docker compose up -d agentsstock
```
Expected: 构建成功 + agentsstock1 healthy。

- [ ] **Step 3: 容器端到端（实测哪个源命中、取到几条真新闻）**

Run:
```bash
docker exec -w /app agentsstock1 python3 -c "
from sector_strategy_data import SectorStrategyDataFetcher
f = SectorStrategyDataFetcher()
news = f._get_financial_news()
print('取到新闻条数:', len(news))
if news:
    print('命中源:', news[0]['source'])
    print('样本:', news[0]['title'][:40], '|', news[0]['publish_time'])
"
```
Expected: 条数>0、命中源为 5 源之一、样本有标题+时间；无 traceback（某源慢则被 25s 跳过切下一源）。

- [ ] **Step 4: 无新代码改动则跳过 commit。**

---

## Self-Review

**1. Spec 覆盖**
- 5 源真实新闻链（cls→sina→ths→futu→em）→ Task 1 `_get_financial_news` order ✅
- 逐源硬超时首个非空 → `_news_chain` + `_call_with_timeout` ✅
- 列名归一化 `{title,content,publish_time,source}` → `_news_normalize` 候选键映射 ✅
- 全失败空 + 既有 AI 提示 → 返回 [] + format_data_for_ai 既有分支 ✅
- 零新依赖 → 全 akshare ✅
- 测试（归一化各样式/缺列/链选取/全失败）→ Task 1 ✅
- 端到端实测命中源 → Task 2 ✅

**2. Placeholder 扫描**：无 TBD/TODO；候选列名表为实际映射（非占位）。

**3. 一致性**：`_news_normalize(df, source)`/`_news_chain(sources, timeout)` 在 Task1 定义与 `_get_financial_news` 调用一致；输出键 {title,content,publish_time,source} 与 `format_data_for_ai` 既有新闻读取（title/publish_time/content）一致。
