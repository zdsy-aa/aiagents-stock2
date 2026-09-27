# -*- coding: utf-8 -*-
"""automation.chip_data 筹码数据源选型(Phase5 Task5.5)。

探测三个候选筹码数据源并固化结论:

1. akshare stock_cyq_em —— 已装入 venv-data(akshare 1.18.97,2026-09-27 经
   清华镜像),数据链路 = 东财 push2his 日K(f51~f61 含换手率)+ JS CYQCalculator
   本地计算;但本机 IP 被 push2his.eastmoney.com 封禁(akshare_gateway.py 的
   BLOCKED_EM_FUNCS 已有记录),实测不可用;
2. 东财 HTTP —— push2/push2his/push2delay 均不可达;emweb F10 与
   datacenter-web 可达但无筹码分布接口(仅股东户数可作集中度近似);
3. TDX 本地文件 —— 本机无通达信客户端安装目录(全盘 find 无 vipdoc/T0002/
   *.day,无 wine);项目 tdx-api 本地 sqlite K线不含换手率/流通股本,无法本地
   计算 CYQ。

结论(记录型,不发网络请求): source=unavailable;fetch_chip 抛
NotImplementedError 并附指引。东财解封后改 ``_DECISION`` 的 source 为
"akshare" 即可启用(akshare 取数映射 ``_fetch_via_akshare`` 已实现并有单测
覆盖)。完整探测日志与选型理由见 docs/chip_data_decision.md。

用法:
    python -m automation.chip_data --probe   # 复跑三源实时探测(网络/本地盘)
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import sqlite3
import urllib.request
from datetime import datetime

logger = logging.getLogger(__name__)

__all__ = [
    "chip_decision",
    "fetch_chip",
    "probe_akshare",
    "probe_em_http",
    "probe_tdx_file",
]

# ---------------------------------------------------------------------------
# 记录型选型结论(2026-09-27 实测探测,探测日志见 docs/chip_data_decision.md)
# ---------------------------------------------------------------------------
_DECISION = {
    "source": "unavailable",
    "status": "unavailable",
    "notes": (
        "2026-09-27 探测结论:三个候选筹码源在本机均不可用。\n"
        "[1] akshare: venv-data 已装 akshare 1.18.97(经清华镜像);stock_cyq_em "
        "链路=push2his 日K(f51-f61 含换手率)+JS CYQCalculator 本地计算,算法与"
        "输出字段已核实;但上游 push2his.eastmoney.com 对本机 IP 封禁"
        "(akshare_gateway.py BLOCKED_EM_FUNCS 已有记录)。实测:走代理 127.0.0.1:7890 "
        "连发 10 次 0 成功,直连与容器直连均 RemoteDisconnected,唯一 1 次成功为"
        "代理出口轮换偶发,不可作为生产通道。\n"
        "[2] 东财 HTTP: push2/push2his/push2delay 均不可达(000/连接重置);"
        "emweb F10 与 datacenter-web 可达(200)但无筹码分布接口,仅有股东户数"
        "(RPT_HOLDERNUM_DET)可作筹码集中度近似。\n"
        "[3] TDX 本地文件: 本机无通达信客户端安装目录(全盘 find 无 vipdoc/"
        "T0002/*.day,无 wine);项目 tdx-api 本地 sqlite K线(Code/Date/OHLCV/"
        "Amount/InDate,数据新至 2026-09-24)不含换手率/流通股本,tdx-api 服务亦"
        "无筹码/股本接口(已核对 server.go 全部路由)→ CYQ 算法无法本地计算。\n"
        "推荐: 首选 akshare(东财解封或更换出口 IP 后即用,fetch 映射已内置并单测);"
        "备选 tdx_file(需补齐流通股本/换手率数据)。详见 docs/chip_data_decision.md。"
    ),
}


def chip_decision() -> dict:
    """返回筹码数据源选型结论(记录型实现,不发网络请求,结果确定)。

    Returns:
        {"source": "akshare"|"tdx_file"|"unavailable", "status": str, "notes": str}
    """
    return dict(_DECISION)


# ---------------------------------------------------------------------------
# 取数接口
# ---------------------------------------------------------------------------
def _ak_cyq_df(code: str, adjust: str = ""):
    """经 akshare.stock_cyq_em 取原始筹码表(独立成函数便于单测注入)。"""
    import akshare as ak

    return ak.stock_cyq_em(symbol=code, adjust=adjust)


def _fetch_via_akshare(code: str, adjust: str = "") -> dict:
    """akshare 取数 → 标准化字段(取最新一行)。

    akshare stock_cyq_em 输出列: 日期/获利比例/平均成本/90成本-低/90成本-高/
    90集中度/70成本-低/70成本-高/70集中度(最近 90 行)。
    """
    df = _ak_cyq_df(code, adjust)
    if df is None or len(df) == 0:
        raise ValueError(f"akshare 未返回 {code} 筹码数据(空表)")
    last = df.iloc[-1]
    date_val = last["日期"]
    date_str = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)
    return {
        "date": date_str,
        "获利盘": float(last["获利比例"]),
        "平均成本": float(last["平均成本"]),
        "90%集中度区间": [float(last["90成本-低"]), float(last["90成本-高"])],
    }


def fetch_chip(code: str, adjust: str = "") -> dict:
    """按选型结论取单票筹码数据(不落全市场,单票按需)。

    Returns:
        {"date": "YYYY-MM-DD", "获利盘": 0~1, "平均成本": float,
         "90%集中度区间": [低, 高]}

    Raises:
        NotImplementedError: 当前选型结论为 unavailable 时抛出,附结论指引。
    """
    decision = chip_decision()
    if decision["source"] == "unavailable":
        raise NotImplementedError(
            "筹码数据源当前不可用(source=unavailable,2026-09-27 探测结论)。"
            "指引: 东财 push2his 解封或更换出口 IP 后,将 automation/chip_data.py "
            "中 _DECISION 改回 source='akshare'(akshare 取数映射已内置并有单测);"
            "或补齐流通股本/换手率后启用 tdx_file 本地计算。详见 docs/chip_data_decision.md。"
        )
    if decision["source"] == "akshare":
        return _fetch_via_akshare(code, adjust)
    raise NotImplementedError(f"未实现的筹码源: {decision['source']}")


# ---------------------------------------------------------------------------
# 实时探测(复评用;akshare/东财两项会发网络请求,勿在单测中断言其结果)
# ---------------------------------------------------------------------------
def _run_with_timeout(fn, timeout_s: float):
    """线程池执行 fn,超时返回 TimeoutError。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            return TimeoutError(f"探测超时(>{timeout_s}s)")


