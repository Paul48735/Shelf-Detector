<?php
/**
 * DB จริงไม่มี category — endpoint นี้คืนรายการ shelf สำหรับ filter แทน
 * GET /backend/api/categories.php
 */
require_once __DIR__ . '/../config/database.php';

handleCors();

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}

try {
    $db = getDB();
    $rows = $db->query("
        SELECT
            s.shelf_code,
            s.shelf_name,
            COUNT(si.id) AS item_count
        FROM shelves s
        LEFT JOIN shelf_inventory si ON si.shelf_id = s.id
        GROUP BY s.id, s.shelf_code, s.shelf_name
        ORDER BY s.shelf_code ASC
    ")->fetchAll();

    jsonResponse([
        'success' => true,
        'count' => count($rows),
        'data' => $rows,
        'note' => 'No product category column — returning shelves for filter',
    ]);
} catch (Throwable $e) {
    jsonResponse([
        'success' => false,
        'message' => 'Database error',
        'error' => $e->getMessage(),
    ], 500);
}
