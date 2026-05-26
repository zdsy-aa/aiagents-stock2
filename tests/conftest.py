"""Pytest 配置：把项目根目录加入 sys.path，便于直接 import 业务模块。

重要：本文件由 pytest 在收集/import 任何测试模块之前加载，因此是设置
LOCAL_DB_* 环境变量的唯一可靠位置。akshare_gateway.akshare_gw 是单例，
在首个测试文件 import 时即初始化并锁定 LOCAL_DB_DIR；若把 env 写在单个
测试文件顶部，当别的测试先 import 网关时该值已来不及生效，导致全量
`pytest tests/` 时分钟测试拿到空目录而失败（单独跑该文件却通过）。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 在任何业务模块 import 之前锁定本地分钟库目录（相对 ROOT，便于跨机/CI）。
os.environ["LOCAL_DB_DIR"] = os.path.join(ROOT, "tdx-data", "database", "kline")
os.environ.setdefault("LOCAL_DB_ENABLED", "true")
