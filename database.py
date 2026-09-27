import json
from datetime import datetime
from base_db import BaseDatabase

def _safe_json(text, fallback):
    """JSON 文本 -> 对象;空/非法文本回退(不抛异常,保证旧数据可读)。"""
    if not text:
        return fallback
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text

class StockAnalysisDatabase(BaseDatabase):
    def __init__(self, db_path="stock_analysis.db"):
        super().__init__(db_path)

    def init_tables(self):
        """初始化数据库表结构(含 Task4.4 版本/快照列的幂等兼容迁移)"""
        with self.conn() as conn:
            cursor = conn.cursor()

            # 创建分析记录表(新库直接含版本列;老库由 _migrate_analysis_columns 补齐)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS analysis_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    stock_name TEXT,
                    analysis_date TEXT NOT NULL,
                    period TEXT NOT NULL,
                    stock_info TEXT,
                    agents_results TEXT,
                    discussion_result TEXT,
                    final_decision TEXT,
                    created_at TEXT NOT NULL,
                    prompt_version TEXT NOT NULL DEFAULT '',
                    model_version TEXT NOT NULL DEFAULT '',
                    input_snapshot TEXT NOT NULL DEFAULT ''
                )
            ''')

            self._migrate_analysis_columns(cursor)
            conn.commit()

    @staticmethod
    def _migrate_analysis_columns(cursor):
        """Task4.4 兼容迁移:老库缺列则 ALTER TABLE ADD COLUMN(幂等)。

        - 用 PRAGMA table_info 检查列存在性,只加缺的列,不重建表、不迁移数据;
        - 新列:prompt_version / model_version(默认空串)、input_snapshot
          (JSON 文本,默认空串);既有行自动补默认值,旧数据不受影响。
        """
        cursor.execute("PRAGMA table_info(analysis_records)")
        existing = {row[1] for row in cursor.fetchall()}
        for name, ddl in (
            ("prompt_version", "TEXT NOT NULL DEFAULT ''"),
            ("model_version", "TEXT NOT NULL DEFAULT ''"),
            ("input_snapshot", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in existing:
                cursor.execute(
                    f"ALTER TABLE analysis_records ADD COLUMN {name} {ddl}")

    def save_analysis(self, symbol, stock_name, period, stock_info, agents_results, discussion_result, final_decision, prompt_version="", model_version="", input_snapshot=""):
        """保存分析记录到数据库

        Task4.4 增默认参数 prompt_version / model_version / input_snapshot
        (默认空串,旧调用兼容);input_snapshot 传 dict 时序列化为 JSON 文本。
        """
        with self.conn() as conn:
            cursor = conn.cursor()

            # 准备数据
            analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            created_at = datetime.now().isoformat()

            # 将复杂对象转换为JSON字符串
            stock_info_json = json.dumps(stock_info, ensure_ascii=False, default=str)
            agents_results_json = json.dumps(agents_results, ensure_ascii=False, default=str)
            discussion_result_json = json.dumps(discussion_result, ensure_ascii=False, default=str)
            final_decision_json = json.dumps(final_decision, ensure_ascii=False, default=str)
            snapshot_json = (input_snapshot if isinstance(input_snapshot, str)
                             else json.dumps(input_snapshot, ensure_ascii=False, default=str))

            cursor.execute('''
                INSERT INTO analysis_records
                (symbol, stock_name, analysis_date, period, stock_info, agents_results, discussion_result, final_decision, created_at, prompt_version, model_version, input_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (symbol, stock_name, analysis_date, period, stock_info_json, agents_results_json, discussion_result_json, final_decision_json, created_at, prompt_version or "", model_version or "", snapshot_json))

            conn.commit()
            return cursor.lastrowid
    
    def get_all_records(self):
        """获取所有分析记录"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, symbol, stock_name, analysis_date, period, final_decision, created_at
                FROM analysis_records 
                ORDER BY created_at DESC
            ''')
            
            records = cursor.fetchall()
        
        result = []
        for record in records:
            # 解析final_decision获取评级
            final_decision = json.loads(record[5]) if record[5] else {}
            rating = final_decision.get('rating', '未知') if isinstance(final_decision, dict) else '未知'
            
            result.append({
                'id': record[0],
                'symbol': record[1],
                'stock_name': record[2],
                'analysis_date': record[3],
                'period': record[4],
                'rating': rating,
                'created_at': record[6]
            })
        
        return result
    
    def get_record_count(self):
        """获取记录总数"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) FROM analysis_records')
            count = cursor.fetchone()[0]
        
        return count
    
    def get_record_by_id(self, record_id):
        """根据ID获取详细分析记录(含 Task4.4 版本/快照字段)"""
        with self.conn() as conn:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, symbol, stock_name, analysis_date, period, stock_info, agents_results, discussion_result, final_decision, created_at, prompt_version, model_version, input_snapshot
                FROM analysis_records WHERE id = ?
            ''', (record_id,))

            record = cursor.fetchone()

        if not record:
            return None

        # 解析JSON数据
        return {
            'id': record[0],
            'symbol': record[1],
            'stock_name': record[2],
            'analysis_date': record[3],
            'period': record[4],
            'stock_info': json.loads(record[5]) if record[5] else {},
            'agents_results': json.loads(record[6]) if record[6] else {},
            'discussion_result': json.loads(record[7]) if record[7] else {},
            'final_decision': json.loads(record[8]) if record[8] else {},
            'created_at': record[9],
            'prompt_version': record[10] or "",
            'model_version': record[11] or "",
            'input_snapshot': _safe_json(record[12], {}),
        }
    
    def delete_record(self, record_id):
        """删除指定记录"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM analysis_records WHERE id = ?', (record_id,))
            conn.commit()
            return cursor.rowcount > 0

# P3 整改十八: 延迟加载单例
_db_instance = None
def get_db():
    global _db_instance
    if _db_instance is None:
        _db_instance = StockAnalysisDatabase()
    return _db_instance

# 为了兼容旧代码，保留 db 变量，但改为动态获取
class DBProxy:
    def __getattr__(self, name):
        return getattr(get_db(), name)

db = DBProxy()
