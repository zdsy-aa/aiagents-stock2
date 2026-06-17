"""
智策板块数据采集模块
使用AKShare获取板块相关数据
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import warnings
import time
import threading
import logging
import os
from dotenv import load_dotenv
from sector_strategy_db import SectorStrategyDatabase

# 财经新闻抓取每源超时(秒)：新闻是 AI 的次要输入，源抽风时(akshare 无超时可挂起 ~8min/次)
# 不应拖死整个智策任务，超时即视为空新闻继续。
NEWS_FETCH_TIMEOUT = 30


def _call_with_timeout(func, timeout_sec):
    """在 daemon 线程跑 func，超时或异常返回 None。

    超时时挂起线程为 daemon，不阻塞进程退出（批处理结束即回收）；
    用于给无超时的第三方抓取(akshare)套一层硬上限。
    """
    box = {}

    def _run():
        try:
            box["v"] = func()
        except Exception:
            box["v"] = None

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_sec)
    return box.get("v")


def _try_sources(sources):
    """按序尝试 (label, callable, timeout_sec)，第一个返回非空(非 None、非空 DataFrame/dict/list)即用。

    每源用 _call_with_timeout 套硬超时；异常/超时/空 → 试下一个；全失败返回 None。
    """
    import logging as _lg
    log = _lg.getLogger(__name__)
    for label, fn, timeout_sec in sources:
        r = _call_with_timeout(fn, timeout_sec)
        empty = (r is None) or (hasattr(r, "empty") and r.empty) or \
                (isinstance(r, (dict, list)) and len(r) == 0)
        if not empty:
            log.info("    [多源] 命中: %s", label)
            return r
        log.info("    [多源] 跳过(空/超时): %s", label)
    return None


def _breadth_from_spot(df):
    """全A快照 df(含'涨跌幅'列) -> 涨跌家数/涨停跌停 统计 dict。"""
    out = {}
    if df is None or df.empty or "涨跌幅" not in df.columns:
        out["total_stocks"] = 0
        return out
    pct = pd.to_numeric(df["涨跌幅"], errors="coerce").dropna()
    total = len(pct)
    up = int((pct > 0).sum()); down = int((pct < 0).sum()); flat = total - up - down
    out.update({
        "total_stocks": total, "up_count": up, "down_count": down, "flat_count": flat,
        "up_ratio": round(up / total * 100, 2) if total else 0,
        "limit_up": int((pct >= 9.5).sum()), "limit_down": int((pct <= -9.5).sum()),
    })
    return out


def _parse_tencent_index(raw_text):
    """腾讯 qt.gtimg 指数报文 -> {code: {close, change_pct, change}}。
    每行 v_xxx="名称~代码~最新价~...~涨跌额~涨跌幅~..."；f[1]名 f[2]码 f[3]最新 f[31]涨跌额 f[32]涨跌幅。"""
    out = {}
    for line in str(raw_text).strip().split("\n"):
        if "~" not in line or '="' not in line:
            continue
        try:
            payload = line.split('="', 1)[1].rstrip('";')
            f = payload.split("~")
            if len(f) <= 32:
                continue
            out[f[2]] = {"close": float(f[3]), "change": float(f[31]), "change_pct": float(f[32])}
        except (ValueError, IndexError):
            continue
    return out


logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

warnings.filterwarnings('ignore')


class SectorStrategyDataFetcher:
    """板块策略数据获取类"""
    
    def __init__(self):
        logger.info("[智策] 板块数据获取器初始化...")
        self.max_retries = 3  # 最大重试次数
        self.retry_delay = 2  # 重试延迟（秒）
        self.request_delay = 1  # 请求间隔（秒）
        
        # 初始化数据库和日志
        self.database = SectorStrategyDatabase()
        self.logger = logging.getLogger(__name__)
        
        # 配置日志
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def _safe_request(self, func, *args, **kwargs):
        """安全的请求函数，包含重试机制"""
        for attempt in range(self.max_retries):
            try:
                result = func(*args, **kwargs)
                # 添加请求延迟，避免请求过快
                time.sleep(self.request_delay)
                return result
            except Exception as e:
                if attempt < self.max_retries - 1:
                    logger.error(f"    请求失败，{self.retry_delay}秒后重试... (尝试 {attempt + 1}/{self.max_retries})")
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"    请求失败，已达最大重试次数: {e}")
                    raise e
    
    def get_all_sector_data(self):
        """
        获取所有板块的综合数据
        
        Returns:
            dict: 包含多个维度的板块数据
        """
        logger.info("[智策] 开始获取板块综合数据...")
        
        data = {
            "success": False,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "sectors": {},
            "sector_fund_flow": {},
            "market_overview": {},
            "north_flow": {},
            "news": []
        }
        
        try:
            # 1. 获取行业板块数据
            logger.info("  [1/6] 获取行业板块行情...")
            sectors_data = self._get_sector_performance()
            if sectors_data:
                data["sectors"] = sectors_data
                logger.info(f"    ✓ 成功获取 {len(sectors_data)} 个行业板块数据")
            
            # 2. 获取概念板块数据
            logger.info("  [2/6] 获取概念板块行情...")
            concept_data = self._get_concept_performance()
            if concept_data:
                data["concepts"] = concept_data
                logger.info(f"    ✓ 成功获取 {len(concept_data)} 个概念板块数据")
            
            # 3. 获取板块资金流向
            logger.info("  [3/6] 获取行业资金流向...")
            fund_flow_data = self._get_sector_fund_flow()
            if fund_flow_data:
                data["sector_fund_flow"] = fund_flow_data
                logger.info(f"    ✓ 成功获取资金流向数据")
            
            # 4. 获取市场总体情况
            logger.info("  [4/6] 获取市场总体情况...")
            market_data = self._get_market_overview()
            if market_data:
                data["market_overview"] = market_data
                logger.info(f"    ✓ 成功获取市场概况")
            
            # 5. 获取北向资金流向
            logger.info("  [5/6] 获取北向资金流向...")
            north_flow = self._get_north_money_flow()
            if north_flow:
                data["north_flow"] = north_flow
                logger.info(f"    ✓ 成功获取北向资金数据")
            
            # 6. 获取财经新闻
            logger.info("  [6/6] 获取财经新闻...")
            news_data = self._get_financial_news()
            if news_data:
                data["news"] = news_data
                logger.info(f"    ✓ 成功获取 {len(news_data)} 条新闻")
            
            data["success"] = True
            logger.info("[智策] ✓ 板块数据获取完成！")
            
            # 保存原始数据到数据库
            self._save_raw_data_to_db(data)
            
        except Exception as e:
            logger.error(f"[智策] ✗ 数据获取出错: {e}")
            data["error"] = str(e)
        
        return data
    
    def _get_sector_performance(self):
        """获取行业板块表现（同花顺源优先，避开东财反爬；东财兜底）"""
        try:
            # 主源：同花顺行业资金流（含 行业/涨跌幅/领涨股/净额，走 10jqka 不碰东财 push2）
            df = self._safe_request(ak.stock_fund_flow_industry, symbol="即时")
            if df is not None and not df.empty and '行业' in df.columns:
                sectors = {}
                for row in df.to_dict('records'):
                    name = row.get('行业', '')
                    if name:
                        sectors[name] = {
                            "name": name,
                            "change_pct": row.get('行业-涨跌幅', 0),
                            "turnover": 0,            # 同花顺该接口无换手率
                            "total_market_cap": 0,    # 同花顺该接口无总市值
                            "top_stock": row.get('领涨股', ''),
                            "top_stock_change": row.get('领涨股-涨跌幅', 0),
                            "up_count": 0,            # 同花顺该接口无涨跌家数
                            "down_count": 0
                        }
                return sectors

            # 兜底：东财行业板块（当前受反爬，多半失败）
            df = self._safe_request(ak.stock_board_industry_name_em)
            if df is None or df.empty:
                return {}
            sectors = {}
            for row in df.to_dict('records'):  # to_dict 比 iterrows 快 ~10-30x，语义等价
                sector_name = row.get('板块名称', '')
                if sector_name:
                    sectors[sector_name] = {
                        "name": sector_name,
                        "change_pct": row.get('涨跌幅', 0),
                        "turnover": row.get('换手率', 0),
                        "total_market_cap": row.get('总市值', 0),
                        "top_stock": row.get('领涨股票', ''),
                        "top_stock_change": row.get('领涨股票涨跌幅', 0),
                        "up_count": row.get('上涨家数', 0),
                        "down_count": row.get('下跌家数', 0)
                    }
            return sectors

        except Exception as e:
            logger.error(f"    获取行业板块数据失败: {e}")
            return {}
    
    def _get_concept_performance(self):
        """获取概念板块表现（同花顺源优先，避开东财反爬；东财兜底）"""
        try:
            # 主源：同花顺概念资金流（含 概念名/涨跌幅/领涨股/净额，列名沿用「行业」）
            df = self._safe_request(ak.stock_fund_flow_concept, symbol="即时")
            if df is not None and not df.empty and '行业' in df.columns:
                concepts = {}
                for row in df.to_dict('records'):
                    name = row.get('行业', '')
                    if name:
                        concepts[name] = {
                            "name": name,
                            "change_pct": row.get('行业-涨跌幅', 0),
                            "turnover": 0,
                            "total_market_cap": 0,
                            "top_stock": row.get('领涨股', ''),
                            "top_stock_change": row.get('领涨股-涨跌幅', 0),
                            "up_count": 0,
                            "down_count": 0
                        }
                return concepts

            # 兜底：东财概念板块（当前受反爬，多半失败）
            df = self._safe_request(ak.stock_board_concept_name_em)
            if df is None or df.empty:
                return {}
            concepts = {}
            for row in df.to_dict('records'):  # to_dict 比 iterrows 快 ~10-30x，语义等价
                concept_name = row.get('板块名称', '')
                if concept_name:
                    concepts[concept_name] = {
                        "name": concept_name,
                        "change_pct": row.get('涨跌幅', 0),
                        "turnover": row.get('换手率', 0),
                        "total_market_cap": row.get('总市值', 0),
                        "top_stock": row.get('领涨股票', ''),
                        "top_stock_change": row.get('领涨股票涨跌幅', 0),
                        "up_count": row.get('上涨家数', 0),
                        "down_count": row.get('下跌家数', 0)
                    }
            return concepts

        except Exception as e:
            logger.error(f"    获取概念板块数据失败: {e}")
            return {}
    
    def _get_sector_fund_flow(self):
        """获取行业资金流向（同花顺源优先，避开东财反爬；东财兜底）"""
        try:
            fund_flow = {
                "today": [],
                "update_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            # 主源：同花顺行业资金流（净额单位「亿」，×10000 转「万」对齐下游展示）
            df = self._safe_request(ak.stock_fund_flow_industry, symbol="即时")
            if df is not None and not df.empty and '行业' in df.columns:
                df = df.sort_values('净额', ascending=False) if '净额' in df.columns else df
                for row in df.head(50).to_dict('records'):
                    net = row.get('净额', 0) or 0
                    fund_flow["today"].append({
                        "sector": row.get('行业', ''),
                        "main_net_inflow": net * 10000,          # 亿 → 万
                        "main_net_inflow_pct": 0,                # 同花顺该接口无净占比
                        "super_large_net_inflow": 0,            # 同花顺该接口无单类细分
                        "large_net_inflow": 0,
                        "medium_net_inflow": 0,
                        "small_net_inflow": 0,
                        "change_pct": row.get('行业-涨跌幅', 0)
                    })
                return fund_flow

            # 兜底：东财行业资金流（当前受反爬，多半失败）
            df = self._safe_request(ak.stock_sector_fund_flow_rank, indicator="今日")
            if df is None or df.empty:
                return {}
            for idx, row in df.head(50).iterrows():  # 取前50个
                fund_flow["today"].append({
                    "sector": row.get('名称', ''),
                    "main_net_inflow": row.get('今日主力净流入-净额', 0),
                    "main_net_inflow_pct": row.get('今日主力净流入-净占比', 0),
                    "super_large_net_inflow": row.get('今日超大单净流入-净额', 0),
                    "large_net_inflow": row.get('今日大单净流入-净额', 0),
                    "medium_net_inflow": row.get('今日中单净流入-净额', 0),
                    "small_net_inflow": row.get('今日小单净流入-净额', 0),
                    "change_pct": row.get('今日涨跌幅', 0)
                })

            return fund_flow

        except Exception as e:
            logger.error(f"    获取行业资金流向失败: {e}")
            return {}
    
    _INDEX_MAP = [("sh_index", "000001", "上证指数"),
                  ("sz_index", "399001", "深证成指"),
                  ("cyb_index", "399006", "创业板指")]

    def _index_from_tencent(self):
        import urllib.request
        raw = urllib.request.urlopen(
            "https://qt.gtimg.cn/q=sh000001,sz399001,sz399006", timeout=8).read().decode("gbk")
        parsed = _parse_tencent_index(raw)   # {code: {close,change,change_pct}}
        out = {}
        for key, code, name in self._INDEX_MAP:
            if code in parsed:
                out[key] = {"code": code, "name": name, **parsed[code]}
        return out

    def _index_from_sina(self):
        df = ak.stock_zh_index_spot_sina()
        if df is None or df.empty:
            return {}
        out = {}
        for key, code, name in self._INDEX_MAP:
            hit = df[df["名称"] == name]
            if not hit.empty:
                r = hit.iloc[0]
                out[key] = {"code": code, "name": name,
                            "close": float(r.get("最新价", 0)),
                            "change_pct": float(r.get("涨跌幅", 0)),
                            "change": float(r.get("涨跌额", 0))}
        return out

    def _index_from_em(self):
        out = {}
        try:
            df = ak.stock_zh_index_spot_em(symbol="上证系列指数")
        except Exception:
            df = None
        if df is not None and not df.empty and "名称" in df.columns:
            for key, code, name in self._INDEX_MAP:
                hit = df[df["名称"] == name]
                if not hit.empty:
                    r = hit.iloc[0]
                    out[key] = {"code": code, "name": name,
                                "close": float(r.get("最新价", 0)),
                                "change_pct": float(r.get("涨跌幅", 0)),
                                "change": float(r.get("涨跌额", 0))}
        return out

    def _get_index_quotes(self):
        """大盘指数多源链：腾讯(0.3s)→新浪(1.2s)→东财(兜底)。返回 {sh_index,sz_index,cyb_index} 部分/全部。"""
        return _try_sources([
            ("腾讯指数", self._index_from_tencent, 8),
            ("新浪指数", self._index_from_sina, 15),
            ("东财指数", self._index_from_em, 6),
        ]) or {}

    def _get_market_overview(self):
        """获取市场总体情况（涨跌家数多源:新浪→东财；大盘指数多源:腾讯→新浪→东财）。"""
        try:
            overview = {}
            # 涨跌家数/涨停：新浪全A → 东财全A
            spot = _try_sources([
                ("新浪全A", ak.stock_zh_a_spot, 40),
                ("东财全A", ak.stock_zh_a_spot_em, 8),
            ])
            if spot is not None and not spot.empty:
                overview.update(_breadth_from_spot(spot))

            # 大盘指数：腾讯 → 新浪 → 东财
            overview.update(self._get_index_quotes())
            return overview
        except Exception as e:
            logger.error(f"    获取市场概况失败: {e}")
            return {}
    
    def _get_north_money_flow(self):
        """获取北向资金流向（优先使用Tushare，失败时使用Akshare）"""
        # 优先使用Tushare获取沪深港通资金流向
        self.ts_pro = None
        tushare_token = os.getenv('TUSHARE_TOKEN', '')
        try:
            # 初始化Tushare（如果尚未初始化）
            if not hasattr(self, '_tushare_api'):
                TUSHARE_TOKEN = os.getenv('TUSHARE_TOKEN', '')
                if TUSHARE_TOKEN:
                    try:
                        import tushare as ts
                        ts.set_token(tushare_token)
                        self.ts_pro = ts.pro_api()
                        logger.info("    [Tushare] ✅ 初始化成功")
                    except Exception as e:
                        logger.error(f"    [Tushare] 初始化失败: {e}")
                        self._tushare_api = None
                else:
                    logger.info("    [Tushare] 未配置Token")
                    self._tushare_api = None
            
            
            # 如果Tushare可用，获取数据
            if hasattr(self, '_tushare_api') and self._tushare_api:
                logger.info("    [Tushare] 正在获取沪深港通资金流向...")
                
                # 获取最近30天的数据
                end_date = datetime.now()
                start_date = end_date - timedelta(days=20)
                
                df = self._tushare_api.moneyflow_hsgt(
                    start_date=start_date.strftime('%Y%m%d'),
                    end_date=end_date.strftime('%Y%m%d')
                )
                
                if df is not None and not df.empty:
                    logger.info("    [Tushare] ✅ 成功获取数据")
                    
                    # 按日期降序排列，获取最新数据
                    df = df.sort_values('trade_date', ascending=False)
                    latest = df.iloc[0]
                    
                    # 转换数据格式以匹配原有结构
                    north_flow = {
                        "date": str(latest['trade_date']),
                        "north_net_inflow": float(latest['north_money']),
                        "hgt_net_inflow": float(latest['hgt']),
                        "sgt_net_inflow": float(latest['sgt']),
                        "north_total_amount": float(latest['north_money'])  # Tushare没有总成交金额，使用净流入作为近似值
                    }
                    
                    # 获取历史趋势（最近20天）
                    history = []
                    for idx, row in df.head(20).iterrows():
                        history.append({
                            "date": str(row['trade_date']),
                            "net_inflow": float(row['north_money'])
                        })
                    north_flow["history"] = history
                    
                    return north_flow
                else:
                    logger.error("    [Tushare] ❌ 未获取到数据")
            else:
                logger.info("    [Tushare] 不可用")
        except Exception as e:
            logger.error(f"    [Tushare] 获取北向资金失败: {e}")
        
        # Tushare失败，尝试使用Akshare
        try:
            logger.info("    [Akshare] 正在获取沪深港通资金流向（备用数据源）...")
            df = self._safe_request(ak.stock_hsgt_fund_flow_summary_em)
            
            if df is not None and not df.empty:
                logger.info("    [Akshare] ✅ 成功获取数据")
                
                # 获取最新数据
                latest = df.iloc[0]
                
                north_flow = {
                    "date": str(latest.get('日期', '')),
                    "north_net_inflow": latest.get('北向资金-成交净买额', 0),
                    "hgt_net_inflow": latest.get('沪股通-成交净买额', 0),
                    "sgt_net_inflow": latest.get('深股通-成交净买额', 0),
                    "north_total_amount": latest.get('北向资金-成交金额', 0)
                }
                
                # 获取历史趋势（最近20天）
                history = []
                for idx, row in df.head(20).iterrows():
                    history.append({
                        "date": str(row.get('日期', '')),
                        "net_inflow": row.get('北向资金-成交净买额', 0)
                    })
                north_flow["history"] = history
                
                return north_flow
            else:
                logger.error("    [Akshare] ❌ 未获取到数据")
        except Exception as e:
            logger.error(f"    [Akshare] 获取北向资金失败: {e}")
        
        # 所有数据源都失败
        logger.error("    ❌ 所有数据源均获取失败")
        return {}
    
    def _get_financial_news(self):
        """获取财经新闻

        说明：原用 ak.stock_news_em(symbol="全球") 在 akshare 1.18+ 上会触发内部
        "Invalid regular expression: \\u" 错误（且 stock_news_em 实为个股新闻接口，
        传 "全球" 用法不当）。改用 stock_info_global_cls（财联社全球电报）作为主源，
        东财全球快讯 stock_info_global_em 作为备源，均带接口存在性防御。
        """
        # 主源：财联社全球电报（列：标题/内容/发布日期/发布时间）
        if hasattr(ak, 'stock_info_global_cls'):
            try:
                df = _call_with_timeout(ak.stock_info_global_cls, NEWS_FETCH_TIMEOUT)
                if df is not None and not df.empty:
                    news_list = []
                    for _, row in df.head(150).iterrows():
                        pub = f"{row.get('发布日期', '')} {row.get('发布时间', '')}".strip()
                        news_list.append({
                            "title": row.get('标题', ''),
                            "content": row.get('内容', ''),
                            "publish_time": pub,
                            "source": "财联社",
                            "url": ''
                        })
                    return news_list
            except Exception as e:
                logger.error(f"    财联社财经新闻获取失败，尝试备源: {e}")

        # 备源：东财全球财经快讯（列：标题/摘要/发布时间/链接）
        if hasattr(ak, 'stock_info_global_em'):
            try:
                df = _call_with_timeout(ak.stock_info_global_em, NEWS_FETCH_TIMEOUT)
                if df is not None and not df.empty:
                    news_list = []
                    for _, row in df.head(150).iterrows():
                        news_list.append({
                            "title": row.get('标题', ''),
                            "content": row.get('摘要', '') or row.get('内容', ''),
                            "publish_time": str(row.get('发布时间', '')),
                            "source": "东方财富",
                            "url": row.get('链接', '')
                        })
                    return news_list
            except Exception as e:
                logger.error(f"    获取财经新闻失败: {e}")

        return []
    
    def format_data_for_ai(self, data):
        """
        将数据格式化为适合AI分析的文本格式
        """
        if not data.get("success"):
            return "数据获取失败"
        
        text_parts = []
        
        # 市场概况
        if data.get("market_overview"):
            market = data["market_overview"]
            text_parts.append(f"""
