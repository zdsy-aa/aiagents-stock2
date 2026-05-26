"""StockAnalysisEngine.run_full_analysis 接线测试（桩替换数据层/AI/DB，无网络无费用）。

回归保护：曾因取数方法名错误 + db.save_analysis kwargs 错误而整体崩溃。
"""
import pandas as pd
import database
from stock_analysis_engine import StockAnalysisEngine


def test_run_full_analysis_wiring(monkeypatch):
    e = StockAnalysisEngine()

    # 桩掉数据层（无网络）
    e.fetcher.get_stock_info = lambda s: {'symbol': s, 'name': '测试股'}
    e.fetcher.get_stock_data = lambda s, p='1y': pd.DataFrame({'close': [1.0, 2.0, 3.0]})
    e.fetcher.calculate_technical_indicators = lambda df: df
    e.fetcher.get_latest_indicators = lambda df: {'ma5': 2.0}
    e.fetcher.get_financial_data = lambda s: {}
    e.fetcher._is_chinese_stock = lambda s: True

    # 桩掉 AI + DB（无网络/无费用）
    captured = {}

    def fake_multi(*args, **kwargs):
        captured['n_pos'] = len(args)
        captured['kw'] = list(kwargs.keys())
        return {'technical': {'analysis': 'x'}}

    e.agents.run_multi_agent_analysis = fake_multi
    e.agents.comprehensive_discussion = lambda reports, si: 'discussion'
    e.agents.deepseek_client.final_decision = lambda disc, si, ind: {'rating': '买入'}
    def fake_save(**kw):
        captured['save_kw'] = sorted(kw)
        return 99
    monkeypatch.setattr(database.db, 'save_analysis', fake_save)

    res = e.run_full_analysis(
        '600519',
        enabled_analysts={'technical': True, 'fundamental': False, 'fund_flow': False,
                          'risk': False, 'sentiment': False, 'news': False},
    )

    assert res['analysis_id'] == 99
    assert res['final_decision'] == {'rating': '买入'}
    assert set(res) >= {'stock_info', 'indicators', 'agents_results', 'discussion_result', 'final_decision'}
    # agents 收到 9 个位置参数 + enabled_analysts 关键字
    assert captured['n_pos'] == 9 and captured['kw'] == ['enabled_analysts']
    # db.save_analysis 收到正确的 kwargs 集合
    assert captured['save_kw'] == ['agents_results', 'discussion_result', 'final_decision',
                                   'period', 'stock_info', 'stock_name', 'symbol']
