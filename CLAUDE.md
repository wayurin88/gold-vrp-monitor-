# gold-vrp-monitor-

Diagnostic log ความผันผวนทองคำ (GVZ เทียบ RV, HAR forecast) + สมมติฐาน H5 เจ้าของ repo สื่อสารภาษาไทย ตอบเป็นภาษาไทย
repo เป็น **public** · เครื่อง local เป็น Windows มี `git` และ `gh` (login เป็น wayurin88)

## ข้อมูลไหลอย่างไร
- `gold_vrp_monitor.py` (22:37 UTC จ.–ศ.) → `gold_vrp_log.csv` : GVZ, RV7, RV30, Parkinson7 และส่วนต่าง
- `gold_har_baseline.py` (22:47 UTC จ.–ศ.) → `gold_har_log.csv`, `gold_har_coeffs.txt` → `h5_har_eval.py` → `h5/`
- ทั้งสองใช้ `gold_bars.py`: ใช้เฉพาะแท่ง GC=F/GVZ รายวันที่จบแล้ว (เลย 17:00 ET) และไม่ log ซ้ำถ้าแท่งล่าสุดเคย log แล้ว
- `backfill_logs.py` เติมย้อนหลังด้วยสูตรเดียวกัน (รันครั้งเดียวไปแล้ว 7 ต.ค. 2026)
- ทั้งสอง workflow ใช้ concurrency group `gold-vrp-commit` และ `git pull --rebase` ก่อน push

## คอลัมน์ที่ต้องรู้ใน log
- `source`: `backfill` (คำนวณย้อนหลัง, `timestamp_utc` ว่าง) · `live_v1` (แถวก่อน 7 ต.ค. 2026 ที่คำนวณรวมแท่งที่ยังไม่ปิด **อย่าใช้**) · `live`
- `partial_bar` = 1 → แท่งล่าสุดยังไม่จบตอนคำนวณ **อย่าใช้**
- วิเคราะห์: กรอง `source != "live_v1"` และ `partial_bar == 0`
- Parkinson7 ว่างใน backfill ที่หน้าต่างมีแท่ง High == Low (Yahoo GC=F ก่อนปี 2021)

## สมมติฐานที่ลงทะเบียนไว้
| | ไฟล์กฎ | นับตั้งแต่ | ประเมิน |
|---|---|---|---|
| H5 (HAR+GVZ)/2 พยากรณ์ vol วันถัดไป | `docs/strategies/H5_har_gvz_combo.md` | แท่ง 7 ต.ค. 2026 | 250 คู่ หรือ 6 ต.ค. 2027 |

- เลขสมมติฐานใช้ร่วมกับ `wayurin88/qs-archive` (H1–H4 อยู่ที่นั่น) ตัวถัดไปคือ **H6** และต้องเพิ่มลงตารางใน `CLAUDE.md` ของ qs-archive ด้วย
- **กฎเหล็ก:** ห้ามแก้กฎ หรือโค้ดที่เปลี่ยนค่าใน log (`gold_har_baseline.py`, `gold_bars.py`, `h5_har_eval.py`) ก่อนวันประเมิน ถ้าต้องเปลี่ยนให้ตั้งเป็นสมมติฐานใหม่ ห้ามดูผลระหว่างทางแล้วปรับกฎ
- H5 เลือกหลังดูข้อมูล backfill แล้ว (แผนเดิม "HAR ดีกว่า GVZ" ไม่ผ่านใน backfill เมื่อวัดด้วย QLIKE) และกำลังทดสอบต่ำ คาดว่าได้ระดับ "สอดคล้อง" มากกว่า "ผ่าน"

## สิ่งที่รู้จากข้อมูลย้อนหลัง (7 ต.ค. 2026, ยังไม่ใช่ผลที่ทดสอบไปข้างหน้า)
- 2008–2026: GVZ สูงกว่า RV30 และ RV ของ 21 วันถัดไป ~76% ของวัน เฉลี่ย +2pp แต่ 2025–2026 แคบลงจนเกือบ 0
- ขนาดส่วนต่าง GVZ − RV30 วันนี้ไม่ได้บอก VRP ของเดือนถัดไป (ทุก quintile ~72–80%) → ป้ายใน `classify_vrp()` เป็นแค่คำอธิบาย ไม่ใช่สัญญาณ
- RV7 ขึ้นกับวันแรงวันเดียว อย่าใช้ตัดสินว่า IV แพง/ถูก
- HAR (QLIKE 0.330) ดีกว่า naive (0.622) ชัดเจน แต่ไม่ต่างจาก GVZ (0.325) · combo 0.309 · R² ของ HAR แกว่ง 0.02–0.52

## ข้อควรระวังตอนแก้ไฟล์บน Windows
ไฟล์ใน repo เป็น LF ถ้า clone ด้วย `core.autocrlf=true` แล้ว commit จะกลายเป็น CRLF ทั้งไฟล์ → ตั้ง `git config core.autocrlf false` และแปลงเป็น LF ก่อน commit
