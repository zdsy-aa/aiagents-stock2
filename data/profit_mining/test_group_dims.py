# test_group_dims.py —— 分组工具单测
import numpy as np
import group_dims as GD


def test_bucketize():
    cuts = [10.0, 20.0]
    assert GD.bucketize(5, cuts) == 0      # <c1 低/小
    assert GD.bucketize(10, cuts) == 1     # ==c1 左闭 → 中
    assert GD.bucketize(15, cuts) == 1
    assert GD.bucketize(20, cuts) == 2     # ==c2 → 最高桶
    assert GD.bucketize(99, cuts) == 2
    print("OK bucketize")


def test_board_group():
    assert GD.board_group("创业板") == "板块=创业板"
    assert GD.board_group("") is None
    assert GD.board_group(None) is None
    print("OK board_group")


def test_size_group():
    cuts = [50.0, 200.0]
    assert GD.size_group(30, cuts) == "市值=小盘"
    assert GD.size_group(100, cuts) == "市值=中盘"
    assert GD.size_group(500, cuts) == "市值=大盘"
    assert GD.size_group(None, cuts) is None     # 快照缺 → 不分组
    assert GD.size_group(100, None) is None
    print("OK size_group")


def test_vol20_series():
    import pandas as pd
    df = pd.DataFrame({"High": [11, 12, 13], "Low": [9, 10, 11], "Close": [10, 10, 10]})
    v = GD.vol20_series(df, win=20)
    # amp = (H-L)/C = 0.2 每根；min_periods=1 → 累进均值仍 0.2
    assert np.allclose(v, [0.2, 0.2, 0.2]), v
    print("OK vol20_series")


def test_split_windows_by_vol():
    # vol20 在各 bar 的值，拐点=window[0]
    vol20 = np.array([0.0, 0.1, 0.5, 0.0, 0.9, 0.0])
    cuts = [0.2, 0.6]
    windows = [[1, 2], [2, 3], [4, 5]]   # 拐点 vol20 = 0.1(低),0.5(中),0.9(高)
    out = GD.split_windows_by_vol(windows, vol20, cuts)
    assert out[0] == [[1, 2]]
    assert out[1] == [[2, 3]]
    assert out[2] == [[4, 5]]
    print("OK split_windows_by_vol")


def test_extract_mktcap():
    import pandas as pd
    import fetch_mktcap_snapshot as FM
    df = pd.DataFrame({"代码": ["000001", "600000"],
                       "名称": ["平安银行", "浦发银行"],
                       "总市值": [3.5e11, 4.2e11]})
    out = FM.extract_mktcap(df)
    assert list(out.columns) == ["代码", "总市值"]
    assert out.iloc[0]["代码"] == "000001"
    assert abs(out.iloc[0]["总市值"] - 3.5e11) < 1
    print("OK extract_mktcap")


def test_extract_mktcap_missing_col():
    import pandas as pd
    import fetch_mktcap_snapshot as FM
    df = pd.DataFrame({"代码": ["000001"], "最新价": [10.0]})   # 无总市值
    try:
        FM.extract_mktcap(df)
        assert False, "应抛错"
    except ValueError:
        print("OK extract_mktcap_missing_col")


def test_terciles():
    import calibrate_buckets as CB
    vals = list(range(1, 100))            # 1..99
    c1, c2 = CB.terciles(vals)
    assert 32 <= c1 <= 35, c1            # ~33 分位
    assert 65 <= c2 <= 68, c2            # ~66 分位
    print("OK terciles")


def test_terciles_empty():
    import calibrate_buckets as CB
    try:
        CB.terciles([])
        assert False
    except ValueError:
        print("OK terciles_empty")


if __name__ == "__main__":
    test_bucketize()
    test_board_group()
    test_size_group()
    test_vol20_series()
    test_split_windows_by_vol()
    test_extract_mktcap()
    test_extract_mktcap_missing_col()
    test_terciles()
    test_terciles_empty()
    print("ALL OK")
