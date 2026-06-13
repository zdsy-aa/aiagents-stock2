import numpy as np
import setup_modeling as SM

def test_auc_known():
    y = np.array([0,0,1,1]); s = np.array([0.1,0.2,0.3,0.4])
    assert abs(SM.auc(y, s) - 1.0) < 1e-9
    assert abs(SM.auc(y, -s) - 0.0) < 1e-9
    assert abs(SM.auc(np.array([0,1,0,1]), np.array([1,1,2,2])) - 0.5) < 1e-9

def test_lift_top_decile():
    y = np.array([0]*90 + [1]*10); s = np.arange(100.0)
    assert abs(SM.lift_top_decile(y, s, q=0.1) - (1.0/0.1)) < 1e-6

def test_logistic_separable():
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(-2,1,(200,3)), rng.normal(2,1,(200,3))])
    y = np.array([0]*200 + [1]*200)
    Xs, mu, sd = SM.standardize_fit(X)
    w, b = SM.fit_logistic(Xs, y, l2=0.1, lr=0.5, epochs=400)
    sc = SM.predict_logistic(SM.standardize_apply(X, mu, sd), w, b)
    assert SM.auc(y, sc) > 0.97, SM.auc(y, sc)

def test_median_fill_uses_train_only():
    Xtr = np.array([[1.0],[3.0],[np.nan]]); Xoos = np.array([[np.nan]])
    med = SM.col_median(Xtr)
    Xtr2 = SM.fill_na(Xtr, med); Xoos2 = SM.fill_na(Xoos, med)
    assert Xtr2[2,0] == 2.0 and Xoos2[0,0] == 2.0

def test_time_split():
    dates = np.array(["2023-06-01","2023-12-31","2024-01-01","2025-09-01"], dtype="datetime64[D]")
    tr, oos = SM.time_split_mask(dates, "2023-12-31", "2024-01-01", "2025-10-31")
    assert tr.tolist() == [True,True,False,False]
    assert oos.tolist() == [False,False,True,True]

if __name__ == "__main__":
    test_auc_known(); test_lift_top_decile(); test_logistic_separable()
    test_median_fill_uses_train_only(); test_time_split()
    print("ALL setup_modeling OK")
