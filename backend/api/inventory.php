<?php
/**
 * GET /backend/api/inventory.php
 * Query:
 *   status = Full|Normal|Low Stock|Out of Stock
 *   shelf  = shelf_code e.g. A1
 *   q      = ค้นหาชื่อสินค้า / product_code / yolo_class
 *   alerts = 1  (เฉพาะ Low Stock + Out of Stock)
 */
require_once __DIR__ . '/../config/database.php';

handleCors();

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}

try {
    $db = getDB();

    $sql = "
        SELECT
            si.id AS inventory_id,
            s.id AS shelf_id,
            s.shelf_code,
            s.shelf_name,
            p.id AS product_id,
            p.product_code,
            p.product_name,
            p.yolo_class_name,
            si.quantity,
            si.capacity,
            si.low_stock_threshold,
            si.last_detected_at,
            si.updated_at
        FROM shelf_inventory si
        JOIN shelves s ON s.id = si.shelf_id
        JOIN products p ON p.id = si.product_id
        WHERE 1=1
    ";

    $params = [];

    if (!empty($_GET['shelf'])) {
        $sql .= " AND s.shelf_code = ?";
        $params[] = $_GET['shelf'];
    }

    if (!empty($_GET['q'])) {
        $sql .= " AND (
            p.product_name LIKE ?
            OR p.product_code LIKE ?
            OR p.yolo_class_name LIKE ?
        )";
        $term = '%' . $_GET['q'] . '%';
        $params[] = $term;
        $params[] = $term;
        $params[] = $term;
    }

    $sql .= " ORDER BY s.shelf_code ASC, p.product_name ASC";

    $stmt = $db->prepare($sql);
    $stmt->execute($params);
    $rows = $stmt->fetchAll();

    $filterStatus = isset($_GET['status']) ? trim($_GET['status']) : '';
    $alertsOnly = isset($_GET['alerts']) && $_GET['alerts'] === '1';

    $items = [];
    $summary = [
        'total' => 0,
        'full' => 0,
        'normal' => 0,
        'low_stock' => 0,
        'out_of_stock' => 0,
    ];

    foreach ($rows as $row) {
        $qty = (int) $row['quantity'];
        $threshold = (int) $row['low_stock_threshold'];
        $capacity = (int) $row['capacity'];
        $status = calcStockStatus($qty, $threshold, $capacity);

        $summary['total']++;
        if ($status === 'Full') {
            $summary['full']++;
        } elseif ($status === 'Normal') {
            $summary['normal']++;
        } elseif ($status === 'Low Stock') {
            $summary['low_stock']++;
        } else {
            $summary['out_of_stock']++;
        }

        if ($filterStatus !== '' && strcasecmp($status, $filterStatus) !== 0) {
            continue;
        }

        if ($alertsOnly && !in_array($status, ['Low Stock', 'Out of Stock'], true)) {
            continue;
        }

        $fill = $capacity > 0 ? round(($qty / $capacity) * 100, 1) : 0;

        $items[] = [
            'inventory_id' => (int) $row['inventory_id'],
            'shelf_id' => (int) $row['shelf_id'],
            'shelf_code' => $row['shelf_code'],
            'shelf_name' => $row['shelf_name'],
            'product_id' => (int) $row['product_id'],
            'product_code' => $row['product_code'],
            'product_name' => $row['product_name'],
            'yolo_class_name' => $row['yolo_class_name'],
            'quantity' => $qty,
            'capacity' => $capacity,
            'low_stock_threshold' => $threshold,
            'fill_percent' => $fill,
            'stock_status' => $status,
            'last_detected_at' => $row['last_detected_at'],
            'updated_at' => $row['updated_at'],
        ];
    }

    jsonResponse([
        'success' => true,
        'count' => count($items),
        'summary' => $summary,
        'data' => $items,
        'server_time' => date('Y-m-d H:i:s'),
    ]);
} catch (Throwable $e) {
    jsonResponse([
        'success' => false,
        'message' => 'Database error',
        'error' => $e->getMessage(),
    ], 500);
}
