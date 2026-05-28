"""特征测试：锁定 sector 板块/概念表现的 DataFrame→dict 构建行为，
保护将 iterrows 替换为 to_dict('records') 的等价改造。
"""
import pandas as pd

from sector_strategy_data import SectorStrategyDataFetcher


def _fetcher(monkeypatch, df):
    f = SectorStrategyDataFetcher()
    monkeypatch.setattr(f, "_safe_request", lambda *a, **k: df)
    return f


def test_get_sector_performance_builds_dict_and_skips_empty_name(monkeypatch):
    df = pd.DataFrame([
        {'板块名称': '银行', '涨跌幅': 1.2, '换手率': 0.5, '总市值': 1e12,
         '领涨股票': 'A', '领涨股票涨跌幅': 3.0, '上涨家数': 10, '下跌家数': 2},
        {'板块名称': '', '涨跌幅': 9.9, '换手率': 1, '总市值': 1,
         '领涨股票': 'B', '领涨股票涨跌幅': 1, '上涨家数': 1, '下跌家数': 1},
        {'板块名称': '券商', '涨跌幅': -0.5, '换手率': 0.8, '总市值': 5e11,
         '领涨股票': 'C', '领涨股票涨跌幅': -1.0, '上涨家数': 3, '下跌家数': 7},
    ])
    out = _fetcher(monkeypatch, df)._get_sector_performance()

    assert set(out.keys()) == {'银行', '券商'}  # 空名应被跳过
    assert out['银行'] == {
        'name': '银行', 'change_pct': 1.2, 'turnover': 0.5,
        'total_market_cap': 1e12, 'top_stock': 'A', 'top_stock_change': 3.0,
        'up_count': 10, 'down_count': 2,
    }
    assert out['券商']['change_pct'] == -0.5


def test_get_concept_performance_builds_dict(monkeypatch):
    df = pd.DataFrame([
        {'板块名称': 'AI', '涨跌幅': 2.0, '换手率': 3.0, '总市值': 2e12,
         '领涨股票': 'X', '领涨股票涨跌幅': 5.0, '上涨家数': 20, '下跌家数': 1},
    ])
    out = _fetcher(monkeypatch, df)._get_concept_performance()

    assert list(out.keys()) == ['AI']
    assert out['AI']['up_count'] == 20
    assert out['AI']['total_market_cap'] == 2e12


def test_get_sector_performance_empty_df_returns_empty(monkeypatch):
    out = _fetcher(monkeypatch, pd.DataFrame())._get_sector_performance()
    assert out == {}
