"""news_flow_db.NewsFlowDatabase 核心CRUD回路特征测试

覆盖核心读写回路：
  save_flow_snapshot -> get_latest_snapshot -> get_recent_snapshots
  save_sentiment_record -> get_recent_scores
  get_daily_statistics (运行+返回类型校验)
"""
import os
import tempfile

from news_flow_db import NewsFlowDatabase


def _make_db():
    return NewsFlowDatabase(db_path=os.path.join(tempfile.mkdtemp(), "t.db"))


def test_save_flow_snapshot_and_get_latest():
    db = _make_db()

    flow_data = {
        'total_score': 88,
        'level': '高',
        'social_score': 20,
        'news_score': 25,
        'finance_score': 22,
        'tech_score': 21,
        'analysis': '整体流量偏热',
    }

    platforms_data = [
        {
            'platform': 'weibo',
            'platform_name': '微博',
            'category': 'social',
            'weight': 10,
            'success': True,
            'data': [
                {
                    'title': '某股票大涨',
                    'content': '内容详情',
                    'url': 'http://example.com/1',
                    'source': '微博热搜',
                    'publish_time': '2026-06-14 09:00:00',
                    'rank': 1,
                }
            ],
        },
        {
            'platform': 'baidu',
            'platform_name': '百度',
            'category': 'news',
            'weight': 5,
            'success': False,
            'data': [],
        },
    ]

    stock_news = [
        {
            'platform': 'weibo',
            'platform_name': '微博',
            'category': 'social',
            'weight': 10,
            'title': '某股票利好消息',
            'content': '相关内容',
            'url': 'http://example.com/2',
            'source': '微博',
            'publish_time': '2026-06-14 09:05:00',
            'matched_keywords': ['利好', '某股票'],
            'keyword_count': 2,
            'score': 15,
        }
    ]

    hot_topics = [
        {
            'topic': '某股票大涨',
            'count': 3,
            'heat': 999,
            'cross_platform': 1,
            'sources': ['weibo', 'baidu'],
        }
    ]

    snapshot_id = db.save_flow_snapshot(flow_data, platforms_data, stock_news, hot_topics)
    assert snapshot_id, "save_flow_snapshot 应返回非空的 snapshot_id"
    assert isinstance(snapshot_id, int)

    latest = db.get_latest_snapshot()
    assert latest is not None
    assert latest['id'] == snapshot_id
    assert latest['total_score'] == flow_data['total_score']
    assert latest['flow_level'] == flow_data['level']
    assert latest['social_score'] == flow_data['social_score']
    assert latest['analysis'] == flow_data['analysis']
    # platforms_data 中只有 1 个 success=True
    assert latest['success_count'] == 1
    assert latest['total_platforms'] == len(platforms_data)


def test_get_recent_snapshots_contains_saved():
    db = _make_db()

    flow_data = {'total_score': 70, 'level': '中'}
    platforms_data = [
        {
            'platform': 'weibo',
            'platform_name': '微博',
            'category': 'social',
            'weight': 10,
            'success': True,
            'data': [],
        }
    ]

    snapshot_id = db.save_flow_snapshot(flow_data, platforms_data, [], [])
    assert snapshot_id

    recent = db.get_recent_snapshots(10)
    assert isinstance(recent, list)
    assert len(recent) >= 1
    assert any(s['id'] == snapshot_id for s in recent)
    saved = next(s for s in recent if s['id'] == snapshot_id)
    assert saved['total_score'] == 70
    assert saved['flow_level'] == '中'


def test_sentiment_record_round_trip():
    db = _make_db()

    flow_data = {'total_score': 60, 'level': '中'}
    platforms_data = [
        {
            'platform': 'weibo',
            'platform_name': '微博',
            'category': 'social',
            'weight': 10,
            'success': True,
            'data': [],
        }
    ]
    snapshot_id = db.save_flow_snapshot(flow_data, platforms_data, [], [])
    assert snapshot_id

    sentiment_data = {
        'sentiment_index': 75,
        'sentiment_class': '乐观',
        'flow_stage': '上升期',
        'momentum': 1.5,
        'viral_k': 1.8,
        'flow_type': '突发',
        'stage_analysis': '情绪持续走高',
    }

    record_id = db.save_sentiment_record(snapshot_id, sentiment_data)
    assert record_id, "save_sentiment_record 应返回非空的 record_id"

    scores = db.get_recent_scores(24)
    assert isinstance(scores, list)
    assert len(scores) >= 1
    assert any(s['id'] == snapshot_id for s in scores)
    matched = next(s for s in scores if s['id'] == snapshot_id)
    assert matched['total_score'] == 60
    assert matched['flow_level'] == '中'


def test_get_daily_statistics_runs_and_returns_list():
    db = _make_db()

    flow_data = {'total_score': 50, 'level': '低'}
    platforms_data = [
        {
            'platform': 'weibo',
            'platform_name': '微博',
            'category': 'social',
            'weight': 10,
            'success': True,
            'data': [],
        }
    ]
    hot_topics = [
        {'topic': '话题A', 'count': 1, 'heat': 100, 'cross_platform': 0, 'sources': ['weibo']}
    ]
    db.save_flow_snapshot(flow_data, platforms_data, [], hot_topics)

    stats = db.get_daily_statistics(7)
    assert isinstance(stats, list)
    assert len(stats) >= 1
    today_stat = stats[0]
    assert 'avg_score' in today_stat
    assert 'top_topics' in today_stat
    assert isinstance(today_stat['top_topics'], list)
    assert today_stat['snapshot_count'] >= 1


if __name__ == "__main__":
    test_save_flow_snapshot_and_get_latest()
    test_get_recent_snapshots_contains_saved()
    test_sentiment_record_round_trip()
    test_get_daily_statistics_runs_and_returns_list()
    print("ALL news_flow_db OK")
