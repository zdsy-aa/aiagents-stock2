"""smart_monitor_engine 交易决策/门控业务逻辑单测（纯规则，不联网/不需 API key/不碰真实 QMT）。

补 test_ai_stack_smoke / test_smart_monitor_db 之外的核心**下单决策**断言——这是会触发真实/模拟
交易的逻辑，此前 0 覆盖：
- _execute_decision：动作×持仓状态的路由与拒绝边界。
- _execute_buy：仓位数量计算(100 股整数倍/默认 20%)、资金不足拒单、落库与止损止盈价。
- analyze_stock：交易时段门控、auto_trade 门控。

技术：用 __new__ 绕过 __init__（避免构造 DeepSeek/QMT/DB/配置），只注入被测方法用到的桩协作者。
"""
import logging

import pytest

from smart_monitor_engine import SmartMonitorEngine


# ───────────────────────── 桩协作者 ─────────────────────────
class _QMT:
    def __init__(self, cash=0.0, position=None, buy_ret=None, sell_ret=None):
        self._cash = cash
        self._position = position
        self._buy_ret = buy_ret if buy_ret is not None else {"success": True, "order_id": "B1"}
        self._sell_ret = sell_ret if sell_ret is not None else {"success": True, "order_id": "S1"}
        self.buy_calls = []
        self.sell_calls = []

    def get_account_info(self):
        return {"available_cash": self._cash}

    def get_position(self, code):
        return self._position

    def buy_stock(self, **kw):
        self.buy_calls.append(kw)
        return self._buy_ret

    def sell_stock(self, **kw):
        self.sell_calls.append(kw)
        return self._sell_ret


class _DB:
    def __init__(self):
        self.trades = []
        self.positions = []
        self.closed = []
        self.ai_decisions = []
        self.exec_updates = []

    def save_trade_record(self, rec):
        self.trades.append(rec)

    def save_position(self, rec):
        self.positions.append(rec)

    def close_position(self, code):
        self.closed.append(code)

    def save_ai_decision(self, rec):
        self.ai_decisions.append(rec)
        return len(self.ai_decisions)  # 返回 decision_id

    def update_decision_execution(self, decision_id, executed, result):
        self.exec_updates.append((decision_id, executed, result))


class _Deepseek:
    def __init__(self, session, decision=None):
        self._session = session
        self._decision = decision

    def get_trading_session(self):
        return self._session

    def analyze_stock_and_decide(self, **kw):
        return {"success": True, "decision": self._decision}


class _DataFetcher:
    def __init__(self, data):
        self._data = data

    def get_comprehensive_data(self, code):
        return self._data


def _engine(**attrs):
    """构造一个未初始化的引擎，仅注入被测方法用到的属性。"""
    eng = SmartMonitorEngine.__new__(SmartMonitorEngine)
    eng.logger = logging.getLogger("test_smart_monitor")
    for k, v in attrs.items():
        setattr(eng, k, v)
    return eng


# ───────────────────────── _execute_decision 路由 ─────────────────────────
class TestExecuteDecisionRouting:
    def test_hold_does_not_trade(self):
        eng = _engine()
        r = eng._execute_decision("600000", {"action": "HOLD"}, {}, has_position=True)
        assert r["success"] is True and r["action"] == "HOLD"

    def test_buy_when_no_position_routes_to_buy(self):
        eng = _engine()
        eng._execute_buy = lambda code, dec, md: {"success": True, "routed": "buy"}
        eng._execute_sell = lambda *a: pytest.fail("不应触发卖出")
        r = eng._execute_decision("600000", {"action": "BUY"}, {}, has_position=False)
        assert r["routed"] == "buy"

    def test_buy_when_already_held_is_rejected(self):
        eng = _engine()
        eng._execute_buy = lambda *a: pytest.fail("已持仓不应再买入")
        r = eng._execute_decision("600000", {"action": "BUY"}, {}, has_position=True)
        assert r["success"] is False and "无效操作" in r["error"]

    def test_sell_when_held_routes_to_sell(self):
        eng = _engine()
        eng._execute_sell = lambda code, dec, md: {"success": True, "routed": "sell"}
        eng._execute_buy = lambda *a: pytest.fail("不应触发买入")
        r = eng._execute_decision("600000", {"action": "SELL"}, {}, has_position=True)
        assert r["routed"] == "sell"

    def test_sell_when_no_position_is_rejected(self):
        eng = _engine()
        eng._execute_sell = lambda *a: pytest.fail("无持仓不应卖出")
        r = eng._execute_decision("600000", {"action": "SELL"}, {}, has_position=False)
        assert r["success"] is False and "无效操作" in r["error"]

    def test_unknown_action_is_rejected(self):
        eng = _engine()
        r = eng._execute_decision("600000", {"action": "FOO"}, {}, has_position=False)
        assert r["success"] is False and "无效操作: FOO" in r["error"]


