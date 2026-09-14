"""
gold_har_baseline.py  --  DIAGNOSTIC เท่านั้น ยังไม่ใช่ trading signal

รันอัตโนมัติทุกสัปดาห์ผ่าน gold-har-baseline.yml (weekly cron) เพื่อ refit
coefficient + สะสม log ไว้เทียบกับ gold_vrp_monitor.py ตามแผนเดิม (ถ้า
RV7/RV30/Parkinson ธรรมดาก็อ่านออกพอแล้ว ก็ยังไม่มีเหตุผลต้องเอา HAR ไป
ผูกเป็น signal จริง -- ตัวนี้แค่เก็บ log คู่ขนานไว้เทียบดูก่อน)
ทุกครั้งที่รันจะเขียนทับ gold_har_coeffs.txt ด้วยค่า b0-b3 ล่าสุด สำหรับ
copy ไปวางใน Gold HAR Forecast (Draft).pine

แนวคิด (Corsi 2009, ตามที่คุยกันไปตอนอธิบาย HAR):
    RV[d] = b0 + b1*RV[d-1] + b2*mean(RV[d-5:d-1]) + b3*mean(RV[d-22:d-1]) + e

ข้อจำกัดที่ต้องรู้ก่อนอ่านผล:
  - เปเปอร์ต้นฉบับ (Corsi 2009 และ Options-driven Volatility Forecasting ที่
    คุยกันไปก่อนหน้า) fit HAR บน realized variance จาก intraday 1-5 นาที
    เรามีแค่ daily OHLC จาก yfinance เลยใช้ "Parkinson daily variance"
    (จาก high-low range) เป็นตัวแทน RV รายวันแทน -- efficiency ดีกว่า
    squared close-close return เปล่าๆ (ดู Table 1 ในเปเปอร์ efficiency
    5.2 เท่าของ close-close) แต่ก็ยังไม่ใช่ intraday RV ของจริง ผลที่ได้
    จึงหยาบกว่าเปเปอร์ต้นฉบับ
  - Fit ด้วย OLS ธรรมดาผ่าน numpy เท่านั้น ไม่มี robust standard errors,
    ไม่มี HARQ correction ใดๆ -- เป็น MVP ที่สุดของ HAR เท่านั้น
  - ยังไม่ผ่าน hypothesis lifecycle ใดๆ -- แค่ script ทดลองอ่านค่า ไม่ใช่
    signal ที่ผ่าน validation

การใช้งาน:
    pip install yfinance pandas numpy --break-system-packages
    python gold_har_baseline.py
    python gold_har_baseline.py --years 3 --no-gvz
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("ต้องติดตั้ง yfinance ก่อน: pip install yfinance --break-system-packages", file=sys.stderr)
    raise

TRADING_DAYS_PER_YEAR = 252
GOLD_FUTURES_TICKER = "GC=F"
GVZ_TICKER = "^GVZ"


def fetch_price_history(ticker: str, period: str) -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"ดึงราคาของ {ticker} ไม่ได้ -- เช็คการเชื่อมต่อเน็ตหรือ ticker ผิด")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def parkinson_daily_variance(high: pd.Series, low: pd.Series) -> pd.Series:
    """Parkinson variance ของ*วันเดียว* (ไม่ annualize) -- ใช้เป็น RV[d] ในสูตร HAR
    หน่วยเป็น variance เปล่าๆ (ไม่ใช่ % ไม่ใช่ vol) ตามธรรมเนียมงาน HAR ดั้งเดิม"""
    return (np.log(high / low) ** 2) / (4.0 * np.log(2.0))


def build_har_features(rv: pd.Series) -> pd.DataFrame:
    """สร้างตาราง feature สำหรับ regression: X = [RV_d-1, mean(RV_d-5:d-1), mean(RV_d-22:d-1)]
    target y = RV_d -- ทุก feature ใช้ข้อมูลถึงแค่ d-1 เพื่อพยากรณ์ d เท่านั้น
    ป้องกัน look-ahead bias"""
    daily = rv.shift(1)
    weekly = rv.shift(1).rolling(window=5).mean()
    monthly = rv.shift(1).rolling(window=22).mean()
    df = pd.DataFrame({
        "rv": rv,
        "daily_lag": daily,
        "weekly_lag": weekly,
        "monthly_lag": monthly,
    }).dropna()
    return df


def fit_har_ols(df: pd.DataFrame) -> tuple[np.ndarray, float]:
    """OLS ธรรมดาผ่าน numpy lstsq -- คืน (coefficients [b0,b1,b2,b3], R^2)"""
    X = np.column_stack([
        np.ones(len(df)),
        df["daily_lag"].values,
        df["weekly_lag"].values,
        df["monthly_lag"].values,
    ])
    y = df["rv"].values
    coeffs, residuals, rank, sv = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ coeffs
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return coeffs, r2


def forecast_tomorrow(coeffs: np.ndarray, rv: pd.Series) -> float:
    """ใช้ค่าล่าสุดจริง (ไม่ใช่ lag) เป็น input พยากรณ์วันถัดไป"""
    b0, b1, b2, b3 = coeffs
    daily_now = rv.iloc[-1]
    weekly_now = rv.tail(5).mean()
    monthly_now = rv.tail(22).mean()
    return float(b0 + b1 * daily_now + b2 * weekly_now + b3 * monthly_now)


def variance_to_annual_vol_pct(var: float) -> float:
    """แปลง daily variance -> annualized volatility (%) เพื่อเทียบกับ GVZ/IV ได้ตรงหน่วย"""
    if var <= 0 or np.isnan(var):
        return float("nan")
    return float(np.sqrt(var * TRADING_DAYS_PER_YEAR) * 100.0)


def fetch_gvz_last(period: str) -> float:
    df = fetch_price_history(GVZ_TICKER, period)
    return float(df["Close"].iloc[-1])


def write_log(path: str, now: datetime, row: dict) -> None:
    """append ต่อท้ายไฟล์เดิม สร้างไฟล์ใหม่พร้อม header ถ้ายังไม่มี -- แบบเดียวกับ
    gold_vrp_monitor.py เพื่อให้ mine ย้อนหลังผ่าน git history ได้แบบเดียวกัน"""
    write_header = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow([
                "timestamp_utc", "years", "n_obs", "r2", "b0", "b1", "b2", "b3",
                "today_vol_pct", "forecast_vol_pct", "gvz", "gap_gvz_forecast",
            ])

        def fmt(v, sig=6):
            return "" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{sig}g}"

        writer.writerow([
            now.isoformat(), row["years"], row["n_obs"], fmt(row["r2"], 4),
            fmt(row["b0"]), fmt(row["b1"], 4), fmt(row["b2"], 4), fmt(row["b3"], 4),
            fmt(row["today_vol_pct"], 4), fmt(row["forecast_vol_pct"], 4),
            fmt(row["gvz"], 4), fmt(row["gap"], 4),
        ])
    print(f"บันทึก log แล้วที่ {os.path.abspath(path)}")


def write_coeffs_file(path: str, now: datetime, coeffs: np.ndarray) -> None:
    """เขียนไฟล์ text แยกต่างหาก เก็บแค่ coefficient ล่าสุด (เขียนทับทุกครั้ง ไม่ append)
    ออกแบบให้ copy "ทั้งไฟล์" ไปวางในช่อง text-area เดียวของ
    gold_har_forecast_draft.pine ได้เลย ไม่ต้องแยกทีละตัวเลข (กันพลาดตัด
    ส่วน e-0X ท้ายเลขหายตอน copy ทีละบรรทัด อย่างที่เจอปัญหามาแล้ว)
    ตั้งใจไม่ใช้ scientific notation เลย -- ใช้ fixed-decimal เต็มรูปแบบ
    เพราะ Pine str.tonumber() ไม่รับประกันว่าจะ parse เลขรูปแบบ 1.5e-05 ได้
    ถูกต้องเสมอ ปลอดภัยกว่าถ้าเป็นทศนิยมธรรมดาล้วนๆ"""
    b0, b1, b2, b3 = coeffs
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# gold_har_baseline.py -- fit ล่าสุด {now:%Y-%m-%d} (UTC)\n")
        f.write("# วาง (paste) เนื้อหาทั้งไฟล์นี้เข้าช่อง 'HAR Coefficients (paste ทั้งไฟล์)'\n")
        f.write("# ใน Pine ได้เลยทั้งก้อน ไม่ต้องแยกทีละบรรทัด/ทีละตัวเลข\n")
        f.write(f"b0={b0:.14f}\n")
        f.write(f"b1={b1:.10f}\n")
        f.write(f"b2={b2:.10f}\n")
        f.write(f"b3={b3:.10f}\n")
        f.write(f"fitted_as_of={now:%Y-%m-%d}\n")
    print(f"บันทึก coefficients แล้วที่ {os.path.abspath(path)}")


def main():
    parser = argparse.ArgumentParser(description="Gold HAR baseline -- DRAFT, ยังไม่ควรตั้ง schedule")
    parser.add_argument("--years", type=int, default=2,
                         help="จำนวนปีย้อนหลังที่ใช้ fit HAR (default 2 -- ยิ่งยาวยิ่งเสถียรแต่ปรับตัวช้าลง)")
    parser.add_argument("--no-gvz", action="store_true", help="ข้ามการดึง GVZ มาเทียบ")
    parser.add_argument("--log-path", type=str, default="gold_har_log.csv",
                         help="ไฟล์ CSV สะสมประวัติทุกครั้งที่รัน (default: gold_har_log.csv)")
    parser.add_argument("--coeffs-path", type=str, default="gold_har_coeffs.txt",
                         help="ไฟล์ text เก็บ coefficient ล่าสุด สำหรับ copy เข้า Pine (เขียนทับทุกครั้ง ไม่ append)")
    parser.add_argument("--no-log", action="store_true", help="แค่พิมพ์รายงาน ไม่เขียนไฟล์ log/coeffs (ใช้ตอนทดสอบ)")
    args = parser.parse_args()

    period = f"{args.years}y"
    price = fetch_price_history(GOLD_FUTURES_TICKER, period)
    rv = parkinson_daily_variance(price["High"], price["Low"]).dropna()

    n_obs = len(rv)
    min_needed = 22 + 30  # ต้องมี lag 22 วัน + เผื่อ observation พอ fit อย่างน้อย ~30 จุด
    if n_obs < min_needed:
        print(f"⚠️  มีข้อมูลแค่ {n_obs} วัน -- น้อยกว่า {min_needed} วันที่แนะนำขั้นต่ำ "
              f"ผลลัพธ์จะไม่เสถียร ลองเพิ่ม --years", file=sys.stderr)

    feat = build_har_features(rv)
    if len(feat) < 30:
        print(f"❌ มีข้อมูลพอ fit ได้แค่ {len(feat)} จุด -- น้อยเกินไปที่จะเชื่อค่า coefficient ใดๆ หยุดที่นี่")
        return

    coeffs, r2 = fit_har_ols(feat)
    b0, b1, b2, b3 = coeffs

    forecast_var = forecast_tomorrow(coeffs, rv)
    forecast_vol_pct = variance_to_annual_vol_pct(forecast_var)
    today_vol_pct = variance_to_annual_vol_pct(rv.iloc[-1])

    gvz = float("nan")
    if not args.no_gvz:
        try:
            gvz = fetch_gvz_last(period)
        except RuntimeError as e:
            print(f"⚠️  {e}")

    now = datetime.now(timezone.utc)
    print("=" * 62)
    print(f"Gold HAR Baseline (DRAFT) -- {now:%Y-%m-%d %H:%M} UTC")
    print("=" * 62)
    print(f"Fit บนข้อมูล {len(feat)} วัน (จาก {args.years} ปีย้อนหลัง, Parkinson daily variance)")
    print(f"R^2 ของ in-sample fit : {r2:.3f}")
    print(f"Coefficients: b0={b0:.6g}  b1(daily)={b1:.3f}  b2(weekly)={b2:.3f}  b3(monthly)={b3:.3f}")
    print("-" * 62)
    print(f"Vol (Parkinson) วันนี้        : {today_vol_pct:.2f}%")
    print(f"HAR forecast สำหรับพรุ่งนี้    : {forecast_vol_pct:.2f}%")
    if not np.isnan(gvz):
        print(f"GVZ (IV proxy) ล่าสุด          : {gvz:.2f}%")
        print(f"Gap (GVZ - HAR forecast)      : {gvz - forecast_vol_pct:+.2f}pp")
    print("=" * 62)
    print("⚠️  DRAFT เท่านั้น -- coefficient/threshold ยังไม่ผ่าน validation ใดๆ "
          "ห้ามใช้ตัดสินใจเทรดตรงๆ")

    if not args.no_log:
        write_log(args.log_path, now, {
            "years": args.years, "n_obs": len(feat), "r2": r2,
            "b0": b0, "b1": b1, "b2": b2, "b3": b3,
            "today_vol_pct": today_vol_pct, "forecast_vol_pct": forecast_vol_pct,
            "gvz": gvz, "gap": gvz - forecast_vol_pct if not np.isnan(gvz) else float("nan"),
        })
        write_coeffs_file(args.coeffs_path, now, coeffs)


if __name__ == "__main__":
    main()
