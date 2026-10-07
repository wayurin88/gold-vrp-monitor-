"""
h5_har_eval.py -- ประเมิน H5 (docs/strategies/H5_har_forecast.md) จาก gold_har_log.csv

จับคู่: แถว D (forecast_vol_pct, today_vol_pct, gvz) กับแถวถัดไป D+1 (today_vol_pct = vol จริงของวัน D+1)
ตัวพยากรณ์ที่ทดสอบ: combo = (HAR + GVZ) / 2 เทียบกับ HAR และ GVZ ด้วย QLIKE บน variance (ค่าหลัก)
naive (vol วันนี้) แสดงประกอบเท่านั้น · ทดสอบด้วย Diebold-Mariano แบบ Newey-West (lag 5)

    python h5_har_eval.py                      # นับผลจริง: แถว source=live เท่านั้น
    python h5_har_eval.py --source backfill    # ข้อมูลก่อนลงทะเบียน (ไม่ใช้ตัดสิน)
"""

import argparse
import os
from math import erf, sqrt

import numpy as np
import pandas as pd

START_BAR = "2026-10-07"     # แถว forecast แรกที่นับ (พยากรณ์วันเทรด 8 ต.ค. 2026)
EVAL_DATE = "2027-10-06"
MIN_PAIRS = 250
NW_LAG = 5
COMPETITORS = ["har", "gvz"]   # ใช้ตัดสิน
INFO_ONLY = ["naive"]


def qlike(real_vol: pd.Series, fc_vol: pd.Series) -> pd.Series:
    """QLIKE บน variance: r/f - ln(r/f) - 1  (0 = พยากรณ์ตรง, ทนต่อ proxy ที่มี noise ตาม Patton 2011)"""
    r = (real_vol / fc_vol) ** 2
    return r - np.log(r) - 1.0


def dm_test(d: np.ndarray, lag: int = NW_LAG) -> tuple[float, float, float, float]:
    """Diebold-Mariano: d = loss(คู่แข่ง) - loss(combo) > 0 แปลว่า combo ดีกว่า
    คืน (ค่าเฉลี่ย, ขอบล่าง 95% ข้างเดียว, t, p ข้างเดียว)"""
    n = len(d)
    m = d.mean()
    e = d - m
    var = np.dot(e, e) / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - k / (lag + 1)) * np.dot(e[k:], e[:-k]) / n
    se = sqrt(max(var, 1e-18) / n)
    t = m / se
    p = 1 - 0.5 * (1 + erf(t / sqrt(2)))
    return m, m - 1.645 * se, t, p


def pairs(log: pd.DataFrame, source: str) -> pd.DataFrame:
    df = log[(log["source"] == source) & (log["partial_bar"].astype(str) == "0")].copy()
    df = df.dropna(subset=["last_bar_date"]).drop_duplicates("last_bar_date", keep="first")
    df = df.sort_values("last_bar_date").reset_index(drop=True)
    if source == "live":
        df = df[df["last_bar_date"] >= START_BAR].reset_index(drop=True)
    nxt = df.shift(-1)
    out = pd.DataFrame({
        "bar_date": df["last_bar_date"], "target_date": nxt["last_bar_date"],
        "har": df["forecast_vol_pct"], "naive": df["today_vol_pct"], "gvz": df["gvz"],
        "real": nxt["today_vol_pct"],
    }).dropna()
    # วันที่ไม่ติดกันในตารางวันเทรด (workflow พลาด) ไม่นับ: ต้องห่างไม่เกิน 4 วันปฏิทิน
    gap = (pd.to_datetime(out["target_date"]) - pd.to_datetime(out["bar_date"])).dt.days
    out = out[gap <= 4]
    for c in ["har", "naive", "gvz", "real"]:
        out[c] = out[c].astype(float)
    out = out[(out[["har", "naive", "gvz", "real"]] > 0).all(axis=1)]
    out["combo"] = (out["har"] + out["gvz"]) / 2.0
    for name in ["combo", *COMPETITORS, *INFO_ONLY]:
        out[f"ql_{name}"] = qlike(out["real"], out[name])
        out[f"ae_{name}"] = (out[name] - out["real"]).abs()
    return out.reset_index(drop=True)


def report(p: pd.DataFrame, source: str) -> str:
    lines = [f"H5 combo (HAR+GVZ)/2 -- source={source} -- {len(p)} คู่"]
    if len(p):
        lines.append(f"ช่วง: forecast จากแท่ง {p['bar_date'].iloc[0]} ถึง {p['bar_date'].iloc[-1]}")
    if source == "live":
        lines.append(f"ประเมิน: ครบ {MIN_PAIRS} คู่ หรือ {EVAL_DATE} (ถึงก่อนใช้อันนั้น)")
    if len(p) < 10:
        lines.append("ข้อมูลยังน้อยเกินไป")
        return "\n".join(lines)
    lines.append("")
    lines.append("ค่าเฉลี่ย loss      QLIKE     MAE(pp)")
    for name in ["combo", *COMPETITORS, *INFO_ONLY]:
        lines.append(f"  {name:<8}       {p[f'ql_{name}'].mean():.4f}   {p[f'ae_{name}'].mean():6.2f}")
    lines.append("")
    half = len(p) // 2
    passed, consistent = True, True
    for name in COMPETITORS:
        d = (p[f"ql_{name}"] - p["ql_combo"]).to_numpy()
        m, lo, t, pv = dm_test(d)
        h1, h2 = d[:half].mean(), d[half:].mean()
        ok = lo > 0 and h1 > 0 and h2 > 0
        passed &= ok
        consistent &= m > 0
        lines.append(f"combo vs {name}: ΔQLIKE {m:+.4f} (ขอบล่าง 95% {lo:+.4f}, t {t:.2f}, p {pv:.4f}) "
                     f"ครึ่งแรก {h1:+.4f} ครึ่งหลัง {h2:+.4f}")
    lines.append("")
    level = "ผ่าน" if passed else ("สอดคล้อง (ยังไม่มีนัยสำคัญ)" if consistent else "ไม่ผ่าน")
    lines.append(f"ระดับตามเกณฑ์ ณ ตอนนี้ (ผลทางการคือวันประเมิน): {level}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="gold_har_log.csv")
    ap.add_argument("--source", default="live", choices=["live", "backfill"])
    ap.add_argument("--out", default="h5")
    args = ap.parse_args()

    p = pairs(pd.read_csv(args.log, dtype=str), args.source)
    txt = report(p, args.source)
    print(txt)
    if args.source == "live":
        os.makedirs(args.out, exist_ok=True)
        p.to_csv(os.path.join(args.out, "h5_log.csv"), index=False, float_format="%.6g")
        with open(os.path.join(args.out, "h5_report.txt"), "w", encoding="utf-8") as f:
            f.write(txt + "\n")


if __name__ == "__main__":
    main()
