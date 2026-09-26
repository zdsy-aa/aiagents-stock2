# scripts/assets_check.py
import pathlib
ROOTS = {
    "aiagents-stock 代码": pathlib.Path("/home/tdxback/aiagents-stock"),
    "通达信脚本": pathlib.Path("/home/tdxback/通达信py脚本"),
    "指标库": pathlib.Path("/home/tdxback/通达信指标/20260424001/tdx_v4_standalone"),
    "K线库": pathlib.Path("/home/tdxback/aiagents-stock/tdx-data/database/kline"),
    # 原简报路径 /home/tdxback/tdxgp 已迁移/不存在(2026-09-26 盘点),改指实际路径:
    "行业数据集": pathlib.Path("/home/tdxback/通达信股票上下游分析"),
}
for name, p in ROOTS.items():
    files = [f for f in p.rglob("*") if f.is_file()]
    print(f"{name}: {len(files)} 个文件, 最近修改: "
          f"{max((f.stat().st_mtime for f in files), default=0):.0f}")
