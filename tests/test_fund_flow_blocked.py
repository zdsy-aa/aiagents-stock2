"""东财个股资金流接口在本机被 IP 封锁，直连会抛 RemoteDisconnected 并刷 traceback。
命中封锁名单时应跳过 akshare 直连、改走备用源，整体优雅降级（不抛异常、不刷屏）。"""
import fund_flow_akshare as ffa
from akshare_gateway import BLOCKED_EM_FUNCS


def test_blocked_fund_flow_skips_eastmoney_no_traceback(monkeypatch):
    # 前提：该接口确实在封锁名单里
    assert 'stock_individual_fund_flow' in BLOCKED_EM_FUNCS

    called = {'ak': False}

    def boom(*a, **k):
        called['ak'] = True
        raise RuntimeError("eastmoney blocked - 不应被直连调用")

    monkeypatch.setattr(ffa.ak, 'stock_individual_fund_flow', boom)

    fetcher = ffa.FundFlowAkshareDataFetcher()
    data = fetcher.get_fund_flow_data('000001')

    # 被封时绝不调用东财直连（否则又会抛 RemoteDisconnected + traceback）
    assert called['ak'] is False
    # 本机无可用个股资金流源（东财封锁 + Tushare 无权限），应优雅返回失败而非崩溃
    assert data['data_success'] is False
    assert 'symbol' in data
