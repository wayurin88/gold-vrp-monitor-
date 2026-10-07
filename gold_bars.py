"""
gold_bars.py -- ตัวช่วยร่วมของ gold_vrp_monitor.py และ gold_har_baseline.py

ปัญหาที่แก้: yfinance ส่งแท่งรายวันของ "วันเทรดที่ยังไม่จบ" มาด้วย (GC=F เปิด Globex
18:00 ET ของวันก่อนหน้า จบ 17:00 ET) ถ้าเอาแท่งนั้นมาคำนวณ ค่า RV / Parkinson / ราคาปิด
จะขึ้นกับเวลาที่สคริปต์รัน ไม่ใช่ข้อมูลจริงของวันนั้น
เช่น log 7 ต.ค. 2026: RV7 = 9.52 แทน ~23 เพราะแท่งครึ่งวันดัน return วัน 28 ก.ย. ออกจากหน้าต่าง

กติกา: แท่งวันที่ D นับว่าจบแล้วเมื่อเวลา New York เลย 17:00 ของวัน D
"""

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd

NY = ZoneInfo("America/New_York")
SESSION_END = time(17, 0)  # COMEX Globex ปิดรอบวัน 17:00 ET


def completed_bars(df: pd.DataFrame, now: datetime | None = None) -> pd.DataFrame:
    """ตัดแท่งที่วันเทรดยังไม่จบออก -- index ต้องเป็นวันที่แบบไม่มี tz (วันที่ตาม New York)"""
    now_ny = (now or datetime.now(timezone.utc)).astimezone(NY)
    last_done = now_ny.date() if now_ny.time() >= SESSION_END else None
    keep = [d.date() < now_ny.date() or (last_done is not None and d.date() <= last_done) for d in df.index]
    return df[keep]


def last_logged_bar(path: str, column: str = "last_bar_date") -> str | None:
    """วันที่ของแท่งล่าสุดที่ log ไว้แล้ว (กัน log ซ้ำเมื่อยังไม่มีแท่งใหม่)"""
    try:
        df = pd.read_csv(path, dtype=str)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return None
    if column not in df.columns:
        return None
    vals = df[column].dropna()
    return vals.iloc[-1] if len(vals) else None
