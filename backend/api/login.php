<?php
/**
 * POST /backend/api/login.php
 * Body: { "username": "admin", "password": "admin1234" }
 * Response: { "success": true, "token": "...", "user": { "id": 1, "username": "admin", "role": "admin" } }
 */
require_once __DIR__ . '/../config/database.php';

handleCors();

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'POST') {
    jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}

try {
    $in = getJsonInput();
    $username = trim($in['username'] ?? '');
    $password = (string) ($in['password'] ?? '');

    if ($username === '' || $password === '') {
        jsonResponse(['success' => false, 'message' => 'username and password required'], 400);
    }

    $db = getDB();
    $stmt = $db->prepare("SELECT id, username, password_hash, role FROM users WHERE username = ?");
    $stmt->execute([$username]);
    $user = $stmt->fetch();

    if (!$user || !password_verify($password, $user['password_hash'])) {
        jsonResponse(['success' => false, 'message' => 'Invalid credentials'], 401);
    }

    $token = generateJwt([
        'sub' => (int) $user['id'],
        'username' => $user['username'],
        'role' => $user['role'],
    ]);

    jsonResponse([
        'success' => true,
        'token' => $token,
        'user' => [
            'id' => (int) $user['id'],
            'username' => $user['username'],
            'role' => $user['role'],
        ],
    ]);
} catch (Throwable $e) {
    jsonResponse([
        'success' => false,
        'message' => 'Server error',
        'error' => $e->getMessage(),
    ], 500);
}
