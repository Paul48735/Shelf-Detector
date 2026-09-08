<?php
/**
 * GET /backend/api/auth.php
 * Header: Authorization: Bearer <token>
 * Response: { "success": true, "authenticated": true, "user_id": 1, "role": "admin" }
 *
 * ใช้สำหรับทดสอบว่า token ยังใช้ได้
 */
require_once __DIR__ . '/../config/database.php';

handleCors();

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}

try {
    $auth = requireAuth();

    jsonResponse([
        'success' => true,
        'authenticated' => true,
        'user_id' => (int) $auth['sub'],
        'username' => $auth['username'] ?? '',
        'role' => $auth['role'] ?? '',
    ]);
} catch (Throwable $e) {
    jsonResponse([
        'success' => false,
        'message' => 'Server error',
        'error' => $e->getMessage(),
    ], 500);
}
