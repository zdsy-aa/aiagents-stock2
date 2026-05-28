import logging
import sys

def setup_logging(level=logging.INFO):
    """统一日志配置 (P2 整改七)"""
    # 如果已经配置过，则不再重复配置
    if logging.getLogger().hasHandlers():
        return
        
    logging.basicConfig(
        level=level,
        format='[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # 降低一些第三方库的日志级别
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
