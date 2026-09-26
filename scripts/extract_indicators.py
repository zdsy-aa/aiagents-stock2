# scripts/extract_indicators.py
import re, pathlib
NAMES = set()
SRC_DIRS = ["/home/tdxback/aiagents-stock", "/home/tdxback/通达信py脚本",
            "/home/tdxback/aiagents-stock/data/profit_mining"]
# 规则1: features.py 中 def xxx_features / 指标注释行
# 规则2: 通达信公式名:文件名(如 MACD.tn6 的 stem)
for d in SRC_DIRS:
    for f in pathlib.Path(d).rglob("*.py"):
        for m in re.finditer(r"(?:def\s+)?([A-Za-z_]*MACD[A-Za-z_]*|[A-Za-z_]*(?:RSI|KDJ|BOLL|MA|EMA)[A-Za-z_]*)", f.read_text(encoding="utf-8", errors="ignore")):
            NAMES.add(m.group(1))
pathlib.Path("/home/tdxback/通达信指标/all.txt").write_text("\n".join(sorted(NAMES)), encoding="utf-8")
