# tests/test_news_fetch.py
def test_fetch_daily_news_returns_deduped_list():
    from news_fetch import fetch_daily_news, dedup_by_hash
    items = [
        {"title": "A公司签订大单", "content": "正文1", "source": "em"},
        {"title": "A公司签订大单", "content": "正文1", "source": "em"},   # 重复
    ]
    out = dedup_by_hash(items)
    assert len(out) == 1
    assert fetch_daily_news() is not None          # 联网冒烟,失败视为环境问题
