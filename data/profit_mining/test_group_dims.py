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


if __name__ == "__main__":
    test_bucketize()
    test_board_group()
    test_size_group()
    test_vol20_series()
    test_split_windows_by_vol()
    print("ALL OK")
