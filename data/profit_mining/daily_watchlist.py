# daily_watchlist.py —— 工程化每日选股：对最近缠论买点应用验证规则，输出当日自选股清单。
#   规则=稳定组合 A∪B：A 极限抄底+量比≥1.3；B 尖刺金叉(筹码，需换手率)。
#   过滤：大盘非空头/危险(SID≤2)，剔除获利盘>70%。优先1买。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/daily_watchlist.py [scan_date]
import sys, sqlite3, csv, time, os
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
import pandas as pd
import features as F
import turnover_features as TF
import star_calibrate as SC

SIGDB = "/app/data/chanlun_signals.db"
IDXCSV = "/app/data/profit_mining/index_sh000001.csv"
OUT = "/app/data/profit_mining/每日自选股清单.csv"
HISTDIR = "/app/data/profit_mining/watchlist_history"   # 按扫描日期存历史选股记录
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}


def entry_status(gap, close, buy, stop, tp, premium=0.05):
    """扫描日这条信号是否仍可入。
    gap=信号日到扫描日的交易日数(>=0)；close=扫描日收盘；buy/stop/tp=买入/止损/止盈价。
    价格类(破止损/止盈/涨过)优先于窗口类——价格跑掉则进场前提已失效。
    入参缺失或 gap<0 → '—'。"""
    if close is None or buy is None or gap is None or gap < 0:
        return "—"
    if stop is not None and close < stop:
        return "已破止损"
    if tp is not None and close >= tp:
        return "已止盈"
    if close > buy * (1 + premium):
        return "已涨过"
    if gap > 2:
        return "已过窗"
    if gap == 2:
        return "尾窗"
    return "可入"


def _load(code):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=600)
    if df is None or df.empty:
        return None
    return df.rename(columns=_RENAME).set_index("日期").sort_index()[["Open", "High", "Low", "Close", "Volume"]]


def _refresh_index():
    """盘后刷新上证指数缓存(实时口径)；失败则沿用旧缓存。"""
    try:
        import akshare as ak
        d = ak.stock_zh_index_daily(symbol="sh000001").rename(columns={
            "date": "日期", "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume"})
        d.to_csv(IDXCSV, index=False, encoding="utf-8-sig")
    except Exception:
        pass


def _bcode(code):
    code = str(code).zfill(6)
    if code[0] == "6":
        return "sh." + code
    if code[0] in ("0", "3"):
        return "sz." + code
    return None


def _fetch_turn(bs, code, start):
    """baostock 取单只历史换手率 Series(index=datetime)。失败返回 None。"""
    bc = _bcode(code)
    if not bc:
        return None
    try:
        rs = bs.query_history_k_data_plus(bc, "date,turn", start_date=start,
                                          frequency="d", adjustflag="2")
        d, t = [], []
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            if row[1]:
                d.append(row[0]); t.append(float(row[1]))
        if not d:
            return None
        return pd.Series(t, index=pd.to_datetime(d))
    except Exception:
        return None


