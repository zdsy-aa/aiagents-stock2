import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from base_db import BaseDatabase

logger = logging.getLogger(__name__)


class StockMonitorDatabase(BaseDatabase):
    """股票监测数据库管理类"""
    
    def __init__(self, db_path: str = "stock_monitor.db"):
        super().__init__(db_path)
    
    def init_tables(self):
        """初始化数据库表结构"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            # 创建监测股票表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS monitored_stocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    entry_range TEXT NOT NULL,  -- JSON格式: {"min": 10.0, "max": 12.0}
                    take_profit REAL,
                    stop_loss REAL,
                    current_price REAL,
                    last_checked TIMESTAMP,
                    check_interval INTEGER DEFAULT 30,  -- 分钟
                    notification_enabled BOOLEAN DEFAULT TRUE,
                    trading_hours_only BOOLEAN DEFAULT TRUE,  -- 仅交易时段监控
                    quant_enabled BOOLEAN DEFAULT FALSE,  -- 量化交易开关
                    quant_config TEXT,  -- 量化配置JSON
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 添加复合索引以优化查询性能 (P0 整改三)
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_monitored_stocks_symbol_rating ON monitored_stocks(symbol, rating)')
            
            # 检查并添加trading_hours_only字段（兼容已有数据库）
            try:
                cursor.execute("SELECT trading_hours_only FROM monitored_stocks LIMIT 1")
            except Exception:
                cursor.execute("ALTER TABLE monitored_stocks ADD COLUMN trading_hours_only BOOLEAN DEFAULT TRUE")
                logger.info("已添加trading_hours_only字段")
            
            # 创建价格历史表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_id INTEGER,
                    price REAL NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (stock_id) REFERENCES monitored_stocks (id)
                )
            ''')
            
            # 添加索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_history_stock_id_time ON price_history(stock_id, timestamp)')
            
            # 创建提醒记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_id INTEGER,
                    type TEXT NOT NULL,  -- entry/take_profit/stop_loss
                    message TEXT NOT NULL,
                    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (stock_id) REFERENCES monitored_stocks (id)
                )
            ''')
            
            # 添加索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifications_stock_id_type ON notifications(stock_id, type)')
            
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
    
    def add_monitored_stock(self, symbol: str, name: str, rating: str, 
                           entry_range: Dict, take_profit: float, 
                           stop_loss: float, check_interval: int = 30, 
                           notification_enabled: bool = True,
                           trading_hours_only: bool = True,
                           quant_enabled: bool = False,
                           quant_config: Dict = None) -> int:
        """添加监测股票"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            quant_config_json = json.dumps(quant_config) if quant_config else None
            
            cursor.execute('''
                INSERT INTO monitored_stocks 
                (symbol, name, rating, entry_range, take_profit, stop_loss, check_interval, 
                 notification_enabled, trading_hours_only, quant_enabled, quant_config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (symbol, name, rating, json.dumps(entry_range), take_profit, stop_loss, 
                  check_interval, notification_enabled, trading_hours_only, quant_enabled, quant_config_json))
            
            stock_id = cursor.lastrowid
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
            return stock_id
    
    def get_monitored_stocks(self) -> List[Dict]:
        """获取所有监测股票"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, symbol, name, rating, entry_range, take_profit, stop_loss, 
                       current_price, last_checked, check_interval, notification_enabled,
                       trading_hours_only, quant_enabled, quant_config, created_at, updated_at
                FROM monitored_stocks
                ORDER BY created_at DESC
            ''')
            
            stocks = []
            for row in cursor.fetchall():
                try:
                    quant_config = json.loads(row[13]) if row[13] else None
                    entry_range = json.loads(row[4]) if row[4] else None
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"股票 {row[1]} 的JSON解析失败: {e}")
                    entry_range = None
                    quant_config = None
                    
                stocks.append({
                    'id': row[0],
                    'symbol': row[1],
                    'name': row[2],
                    'rating': row[3],
                    'entry_range': entry_range,
                    'take_profit': row[5],
                    'stop_loss': row[6],
                    'current_price': row[7],
                    'last_checked': row[8],
                    'check_interval': row[9],
                    'notification_enabled': bool(row[10]),
                    'trading_hours_only': bool(row[11]) if row[11] is not None else True,
                    'quant_enabled': bool(row[12]),
                    'quant_config': quant_config,
                    'created_at': row[14],
                    'updated_at': row[15]
                })
        
        return stocks
    
    def update_stock_price(self, stock_id: int, price: float):
        """更新股票价格 (P2 整改十一: 自动清理)"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            # 更新当前价格
            cursor.execute('''
                UPDATE monitored_stocks 
                SET current_price = ?, last_checked = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (price, stock_id))
            
            # 记录价格历史
            cursor.execute('''
                INSERT INTO price_history (stock_id, price)
                VALUES (?, ?)
            ''', (stock_id, price))
            
            # P2 整改十一: 定期清理 price_history 旧数据（保留30天）
            self.cleanup_old_data('price_history', days=30, time_column='timestamp')
            
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
    
    def update_last_checked(self, stock_id: int):
        """仅更新最后检查时间（用于获取失败的情况）"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE monitored_stocks 
                SET last_checked = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (stock_id,))
            
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
    
    def has_recent_notification(self, stock_id: int, notification_type: str, minutes: int = 60) -> bool:
        """检查是否在最近X分钟内已有相同类型的通知"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT COUNT(*) FROM notifications
                WHERE stock_id = ? AND type = ?
                AND datetime(triggered_at) > datetime('now', '-' || ? || ' minutes')
            ''', (stock_id, notification_type, minutes))
            
            count = cursor.fetchone()[0]
        
        return count > 0
    
    def add_notification(self, stock_id: int, notification_type: str, message: str):
        """添加提醒记录"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO notifications (stock_id, type, message)
                VALUES (?, ?, ?)
            ''', (stock_id, notification_type, message))
            
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
    
    def get_pending_notifications(self) -> List[Dict]:
        """获取待发送的提醒"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT n.id, n.stock_id, s.symbol, s.name, n.type, n.message, n.triggered_at
                FROM notifications n
                JOIN monitored_stocks s ON n.stock_id = s.id
                WHERE n.sent = FALSE
                ORDER BY n.triggered_at
            ''')
            
            notifications = []
            for row in cursor.fetchall():
                notifications.append({
                    'id': row[0],
                    'stock_id': row[1],
                    'symbol': row[2],
                    'name': row[3],
                    'type': row[4],
                    'message': row[5],
                    'triggered_at': row[6]
                })
        
        return notifications
    
    def get_all_recent_notifications(self, limit: int = 10) -> List[Dict]:
        """获取最近的所有通知（包括已发送和未发送的）"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT n.id, n.stock_id, s.symbol, s.name, n.type, n.message, n.triggered_at, n.sent
                FROM notifications n
                JOIN monitored_stocks s ON n.stock_id = s.id
                ORDER BY n.triggered_at DESC
                LIMIT ?
            ''', (limit,))
            
            notifications = []
            for row in cursor.fetchall():
                notifications.append({
                    'id': row[0],
                    'stock_id': row[1],
                    'symbol': row[2],
                    'name': row[3],
                    'type': row[4],
                    'message': row[5],
                    'triggered_at': row[6],
                    'sent': bool(row[7])
                })
        
        return notifications
    
    def mark_notification_sent(self, notification_id: int):
        """标记提醒已发送"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE notifications SET sent = TRUE WHERE id = ?
            ''', (notification_id,))
            
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
    
    def mark_all_notifications_sent(self):
        """标记所有通知为已读"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('UPDATE notifications SET sent = TRUE WHERE sent = FALSE')
            
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
            return cursor.rowcount
    
    def clear_all_notifications(self):
        """清空所有通知"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM notifications')
            
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
            return cursor.rowcount
    
    def remove_monitored_stock(self, stock_id: int):
        """移除监测股票"""
        try:
            with self.conn() as conn:
                cursor = conn.cursor()
                
                # 删除相关记录
                cursor.execute('DELETE FROM price_history WHERE stock_id = ?', (stock_id,))
                cursor.execute('DELETE FROM notifications WHERE stock_id = ?', (stock_id,))
                cursor.execute('DELETE FROM monitored_stocks WHERE id = ?', (stock_id,))
                
                affected_rows = cursor.rowcount
                # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
                return affected_rows > 0
        except Exception:
            logger.exception("删除股票失败")
            return False
    
    def update_monitored_stock(self, stock_id: int, rating: str, entry_range: Dict, 
                              take_profit: float, stop_loss: float, 
                              check_interval: int, notification_enabled: bool,
                              trading_hours_only: bool = None,
                              quant_enabled: bool = None,
                              quant_config: Dict = None):
        """更新监测股票"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            if quant_enabled is not None and quant_config is not None:
                quant_config_json = json.dumps(quant_config) if quant_config else None
                trading_hours_sql = ", trading_hours_only = ?" if trading_hours_only is not None else ""
                params = [rating, json.dumps(entry_range), take_profit, stop_loss, 
                          check_interval, notification_enabled, quant_enabled, quant_config_json]
                if trading_hours_only is not None:
                    params.append(trading_hours_only)
                params.append(stock_id)
                
                cursor.execute(f'''
                    UPDATE monitored_stocks 
                    SET rating = ?, entry_range = ?, take_profit = ?, stop_loss = ?, 
                        check_interval = ?, notification_enabled = ?, 
                        quant_enabled = ?, quant_config = ?{trading_hours_sql},
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', tuple(params))
            else:
                trading_hours_sql = ", trading_hours_only = ?" if trading_hours_only is not None else ""
                params = [rating, json.dumps(entry_range), take_profit, stop_loss, check_interval, notification_enabled]
                if trading_hours_only is not None:
                    params.append(trading_hours_only)
                params.append(stock_id)
                
                cursor.execute(f'''
                    UPDATE monitored_stocks 
                    SET rating = ?, entry_range = ?, take_profit = ?, stop_loss = ?, 
                        check_interval = ?, notification_enabled = ?{trading_hours_sql}, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', tuple(params))
            
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
            return cursor.rowcount > 0
    
    def toggle_notification(self, stock_id: int, enabled: bool):
        """切换通知状态"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE monitored_stocks 
                SET notification_enabled = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (enabled, stock_id))
            
            # P2 整改十: BaseDatabase 已实现自动 commit，此处可移除手动调用
            return cursor.rowcount > 0

# P3 整改十八: 延迟加载单例
_monitor_db_instance = None
def get_monitor_db():
    global _monitor_db_instance
    if _monitor_db_instance is None:
        _monitor_db_instance = StockMonitorDatabase()
    return _monitor_db_instance

# 为了兼容旧代码，保留 monitor_db 变量，但改为动态获取
class MonitorDBProxy:
    def __getattr__(self, name):
        return getattr(get_monitor_db(), name)

monitor_db = MonitorDBProxy()
