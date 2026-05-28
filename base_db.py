import sqlite3
import os
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 所有 .db 文件统一存放目录，便于备份/迁移/部署（可用环境变量 AIAGENTS_DATA_DIR 覆盖）
DATA_DIR = os.environ.get("AIAGENTS_DATA_DIR", "data")


class BaseDatabase:
    """数据库基类，提供统一的连接管理和WAL模式配置"""
    
    def __init__(self, db_path: str):
        # 裸文件名（不含目录）统一落到 DATA_DIR 下；已带目录/绝对路径的保持原样
        if db_path and not os.path.dirname(db_path):
            db_path = os.path.join(DATA_DIR, db_path)
        self.db_path = db_path
        # 确保数据库所在目录存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        self.init_tables()

    @contextmanager
    def conn(self):
        """获取数据库连接的上下文管理器 (P2 整改十: 自动 commit)"""
        # 设置超时时间为 30 秒
        c = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        try:
            # 每次连接都强制设置 WAL 和 busy_timeout
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            yield c
            # P2 整改十: 成功则自动提交
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def init_tables(self):
        """初始化表结构，由子类实现"""
        raise NotImplementedError

    def cleanup_old_data(self, table_name: str, days: int = 30, time_column: str = 'created_at'):
        """清理指定天数之前的旧数据 (P1 整改三)"""
        # P0 整改一: 添加 SQL 注入白名单校验
        ALLOWED_TABLES = {'notifications', 'price_history', 'analysis_records', 'monitored_stocks'}
        ALLOWED_COLUMNS = {'created_at', 'triggered_at', 'timestamp', 'updated_at'}
        if table_name not in ALLOWED_TABLES or time_column not in ALLOWED_COLUMNS:
            raise ValueError(f"非法的表名或列名: {table_name}.{time_column}")

        with self.conn() as conn:
            cursor = conn.cursor()
            try:
                # days 是整数，可以通过参数绑定
                cursor.execute(f"DELETE FROM {table_name} WHERE {time_column} < datetime('now', ?)", (f'-{days} days',))
                # BaseDatabase 之后会改为自动 commit，目前保留手动以防万一
                conn.commit()
                return cursor.rowcount
            except Exception:
                logger.exception(f"清理数据失败 {table_name}")
                return 0
