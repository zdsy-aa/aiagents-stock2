# tests/test_qizhang_picks_db.py
"""QizhangPicksDatabase round-trip：daily_picks / realized / run_meta。"""
import tempfile, os
import pytest
from qizhang_picks_db import QizhangPicksDatabase


def _db():
    d = tempfile.mkdtemp()
    return QizhangPicksDatabase(db_path=os.path.join(d, "qz.db"))


def test_save_and_get_daily_picks():
    db = _db()
    picks = [
        {"code": "600000", "name": "浦发", "score": 0.9, "rank": 1, "entry_ref_price": 10.0},
        {"code": "000001", "name": "平安", "score": 0.8, "rank": 2, "entry_ref_price": 12.0},
    ]
    db.save_daily_picks("2026-06-14", picks, riskoff=False)
    df = db.get_picks_by_date("2026-06-14")
    assert len(df) == 2
    assert set(df["code"]) == {"600000", "000001"}
    assert int(df[df["code"] == "600000"]["rank"].iloc[0]) == 1
    assert int(df[df["code"] == "600000"]["riskoff"].iloc[0]) == 0


def test_riskoff_day_saves_no_picks_but_flag():
    db = _db()
    db.save_daily_picks("2026-06-14", [], riskoff=True)
    assert db.get_picks_by_date("2026-06-14").empty
    # run_meta 单独记 gate(见 save_run_meta)；daily_picks 空属正常


def test_latest_pick_date():
    db = _db()
    db.save_daily_picks("2026-06-12", [{"code": "600000", "name": "x", "score": 1.0, "rank": 1, "entry_ref_price": 1.0}], riskoff=False)
    db.save_daily_picks("2026-06-14", [{"code": "000001", "name": "y", "score": 1.0, "rank": 1, "entry_ref_price": 1.0}], riskoff=False)
    assert db.get_latest_pick_date() == "2026-06-14"


def test_get_latest_pick_date_empty_is_none():
    assert _db().get_latest_pick_date() is None


def test_unrealized_picks_excludes_riskoff_and_realized():
    db = _db()
    db.save_daily_picks("2026-06-12", [
        {"code": "600000", "name": "x", "score": 1.0, "rank": 1, "entry_ref_price": 1.0},
        {"code": "000001", "name": "y", "score": 0.9, "rank": 2, "entry_ref_price": 1.0},
    ], riskoff=False)
    db.save_realized([{"scan_date": "2026-06-12", "code": "600000", "exit_date": "2026-06-20",
                       "holding_days": 6, "realized_return": 0.05, "hit_10pct": False,
                       "exit_reason": "到期", "bench_return": 0.01}])
    pending = db.get_unrealized_picks()
    assert ("2026-06-12", "000001") in pending
    assert ("2026-06-12", "600000") not in pending  # 已回填


def test_save_and_get_realized_stats():
    db = _db()
    db.save_realized([
        {"scan_date": "2026-06-12", "code": "600000", "exit_date": "2026-06-20",
         "holding_days": 6, "realized_return": 0.05, "hit_10pct": True,
         "exit_reason": "移动止盈", "bench_return": 0.01},
        {"scan_date": "2026-06-12", "code": "000001", "exit_date": "2026-06-19",
         "holding_days": 5, "realized_return": -0.05, "hit_10pct": False,
         "exit_reason": "止损", "bench_return": 0.02},
    ])
    df = db.get_realized_df()
    assert len(df) == 2
    assert abs(df["realized_return"].mean() - 0.0) < 1e-9


def test_save_and_get_run_meta():
    db = _db()
    db.save_run_meta("2026-06-14", model_train_rows=12345, train_end_date="2026-05-30",
                     sh_ma20_gate=False, status="ok")
    m = db.get_latest_run_meta()
    assert m["scan_date"] == "2026-06-14"
    assert m["status"] == "ok"
    assert int(m["sh_ma20_gate"]) == 0
