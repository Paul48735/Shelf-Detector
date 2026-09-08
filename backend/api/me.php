<?php
/**
 * GET /backend/api/me.php
 * Header: Authorization: Bearer <token>
 * Response: { "success": true, "user": { "id": 1, "username": "admin", "role": "admin" } }
 */
require_once __DIR__ . '/../config/database.php';

handleCors();

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}

try {
    $auth = requireAuth();

    $db = getDB();
    $stmt = $db->prepare("SELECT id, username, role, created_at FROM users WHERE id = ?");
    $stmt->execute([(int) $auth['sub']]);
    $user = $stmt->fetch();

    if (!$user) {
        jsonResponse(['success' => false, 'message' => 'User not found'], 404);
    }

    jsonResponse([
        'success' => true,
        'user' => [
            'id' => (int) $user['id'],
            'username' => $user['username'],
            'role' => $user['role'],
            'created_at' => $user['created_at'],
        ],
    ]);
} catch (Throwable $e) {
    jsonResponse([
        'success' => false,
        'message' => 'Server error',
        'error' => $e->getMessage(),
    ], 500);
}
