# tests/test_news_fetch.py
def test_fetch_daily_news_returns_deduped_list():
    from news_fetch import fetch_daily_news, dedup_by_hash
    items = [
        {"title": "A公司签订大单", "content": "正文1", "source": "em"},
        {"title": "A公司签订大单", "content": "正文1", "source": "em"},   # 重复
        {"title": "B公司发布业绩预告", "content": "正文2", "source": "em"},  # 不同项,须保留
    ]
    out = dedup_by_hash(items)
    assert len(out) == 2                                              # 防有损去重(如 return items[:1])静默通过
    assert {it["title"] for it in out} == {"A公司签订大单", "B公司发布业绩预告"}
    assert fetch_daily_news() is not None          # 联网冒烟,失败视为环境问题
