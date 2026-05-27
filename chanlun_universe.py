# chanlun_universe.py
"""缠论选股股票池：排除科创板/北交所/ST，标注板块。仅依赖本地 codes.db。"""
import os
import re
import sqlite3
import glob
from typing import List, Tuple, Optional

# 本地K线/代码库文件名可能带市场前缀（sh/sz/bj），统一剥成裸代码
_PREFIX_RE = re.compile(r"^(sh|sz|bj)", re.IGNORECASE)


def _bare(code: str) -> str:
    return _PREFIX_RE.sub("", str(code))

CODES_DB = os.getenv("CODES_DB", "/app/tdx-api/web/data/database/codes.db")


def board_of(code: str) -> str:
    if code.startswith(("688", "689")):
        return "科创板"
    if code.startswith(("8", "4", "920")):
        return "北交所"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith("002"):
        return "中小板"
    if code.startswith(("000", "001", "003")):
        return "深主板"
    if code.startswith(("600", "601", "603", "605")):
        return "沪主板"
    return "其他"


def is_eligible(code: str, name: Optional[str]) -> bool:
    """排除科创/北交/ST/*ST；其余沪深主板/中小/创业保留。"""
    if board_of(code) in ("科创板", "北交所", "其他"):
        return False
    if name and "ST" in name.upper():
        return False
    return True


def _name_map() -> dict:
    """从 codes.db 取 code->name；失败返回空 dict（名字仅用于 ST 判定）。"""
    m = {}
    if not os.path.exists(CODES_DB):
        return m
    try:
        conn = sqlite3.connect(f"file:{CODES_DB}?mode=ro", uri=True)
        try:
            for code, name in conn.execute("SELECT Code, Name FROM codes"):
                m[_bare(code)] = name
        finally:
            conn.close()
    except Exception:
        pass
    return m


def list_universe(kline_dir: Optional[str] = None) -> List[Tuple[str, str, str]]:
    """枚举本地 kline 库中合格股票，返回 [(code, name, board)]。"""
    from akshare_gateway import akshare_gw
    kline_dir = kline_dir or akshare_gw.local.base_dir
    names = _name_map()
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for path in glob.glob(os.path.join(kline_dir, "*.db")):
        # 文件名兼容裸代码（600519）与带市场前缀（sh600519/sz000001/bj920000）
        code = _bare(os.path.splitext(os.path.basename(path))[0])
        if code in seen:  # 同代码裸名+前缀名并存时去重
            continue
        seen.add(code)
        name = names.get(code, "")
        if is_eligible(code, name):
            out.append((code, name, board_of(code)))
    return sorted(out)