# ───────────────────────── _execute_buy 仓位计算 ─────────────────────────
class TestExecuteBuySizing:
    def test_quantity_floored_to_100_lots(self):
        qmt = _QMT(cash=100_000)
        eng = _engine(qmt=qmt, db=_DB())
        # 20% = 20000 元；20000/10.5/100 = 19.04 → 19 手 → 1900 股
        r = eng._execute_buy("600000", {"position_size_pct": 20},
                             {"current_price": 10.5, "name": "X"})
        assert qmt.buy_calls[0]["quantity"] == 1900
        assert r["success"] is True

    def test_default_position_pct_is_20(self):
        qmt = _QMT(cash=100_000)
        eng = _engine(qmt=qmt, db=_DB())
        # 未给 position_size_pct → 默认 20% → 同上 1900 股
        eng._execute_buy("600000", {}, {"current_price": 10.5})
        assert qmt.buy_calls[0]["quantity"] == 1900

    def test_rejected_when_cash_insufficient_for_one_lot(self):
        qmt = _QMT(cash=500)  # 20% = 100 元；100/10/100 = 0.1 → 0 股 < 100
        eng = _engine(qmt=qmt, db=_DB())
        r = eng._execute_buy("600000", {"position_size_pct": 20}, {"current_price": 10})
        assert r["success"] is False and "资金不足" in r["error"]
        assert qmt.buy_calls == []  # 未真正下单

    def test_persists_trade_and_position_with_stop_levels(self):
        qmt = _QMT(cash=100_000)
        db = _DB()
        eng = _engine(qmt=qmt, db=db)
        eng._execute_buy("600000",
                         {"position_size_pct": 20, "stop_loss_pct": 5, "take_profit_pct": 10},
                         {"current_price": 10.0, "name": "X"})
        assert len(db.trades) == 1 and db.trades[0]["trade_type"] == "BUY"
        pos = db.positions[0]
        assert pos["stop_loss_price"] == pytest.approx(9.5)    # 10×(1-5%)
        assert pos["take_profit_price"] == pytest.approx(11.0)  # 10×(1+10%)

    def test_failed_order_does_not_persist(self):
        qmt = _QMT(cash=100_000, buy_ret={"success": False, "error": "rejected"})
        db = _DB()
        eng = _engine(qmt=qmt, db=db)
        r = eng._execute_buy("600000", {"position_size_pct": 20}, {"current_price": 10.0})
        assert r["success"] is False
        assert db.trades == [] and db.positions == []  # 下单失败不落库


# ───────────────────────── analyze_stock 门控 ─────────────────────────
class TestAnalyzeStockGating:
    def test_skips_outside_trading_hours(self):
        eng = _engine(deepseek=_Deepseek({"session": "已收盘", "can_trade": False}))
        r = eng.analyze_stock("600000", trading_hours_only=True, notify=False)
        assert r["success"] is False and r.get("skipped") is True

    def test_no_autotrade_does_not_execute(self):
        decision = {"action": "BUY", "confidence": 80, "reasoning": "理由"}
        eng = _engine(
            deepseek=_Deepseek({"session": "盘中", "can_trade": True}, decision),
            data_fetcher=_DataFetcher({"name": "X", "current_price": 10}),
            qmt=_QMT(cash=100_000, position=None),
            db=_DB(),
        )
        called = []
        eng._execute_decision = lambda **kw: called.append(kw) or {"success": True}
        eng._send_notification = lambda **kw: None
        r = eng.analyze_stock("600000", auto_trade=False, notify=False, has_position=False)
        assert r["success"] is True
        assert called == []                 # 未开自动交易 → 不执行
        assert r["execution_result"] is None

    def test_autotrade_executes_when_can_trade(self):
        decision = {"action": "BUY", "confidence": 80, "reasoning": "理由"}
        eng = _engine(
            deepseek=_Deepseek({"session": "盘中", "can_trade": True}, decision),
            data_fetcher=_DataFetcher({"name": "X", "current_price": 10}),
            qmt=_QMT(cash=100_000, position=None),
            db=_DB(),
        )
        called = []
        eng._execute_decision = lambda **kw: (called.append(kw), {"success": True})[1]
        eng._send_notification = lambda **kw: None
        r = eng.analyze_stock("600000", auto_trade=True, notify=False, has_position=False)
        assert len(called) == 1
        assert called[0]["stock_code"] == "600000"
