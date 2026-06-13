import os, tempfile, glob
import mine_presetup as MP

def test_write_reports_creates_files():
    # 构造两行 finalize 结果(A达标/B不达标)
    rows = [
        {"group":"ALL","plan":"A","side":"buy","pct":0.06,
         "params":(20,0.618,0.01,5,17,5),"seg_hit":6,"seg_total":10,
         "fires_all":100,"coverage":0.6,"rate_all":0.02,"lift":2.5,"precision":0.7},
        {"group":"ALL","plan":"B","side":"buy","pct":0.06,
         "params":((3,6,12,24),"cross",6,19,9),"seg_hit":3,"seg_total":10,
         "fires_all":80,"coverage":0.3,"rate_all":0.02,"lift":1.8,"precision":0.6},
    ]
    d = tempfile.mkdtemp()
    paths = MP.write_presetup_reports(rows, out_dir=d, ts="T")
    names = sorted(os.path.basename(p) for p in paths)
    assert any("方案A_起涨前蓄势_zz6_T.csv" == n for n in names), names
    assert any("最佳可达" in n for n in names), names
    assert any(n.endswith(".md") for n in names), names
    # A 达标主榜应含该行; B 主榜应空(coverage 0.3<0.5)
    a_main = [p for p in paths if "方案A_起涨前蓄势_zz6_T.csv" in p][0]
    assert "0.618" in open(a_main, encoding="utf-8-sig").read()

if __name__ == "__main__":
    test_write_reports_creates_files(); print("ALL presetup_report OK")