【市场总体情况】
时间: {data.get('timestamp', 'N/A')}

大盘指数:
""")
            if market.get("sh_index"):
                sh = market["sh_index"]
                text_parts.append(f"  上证指数: {sh['close']} ({sh['change_pct']:+.2f}%)")
            if market.get("sz_index"):
                sz = market["sz_index"]
                text_parts.append(f"  深证成指: {sz['close']} ({sz['change_pct']:+.2f}%)")
            if market.get("cyb_index"):
                cyb = market["cyb_index"]
                text_parts.append(f"  创业板指: {cyb['close']} ({cyb['change_pct']:+.2f}%)")
            
            if market.get("total_stocks"):
                text_parts.append(f"""
市场统计:
  总股票数: {market['total_stocks']}
  上涨: {market['up_count']} ({market['up_ratio']:.1f}%)
  下跌: {market['down_count']}
  平盘: {market['flat_count']}
  涨停: {market['limit_up']}
  跌停: {market['limit_down']}
""")
        
        # 北向资金
        if data.get("north_flow"):
            north = data["north_flow"]
            text_parts.append(f"""
【北向资金流向】
日期: {north.get('date', 'N/A')}
北向资金净流入: {north.get('north_net_inflow', 0):.2f} 万元
  沪股通: {north.get('hgt_net_inflow', 0):.2f} 万元
  深股通: {north.get('sgt_net_inflow', 0):.2f} 万元
