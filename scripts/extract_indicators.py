# scripts/extract_indicators.py
import re, pathlib

OUT = pathlib.Path("/home/tdxback/通达信指标/all.txt")

# 先读已有清单(含人工补充的中文组合指标等),与本次正则结果做并集、去重、排序后写回;
# 不覆盖人工条目,可重复运行(控制器裁决:合并去重而非覆盖)。
NAMES = set()
if OUT.exists():
    NAMES = {ln.strip() for ln in OUT.read_text(encoding="utf-8").splitlines() if ln.strip()}

# 正则误命中的非指标词(人工复核剔除清单:SQL MAX(scan_date)、配置常量、邮件、下划线函数
# 与基础名重复等)。只过滤正则结果,不影响 all.txt 中已有条目。
NOISE = {"DECIMAL", "EMAIL_ENABLED", "EMAIL_FROM", "EMAIL_PASSWORD", "EMAIL_TO", "IMAP",
         "JACCARD_MAX", "MAE", "MARKET", "MARKET_NUM_BY_SUFFIX", "MAX", "MAXHOLD", "MAXPOS",
         "MAXPOS_GRID", "MAX_STARS", "NORMAL", "PRAGMA", "PRIMARY", "SCHEMA",
         "SUPPORTED_MARKET_NUMBERS", "XTP_PRICE_MARKET_OR_CANCEL",
         "_EMA", "_INDEX_MAP", "_KDJ", "_LIUMAI_SCRIPT", "_MA", "_MACD", "_RSI", "_SMA",
         "_SPOT_MAP", "nMA"}

SRC_DIRS = ["/home/tdxback/aiagents-stock", "/home/tdxback/通达信py脚本",
            "/home/tdxback/aiagents-stock/data/profit_mining"]
# 规则1: features.py 中 def xxx_features / 指标注释行
# 规则2: 通达信公式名:文件名(如 MACD.tn6 的 stem)
for d in SRC_DIRS:
    for f in pathlib.Path(d).rglob("*.py"):
        for m in re.finditer(r"(?:def\s+)?([A-Za-z_]*MACD[A-Za-z_]*|[A-Za-z_]*(?:RSI|KDJ|BOLL|MA|EMA)[A-Za-z_]*)", f.read_text(encoding="utf-8", errors="ignore")):
            if m.group(1) not in NOISE:
                NAMES.add(m.group(1))
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(sorted(NAMES)) + "\n", encoding="utf-8")