def main():
    _refresh_index()
    idx = pd.read_csv(IDXCSV, encoding="utf-8-sig"); idx["日期"] = pd.to_datetime(idx["日期"])
    idx = idx.set_index("日期").sort_index()
    ist = F.index_state(idx[["Open", "High", "Low", "Close", "Volume"]])

    con = sqlite3.connect(SIGDB)
    con.row_factory = sqlite3.Row
    sd = sys.argv[1] if len(sys.argv) > 1 else con.execute(
        "SELECT MAX(scan_date) FROM signals").fetchone()[0]
    rows = con.execute(
        "SELECT code,name,board,signal_type,signal_date,buy_price FROM signals "
        "WHERE scan_date=? AND signal_type IN ('1买','2买','3买')", (sd,)).fetchall()
    print(f"[每日选股] scan_date={sd}，候选缠论买点 {len(rows)} 个，过滤中(含尖刺金叉筹码计算)…", flush=True)

    # 星级阈值(阶段一回测固化)：核心5★/精选2★。缺失则降级为不打星。
    try:
        STARS = SC.load_thresholds()
        print("[每日选股] 已载入星级阈值 star_thresholds.json（核心/精选打星启用）", flush=True)
    except Exception as e:
        STARS = None
        print(f"[每日选股] 星级阈值缺失({type(e).__name__})，本次不打星", flush=True)

    # baostock 登录（拿不到则降级为 A-only）。WL_SKIP_BAOSTOCK=1 强制仅A(网络不通时用)。
    bs = None
    if os.getenv("WL_SKIP_BAOSTOCK") == "1":
        print("[每日选股] WL_SKIP_BAOSTOCK=1，跳过baostock(仅A，核心B尖刺金叉/获利盘过滤略)", flush=True)
    else:
        try:
            import socket
            socket.setdefaulttimeout(20)          # 防 baostock 网络无超时挂死(单次调用>20s即中断该股)
            import baostock
            lg = baostock.login()
            if getattr(lg, "error_code", "1") != "0":
                raise RuntimeError(f"login {getattr(lg, 'error_code', '?')}")
            bs = baostock
        except Exception as e:
            print(f"[每日选股] baostock 不可用({type(e).__name__})，核心B尖刺金叉跳过(仅A)", flush=True)
    turn_start = (pd.Timestamp.now() - pd.Timedelta(days=760)).strftime("%Y-%m-%d")

    out = []
    t0 = time.time()
    for k, r in enumerate(rows, 1):
        code = str(r["code"]).zfill(6)
        df = _load(code)
        if df is None or len(df) < 70:
            continue
        dates = {d.strftime("%Y-%m-%d"): p for p, d in enumerate(df.index)}
        if r["signal_date"] not in dates:
            continue
        i = dates[r["signal_date"]]
        # 核心A
        tdx = F.tdx_extra_features(df, code=code)
        cd = tdx["极限抄底"]
        vf = F.volume_features(df)
        ql = (vf["量比"] >= 1.3).astype(int)
        hitA = bool(F.window_or_at(cd, i, 2) and F.window_or_at(ql, i, 2))
        # 全量信号库加分项(2026-06-01研究)：机构净买=资金确认(状态,取当日)；中枢底部=中枢极限底/底部回升(事件,±2窗)
        try:
            zj_buy = int(F.capitalflow_features(df)["机构净买"].iloc[i]) == 1
        except Exception:
            zj_buy = False
        zs_bottom = bool(F.window_or_at(tdx["中枢极限底"], i, 2) or F.window_or_at(tdx["中枢底部回升"], i, 2))
        # 核心B + 反向过滤(获利盘) —— 需换手率重建筹码
        hitB, profit_chip = False, None
        if bs is not None:
            turn = _fetch_turn(bs, code, turn_start)
            if turn is not None and len(turn) >= 60:
                ch = TF.chip_series(df, turn)
                cross = (ch["爆破线"] > ch["堡垒线"]) & (ch["爆破线"].shift(1) <= ch["堡垒线"].shift(1))
                hitB = bool(F.window_or_at(cross.astype(int), i, 2))
                pv = ch["获利盘"].iloc[i]
                profit_chip = float(pv) if pd.notna(pv) else None
        if not (hitA or hitB):
            continue
        if profit_chip is not None and profit_chip > 70:   # 反向过滤：获利盘过高放弃
            continue
        # 大盘环境
        sdate = pd.Timestamp(r["signal_date"])
        env_id = int(ist["大盘状态ID"].asof(sdate)) if len(ist) else 2
        env = {1: "多头", 2: "震荡", 3: "空头", 4: "危险"}.get(env_id, "?")
        if env_id > 2:
            continue
        rule = "A∪B" if (hitA and hitB) else ("A抄底" if hitA else "B抢筹")
        # 精选层（refine_backtest.py 样本外验证：基础集∩1买∩非陷阱 比基础集 +10~12pt/2024-25，无过拟合）
        #   只对1买生效；陷阱=大盘多头 或 相对强弱≥0（极限抄底=震荡市超跌反弹，转强反失效，基础集内-19pt）；
        #   命中量能金叉再升一档（1买内 +4.8pt）。普通票仍保留，只是不打精选标、排序靠后。
        refine = ""
        if r["signal_type"] == "1买":
            idx_close = idx["Close"].reindex(df.index).ffill()
            rs_i = F.relative_strength(df["Close"], idx_close)["相对强弱"].iloc[i]
            trap = (env_id == 1) or (pd.notna(rs_i) and rs_i >= 0)
            if not trap:
                vjc = F.CROSS(F.MA(df["Volume"], 5), F.MA(df["Volume"], 60)).astype(int)
                refine = "★★核心" if F.window_or_at(vjc, i, 2) else "★精选"
        # 星级：仅对 1买非陷阱候选(核心/精选)按阶段一阈值查表打星，口径与训练一致。
        star_label, est_win, big_rise = "", "", ""
        if refine and STARS is not None:
            tier_name = "核心" if refine == "★★核心" else "精选"
            star_row = {
                "极限抄底": F.window_or_at(cd, i, 2),
                "中枢极限底": F.window_or_at(tdx["中枢极限底"], i, 2),
                "中枢底部回升": F.window_or_at(tdx["中枢底部回升"], i, 2),
                "量比": float(vf["量比"].iloc[i]),
                "相对强弱": float(rs_i) if pd.notna(rs_i) else "",
            }
            st, ew, br, _ = SC.assign_star(tier_name, star_row, STARS)
            star_label = f"{tier_name}{'★' * st}"
            est_win = round(ew * 100, 1) if ew is not None else ""
            big_rise = round(br * 100, 1) if br is not None else ""
        # 止损/止盈位：止损取「-8%固定」与「信号前5日结构低点-1%」更近(更高)者→更保守；
        #   止盈=+30%固定(回测TP30口径)。买点是进场理由非持有理由，跌破止损即出场不看信号是否仍命中。
        bp = float(r["buy_price"])
        lo5 = float(df["Low"].iloc[max(0, i - 5):i + 1].min())
        stop_loss = round(max(bp * 0.92, lo5 * 0.99), 2)
        take_profit = round(bp * 1.30, 2)
        # 可入状态：扫描日(≤sd 的最后一根 bar)收盘 + 信号到扫描日的交易日间隔，判时效/价格
        j = int(df.index.searchsorted(pd.Timestamp(sd), side="right")) - 1
        close_scan = float(df["Close"].iloc[j]) if 0 <= j < len(df) else None
        gap = j - i if (close_scan is not None and j >= i) else -1
        es = entry_status(gap, close_scan, bp, stop_loss, take_profit)
        out.append({"股票代码": code, "股票名称": r["name"], "板块": r["board"],
                    "买点类型": r["signal_type"], "信号日期": r["signal_date"],
                    "买入价": r["buy_price"], "止损价": stop_loss, "止盈价": take_profit,
                    "命中规则": rule, "精选": refine,
                    "星级": star_label, "预估胜率": est_win, "大涨率": big_rise,
                    "资金确认": "✓机构净买" if zj_buy else "",
                    "中枢底部": "✓" if zs_bottom else "",
                    "量比": round(float(vf["量比"].iloc[i]), 2),
                    "获利盘%": round(profit_chip, 0) if profit_chip is not None else "",
                    "大盘环境": env,
                    "优先级": "★高(1买)" if r["signal_type"] == "1买" else "中",
                    "可入状态": es})
        if k % 200 == 0:
            print(f"  …已扫 {k}/{len(rows)}，命中 {len(out)}，{int(time.time()-t0)}s", flush=True)
    if bs is not None:
        try:
            bs.logout()
        except Exception:
            pass

    _rk = {"★★核心": 0, "★精选": 1, "": 2}      # 层主键：核心>精选>普通；层内再按 星数↓>1买>A∪B>资金确认>中枢底部>量比
    out.sort(key=lambda x: (_rk.get(x["精选"], 2), -x["星级"].count("★"),
                            x["买点类型"] != "1买",
                            x["命中规则"] != "A∪B", x["资金确认"] == "", x["中枢底部"] == "", -x["量比"]))
    for x in out:
        x["扫描日期"] = sd                 # 记录是哪天扫描的，供历史区分/过滤
    cols = ["扫描日期", "股票代码", "股票名称", "板块", "买点类型", "信号日期", "买入价",
            "止损价", "止盈价",
            "命中规则", "精选", "资金确认", "中枢底部", "量比", "获利盘%", "大盘环境", "优先级",
            "可入状态", "星级", "预估胜率", "大涨率"]
    # 1) latest（向后兼容）；2) 按扫描日期存历史(不覆盖)
    os.makedirs(HISTDIR, exist_ok=True)
    for path in (OUT, f"{HISTDIR}/每日自选股清单_{sd}.csv"):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(out)
    nA = sum(1 for x in out if "A" in x["命中规则"]); nB = sum(1 for x in out if "B" in x["命中规则"])
    nC = sum(1 for x in out if x["精选"] == "★★核心"); nR = sum(1 for x in out if x["精选"])
    nZ = sum(1 for x in out if x["资金确认"]); nZS = sum(1 for x in out if x["中枢底部"])
    print(f"[每日选股] scan_date={sd} 命中 {len(out)} 只（A抄底{nA}/B抢筹{nB}，精选{nR}其中核心{nC}，"
          f"资金确认{nZ}/中枢底部{nZS}，已剔除获利盘>70%，大盘非空头危险），写入 {OUT} + 历史，{int(time.time()-t0)}s", flush=True)
    for x in out[:15]:
        print(f"  {x['精选']:<5} {x['优先级']:<7} {x['命中规则']:<5} {x['股票代码']} "
              f"{x['股票名称']:<6} {x['买点类型']} 量比{x['量比']} {x['大盘环境']}")


if __name__ == "__main__":
    main()
