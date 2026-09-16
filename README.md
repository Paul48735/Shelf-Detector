# Shelf-Detector-v2

สำเนาโปรเจกต์สำหรับพัฒนาเวอร์ชันใหม่ แยกจาก Shelf-Detector เดิม

## โครงสร้าง

- ai/: Flask API, โมเดล YOLO, กฎ Planogram
- backend/api/: PHP API
- backend/config/: ค่าเชื่อม AI และ MySQL
- frontend/detect/: หน้าตรวจจับสินค้า
- frontend/dashboard/: หน้าภาพรวม
- frontend/planogram/: หน้าจัดแผนชั้นวาง
- frontend/shared/: CSS ที่ทุกหน้าใช้ร่วมกัน
- database/: SQL สำหรับฐานข้อมูล
- storage/: ภาพอัปโหลด ภาพผลลัพธ์ และภาพ Planogram

## ส่วนหน้า

ทั้งสามหน้าใช้ Bootstrap 5.3.8 CSS ผ่าน jsDelivr CDN จึงต้องเชื่อมต่ออินเทอร์เน็ตเมื่อเปิดหน้าเว็บ
CSS ที่เขียนเองเหลือเฉพาะส่วนอัปโหลดภาพ พื้นที่แสดงภาพ และตัวแก้ไข Planogram

## เริ่มใช้งาน

1. ใช้ Python 3.11 ขึ้นไป สร้าง virtual environment แล้วติดตั้ง ai/requirements.txt
2. เปิด Apache และ MySQL ใน XAMPP
3. นำเข้า database/shelf_detection.sql ในฐานข้อมูลใหม่ shelf_detection_v2 เท่านั้น (ไฟล์นี้สร้างฐานข้อมูลให้) ไม่ต้องนำเข้า add_product_placement.sql ซ้ำ
4. ตรวจชื่อผู้ใช้และรหัสผ่าน MySQL ใน backend/config/database.php
5. รัน python ai/app.py ซึ่งเปิด AI ที่ http://127.0.0.1:8001
6. เปิด http://localhost/Shelf-Detector-v2/

ค่าที่แยกจากโปรเจกต์เดิม: AI พอร์ต 8001 และ MySQL ฐานข้อมูล shelf_detection_v2
