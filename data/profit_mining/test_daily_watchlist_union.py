import sqlite3, tempfile, os
import daily_watchlist as dw

_DDL = ("CREATE TABLE signals(code TEXT,name TEXT,board TEXT,signal_type TEXT,"
        "signal_date TEXT,buy_price REAL,scan_date TEXT)")


def _mkdb(path, rows, scan_date):
    c = sqlite3.connect(path); c.execute(_DDL)
    for r in rows:
        c.execute("INSERT INTO signals VALUES(?,?,?,?,?,?,?)",
                  (r[0], r[1], r[2], r[3], r[4], r[5], scan_date))
    c.commit(); c.close()


def test_union_dedup_intraday_priority():
    d = tempfile.mkdtemp()
    post = os.path.join(d, "post.db"); intra = os.path.join(d, "intra.db")
    # 盘后库：A 信号(窗内 06-09) 和 B(超窗 06-01，应被剔)
    _mkdb(post, [("600519", "贵州茅台", "主板", "1买", "2026-06-09", 1700.0),
                 ("000002", "万科", "主板", "1买", "2026-06-01", 10.0)], "2026-06-09")
    # 盘中库：A 同 code 同日(盘中优先) + 新出 C
    _mkdb(intra, [("600519", "贵州茅台", "主板", "1买", "2026-06-09", 1705.0),
                  ("300750", "宁德时代", "创业板", "2买", "2026-06-10", 200.0)], "2026-06-10")

    rows = dw.load_signals(post_db=post, intraday_db=intra,
                           today="2026-06-10", window_days=2)
    keyed = {(r["code"], r["signal_date"]): r for r in rows}
    assert ("600519", "2026-06-09") in keyed
    assert keyed[("600519", "2026-06-09")]["buy_price"] == 1705.0, "盘中优先"
    assert ("300750", "2026-06-10") in keyed, "盘中新出应纳入"
    assert ("000002", "2026-06-01") not in keyed, "超窗(>2交易日)盘后信号应剔除"


def test_post_only_equivalent_old():
    # intraday_db=None → 仅盘后批次(MAX scan_date)，不做窗口过滤，等价旧行为
    d = tempfile.mkdtemp()
    post = os.path.join(d, "post.db")
    _mkdb(post, [("600519", "贵州茅台", "主板", "1买", "2026-06-01", 1700.0),
                 ("000002", "万科", "主板", "2买", "2026-06-02", 10.0)], "2026-06-09")
    rows = dw.load_signals(post_db=post)
    codes = {r["code"] for r in rows}
    assert codes == {"600519", "000002"}, "盘后全批应保留(不按窗口剔)"


if __name__ == "__main__":
    test_union_dedup_intraday_priority()
    test_post_only_equivalent_old()
    print("ALL OK")
