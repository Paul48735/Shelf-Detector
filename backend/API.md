# Shelf Detection — API Documentation

Base URL: `http://localhost/backend/api/`

---

## Image Detection

### GET /classes.php

อ่านรายชื่อ class จากโมเดล YOLO ผ่าน Python AI service สำหรับสร้าง Dropdown

Response 200:
```json
{
  "success": true,
  "count": 30,
  "data": ["Taokaenoi-g", "campus", "lay-nori", "oreo", "pocky"]
}
```

### PUT /detect.php

ส่ง binary ของภาพเป็น request body พร้อม headers:

```text
Content-Type: image/jpeg
X-File-Extension: jpg
X-Product-Class: lay-nori
X-Max-Capacity: 5
X-Confidence: 0.5
```

Response 200:
```json
{
  "success": true,
  "product_class": "lay-nori",
  "max_capacity": 5,
  "detected_quantity": 2,
  "missing_quantity": 3,
  "status": "Low Stock",
  "confidence": 0.5,
  "result_image_url": "http://127.0.0.1:8000/results/example.jpg",
  "detections": []
}
```

Python AI service ต้องทำงานที่ `http://127.0.0.1:8000` ก่อนเรียก endpoint เหล่านี้

---

## Auth

### POST /login.php

Body:
```json
{ "username": "admin", "password": "admin1234" }
```

Response 200:
```json
{
  "success": true,
  "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "user": { "id": 1, "username": "admin", "role": "admin" }
}
```

Response 401:
```json
{ "success": false, "message": "Invalid credentials" }
```

---

### GET /me.php

Header: `Authorization: Bearer <token>`

Response 200:
```json
{
  "success": true,
  "user": { "id": 1, "username": "admin", "role": "admin", "created_at": "2026-08-25 17:00:00" }
}
```

---

### GET /auth.php

Header: `Authorization: Bearer <token>`

Response 200:
```json
{ "success": true, "authenticated": true, "user_id": 1, "username": "admin", "role": "admin" }
```

Response 401:
```json
{ "success": false, "message": "Invalid or expired token" }
```

---

## Inventory

### GET /inventory.php

Query params:
- `status` = Full | Normal | Low Stock | Out of Stock
- `shelf` = shelf_code (e.g. A1)
- `q` = search product name / code / yolo_class
- `alerts` = 1 (only Low Stock + Out of Stock)

Response 200:
```json
{
  "success": true,
  "count": 5,
  "summary": { "total": 5, "full": 2, "normal": 1, "low_stock": 1, "out_of_stock": 1 },
  "data": [
    {
      "inventory_id": 1,
      "shelf_id": 1,
      "shelf_code": "A1",
      "shelf_name": "Shelf A1",
      "product_id": 1,
      "product_code": "P001",
      "product_name": "Water",
      "yolo_class_name": "water",
      "quantity": 3,
      "capacity": 8,
      "low_stock_threshold": 2,
      "fill_percent": 37.5,
      "stock_status": "Normal",
      "last_detected_at": "2026-08-25 16:30:00",
      "updated_at": "2026-08-25 16:30:00"
    }
  ],
  "server_time": "2026-08-25 17:00:00"
}
```

---

## Shelves

### GET /shelves.php

Response 200:
```json
{ "success": true, "count": 3, "data": [{ "id": 1, "shelf_code": "A1", "shelf_name": "..." }] }
```

### GET /shelves.php?id=1

Response 200:
```json
{
  "success": true,
  "data": {
    "id": 1,
    "shelf_code": "A1",
    "inventory": [
      {
        "inventory_id": 1,
        "product_id": 1,
        "product_name": "Water",
        "quantity": 3,
        "capacity": 8,
        "low_stock_threshold": 2,
        "stock_status": "Normal",
        "fill_percent": 37.5
      }
    ]
  }
}
```

### POST /shelves.php

Actions:

**Create shelf:**
```json
{ "action": "create", "shelf_code": "A1", "shelf_name": "Shelf A1" }
```

**Assign product:**
```json
{ "action": "assign", "shelf_id": 1, "product_id": 2, "quantity": 0, "capacity": 8, "low_stock_threshold": 2 }
```

**Unassign product:**
```json
{ "action": "unassign", "shelf_id": 1, "product_id": 2 }
```

**Update inventory:**
```json
{ "action": "update_inventory", "inventory_id": 1, "capacity": 8, "low_stock_threshold": 2, "quantity": 3 }
```

### PUT /shelves.php

Body:
```json
{ "id": 1, "shelf_code": "A1", "shelf_name": "New Name" }
```

### DELETE /shelves.php?id=1

Response 200:
```json
{ "success": true, "message": "Shelf deleted" }
```

---

## Products

### GET /products.php

Query: `q` = search term

Response 200:
```json
{ "success": true, "count": 10, "data": [{ "id": 1, "product_code": "P001", "product_name": "Water", "yolo_class_name": "water" }] }
```

### POST /products.php

Body:
```json
{ "product_code": "P001", "product_name": "Water", "yolo_class_name": "water" }
```

### PUT /products.php

Body:
```json
{ "id": 1, "product_name": "Mineral Water" }
```

### DELETE /products.php?id=1

Response 200:
```json
{ "success": true, "message": "Product deleted" }
```

---

## Categories

### GET /categories.php

Response 200:
```json
{
  "success": true,
  "count": 3,
  "data": [
    { "shelf_code": "A1", "shelf_name": "Shelf A1", "item_count": 5 }
  ]
}
```

---

## Health

### GET /health.php

Response 200:
```json
{ "success": true, "message": "OK", "database": "shelf_detection", "server_time": "2026-08-25 17:00:00" }
```

---

## Auth Flow (Frontend)

```
1. POST /login.php → รับ token
2. เก็บ token ใน localStorage
3. ทุก request แนบ header: Authorization: Bearer <token>
4. ถ้า response 401 → ลบ token, redirect ไป /login.html
```

## SQL Setup

```sql
CREATE TABLE users (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('admin','staff') NOT NULL DEFAULT 'staff',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (username, password_hash, role)
VALUES ('admin', '$2y$10$BRdtdYdzHfAm4Vqp60grdu68eeX1.WmXCmBJ2KL9pYJ0MZ41H9Fvu', 'admin');
```