""")
        
        # 行业板块表现（前20）
        if data.get("sectors"):
            sectors = data["sectors"]
            sorted_sectors = sorted(sectors.items(), key=lambda x: x[1]["change_pct"], reverse=True)
            
            text_parts.append(f"""
【行业板块表现 TOP20】
涨幅榜前10:
""")
            for name, info in sorted_sectors[:10]:
                text_parts.append(f"  {name}: {info['change_pct']:+.2f}% | 领涨: {info['top_stock']} ({info['top_stock_change']:+.2f}%)")
            
            text_parts.append(f"""
跌幅榜前10:
""")
            for name, info in sorted_sectors[-10:]:
                text_parts.append(f"  {name}: {info['change_pct']:+.2f}% | 领跌: {info['top_stock']} ({info['top_stock_change']:+.2f}%)")
        
        # 概念板块表现（前20）
        if data.get("concepts"):
            concepts = data["concepts"]
            sorted_concepts = sorted(concepts.items(), key=lambda x: x[1]["change_pct"], reverse=True)
            
            text_parts.append(f"""
【概念板块表现 TOP20】
涨幅榜前10:
""")
            for name, info in sorted_concepts[:10]:
                text_parts.append(f"  {name}: {info['change_pct']:+.2f}% | 领涨: {info['top_stock']} ({info['top_stock_change']:+.2f}%)")
        
        # 板块资金流向（前15）
        if data.get("sector_fund_flow") and data["sector_fund_flow"].get("today"):
            flow = data["sector_fund_flow"]["today"]
            
            text_parts.append(f"""
