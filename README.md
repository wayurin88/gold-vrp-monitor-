# gold-vrp-monitor-

Diagnostic log ของความผันผวนทองคำ (ยังไม่ใช่สัญญาณเทรด) รันเองทุกวันผ่าน GitHub Actions

| สคริปต์ | ทำอะไร | Log |
|---|---|---|
| `gold_vrp_monitor.py` | เทียบ GVZ (IV proxy) กับ RV7 / RV30 / Parkinson7 ของ GC=F | `gold_vrp_log.csv` |
| `gold_har_baseline.py` | fit HAR (Corsi 2009) บน Parkinson daily variance แล้วพยากรณ์ vol วันถัดไป | `gold_har_log.csv`, `gold_har_coeffs.txt` (วางใน Pine) |
| `gold_bars.py` | ตัวช่วยร่วม: ตัดแท่งรายวันที่ยังไม่จบ (ก่อน 17:00 ET) และกัน log ซ้ำ | |

## สมมติฐานที่ลงทะเบียนไว้ (pre-registered)
| | ไฟล์กฎ | นับตั้งแต่ | ประเมิน |
|---|---|---|---|
| H5 combo (HAR+GVZ)/2 พยากรณ์ vol วันถัดไป | `docs/strategies/H5_har_gvz_combo.md` | แท่ง 7 ต.ค. 2026 | 250 คู่ หรือ 6 ต.ค. 2027 |

ผลอยู่ที่ `h5/h5_report.txt` (อัปเดตทุกวันใน workflow HAR)
**กฎเหล็ก:** ห้ามแก้กฎ หรือโค้ดที่เปลี่ยนค่าใน log (`gold_har_baseline.py`, `gold_bars.py`) ก่อนวันประเมิน ถ้าต้องเปลี่ยนให้ตั้งเป็นสมมติฐานใหม่

## เวลารัน
- VRP Monitor 22:37 UTC และ HAR 22:47 UTC วันจันทร์–ศุกร์ (05:37 / 05:47 น. ไทยของวันถัดไป) หลังตลาดปิดทั้งสองฤดู
- ถ้า GitHub ดีเลย์ ค่าไม่เพี้ยน เพราะใช้แท่งที่จบแล้วเท่านั้น และถ้ายังไม่มีแท่งใหม่จะไม่เพิ่มแถว
- รันเองได้ที่ Actions › Run workflow (VRP ใส่ `front_iv` จาก QuikStrike ได้)

## คอลัมน์ใน log
- `last_bar_date` วันที่ของแท่ง GC ล่าสุดที่ใช้คำนวณ (ว่างในแถวก่อน 7 ต.ค. 2026)
- `partial_bar` = 1 ถ้าแถวนั้นคำนวณตอนตลาดยังเปิด (แท่งล่าสุดยังไม่จบ) **ไม่ควรใช้แถวเหล่านี้วิเคราะห์** เก็บไว้เพื่อความโปร่งใส
- `source`
  - `backfill` = เติมย้อนหลังด้วย `backfill_logs.py` (VRP ตั้งแต่ 3 มิ.ย. 2008, HAR ตั้งแต่ 28 มี.ค. 2022) ใช้ข้อมูลถึงวันนั้นเท่านั้น `timestamp_utc` ว่าง
  - `live_v1` = แถวที่รันจริงก่อน PR #1 (14 ก.ย. – 7 ต.ค. 2026) ซ้ำกับ backfill ช่วงเดียวกัน ใช้ backfill แทน
  - `live` = แถวที่รันจริงหลัง PR #1
- `parkinson7` ว่างในแถว backfill ที่หน้าต่าง 7 วันมีแท่ง High == Low (Yahoo GC=F ก่อนปี 2021 มีแท่งแบบนี้ปนอยู่)

สำหรับวิเคราะห์ ให้กรอง `source != "live_v1"` และ `partial_bar == 0`

## รันในเครื่อง
```
pip install -r requirements.txt
python gold_vrp_monitor.py --no-log
python gold_har_baseline.py --no-log
```
