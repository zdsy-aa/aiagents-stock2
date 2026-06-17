"""智策数据层：财经新闻抓取超时兜底 + 无新闻时的 AI 提示兜底。

锁定两点行为：
1. _call_with_timeout：func 超时/异常 → 返回 None 且不等满（不被无超时请求拖死）。
2. format_data_for_ai：无新闻时输出"仅用量化数据、勿臆测消息面"的提示，避免 AI 脑补消息面。
"""
import time

from sector_strategy_data import SectorStrategyDataFetcher, _call_with_timeout


def test_call_with_timeout_returns_value_when_fast():
    assert _call_with_timeout(lambda: "ok", 2) == "ok"


def test_call_with_timeout_returns_none_and_does_not_block_when_slow():
    t0 = time.time()
    r = _call_with_timeout(lambda: time.sleep(5) or "late", 0.3)
    assert r is None
    assert time.time() - t0 < 2.0  # 未等满 5 秒，超时即返回


def test_call_with_timeout_returns_none_on_exception():
    def boom():
        raise RuntimeError("x")
    assert _call_with_timeout(boom, 2) is None


def test_format_includes_no_news_safeguard_when_news_empty():
    f = SectorStrategyDataFetcher()
    txt = f.format_data_for_ai({"success": True, "news": []})
    assert "未获取到财经新闻" in txt
    assert "不要臆测或编造" in txt  # 防 AI 脑补消息面


def test_format_has_news_section_when_present():
    f = SectorStrategyDataFetcher()
    txt = f.format_data_for_ai({
        "success": True,
        "news": [{"publish_time": "2026-06-16", "title": "标题A", "content": ""}],
    })
    assert "标题A" in txt
    assert "未获取到财经新闻" not in txt  # 有新闻就不出提示
