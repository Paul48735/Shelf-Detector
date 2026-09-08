<?php
/**
 * GET /backend/api/health.php — ทดสอบการเชื่อมต่อ DB
 */
require_once __DIR__ . '/../config/database.php';

handleCors();

try {
    $db = getDB();
    $db->query('SELECT 1');
    jsonResponse([
        'success' => true,
        'message' => 'OK',
        'database' => DB_NAME,
        'server_time' => date('Y-m-d H:i:s'),
    ]);
} catch (Throwable $e) {
    jsonResponse([
        'success' => false,
        'message' => 'DB connection failed',
        'error' => $e->getMessage(),
    ], 500);
}
