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


def test_build_pair_lift_and_marginal():
    # L2 子集表(故意乱序: a/b 存成 "b + a")
    l2 = pd.DataFrame([
        {"方案": "b + a", "提升度": 2.0, "层级": "L2"},
        {"方案": "a + c", "提升度": 3.0, "层级": "L2"},
        {"方案": "c + b", "提升度": 1.5, "层级": "L2"},
    ])
    pl = S.build_pair_lift(l2)
    assert pl[frozenset(("a", "b"))] == 2.0      # 集合匹配,无视顺序
    assert pl[frozenset(("b", "c"))] == 1.5
    # L3 "a + b + c" 提升度3.5 → 子集 {a,b}=2,{a,c}=3,{b,c}=1.5 → 最优3.0(a+c) → 增量0.5
    subset, blift, inc = S.l3_marginal("a + b + c", 3.5, pl)
    assert blift == 3.0, blift
    assert abs(inc - 0.5) < 1e-9, inc
    assert frozenset(S.split_conditions(subset)) == frozenset(("a", "c")), subset
    print("OK build_pair_lift_and_marginal")


def test_marginal_inf_sentinel():
    pl = {frozenset(("a", "b")): 2.0, frozenset(("a", "c")): 3.0,
          frozenset(("b", "c")): 999.0}
    # L3 提升度999(inf) → 增量 inf
    _, _, inc1 = S.l3_marginal("a + b + c", 999.0, pl)
    assert inc1 == float("inf"), inc1
    # L3 有限 但最优子集是999 → 增量 -inf
    pl2 = {frozenset(("a", "b")): 999.0, frozenset(("a", "c")): 3.0,
           frozenset(("b", "c")): 1.5}
    _, blift2, inc2 = S.l3_marginal("a + b + c", 4.0, pl2)
    assert blift2 == 999.0 and inc2 == float("-inf"), (blift2, inc2)
    print("OK marginal_inf_sentinel")


if __name__ == "__main__":
    test_split_conditions()
    test_load_scores()
    test_build_pair_lift_and_marginal()
    test_marginal_inf_sentinel()
    print("ALL OK")
