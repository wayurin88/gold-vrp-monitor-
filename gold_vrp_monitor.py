"""
gold_vrp_monitor.py
Gold VRP (Volatility Risk Premium) Monitor -- เวอร์ชัน Gold ของ BTC VRP Monitor เดิม

แนวคิด: เทียบ implied volatility (proxy จาก GVZ) กับ realized volatility ของ
Gold futures (RV7 / RV30 / Parkinson7) เพื่อดูว่า IV วันนี้ "แพง" หรือ "ถูก"
เทียบกับความผันผวนที่เกิดขึ้นจริงในราคา -- เป็น diagnostic/QA layer แยกจาก
GOD.pine โดยสิ้นเชิง เพราะกินข้อมูลราคาล้วนๆ ไม่ต้องพึ่ง CME QuikStrike
manual-paste pipeline เลย

⚠️ ข้อจำกัดที่ต้องรู้ก่อนใช้:
  - GVZ คือ 30-day IV ของ GLD (ETF) options ไม่ใช่ IV ของ Gold futures (GC)
    options ตรงๆ -- ใช้เป็น proxy ที่ใกล้เคียงที่สุดที่มีข้อมูลฟรีต่อเนื่อง
    รายวัน ถ้าต้องการเทียบกับ front-week ATM IV ของ OG/GC จริง (sub-1 DTE
    แบบที่ DVOL ให้ฝั่ง BTC) ต้องคัดลอกตัวเลขจากตาราง QuikStrike มาเอง
    ผ่าน --front-iv (ดูคอลัมน์ ATM ใน "This Week in Options")
  - ตัวเลข threshold ใน classify_vrp() เป็นค่าเริ่มต้นหยาบๆ ยังไม่ผ่าน
    validation ใดๆ -- ใช้เป็นป้ายกำกับให้อ่านง่าย ไม่ใช่สัญญาณเทรด
  - เป็น diagnostic tool ไม่ใช่ hypothesis ที่ผ่าน pre-registration -- ถ้า
    เห็นอะไรน่าสนใจจากการ log สะสม ค่อยยกระดับเข้า lifecycle ปกติทีหลัง

การใช้งาน:
    pip install yfinance pandas numpy --break-system-packages
    python gold_vrp_monitor.py
    python gold_vrp_monitor.py --front-iv 15.69
    python gold_vrp_monitor.py --log-path C:\\Trading\\Vol2VolData\\gold_vrp_log.csv

ตั้ง Windows Task Scheduler ให้รันวันละ 2 ครั้งแบบเดียวกับ BTC VRP Monitor
ได้เลย -- ไม่มี dependency กับ Tampermonkey/CME feed ใดๆ
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
GOLD_FUTURES_TICKER = "GC=F"   # COMEX Gold futures (continuous), Yahoo Finance
GVZ_TICKER = "^GVZ"            # CBOE Gold ETF (GLD) Volatility Index, Yahoo Finance


def fetch_price_history(ticker: str, days: int) -> pd.DataFrame:
    """ดึงราคา OHLC ย้อนหลัง -- ขอเผื่อเป็นวันปฏิทินเพื่อให้ได้ trading days พอสำหรับ RV30
    (วันหยุด/วันเสาร์อาทิตย์กินไปประมาณ 30% ของช่วงที่ขอ)"""
    df = yf.Ticker(ticker).history(period=f"{days}d", interval="1d", auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"ดึงราคาของ {ticker} ไม่ได้ -- เช็คการเชื่อมต่อเน็ตหรือ ticker ผิด")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def realized_vol(close: pd.Series, window: int) -> float:
    """Close-to-close realized volatility, annualized (%) -- log return มาตรฐาน
    ใช้ window ล่าสุด window วัน (trading days ไม่ใช่วันปฏิทิน)"""
    log_ret = np.log(close / close.shift(1)).dropna()
    if len(log_ret) < window:
        return float("nan")
    recent = log_ret.tail(window)
    return float(recent.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR) * 100.0)


def parkinson_vol(high: pd.Series, low: pd.Series, window: int) -> float:
    """Parkinson high-low range estimator, annualized (%)
    สูตรเดียวกับที่ใช้ในเปเปอร์ Options-driven Volatility Forecasting (eq. 14):
    HLP = sqrt( sum(log(H/L)^2) / (4*ln(2)*window) ) * sqrt(252)"""
    hl_sq = (np.log(high / low) ** 2).dropna()
    if len(hl_sq) < window:
        return float("nan")
    recent = hl_sq.tail(window)
    variance = recent.sum() / (4.0 * np.log(2.0) * window)
    return float(np.sqrt(variance) * np.sqrt(TRADING_DAYS_PER_YEAR) * 100.0)


def fetch_gvz(days: int) -> float:
    """ดึง GVZ ปิดล่าสุด -- proxy ของ 30-day ATM IV (ดู caveat ในหัวไฟล์)"""
    df = fetch_price_history(GVZ_TICKER, days)
    return float(df["Close"].iloc[-1])


def classify_vrp(gap: float, threshold_rich: float = 3.0, threshold_cheap: float = -1.0) -> str:
    """ป้ายกำกับหยาบๆ อ่านง่าย -- ไม่ใช่คำสั่งเทรด เกณฑ์ยังไม่ผ่าน validation
    ปรับ threshold_rich/threshold_cheap เองได้หลังเห็นข้อมูล log สะสมสักพัก"""
    if np.isnan(gap):
        return "ข้อมูลไม่พอ"
    if gap >= threshold_rich:
        return f"IV แพงกว่า RV มาก ({gap:+.1f}pp) -- premium อาจ rich"
    if gap <= threshold_cheap:
        return f"IV ถูกกว่า RV ({gap:+.1f}pp) -- premium อาจ cheap ผิดปกติ"
    return f"IV กับ RV ใกล้กัน ({gap:+.1f}pp) -- ไม่มีอะไรโดดเด่น"


def build_report(price: pd.DataFrame, gvz: float, front_iv: float | None) -> dict:
    rv7 = realized_vol(price["Close"], 7)
    rv30 = realized_vol(price["Close"], 30)
    pk7 = parkinson_vol(price["High"], price["Low"], 7)

    gap_rv30 = gvz - rv30 if not (np.isnan(gvz) or np.isnan(rv30)) else float("nan")
    gap_rv7 = gvz - rv7 if not (np.isnan(gvz) or np.isnan(rv7)) else float("nan")
    gap_pk7 = gvz - pk7 if not (np.isnan(gvz) or np.isnan(pk7)) else float("nan")
    gap_front = None
    if front_iv is not None:
        gap_front = front_iv - rv7 if not np.isnan(rv7) else float("nan")

    return {
        "gc_close": float(price["Close"].iloc[-1]),
        "gvz": gvz,
        "rv7": rv7,
        "rv30": rv30,
        "pk7": pk7,
        "front_iv": front_iv,
        "gap_rv30": gap_rv30,
        "gap_rv7": gap_rv7,
        "gap_pk7": gap_pk7,
        "gap_front": gap_front,
    }


def print_report(r: dict, now: datetime) -> None:
    print("=" * 60)
    print(f"Gold VRP Monitor -- {now:%Y-%m-%d %H:%M} UTC")
    print("=" * 60)
    print(f"GC last close   : {r['gc_close']:.2f}")
    print(f"GVZ (30D IV)    : {r['gvz']:.2f}%" if not np.isnan(r["gvz"]) else "GVZ             : N/A (ดึงไม่สำเร็จ)")
    print(f"RV7             : {r['rv7']:.2f}%")
    print(f"RV30            : {r['rv30']:.2f}%")
    print(f"Parkinson7      : {r['pk7']:.2f}%")
    print("-" * 60)
    print(f"VRP gap (GVZ-RV30) : {r['gap_rv30']:+.2f}pp  -> {classify_vrp(r['gap_rv30'])}")
    print(f"VRP gap (GVZ-RV7)  : {r['gap_rv7']:+.2f}pp  -> {classify_vrp(r['gap_rv7'])}")
    print(f"VRP gap (GVZ-PK7)  : {r['gap_pk7']:+.2f}pp  -> {classify_vrp(r['gap_pk7'])}")
    if r["front_iv"] is not None:
        print(f"Front-week IV (manual) : {r['front_iv']:.2f}%  vs RV7 -> gap {r['gap_front']:+.2f}pp -> {classify_vrp(r['gap_front'])}")
    print("=" * 60)
    print("หมายเหตุ: ตัวเลขนี้เป็น diagnostic เท่านั้น ยังไม่ผ่าน validation -- อย่าใช้ตัดสินใจเทรดตรงๆ")


def write_log(path: str, now: datetime, r: dict) -> None:
    """append ต่อท้ายไฟล์เดิม สร้างไฟล์ใหม่พร้อม header ถ้ายังไม่มี"""
    write_header = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow([
                "timestamp_utc", "gc_close", "gvz", "rv7", "rv30", "parkinson7",
                "front_iv_manual", "gap_gvz_rv30", "gap_gvz_rv7", "gap_gvz_pk7", "gap_front_rv7",
            ])

        def fmt(v):
            return "" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.2f}"

        writer.writerow([
            now.isoformat(), fmt(r["gc_close"]), fmt(r["gvz"]), fmt(r["rv7"]), fmt(r["rv30"]),
            fmt(r["pk7"]), fmt(r["front_iv"]), fmt(r["gap_rv30"]), fmt(r["gap_rv7"]),
            fmt(r["gap_pk7"]), fmt(r["gap_front"]),
        ])
    print(f"บันทึกแล้วที่ {os.path.abspath(path)}")


def main():
    parser = argparse.ArgumentParser(description="Gold VRP Monitor -- เทียบ GVZ (IV proxy) กับ Realized Vol ของ GC")
    parser.add_argument(
        "--front-iv", type=float, default=None,
        help="ATM IV ของ weekly ใกล้สุดจาก QuikStrike (คอลัมน์ ATM ในตาราง 'This Week in Options') "
             "-- ใส่เพื่อเทียบ gap กับ RV7 ด้วย เพราะ GVZ เป็น IV 30 วันของ GLD ไม่ใช่ sub-1 DTE ของ gold futures options ตรงๆ",
    )
    parser.add_argument(
        "--log-path", type=str, default="gold_vrp_log.csv",
        help="ไฟล์ CSV สำหรับสะสมประวัติทุกครั้งที่รัน (default: gold_vrp_log.csv ในโฟลเดอร์ปัจจุบัน)",
    )
    parser.add_argument(
        "--history-days", type=int, default=90,
        help="จำนวนวันปฏิทินย้อนหลังที่ดึงราคามา (default 90 -- พอสำหรับ RV30)",
    )
    parser.add_argument(
        "--no-log", action="store_true",
        help="แค่พิมพ์รายงาน ไม่เขียนลง CSV (ใช้ตอนทดสอบ)",
    )
    args = parser.parse_args()

    price = fetch_price_history(GOLD_FUTURES_TICKER, args.history_days)
    try:
        gvz = fetch_gvz(args.history_days)
    except RuntimeError as e:
        print(f"⚠️  {e}")
        gvz = float("nan")

    report = build_report(price, gvz, args.front_iv)
    now = datetime.now(timezone.utc)
    print_report(report, now)

    if not args.no_log:
        write_log(args.log_path, now, report)


if __name__ == "__main__":
    main()
