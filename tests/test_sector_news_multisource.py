"""智策财经新闻多源链：列名归一化 + 逐源取首个非空。"""
import pandas as pd

from sector_strategy_data import _news_normalize, _news_chain


def test_normalize_cls_style():
    df = pd.DataFrame([{"标题": "A大涨", "内容": "正文" * 80, "发布日期": "2026-06-22", "发布时间": "09:30"}])
    out = _news_normalize(df, "财联社")
    assert out[0]["title"] == "A大涨"
    assert out[0]["source"] == "财联社"
    assert len(out[0]["content"]) <= 200
    assert out[0]["publish_time"]


def test_normalize_em_style():
    df = pd.DataFrame([{"标题": "B消息", "摘要": "摘要内容", "发布时间": "2026-06-22 10:00", "链接": "u"}])
    out = _news_normalize(df, "东财")
    assert out[0]["title"] == "B消息"
    assert out[0]["content"] == "摘要内容"
    assert out[0]["publish_time"] == "2026-06-22 10:00"


def test_normalize_empty_and_missing_cols():
    assert _news_normalize(pd.DataFrame(), "x") == []
    assert _news_normalize(None, "x") == []
    out = _news_normalize(pd.DataFrame([{"标题": "只有标题"}]), "y")
    assert out[0]["title"] == "只有标题" and out[0]["content"] == ""


def test_news_chain_picks_first_nonempty():
    calls = []
    def empty(): calls.append("e"); return pd.DataFrame()
    def good(): calls.append("g"); return pd.DataFrame([{"标题": "命中", "内容": "x"}])
    def never(): calls.append("n"); return pd.DataFrame([{"标题": "不该到"}])
    rows = _news_chain([("源1", empty), ("源2", good), ("源3", never)], timeout=5)
    assert rows[0]["title"] == "命中" and rows[0]["source"] == "源2"
    assert calls == ["e", "g"]


def test_news_chain_all_fail_returns_empty():
    assert _news_chain([("a", lambda: None), ("b", lambda: pd.DataFrame())], timeout=5) == []
