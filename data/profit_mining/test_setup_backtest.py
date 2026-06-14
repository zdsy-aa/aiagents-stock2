import numpy as np
import setup_backtest as BT

def _ohlc(seq_close, highs=None, lows=None):
    c = np.array(seq_close, float)
    o = c.copy()
    h = np.array(highs, float) if highs is not None else c.copy()
    l = np.array(lows, float) if lows is not None else c.copy()
    return o, h, l, c

def test_trade_take_profit():
    o,h,l,c = _ohlc([10,10.5,11.0,10.0], highs=[10,10.5,11.0,10.0], lows=[10,10.2,10.8,9.9])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, tp=0.10, sl=-0.05, maxhold=10, cost=0.002)
    exit_idx, gross, net, reason = r
    assert reason=="止盈" and abs(gross-0.10)<1e-9 and abs(net-0.098)<1e-9, r

def test_trade_stop_loss():
    o,h,l,c = _ohlc([10,9.8,9.4], highs=[10,9.9,9.6], lows=[10,9.8,9.4])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, tp=0.10, sl=-0.05, maxhold=10, cost=0.002)
    assert r[3]=="止损" and abs(r[1]+0.05)<1e-9 and abs(r[2]-(-0.052))<1e-9, r

def test_trade_maxhold():
    o,h,l,c = _ohlc([10,10.1,10.3], highs=[10,10.2,10.4], lows=[10,9.9,10.0])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, tp=0.10, sl=-0.05, maxhold=3, cost=0.002)
    assert r[3]=="到期" and abs(r[1]-0.03)<1e-9 and abs(r[2]-0.028)<1e-9, r

def test_trade_same_bar_tp_and_sl_takes_sl():
    o,h,l,c = _ohlc([10,10.0], highs=[10,11.0], lows=[10,9.4])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, tp=0.10, sl=-0.05, maxhold=10, cost=0.002)
    assert r[3]=="止损", r

def test_select_topn_dedupe():
    picks = BT.select_topn(["A","B","C"], [0.9,0.8,0.7], held={"B"}, topn=2)
    assert picks==["A","C"], picks

def test_max_drawdown_and_cum():
    curve = np.array([1.0, 1.2, 0.9, 1.1])
    assert abs(BT.cum_return(curve) - 0.10) < 1e-9
    assert abs(BT.max_drawdown(curve) - (0.9/1.2 - 1)) < 1e-9

def test_sharpe_zero_std():
    assert BT.sharpe(np.array([0.0,0.0,0.0])) == 0.0

def test_trailing_exit():
    o,h,l,c = _ohlc([10,11.5,10.5,10.0],
                    highs=[10,11.5,11.0,10.5], lows=[10,11.0,10.5,10.0])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, mode="trailing", sl=-0.05, maxhold=10, cost=0.002, trail=0.08)
    assert r[3]=="移动止盈", r
    assert abs(r[1] - (11.5*0.92/10 - 1)) < 1e-9, r

def test_trailing_hard_stop_priority():
    o,h,l,c = _ohlc([10,9.3], highs=[10,11.6], lows=[10,9.3])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, mode="trailing", sl=-0.05, maxhold=10, cost=0.002, trail=0.08)
    assert r[3]=="止损", r

def test_trend_exit_break_ma():
    o,h,l,c = _ohlc([10,10.5,10.2,10.4], highs=[10,10.6,10.3,10.5], lows=[10,10.4,10.1,10.3])
    ma = np.array([np.nan, np.nan, 10.3, 10.3])
    r = BT.simulate_trade(o,h,l,c, entry_idx=0, mode="trend", sl=-0.20, maxhold=10, cost=0.002, ma=ma)
    assert r[3]=="破MA" and r[0]==2, r
    assert abs(r[1]-(10.2/10-1))<1e-9, r

def test_ma_helper():
    c = np.array([1.0,2,3,4,5], float)
    m = BT._ma(c, 3)
    assert np.isnan(m[0]) and np.isnan(m[1]) and abs(m[2]-2.0)<1e-9 and abs(m[4]-4.0)<1e-9, m

if __name__ == "__main__":
    test_trade_take_profit(); test_trade_stop_loss(); test_trade_maxhold()
    test_trade_same_bar_tp_and_sl_takes_sl(); test_select_topn_dedupe()
    test_max_drawdown_and_cum(); test_sharpe_zero_std()
    test_trailing_exit(); test_trailing_hard_stop_priority(); test_trend_exit_break_ma(); test_ma_helper();
    print("ALL setup_backtest OK")
