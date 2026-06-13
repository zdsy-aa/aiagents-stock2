import os, tempfile
import mine_setup_commonality as MS

def test_write_setup_reports():
    rows = [
        {"group":"ALL","plan":"L1","side":"buy","pct":0.06,"params":"box_w20_wd0.10",
         "seg_hit":7,"seg_total":10,"fires_all":50,"coverage":0.7,"rate_all":0.05,"lift":1.6,"precision":0.4},
        {"group":"ALL","plan":"L2","side":"buy","pct":0.06,"params":"box_w20_wd0.10 & dryup_w20_r0.8",
         "seg_hit":3,"seg_total":10,"fires_all":20,"coverage":0.3,"rate_all":0.02,"lift":2.2,"precision":0.5},
    ]
    d = tempfile.mkdtemp()
    paths = MS._write_setup_reports(rows, out_dir=d, ts="T")
    names = sorted(os.path.basename(p) for p in paths)
    assert any("蓄势特征_共性_zz6_T.csv" == n for n in names), names
    assert any("最佳可达" in n for n in names), names
    assert any(n.endswith(".md") for n in names), names
    main_csv = [p for p in paths if "蓄势特征_共性_zz6_T.csv" in p][0]
    txt = open(main_csv, encoding="utf-8-sig").read()
    assert "box_w20_wd0.10" in txt and "coverage" in txt
    # 主榜只收 coverage>=0.5 -> L1(0.7)在, L2(0.3)不在
    assert "box_w20_wd0.10 & dryup" not in txt

if __name__ == "__main__":
    test_write_setup_reports(); print("ALL setup_report OK")
