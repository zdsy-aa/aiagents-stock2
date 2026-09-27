# backtest/engine.py
"""统一回测引擎:ComboSpec 在信号面板上求值,统计训练/测试段指标。

run_backtest(spec, df) -> dict:
    {"name", "n", "wins", "win_rate", "profit_loss_ratio", "avg_ret",
     "max_ret", "max_drawdown", "annual_ret", "trades", "max_consec_loss",
     "ret_std"}

口径注释(与数据基座 3.0 面板口径一致):
- n = trades = 命中行数(即「支持数」,对齐验收与 Top50 JSON 的支持完全一致的依据);
- win_rate = 命中行中「是否盈利」== 1 的占比(标签 NaN 行已在
  load_confirm_panel 剔除,与 mine_confirm 的 m_valid 口径一致);
- avg_ret / max_ret = 命中行「区间涨跌幅」的均值 / 最大值(行内 dropna);
- max_drawdown = 命中行按「信号日期」升序(稳定排序)的 (1+ret).cumprod()
  净值曲线的最大回撤,正值 = 峰值到谷底的相对跌幅(对数空间计算,防面板
  +1996% 级收益的 float64 溢出);
- annual_ret = (1 + avg_ret) ** (250/20) - 1:20 个交易日持仓周期的年化近似
  (250 个交易日/年 ÷ 20 日/周期);1 + avg_ret <= 0 时取 -1(全损);
- profit_loss_ratio = 平均盈利 / 平均亏损(亏损取绝对值);无亏损 -> inf,
  无盈利 -> 0.0,无交易 -> nan;
- max_consec_loss = 命中行按信号日期排序后,连续「未盈利」的最大串长;
- ret_std = 命中行区间涨跌幅的样本标准差(ddof=1;少于 2 行 -> nan);
- n == 0:win_rate/avg_ret/max_ret/max_drawdown/annual_ret 取 0,
  ret_std/profit_loss_ratio 取 nan,max_consec_loss 取 0。

未来函数纪律:引擎只消费面板预计算列(标签/收益/信号布尔),不做任何 shift 回填。
"""
import numpy as np
import pandas as pd

from backtest.combo_engine import eval_combo
from backtest.dataio import LABEL_COL, RET_COL

DATE_COL = "信号日期"
HOLD_DAYS = 20
TRADING_DAYS_PER_YEAR = 250


def _longest_true_run(x):
    """bool 数组中连续 True 的最大串长(向量化)。"""
    padded = np.concatenate(([0], x.view(np.int8), [0]))
    d = np.diff(padded)
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    if len(starts) == 0:
        return 0
    return int((ends - starts).max())


def run_backtest(spec, df):
    """按 spec 求值掩码,在 df 上统计指标。spec 见 backtest/combo_engine.ComboSpec。"""
    mask = eval_combo(spec, df)
    n = int(mask.sum())
    out = {"name": spec["name"], "n": n, "wins": 0, "win_rate": 0.0,
           "profit_loss_ratio": np.nan, "avg_ret": 0.0, "max_ret": 0.0,
           "max_drawdown": 0.0, "annual_ret": 0.0, "trades": n,
           "max_consec_loss": 0, "ret_std": np.nan}
    if n == 0:
        return out
    h = df.loc[mask]
    if DATE_COL in h.columns:
        h = h.sort_values(DATE_COL, kind="stable")
    labels = pd.to_numeric(h[LABEL_COL], errors="coerce").fillna(0)
    wins = int((labels == 1).sum())
    rets = pd.to_numeric(h[RET_COL], errors="coerce")
    rets_v = rets.dropna()
    out["wins"] = wins
    out["win_rate"] = wins / n
    avg_ret = float(rets_v.mean()) if len(rets_v) else 0.0
    out["avg_ret"] = avg_ret
    out["max_ret"] = float(rets_v.max()) if len(rets_v) else 0.0
    out["ret_std"] = float(rets_v.std()) if len(rets_v) > 1 else np.nan
    base = 1.0 + avg_ret
    out["annual_ret"] = (float(base ** (TRADING_DAYS_PER_YEAR / HOLD_DAYS) - 1.0)
                         if base > 0 else -1.0)
    # 盈亏比:平均盈利 / 平均亏损(亏损取绝对值)
    win_rets = rets[labels == 1].dropna()
    loss_rets = rets[labels != 1].dropna()
    avg_win = float(win_rets.mean()) if len(win_rets) else 0.0
    avg_loss = float(-loss_rets.mean()) if len(loss_rets) else 0.0
    if avg_loss > 0:
        out["profit_loss_ratio"] = avg_win / avg_loss
    elif avg_win > 0:
        out["profit_loss_ratio"] = np.inf
    else:
        out["profit_loss_ratio"] = np.nan
    # 最大回撤:按日期累计收益曲线的峰值回撤。
    # 面板收益可达 +1996%((1+ret).cumprod() 会 float64 溢出),用对数空间计算:
    # dd = 1 - exp(log累计净值 - log峰值),log 差值 <= 0,exp 不溢出。
    if len(rets_v):
        log_ret = np.log1p(rets_v.to_numpy(dtype=np.float64))
        log_ret[~np.isfinite(log_ret)] = -1e3  # ret <= -1:净值归零(近似)
        log_eq = log_ret.cumsum()
        log_peak = np.maximum.accumulate(log_eq)
        dd = 1.0 - np.exp(np.clip(log_eq - log_peak, -700.0, 0.0))
        out["max_drawdown"] = float(np.max(dd))
    # 连续未盈利最大串长
    out["max_consec_loss"] = _longest_true_run((labels == 0).to_numpy())
    return out


__all__ = ["run_backtest", "DATE_COL", "HOLD_DAYS", "TRADING_DAYS_PER_YEAR"]
