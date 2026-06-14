import numpy as np, pandas as pd
import setup_features as SF

def _df(close, vol=None, n=None):
    n = n or len(close)
    idx = pd.date_range("2015-01-01", periods=n, freq="D")
    c = pd.Series(close[:n], dtype=float, index=idx)
    return pd.DataFrame({"Open": c, "High": c*1.01, "Low": c*0.99, "Close": c,
                         "Volume": pd.Series((vol or [100.0]*n)[:n], index=idx)}, index=idx)

def test_feature_cols_count():
    assert 20 <= len(SF.FEATURE_COLS) <= 28, len(SF.FEATURE_COLS)

def test_no_future_leak():
    base = [10.0 + 0.01*i for i in range(300)]
    d1 = _df(base)
    d2v = list(base); d2v[250] = 999.0
    d2 = _df(d2v)
    f1 = SF.compute_features(d1, idx_close=None, turn=None)
    f2 = SF.compute_features(d2, idx_close=None, turn=None)
    assert np.allclose(np.nan_to_num(f1[200]), np.nan_to_num(f2[200])), (f1[200], f2[200])

def test_label_fwd():
    close = [10.0]*10 + [11.0]*10 + [10.0]*30
    d = _df(close)
    y = SF.label_fwd(d, H=20, X=0.06)
    assert y[5] == 1
    assert y[40] == 0 or np.isnan(y[40])
    assert np.isnan(y[len(close)-1])

def test_label_zz():
    close = [10.0]*40 + [10.0+0.5*i for i in range(40)] + [30.0]*20
    d = _df(close)
    y = SF.label_zz(d, pct=0.06, K=10)
    assert y.sum() >= 1, y.sum()
    assert set(np.unique(y[~np.isnan(y)])) <= {0.0, 1.0}

def test_label_excess():
    n = 60
    idx = pd.date_range("2015-01-01", periods=n, freq="D")
    stock = pd.Series([10.0]*5 + [13.0]*55, index=idx)
    big = pd.Series([100.0]*n, index=idx)
    d = pd.DataFrame({"Open": stock, "High": stock, "Low": stock, "Close": stock,
                      "Volume": pd.Series([1.0]*n, index=idx)}, index=idx)
    y = SF.label_excess(d, big, H=20, X=0.10)
    assert y[0] == 1.0, y[0]
    assert np.isnan(y[n-1])
    stock2 = pd.Series(np.linspace(10, 13, n), index=idx)
    big2 = pd.Series(np.linspace(100, 130, n), index=idx)
    d2 = pd.DataFrame({"Open": stock2, "High": stock2, "Low": stock2, "Close": stock2,
                       "Volume": pd.Series([1.0]*n, index=idx)}, index=idx)
    y2 = SF.label_excess(d2, big2, H=20, X=0.10)
    assert y2[0] == 0.0, y2[0]
    assert np.isnan(SF.label_excess(d, None)).all()

if __name__ == "__main__":
    test_feature_cols_count(); test_no_future_leak()
    test_label_fwd(); test_label_zz()
    test_label_excess();
    print("ALL setup_features OK")
