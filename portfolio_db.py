"""
持仓股票数据库管理模块

提供持仓股票和分析历史的数据库操作接口
"""

import json
import logging
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from base_db import BaseDatabase

logger = logging.getLogger(__name__)

# 数据库文件路径
DB_PATH = "portfolio_stocks.db"


class PortfolioDB(BaseDatabase):
    """持仓股票数据库管理类"""
    
    def __init__(self, db_path: str = DB_PATH):
        """
        初始化数据库连接
        
        Args:
            db_path: 数据库文件路径
        """
        super().__init__(db_path)
    
    def init_tables(self):
        """初始化数据库表结构"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            # 创建持仓股票表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS portfolio_stocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    cost_price REAL,
                    quantity INTEGER,
                    note TEXT,
                    auto_monitor BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 创建持仓分析历史表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS portfolio_analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portfolio_stock_id INTEGER NOT NULL,
                    analysis_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    rating TEXT,
                    confidence REAL,
                    current_price REAL,
                    target_price REAL,
                    entry_min REAL,
                    entry_max REAL,
                    take_profit REAL,
                    stop_loss REAL,
                    summary TEXT,
                    FOREIGN KEY (portfolio_stock_id) REFERENCES portfolio_stocks(id) ON DELETE CASCADE
                )
            ''')
            
            # 创建索引以提升查询性能
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_portfolio_analysis_stock_id 
                ON portfolio_analysis_history(portfolio_stock_id)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_portfolio_analysis_time 
                ON portfolio_analysis_history(analysis_time DESC)
            ''')
            
            conn.commit()
            logger.info(f"数据库初始化成功: {self.db_path}")
    
    # ==================== 持仓股票CRUD操作 ====================
    
    def add_stock(self, code: str, name: str, cost_price: Optional[float] = None,
                  quantity: Optional[int] = None, note: str = "", 
                  auto_monitor: bool = True) -> int:
        """添加持仓股票"""
        with self.conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO portfolio_stocks 
                    (code, name, cost_price, quantity, note, auto_monitor, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (code, name, cost_price, quantity, note, auto_monitor, 
                      datetime.now(), datetime.now()))
                conn.commit()
                stock_id = cursor.lastrowid
                logger.info(f"添加持仓股票成功: {code} {name} (ID: {stock_id})")
                return stock_id
            except Exception:
                logger.exception(f"添加持仓股票失败: {code} {name}")
                raise
    
    def update_stock(self, stock_id: int, **kwargs) -> bool:
        """更新持仓股票信息"""
        with self.conn() as conn:
            cursor = conn.cursor()
            allowed_fields = ['code', 'name', 'cost_price', 'quantity', 'note', 'auto_monitor']
            update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
            if not update_fields:
                return False
            update_fields['updated_at'] = datetime.now()
            set_clause = ', '.join([f"{field} = ?" for field in update_fields.keys()])
            values = list(update_fields.values()) + [stock_id]
            cursor.execute(f'UPDATE portfolio_stocks SET {set_clause} WHERE id = ?', values)
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_stock(self, stock_id: int) -> bool:
        """删除持仓股票"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM portfolio_stocks WHERE id = ?', (stock_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_stock(self, stock_id: int) -> Optional[Dict]:
        """获取单只持仓股票信息"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, code, name, cost_price, quantity, note, auto_monitor, created_at, updated_at 
                FROM portfolio_stocks WHERE id = ?
            ''', (stock_id,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0], 'code': row[1], 'name': row[2], 'cost_price': row[3],
                    'quantity': row[4], 'note': row[5], 'auto_monitor': bool(row[6]),
                    'created_at': row[7], 'updated_at': row[8]
                }
            return None
    
    def get_stock_by_code(self, code: str) -> Optional[Dict]:
        """根据股票代码获取持仓股票信息"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, code, name, cost_price, quantity, note, auto_monitor, created_at, updated_at 
                FROM portfolio_stocks WHERE code = ?
            ''', (code,))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0], 'code': row[1], 'name': row[2], 'cost_price': row[3],
                    'quantity': row[4], 'note': row[5], 'auto_monitor': bool(row[6]),
                    'created_at': row[7], 'updated_at': row[8]
                }
            return None
    
    def get_all_stocks(self, auto_monitor_only: bool = False) -> List[Dict]:
        """获取所有持仓股票列表"""
        with self.conn() as conn:
            cursor = conn.cursor()
            if auto_monitor_only:
                cursor.execute('''
                    SELECT id, code, name, cost_price, quantity, note, auto_monitor, created_at, updated_at 
                    FROM portfolio_stocks WHERE auto_monitor = 1 ORDER BY created_at DESC
                ''')
            else:
                cursor.execute('''
                    SELECT id, code, name, cost_price, quantity, note, auto_monitor, created_at, updated_at 
                    FROM portfolio_stocks ORDER BY created_at DESC
                ''')
            rows = cursor.fetchall()
            return [{
                'id': r[0], 'code': r[1], 'name': r[2], 'cost_price': r[3],
                'quantity': r[4], 'note': r[5], 'auto_monitor': bool(r[6]),
                'created_at': r[7], 'updated_at': r[8]
            } for r in rows]
    
    def save_analysis(self, stock_id: int, rating: str, confidence: float,
                     current_price: float, target_price: Optional[float] = None,
                     entry_min: Optional[float] = None, entry_max: Optional[float] = None,
                     take_profit: Optional[float] = None, stop_loss: Optional[float] = None,
                     summary: str = "") -> int:
        """保存分析历史记录"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO portfolio_analysis_history 
                (portfolio_stock_id, analysis_time, rating, confidence, current_price,
                 target_price, entry_min, entry_max, take_profit, stop_loss, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (stock_id, datetime.now(), rating, confidence, current_price,
                  target_price, entry_min, entry_max, take_profit, stop_loss, summary))
            conn.commit()
            return cursor.lastrowid
    
    def get_analysis_history(self, stock_id: int, limit: int = 10) -> List[Dict]:
        """获取股票的分析历史记录"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, portfolio_stock_id, analysis_time, rating, confidence, current_price,
                       target_price, entry_min, entry_max, take_profit, stop_loss, summary
                FROM portfolio_analysis_history WHERE portfolio_stock_id = ?
                ORDER BY analysis_time DESC LIMIT ?
            ''', (stock_id, limit))
            rows = cursor.fetchall()
            return [{
                'id': r[0], 'portfolio_stock_id': r[1], 'analysis_time': r[2], 'rating': r[3],
                'confidence': r[4], 'current_price': r[5], 'target_price': r[6], 'entry_min': r[7],
                'entry_max': r[8], 'take_profit': r[9], 'stop_loss': r[10], 'summary': r[11]
            } for r in rows]

    def get_latest_analysis_history(self, stock_id: int, limit: int = 10) -> List[Dict]:
        """获取股票的最新分析历史记录（get_analysis_history 的别名，保持兼容）"""
        return self.get_analysis_history(stock_id, limit)

    def get_latest_analysis(self, stock_id: int) -> Optional[Dict]:
        """获取股票的最新一次分析记录，不存在返回 None"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, portfolio_stock_id, analysis_time, rating, confidence, current_price,
                       target_price, entry_min, entry_max, take_profit, stop_loss, summary
                FROM portfolio_analysis_history WHERE portfolio_stock_id = ?
                ORDER BY analysis_time DESC LIMIT 1
            ''', (stock_id,))
            r = cursor.fetchone()
            if r:
                return {
                    'id': r[0], 'portfolio_stock_id': r[1], 'analysis_time': r[2], 'rating': r[3],
                    'confidence': r[4], 'current_price': r[5], 'target_price': r[6], 'entry_min': r[7],
                    'entry_max': r[8], 'take_profit': r[9], 'stop_loss': r[10], 'summary': r[11]
                }
            return None

    def search_stocks(self, keyword: str) -> List[Dict]:
        """搜索持仓股票（按代码或名称模糊匹配）"""
        with self.conn() as conn:
            cursor = conn.cursor()
            pattern = f"%{keyword}%"
            cursor.execute('''
                SELECT id, code, name, cost_price, quantity, note, auto_monitor, created_at, updated_at
                FROM portfolio_stocks
                WHERE code LIKE ? OR name LIKE ?
                ORDER BY created_at DESC
            ''', (pattern, pattern))
            rows = cursor.fetchall()
            return [{
                'id': r[0], 'code': r[1], 'name': r[2], 'cost_price': r[3],
                'quantity': r[4], 'note': r[5], 'auto_monitor': bool(r[6]),
                'created_at': r[7], 'updated_at': r[8]
            } for r in rows]

    def get_stock_count(self) -> int:
        """获取持仓股票总数"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM portfolio_stocks')
            return cursor.fetchone()[0]

    def get_rating_changes(self, stock_id: int, days: int = 30) -> List[Tuple[str, str, str]]:
        """获取指定天数内的评级变化列表 [(时间, 旧评级, 新评级), ...]"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT analysis_time, rating
                FROM portfolio_analysis_history
                WHERE portfolio_stock_id = ?
                AND analysis_time >= datetime('now', '-' || ? || ' days')
                ORDER BY analysis_time ASC
            ''', (stock_id, days))
            rows = cursor.fetchall()
            changes = []
            for i in range(1, len(rows)):
                prev_rating = rows[i - 1][1]
                curr_rating = rows[i][1]
                if prev_rating != curr_rating:
                    changes.append((rows[i][0], prev_rating, curr_rating))
            return changes

    def get_all_latest_analysis(self) -> List[Dict]:
        """获取所有持仓股票及其最新一次分析记录（LEFT JOIN，无分析的股票分析字段为 None）"""
        with self.conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    s.*,
                    h.rating, h.confidence, h.current_price, h.target_price,
                    h.entry_min, h.entry_max, h.take_profit, h.stop_loss,
                    h.analysis_time
                FROM portfolio_stocks s
                LEFT JOIN (
                    SELECT h1.*
                    FROM portfolio_analysis_history h1
                    INNER JOIN (
                        SELECT portfolio_stock_id, MAX(analysis_time) as max_time
                        FROM portfolio_analysis_history
                        GROUP BY portfolio_stock_id
                    ) h2
                    ON h1.portfolio_stock_id = h2.portfolio_stock_id
                    AND h1.analysis_time = h2.max_time
                ) h ON s.id = h.portfolio_stock_id
                ORDER BY s.created_at DESC
            ''')
            return [dict(row) for row in cursor.fetchall()]

# 全局实例
portfolio_db = PortfolioDB()
