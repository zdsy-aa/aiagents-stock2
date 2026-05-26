"""
智瞰龙虎数据库模块
用于存储龙虎榜历史数据和分析报告
"""

import json
from datetime import datetime
import pandas as pd
import logging
from base_db import BaseDatabase


class LonghubangDatabase(BaseDatabase):
    """龙虎榜数据库管理类"""
    
    def __init__(self, db_path='longhubang.db'):
        """
        初始化数据库
        
        Args:
            db_path: 数据库文件路径
        """
        # 初始化日志
        self.logger = logging.getLogger(__name__)
        if not self.logger.handlers:
            logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
        super().__init__(db_path)
    
    def init_tables(self):
        """初始化数据库表"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            # 龙虎榜原始数据表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS longhubang_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                youzi_name TEXT,
                yingye_bu TEXT,
                list_type TEXT,
                buy_amount REAL,
                sell_amount REAL,
                net_inflow REAL,
                concepts TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, stock_code, youzi_name, yingye_bu)
            )
            ''')
            
            # 创建索引
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_date ON longhubang_records(date)
            ''')
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_stock_code ON longhubang_records(stock_code)
            ''')
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_youzi_name ON longhubang_records(youzi_name)
            ''')
            cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_net_inflow ON longhubang_records(net_inflow)
            ''')
            
            # AI分析报告表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS longhubang_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_date TEXT NOT NULL,
                data_date_range TEXT,
                analysis_content TEXT,
                recommended_stocks TEXT,
                summary TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # 股票追踪表（记录推荐股票的后续表现）
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id INTEGER,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                recommended_date TEXT,
                recommended_price REAL,
                target_price REAL,
                stop_loss_price REAL,
                current_price REAL,
                profit_loss_pct REAL,
                status TEXT,
                notes TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(analysis_id) REFERENCES longhubang_analysis(id)
            )
            ''')
            
            conn.commit()
            self.logger.info("[智瞰龙虎] 数据库初始化完成")
    
    def save_longhubang_data(self, data_list):
        """
        保存龙虎榜数据
        
        Args:
            data_list: 龙虎榜数据列表
            
        Returns:
            int: 成功保存的记录数
        """
        if not data_list:
            return 0

        # 先构建批量插入的参数元组列表（坏数据按条跳过），再用 executemany 一次性写入
        rows = []
        for record in data_list:
            try:
                rows.append((
                    record.get('rq') or record.get('日期'),
                    record.get('gpdm') or record.get('股票代码'),
                    record.get('gpmc') or record.get('股票名称'),
                    record.get('yzmc') or record.get('游资名称'),
                    record.get('yyb') or record.get('营业部'),
                    record.get('sblx') or record.get('榜单类型'),
                    float(record.get('mrje') or record.get('买入金额') or 0),
                    float(record.get('mcje') or record.get('卖出金额') or 0),
                    float(record.get('jlrje') or record.get('净流入金额') or 0),
                    record.get('gl') or record.get('概念')
                ))
            except Exception:
                self.logger.exception("构建龙虎榜记录失败，跳过该条")
                continue

        if not rows:
            return 0

        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
            INSERT OR REPLACE INTO longhubang_records
            (date, stock_code, stock_name, youzi_name, yingye_bu, list_type,
             buy_amount, sell_amount, net_inflow, concepts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', rows)

        saved_count = len(rows)
        self.logger.info(f"[智瞰龙虎] 成功保存 {saved_count} 条龙虎榜记录")
        return saved_count
    
    def get_longhubang_data(self, start_date=None, end_date=None, stock_code=None):
        """
        查询龙虎榜数据
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            stock_code: 股票代码
            
        Returns:
            pd.DataFrame: 查询结果
        """
        with self.conn() as conn:
            query = "SELECT id, date, stock_code, stock_name, youzi_name, yingye_bu, list_type, buy_amount, sell_amount, net_inflow, concepts, created_at FROM longhubang_records WHERE 1=1"
            params = []
            
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            
            if stock_code:
                query += " AND stock_code = ?"
                params.append(stock_code)
            
            query += " ORDER BY date DESC, net_inflow DESC"
            
            df = pd.read_sql_query(query, conn, params=params)
        
        return df
    
    def get_top_youzi(self, start_date=None, end_date=None, limit=20):
        """
        获取活跃游资排名
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            limit: 返回数量
            
        Returns:
            pd.DataFrame: 游资排名
        """
        with self.conn() as conn:
            query = '''
            SELECT 
                youzi_name,
                COUNT(*) as trade_count,
                SUM(buy_amount) as total_buy,
                SUM(sell_amount) as total_sell,
                SUM(net_inflow) as total_net_inflow
            FROM longhubang_records
            WHERE 1=1
            '''
            
            params = []
            
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            
            query += '''
            GROUP BY youzi_name
            ORDER BY total_net_inflow DESC
            LIMIT ?
            '''
            params.append(limit)
            
            df = pd.read_sql_query(query, conn, params=params)
        
        return df
    
    def get_top_stocks(self, start_date=None, end_date=None, limit=20):
        """
        获取热门股票排名
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            limit: 返回数量
            
        Returns:
            pd.DataFrame: 股票排名
        """
        with self.conn() as conn:
            query = '''
            SELECT 
                stock_code,
                stock_name,
                COUNT(DISTINCT youzi_name) as youzi_count,
                SUM(buy_amount) as total_buy,
                SUM(sell_amount) as total_sell,
                SUM(net_inflow) as total_net_inflow,
                GROUP_CONCAT(DISTINCT concepts) as all_concepts
            FROM longhubang_records
            WHERE 1=1
            '''
            
            params = []
            
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            
            query += '''
            GROUP BY stock_code, stock_name
            ORDER BY total_net_inflow DESC
            LIMIT ?
            '''
            params.append(limit)
            
            df = pd.read_sql_query(query, conn, params=params)
        
        return df
    
    def save_analysis_report(self, data_date_range, analysis_content, 
                           recommended_stocks, summary, full_result=None):
        """
        保存AI分析报告（完整版）
        
        Args:
            data_date_range: 数据日期范围
            analysis_content: 分析内容（JSON字符串或字典）
            recommended_stocks: 推荐股票列表
            summary: 摘要
            full_result: 完整的分析结果字典（可选）
            
        Returns:
            int: 报告ID
        """
        with self.conn() as conn:
            cursor = conn.cursor()
            
            # 如果传入的是字典，转换为JSON字符串
            if isinstance(analysis_content, dict):
                analysis_content = json.dumps(analysis_content, ensure_ascii=False, indent=2)
            
            cursor.execute('''
            INSERT INTO longhubang_analysis 
            (analysis_date, data_date_range, analysis_content, recommended_stocks, summary)
            VALUES (?, ?, ?, ?, ?)
            ''', (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                data_date_range,
                analysis_content,
                json.dumps(recommended_stocks, ensure_ascii=False),
                summary
            ))
            
            report_id = cursor.lastrowid
            conn.commit()
            self.logger.info(f"[智瞰龙虎] 分析报告已保存 (ID: {report_id})")
            return report_id
    
    def get_analysis_reports(self, limit=10):
        """
        获取历史分析报告
        
        Args:
            limit: 返回数量
            
        Returns:
            pd.DataFrame: 报告列表
        """
        with self.conn() as conn:
            query = '''
            SELECT id, analysis_date, data_date_range, analysis_content, recommended_stocks, summary, created_at FROM longhubang_analysis
            ORDER BY created_at DESC
            LIMIT ?
            '''
            
            df = pd.read_sql_query(query, conn, params=[limit])
        
        return df
    
    def get_analysis_report(self, report_id):
        """
        获取单个分析报告详情
        
        Args:
            report_id: 报告ID
            
        Returns:
            dict: 报告详情
        """
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT id, analysis_date, data_date_range, analysis_content, recommended_stocks, summary, created_at FROM longhubang_analysis WHERE id = ?
            ''', (report_id,))
            
            row = cursor.fetchone()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
        
        if row:
            report = dict(zip(columns, row))
            
            # 解析JSON字段
            if report.get('recommended_stocks'):
                try:
                    report['recommended_stocks'] = json.loads(report['recommended_stocks'])
                except Exception as e:
                    self.logger.warning(f"推荐股票JSON解析失败: {e}")
            
            # 解析analysis_content字段
            if report.get('analysis_content'):
                try:
                    report['analysis_content_parsed'] = json.loads(report['analysis_content'])
                except json.JSONDecodeError as e:
                    report['analysis_content_parsed'] = None
                except Exception as e:
                    report['analysis_content_parsed'] = None
            
            return report
        
        return None
    
    def delete_analysis_report(self, report_id):
        """
        删除分析报告
        
        Args:
            report_id: 报告ID
            
        Returns:
            bool: 删除是否成功
        """
        try:
            with self.conn() as conn:
                cursor = conn.cursor()
                # 先删除相关的股票追踪记录
                cursor.execute('DELETE FROM stock_tracking WHERE analysis_id = ?', (report_id,))
                # 删除分析报告
                cursor.execute('DELETE FROM longhubang_analysis WHERE id = ?', (report_id,))
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    self.logger.info(f"[智瞰龙虎] 成功删除分析报告 (ID: {report_id})")
                    return True
                else:
                    self.logger.warning(f"[智瞰龙虎] 未找到要删除的分析报告 (ID: {report_id})")
                    return False
        except Exception as e:
            self.logger.error(f"[智瞰龙虎] 删除分析报告失败: {e}")
            return False
    
    def update_stock_tracking(self, analysis_id, stock_code, current_price, status, notes=None):
        """
        更新股票追踪信息
        
        Args:
            analysis_id: 分析报告ID
            stock_code: 股票代码
            current_price: 当前价格
            status: 状态
            notes: 备注
        """
        with self.conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
            UPDATE stock_tracking
            SET current_price = ?, status = ?, notes = ?, updated_at = ?
            WHERE analysis_id = ? AND stock_code = ?
            ''', (
                current_price,
                status,
                notes,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                analysis_id,
                stock_code
            ))
            
            conn.commit()
            return cursor.rowcount > 0

# 全局数据库实例
longhubang_db = LonghubangDatabase()
