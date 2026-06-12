# test_surface_l3.py —— L3独立榜浮出 合成数据测试（python3 test_surface_l3.py）
import pandas as pd
import surface_l3 as S


def test_split_conditions():
    assert S.split_conditions("a + b + c") == ["a", "b", "c"]
    # 含 >= / <= 的真实条件名不被误切
    assert S.split_conditions("相对强弱>=5 + 突破前高") == ["相对强弱>=5", "突破前高"]
    assert S.split_conditions("量比>=1.3") == ["量比>=1.3"]
    print("OK split_conditions")


def test_load_scores(tmp_path="/tmp/l3_scores.csv"):
    pd.DataFrame([
        {"分组": "G", "方案": "a + b", "支持数": "200", "盈利覆盖率": "0.5",
         "非盈利覆盖率": "0.1", "提升度": "2.0", "条件内胜率": "0.6",
         "基线胜率": "0.4", "胜率增益": "0.2", "层级": "L2"},
    ]).to_csv(tmp_path, index=False, encoding="utf-8-sig")
    df = S.load_scores(tmp_path)
    assert df["支持数"].dtype.kind in "if"        # 数值化
    assert abs(df["提升度"].iloc[0] - 2.0) < 1e-9
    assert df["方案"].iloc[0] == "a + b"           # 字符串列保持
    print("OK load_scores")


if __name__ == "__main__":
    test_split_conditions()
    test_load_scores()
    print("ALL OK")
