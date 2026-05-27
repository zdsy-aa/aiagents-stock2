# tests/test_chanlun_engine.py
import pandas as pd
from chanlun_engine import merge_inclusion, KBar


def _df(rows):
    # rows: list of (high, low)；Open/Close/Volume 填充占位
    idx = pd.RangeIndex(len(rows))
    return pd.DataFrame(
        {"Open": [h for h, l in rows], "High": [h for h, l in rows],
         "Low": [l for h, l in rows], "Close": [l for h, l in rows],
         "Volume": [1] * len(rows)}, index=idx)


def test_merge_inclusion_upward_merges_to_higher():
    # 第3根(11,8)被(12,7)向上包含 -> 合并成(12,8)
    df = _df([(10, 5), (12, 7), (11, 8)])
    ks = merge_inclusion(df)
    assert [(k.high, k.low) for k in ks] == [(10, 5), (12, 8)]
    assert ks[-1].i_lo == 1 and ks[-1].i_hi == 2


def test_merge_inclusion_no_inclusion_passthrough():
    df = _df([(10, 5), (12, 7), (14, 9)])
    ks = merge_inclusion(df)
    assert [(k.high, k.low) for k in ks] == [(10, 5), (12, 7), (14, 9)]