【行业资金流向 TOP15】
主力资金净流入前15:
""")
            sorted_flow = sorted(flow, key=lambda x: x["main_net_inflow"], reverse=True)
            for item in sorted_flow[:15]:
                text_parts.append(f"  {item['sector']}: {item['main_net_inflow']:.2f}万 ({item['main_net_inflow_pct']:+.2f}%) | 涨跌: {item['change_pct']:+.2f}%")
        
        # 重要新闻（前20条）
        if data.get("news"):
            text_parts.append(f"""
【重要财经新闻 TOP20】
""")
            for idx, news in enumerate(data["news"][:20], 1):
                text_parts.append(f"{idx}. [{news['publish_time']}] {news['title']}")
                if news.get('content') and len(news['content']) > 100:
                    text_parts.append(f"   {news['content'][:100]}...")
        else:
            # 新闻抓取失败/超时 → 显式提示，禁止 AI 臆测消息面（防幻觉编造新闻）
            text_parts.append("""
【财经新闻】
本次未获取到财经新闻数据。请仅依据上述量化数据（板块行情/资金流向/北向资金）进行研判，
不要臆测或编造消息面/新闻事件；如需提示消息面风险，仅可笼统说明"本次缺新闻数据，消息面待确认"。
""")

        return "\n".join(text_parts)
    
    def _save_raw_data_to_db(self, data):
        """保存原始数据到数据库"""
        try:
            if not data.get("success"):
                self.logger.warning("[智策数据] 数据获取失败，跳过保存")
                return
            
            # 保存板块数据
            if data.get("sectors"):
                # 将字典转换为DataFrame并映射必要列
                sectors_df = pd.DataFrame([
                    {
                        '板块名称': v.get('name', k),
                        '涨跌幅': v.get('change_pct', 0),
                        '成交额': 0,
                        '总市值': v.get('total_market_cap', 0),
                        '市盈率': v.get('pe_ratio', 0),
                        '市净率': v.get('pb_ratio', 0),
                        '最新价': 0,
                        '成交量': 0,
                        'turnover': v.get('turnover', 0)  # 兼容保存方法中的fallback
                    }
                    for k, v in data["sectors"].items()
                ])
                self.database.save_sector_raw_data(
                    data_date=datetime.now().strftime('%Y-%m-%d'),
                    data_type="industry",
                    data_df=sectors_df
                )
                self.logger.info(f"[智策数据] 保存行业板块数据: {len(data['sectors'])} 个板块")
            
            # 保存概念板块数据
            if data.get("concepts"):
                concepts_df = pd.DataFrame([
                    {
                        '板块名称': v.get('name', k),
                        '涨跌幅': v.get('change_pct', 0),
                        '成交额': 0,
                        '总市值': v.get('total_market_cap', 0),
                        '市盈率': v.get('pe_ratio', 0),
                        '市净率': v.get('pb_ratio', 0),
                        '最新价': 0,
                        '成交量': 0,
                        'turnover': v.get('turnover', 0)
                    }
                    for k, v in data["concepts"].items()
                ])
                self.database.save_sector_raw_data(
                    data_date=datetime.now().strftime('%Y-%m-%d'),
                    data_type="concept",
                    data_df=concepts_df
                )
                self.logger.info(f"[智策数据] 保存概念板块数据: {len(data['concepts'])} 个概念")
            
            # 保存资金流向数据
            if data.get("sector_fund_flow"):
                flow_today = data["sector_fund_flow"].get("today", [])
                fund_df = pd.DataFrame([
                    {
                        '行业': item.get('sector', ''),
                        '主力净流入-净额': item.get('main_net_inflow', 0),
                        '主力净流入-净占比': item.get('main_net_inflow_pct', 0),
                        '超大单净流入-净额': item.get('super_large_net_inflow', 0),
                        '超大单净流入-净占比': item.get('super_large_net_inflow_pct', 0),
                        '大单净流入-净额': item.get('large_net_inflow', 0),
                        '大单净流入-净占比': item.get('large_net_inflow_pct', 0)
                    }
                    for item in flow_today
                ])
                if not fund_df.empty:
                    self.database.save_sector_raw_data(
                        data_date=datetime.now().strftime('%Y-%m-%d'),
                        data_type="fund_flow",
                        data_df=fund_df
                    )
                self.logger.info("[智策数据] 保存资金流向数据")
            
            # 保存市场概况数据
            if data.get("market_overview"):
                market = data["market_overview"]
                mo_df = pd.DataFrame([
                    {'名称': '上证指数', '最新价': market.get('sh_index', {}).get('close', 0), '涨跌幅': market.get('sh_index', {}).get('change_pct', 0), '成交量': market.get('sh_index', {}).get('volume', 0), '成交额': market.get('sh_index', {}).get('turnover', 0)},
                    {'名称': '深证成指', '最新价': market.get('sz_index', {}).get('close', 0), '涨跌幅': market.get('sz_index', {}).get('change_pct', 0), '成交量': market.get('sz_index', {}).get('volume', 0), '成交额': market.get('sz_index', {}).get('turnover', 0)},
                    {'名称': '创业板指', '最新价': market.get('cyb_index', {}).get('close', 0), '涨跌幅': market.get('cyb_index', {}).get('change_pct', 0), '成交量': market.get('cyb_index', {}).get('volume', 0), '成交额': market.get('cyb_index', {}).get('turnover', 0)}
                ])
                self.database.save_sector_raw_data(
                    data_date=datetime.now().strftime('%Y-%m-%d'),
                    data_type="market_overview",
                    data_df=mo_df
                )
                self.logger.info("[智策数据] 保存市场概况数据")
            
            # 保存北向资金数据
            # 注：north_flow结构与原始表不一致，此处暂不保存以避免歧义
            
            # 保存新闻数据
            if data.get("news"):
                self.database.save_news_data(
                    news_list=data["news"],
                    news_date=datetime.now().strftime('%Y-%m-%d'),
                    source="akshare"
                )
                self.logger.info(f"[智策数据] 保存财经新闻: {len(data['news'])} 条")
                
        except Exception as e:
            self.logger.error(f"[智策数据] 保存原始数据失败: {e}")
    
    def get_cached_data_with_fallback(self):
        """获取缓存数据，支持回退机制"""
        try:
            # 首先尝试获取最新数据
            logger.info("[智策] 尝试获取最新数据...")
            fresh_data = self.get_all_sector_data()
            
            if fresh_data.get("success"):
                return fresh_data
            
            # 如果获取失败，回退到缓存数据
            logger.error("[智策] 获取最新数据失败，尝试加载缓存数据...")
            cached_data = self._load_cached_data()
            
            if cached_data:
                logger.info("[智策] ✓ 成功加载缓存数据")
                cached_data["from_cache"] = True
                cached_data["cache_warning"] = "当前显示为缓存数据（24小时内），可能不是最新信息"
                return cached_data
            else:
                logger.info("[智策] ✗ 无可用缓存数据")
                return {
                    "success": False,
                    "error": "无法获取数据且无可用缓存",
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
        except Exception as e:
            self.logger.error(f"[智策数据] 获取数据失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
    
    def _load_cached_data(self):
        """加载缓存数据"""
        try:
            # 获取最近的各类数据
            cached_data = {
                "success": True,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "sectors": {},
                "concepts": {},
                "sector_fund_flow": {},
                "market_overview": {},
                "north_flow": {},
                "news": []
            }
            
            # 加载板块数据
            sectors_data = self.database.get_latest_raw_data("sectors")
            if sectors_data:
                cached_data["sectors"] = sectors_data.get("data_content", {})
            
            # 加载概念数据
            concepts_data = self.database.get_latest_raw_data("concepts")
            if concepts_data:
                cached_data["concepts"] = concepts_data.get("data_content", {})
            
            # 加载资金流向数据
            fund_flow_data = self.database.get_latest_raw_data("fund_flow")
            if fund_flow_data:
                cached_data["sector_fund_flow"] = fund_flow_data.get("data_content", {})
            
            # 加载市场概况数据
            market_data = self.database.get_latest_raw_data("market_overview")
            if market_data:
                cached_data["market_overview"] = market_data.get("data_content", {})
            
            # 加载北向资金数据
            north_data = self.database.get_latest_raw_data("north_flow")
            if north_data:
                cached_data["north_flow"] = north_data.get("data_content", {})
            
            # 加载新闻数据
            news_data = self.database.get_latest_news_data()
            if news_data:
                # 仅传递内容列表给下游分析，避免结构不一致
                cached_data["news"] = news_data.get("data_content", [])
            
            # 检查是否有有效数据
            has_data = any([
                cached_data["sectors"],
                cached_data["concepts"],
                cached_data["sector_fund_flow"],
                cached_data["market_overview"],
                cached_data["north_flow"],
                cached_data["news"]
            ])
            
            return cached_data if has_data else None
            
        except Exception as e:
            self.logger.error(f"[智策数据] 加载缓存数据失败: {e}")
            return None


# 测试函数
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("测试智策板块数据采集模块")
    logger.info("=" * 60)
    
    fetcher = SectorStrategyDataFetcher()
    data = fetcher.get_all_sector_data()
    
    if data.get("success"):
        logger.info("\n" + "=" * 60)
        logger.info("数据采集成功！")
        logger.info("=" * 60)
        
        formatted_text = fetcher.format_data_for_ai(data)
        logger.info(formatted_text[:3000])  # 显示前3000字符
        logger.info(f"\n... (总长度: {len(formatted_text)} 字符)")
    else:
        logger.error(f"\n数据采集失败: {data.get('error', '未知错误')}")

