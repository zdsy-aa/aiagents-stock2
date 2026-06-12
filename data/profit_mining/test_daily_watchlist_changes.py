import daily_watchlist as dw


def _row(code, status):
    return {"股票代码": code, "可入状态": status, "精选": "", "星级": "", "量比": 1.0,
            "买点类型": "1买", "命中规则": "A抄底", "资金确认": "", "中枢底部": ""}


def test_mark_new_and_changed():
    prev = [_row("600519", "尾窗"), _row("000001", "可入")]
    cur = [_row("600519", "可入"),     # 尾窗→可入 = 变动
           _row("000001", "可入"),     # 不变
           _row("300750", "可入")]     # 上轮没有 = 新出
    out = dw.mark_changes(cur, prev)
    m = {r["股票代码"]: r["变化标记"] for r in out}
    assert m["300750"] == "🆕新出", m
    assert m["600519"] == "⤴变动", m
    assert m["000001"] == "", m
    # 高亮(新出/变动)置顶
    assert out[0]["股票代码"] in ("300750", "600519")
    assert out[-1]["股票代码"] == "000001"


def test_mark_first_run_no_prev():
    cur = [_row("600519", "可入")]
    out = dw.mark_changes(cur, None)
    assert out[0]["变化标记"] == ""   # 首轮无上轮→不打标


if __name__ == "__main__":
    test_mark_new_and_changed()
    test_mark_first_run_no_prev()
    print("ALL OK")
