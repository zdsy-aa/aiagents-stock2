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


def _scores_df():
    base = {"条件内胜率": 0.6, "基线胜率": 0.4, "胜率增益": 0.2, "非盈利覆盖率": 0.1}
    rows = [
        # G 组 L2 子集
        {"分组": "G", "方案": "a + b", "支持数": 200, "盈利覆盖率": 0.5, "提升度": 2.0, "层级": "L2", **base},
        {"分组": "G", "方案": "a + c", "支持数": 200, "盈利覆盖率": 0.5, "提升度": 3.0, "层级": "L2", **base},
        {"分组": "G", "方案": "b + c", "支持数": 200, "盈利覆盖率": 0.5, "提升度": 1.5, "层级": "L2", **base},
        # 达标 L3
        {"分组": "G", "方案": "a + b + c", "支持数": 150, "盈利覆盖率": 0.30, "提升度": 3.5, "层级": "L3", **base},
        # 支持不足(99<100) 应被剔
        {"分组": "G", "方案": "a + b + d", "支持数": 99, "盈利覆盖率": 0.30, "提升度": 9.0, "层级": "L3", **base},
        # 覆盖不足(0.19<0.20) 应被剔
        {"分组": "G", "方案": "a + c + e", "支持数": 200, "盈利覆盖率": 0.19, "提升度": 9.0, "层级": "L3", **base},
        # 边界: 支持=100 覆盖=0.20 应保留
        {"分组": "G", "方案": "b + c + f", "支持数": 100, "盈利覆盖率": 0.20, "提升度": 1.0, "层级": "L3", **base},
    ]
    return pd.DataFrame(rows)


def test_surface():
    board = S.surface(_scores_df(), support_min=100, cover_min=0.20, topn=15)
    # 仅 a+b+c 与 b+c+f 达标; 按提升度降序 → a+b+c(3.5) 在前
    assert list(board["方案"]) == ["a + b + c", "b + c + f"], list(board["方案"])
    r0 = board.iloc[0]
    assert abs(r0["增量提升度"] - 0.5) < 1e-9, r0["增量提升度"]   # 3.5 - max(2,3,1.5)=3.0
    assert frozenset(S.split_conditions(r0["最优两两子集"])) == frozenset(("a", "c"))
    # 输出列齐全且顺序正确
    assert list(board.columns) == ["分组", "方案", "支持数", "盈利覆盖率", "条件内胜率",
                                   "基线胜率", "胜率增益", "提升度", "最优两两子集",
                                   "子集提升度", "增量提升度"], list(board.columns)
    print("OK surface")


def test_surface_topn():
    # 同组 20 条达标 L3 → Top15 截断
    base = {"条件内胜率": 0.6, "基线胜率": 0.4, "胜率增益": 0.2, "非盈利覆盖率": 0.1}
    rows = [{"分组": "H", "方案": "x + y", "支持数": 300, "盈利覆盖率": 0.5,
             "提升度": 5.0, "层级": "L2", **base}]
    for i in range(20):
        rows.append({"分组": "H", "方案": f"x + y + z{i}", "支持数": 200,
                     "盈利覆盖率": 0.30, "提升度": float(i), "层级": "L3", **base})
    board = S.surface(pd.DataFrame(rows), support_min=100, cover_min=0.20, topn=15)
    assert len(board) == 15, len(board)
    assert board["提升度"].iloc[0] == 19.0      # 降序,最高在前
    print("OK surface_topn")


def test_write_outputs(tmpdir="/tmp/l3_out"):
    import os, glob, shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    os.makedirs(tmpdir, exist_ok=True)
    board = S.surface(_scores_df(), support_min=100, cover_min=0.20, topn=15)
    paths = S.write_outputs(board, tmpdir, "20260612_000000")
    csvs = glob.glob(os.path.join(tmpdir, "L3独立榜_2*.csv"))
    mds = glob.glob(os.path.join(tmpdir, "L3独立榜_对比_*.md"))
    assert len(csvs) == 1 and len(mds) == 1, (csvs, mds)
    head = open(csvs[0], encoding="utf-8-sig").readline()
    assert "增量提升度" in head and "最优两两子集" in head, head
    body = open(mds[0], encoding="utf-8").read()
    assert "真协同" in body or "凑数" in body         # 判定标注存在
    print("OK write_outputs")


if __name__ == "__main__":
    test_split_conditions()
    test_load_scores()
    test_build_pair_lift_and_marginal()
    test_marginal_inf_sentinel()
    test_surface()
    test_surface_topn()
    test_write_outputs()
    print("ALL OK")