def probe_akshare(timeout_s: float = 30.0) -> dict:
    """实时探测 akshare 筹码接口(网络调用)。"""
    def _run():
        import akshare as ak

        version = getattr(ak, "__version__", "?")
        if not hasattr(ak, "stock_cyq_em"):
            return {
                "candidate": "akshare",
                "ok": False,
                "reason": "该版本无 stock_cyq_em 接口",
                "detail": f"akshare {version}",
            }
        df = ak.stock_cyq_em(symbol="000001")
        return {
            "candidate": "akshare",
            "ok": True,
            "rows": int(len(df)),
            "cols": list(df.columns),
            "last_row": df.tail(1).to_dict("records")[0],
            "detail": f"akshare {version}",
        }

    try:
        result = _run_with_timeout(_run, timeout_s)
        if isinstance(result, Exception):
            raise result
        return result
    except Exception as e:  # noqa: BLE001 —— 探测必须吞掉一切异常并如实记录
        return {"candidate": "akshare", "ok": False, "reason": f"{type(e).__name__}: {e}"}


def _http_get(url: str, timeout_s: float = 12.0) -> dict:
    """urllib GET(沿用环境代理变量),返回 {status, body_head}。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read(2048).decode("utf-8", errors="replace")
            return {"status": resp.status, "body_head": body[:200]}
    except Exception as e:  # noqa: BLE001
        return {"status": 0, "error": f"{type(e).__name__}: {e}"}


def probe_em_http(timeout_s: float = 15.0) -> dict:
    """实时探测东财筹码相关 HTTP 接口可达性(网络调用)。

    push2his 日K是 stock_cyq_em 的唯一上游;emweb/datacenter 用于记录
    「可达但无筹码数据」的替代接口。
    """
    urls = {
        "push2his_kline": (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            "?secid=1.000001&klt=101&fqt=0&end=20260927&lmt=3"
            "&fields1=f1,f2,f3&fields2=f51,f52,f53"
        ),
        "push2delay_kline": (
            "https://push2delay.eastmoney.com/api/qt/stock/kline/get"
            "?secid=1.000001&klt=101&fqt=0&end=20260927&lmt=3"
            "&fields1=f1,f2,f3&fields2=f51,f52,f53"
        ),
        "emweb_f10": "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code=SZ000001",
        "datacenter_holdernum": (
            "https://datacenter-web.eastmoney.com/api/data/v1/get"
            "?reportName=RPT_HOLDERNUM_DET&columns=ALL"
            "&filter=(SECURITY_CODE%3D%22000001%22)&pageNumber=1&pageSize=1"
            "&sortTypes=-1&sortColumns=END_DATE"
        ),
    }
    results = {}
    for name, url in urls.items():
        try:
            results[name] = _run_with_timeout(lambda u=url: _http_get(u), timeout_s)
            if isinstance(results[name], Exception):
                results[name] = {"status": 0, "error": str(results[name])}
        except Exception as e:  # noqa: BLE001
            results[name] = {"status": 0, "error": f"{type(e).__name__}: {e}"}
    upstream_ok = results.get("push2his_kline", {}).get("status") == 200 or results.get(
        "push2delay_kline", {}
    ).get("status") == 200
    return {
        "candidate": "em_http",
        "ok": upstream_ok,
        "reason": "push2his/push2delay 日K接口可用即可支撑 CYQ 计算",
        "detail": json.dumps(results, ensure_ascii=False),
    }


def probe_tdx_file() -> dict:
    """探测 TDX 本地文件可用性(仅本地文件系统,不发网络请求)。

    检查: 通达信客户端安装目录(vipdoc/T0002/*.day)、项目 tdx-api 本地 K线库
    是否含换手率/流通股本字段(筹码分布本地计算的前提)。
    """
    import pathlib

    found_client_dirs = []
    roots = [
        pathlib.Path.home(),
        pathlib.Path("/opt"),
        pathlib.Path("/mnt"),
        pathlib.Path("/srv"),
        pathlib.Path("/root"),
    ]
    marks = ("vipdoc", "T0002", "new_tdx")
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*"):
                if p.name in marks and len(str(p)) < 400:
                    found_client_dirs.append(str(p))
        except OSError:
            continue
        if len(found_client_dirs) >= 5:
            break

    # 项目 tdx-api 本地 K线库(仅看 schema,证明缺换手率/流通股本)
    kline_dir = os.environ.get(
        "TDX_KLINE_DIR",
        "/home/tdxback/aiagents-stock/tdx-data/database/kline",
    )
    db_cols = []
    db_files = []
    if os.path.isdir(kline_dir):
        db_files = sorted(f for f in os.listdir(kline_dir) if f.endswith(".db"))[:1]
        for f in db_files:
            try:
                con = sqlite3.connect(f"file:{os.path.join(kline_dir, f)}?mode=ro", uri=True)
                cur = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    cur = con.execute(f"PRAGMA table_info({row[0]})")
                    db_cols = [r[1] for r in cur.fetchall()]
                con.close()
            except sqlite3.Error as e:
                db_cols = [f"sqlite_error: {e}"]

    client_ok = bool(found_client_dirs)
    kline_ok = "hsl" in db_cols or "turnover" in " ".join(db_cols).lower()
    return {
        "candidate": "tdx_file",
        "ok": client_ok and kline_ok,
        "reason": "需通达信客户端数据目录(或含换手率/流通股本的本地K线)才能本地计算筹码",
        "client_dirs": found_client_dirs,
        "kline_db_sample": {"files": db_files, "cols": db_cols},
        "detail": (
            f"客户端目录命中 {len(found_client_dirs)} 个;"
            f"tdx-api 本地K线字段 {db_cols}(无换手率/流通股本)"
        ),
    }


if __name__ == "__main__":
    # python -m automation.chip_data [--probe] —— --probe 复跑三源实时探测
    import sys

    if "--probe" in sys.argv:
        out = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "probes": {
                "akshare": probe_akshare(),
                "em_http": probe_em_http(),
                "tdx_file": probe_tdx_file(),
            },
            "decision": chip_decision(),
        }
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(chip_decision(), ensure_ascii=False, indent=2))
