"""批量 executemany 写入：龙虎榜（坏数据跳过）、板块原始数据、新闻流量快照。"""
import sqlite3

from longhubang_db import LonghubangDatabase
from sector_strategy_db import SectorStrategyDatabase
from news_flow_db import NewsFlowDatabase


def test_longhubang_executemany_skips_bad_row(tmp_path):
    db = LonghubangDatabase(str(tmp_path / "lh.db"))
    n = db.save_longhubang_data([
        {'日期': '2026-05-24', '股票代码': '600519', '股票名称': '茅台',
         '买入金额': '100', '卖出金额': '10', '净流入金额': '90'},
        {'股票代码': 'BAD', '买入金额': 'not_a_number'},  # float() 失败 -> 跳过
    ])
    assert n == 1
    assert len(db.get_longhubang_data()) == 1


def test_sector_raw_data_executemany(tmp_path):
    db = SectorStrategyDatabase(str(tmp_path / "sec.db"))
    n = db.save_raw_data('industry', [
        {'名称': '半导体', '最新价': '12.3', '涨跌幅': '2.1'},
        {'sector': '白酒', 'price': 9.9},
    ])
    assert n == 2
    assert len(db.get_latest_raw_data('industry')) == 2


def test_news_flow_snapshot_executemany(tmp_path):
    db = NewsFlowDatabase(str(tmp_path / "nf.db"))
    flow = {'total_score': 50, 'level': '中', 'social_score': 1, 'news_score': 2,
            'finance_score': 3, 'tech_score': 4, 'analysis': ''}
    platforms = [
        {'success': True, 'platform': 'wb', 'platform_name': '微博', 'category': 's',
         'weight': 1.0, 'data': [{'title': 'a', 'rank': 1}, {'title': 'b', 'rank': 2}]},
        {'success': False, 'platform': 'x', 'platform_name': 'x', 'category': 'c',
         'weight': 1.0, 'data': [{'title': 'skip-me'}]},  # 失败平台应被排除
    ]
    stock_news = [{'platform': 'em', 'platform_name': '东财', 'category': 'f',
                   'weight': 1.0, 'title': 'n1'}]
    hot = [{'topic': 'AI', 'count': 1, 'heat': 9}]
    sid = db.save_flow_snapshot(flow, platforms, stock_news, hot)

    c = sqlite3.connect(str(tmp_path / "nf.db"))
    try:
        assert c.execute("SELECT COUNT(*) FROM platform_news WHERE snapshot_id=?", (sid,)).fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM stock_related_news WHERE snapshot_id=?", (sid,)).fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM hot_topics WHERE snapshot_id=?", (sid,)).fetchone()[0] == 1
    finally:
        c.close()
