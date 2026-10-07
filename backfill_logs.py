"""
backfill_logs.py -- เติม gold_vrp_log.csv / gold_har_log.csv ย้อนหลังจากแท่งรายวันที่จบแล้วของ Yahoo

ทุกค่าคำนวณจากข้อมูลถึงวันนั้นเท่านั้น (ไม่มี look-ahead) ด้วยสูตรเดียวกับสคริปต์รายวัน
แถวที่เติมมี source=backfill และ timestamp_utc ว่าง (ไม่ได้รันจริงตอนนั้น)

ขอบเขต (ตรวจคุณภาพข้อมูล 7 ต.ค. 2026):
  - VRP: ตั้งแต่ GVZ มีข้อมูล (3 มิ.ย. 2008)
  - Parkinson7: เว้นว่างถ้าในหน้าต่าง 7 วันมีแท่งที่ High == Low (Yahoo GC=F ก่อนปี 2021
    มีแท่งแบบนี้ปนหลายปี เช่น 2010 ~15%, 2018 ~14% ทำให้ค่าต่ำเกินจริง)
  - HAR: refit ทุกวันด้วยหน้าต่าง 2 ปีปฏิทิน ใช้เฉพาะวันที่หน้าต่างไม่มีแท่ง High == Low
    (เริ่มได้ราวต้นปี 2023)

    python backfill_logs.py --until 2026-10-06
"""

import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import gold_har_baseline as har
from gold_bars import completed_bars
from gold_vrp_monitor import TRADING_DAYS_PER_YEAR

VRP_COLS = ["timestamp_utc", "last_bar_date", "gc_close", "gvz", "rv7", "rv30", "parkinson7",
            "front_iv_manual", "gap_gvz_rv30", "gap_gvz_rv7", "gap_gvz_pk7", "gap_front_rv7",
            "partial_bar", "source"]
HAR_COLS = ["timestamp_utc", "last_bar_date", "years", "n_obs", "r2", "b0", "b1", "b2", "b3",
            "today_vol_pct", "forecast_vol_pct", "gvz", "gap_gvz_forecast", "partial_bar", "source"]


def f2(v):
    return "" if v is None or pd.isna(v) else f"{v:.2f}"


def g(v, sig=6):
    return "" if v is None or pd.isna(v) else f"{v:.{sig}g}"


def vrp_rows(gc: pd.DataFrame, gvz: pd.Series, start: str) -> list[dict]:
    ann = np.sqrt(TRADING_DAYS_PER_YEAR) * 100.0
    lr = np.log(gc["Close"] / gc["Close"].shift(1))
    rv7 = lr.rolling(7).std(ddof=1) * ann
    rv30 = lr.rolling(30).std(ddof=1) * ann
    hl = np.log(gc["High"] / gc["Low"]) ** 2
    pk7 = np.sqrt(hl.rolling(7).sum() / (4.0 * np.log(2.0) * 7)) * ann
    flat = (gc["High"] <= gc["Low"]).astype(int).rolling(7).sum() > 0
    pk7[flat] = np.nan
    gv = gvz.reindex(gc.index, method="ffill")
    out = []
    for d in gc.index[gc.index >= start]:
        if pd.isna(gv[d]):
            continue
        out.append({
            "timestamp_utc": "", "last_bar_date": f"{d:%Y-%m-%d}", "gc_close": f2(gc["Close"][d]),
            "gvz": f2(gv[d]), "rv7": f2(rv7[d]), "rv30": f2(rv30[d]), "parkinson7": f2(pk7[d]),
            "front_iv_manual": "", "gap_gvz_rv30": f2(gv[d] - rv30[d]), "gap_gvz_rv7": f2(gv[d] - rv7[d]),
            "gap_gvz_pk7": f2(gv[d] - pk7[d]), "gap_front_rv7": "", "partial_bar": 0, "source": "backfill",
        })
    return out


def har_rows(gc: pd.DataFrame, gvz: pd.Series, years: int = 2) -> list[dict]:
    rv_all = har.parkinson_daily_variance(gc["High"], gc["Low"]).dropna()
    flat = gc["High"] <= gc["Low"]
    gv = gvz.reindex(gc.index, method="ffill")
    out = []
    for d in gc.index:
        lo = d - pd.DateOffset(years=years)
        if lo < gc.index[0] or flat[(gc.index > lo) & (gc.index <= d)].any():
            continue
        rv = rv_all[(rv_all.index > lo) & (rv_all.index <= d)]
        feat = har.build_har_features(rv)
        if len(feat) < 30:
            continue
        coeffs, r2 = har.fit_har_ols(feat)
        fc = har.variance_to_annual_vol_pct(har.forecast_tomorrow(coeffs, rv))
        today = har.variance_to_annual_vol_pct(rv.iloc[-1])
        b0, b1, b2, b3 = coeffs
        out.append({
            "timestamp_utc": "", "last_bar_date": f"{d:%Y-%m-%d}", "years": years, "n_obs": len(feat),
            "r2": g(r2, 4), "b0": g(b0), "b1": g(b1, 4), "b2": g(b2, 4), "b3": g(b3, 4),
            "today_vol_pct": g(today, 4), "forecast_vol_pct": g(fc, 4), "gvz": g(gv[d], 4),
            "gap_gvz_forecast": g(gv[d] - fc, 4), "partial_bar": 0, "source": "backfill",
        })
    return out


def merge(path: str, cols: list[str], new: list[dict]) -> None:
    """แถวเดิม (ไม่มี source) ติดป้าย live_v1 แล้วเรียงทั้งหมดตามวันที่ของข้อมูล"""
    old = pd.read_csv(path, dtype=str, keep_default_na=False)
    old = old[old.get("source", "") != "backfill"] if "source" in old.columns else old
    if "source" not in old.columns:
        old["source"] = "live_v1"
    df = pd.concat([pd.DataFrame(new, columns=cols).astype(str), old.reindex(columns=cols, fill_value="")])
    key = df["last_bar_date"].where(df["source"] == "backfill", df["timestamp_utc"].str[:10])
    df = df.assign(_k=key).sort_values("_k", kind="stable").drop(columns="_k")
    df.to_csv(path, index=False, lineterminator="\n")
    print(f"{path}: backfill {len(new)} แถว + เดิม {len(old)} แถว")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default="", help="วันสุดท้ายที่เติม (YYYY-MM-DD) ค่าเริ่มต้น = แท่งที่จบล่าสุด")
    ap.add_argument("--vrp-start", default="2008-06-03")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    gc = completed_bars(har.fetch_price_history(har.GOLD_FUTURES_TICKER, "max").dropna(subset=["Close"]), now)
    gvz = completed_bars(har.fetch_price_history(har.GVZ_TICKER, "max"), now)["Close"].dropna()
    if args.until:
        gc = gc[gc.index <= args.until]
    merge("gold_vrp_log.csv", VRP_COLS, vrp_rows(gc, gvz, args.vrp_start))
    merge("gold_har_log.csv", HAR_COLS, har_rows(gc, gvz))


if __name__ == "__main__":
    main()
