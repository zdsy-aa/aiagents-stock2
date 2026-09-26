# news_fetch.py
r"""每日新闻抓取与去重(信息获取·新闻)。

接口替换说明:计划原定 ak.stock_news_em(symbol="全部")(全部A股要闻),
但容器 agentsstock1 内 akshare 1.18.63 调用该接口对任意 symbol 均抛
ArrowInvalid: Invalid regular expression: invalid escape sequence: \u
(akshare 内部正则与 pyarrow 不兼容),无法在本环境验证。
改用同为东方财富来源的全市场快讯 ak.stock_info_global_em()
(字段:标题/摘要/发布时间/链接,单次 200 条),容器内冒烟通过。
"""
import hashlib


def dedup_by_hash(items):
    seen, out = set(), []
    for it in items:
        h = hashlib.md5((it["title"] + (it.get("content") or "")).encode()).hexdigest()
        if h in seen: continue
        seen.add(h); out.append(it)
    return out


def fetch_daily_news():
    import akshare as ak
    rows = ak.stock_info_global_em()          # 全部A股要闻;stock_news_em 在本环境必报 ArrowInvalid,已替换
    return [{"title": r.get("标题", ""), "content": r.get("摘要", ""),
             "source": "em"} for r in rows.to_dict("records")[:200]]
