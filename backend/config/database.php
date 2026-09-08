<?php
/**
 * Database config — ค่าเดียวกับ webcam.py
 * Schema จริง:
 *   products(id, product_code, product_name, yolo_class_name, created_at, updated_at)
 *   shelves(id, shelf_code, shelf_name, created_at, updated_at)
 *   shelf_inventory(id, shelf_id, product_id, quantity, capacity, low_stock_threshold, last_detected_at, created_at, updated_at)
 */
define('DB_HOST', '127.0.0.1');
define('DB_USER', 'root');
define('DB_PASS', '48735');
define('DB_NAME', 'shelf_detection');
define('DB_CHARSET', 'utf8mb4');

define('JWT_SECRET', 'shelf_detection_secret_key_2026');
define('JWT_EXPIRES', 86400);

function getDB(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }

    $dsn = sprintf(
        'mysql:host=%s;dbname=%s;charset=%s',
        DB_HOST,
        DB_NAME,
        DB_CHARSET
    );

    $pdo = new PDO($dsn, DB_USER, DB_PASS, [
        PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES   => false,
    ]);

    return $pdo;
}

function jsonResponse(array $data, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type, Authorization');
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

function handleCors(): void
{
    if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
        header('Access-Control-Allow-Origin: *');
        header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
        header('Access-Control-Allow-Headers: Content-Type, Authorization');
        http_response_code(204);
        exit;
    }
}

function getJsonInput(): array
{
    $raw = file_get_contents('php://input');
    if (!$raw) {
        return [];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

/** quantity / capacity / low_stock_threshold อยู่ที่ shelf_inventory */
function calcStockStatus(int $qty, int $threshold, int $capacity): string
{
    if ($qty <= 0) {
        return 'Out of Stock';
    }
    if ($qty <= $threshold) {
        return 'Low Stock';
    }
    if ($qty >= $capacity) {
        return 'Full';
    }
    return 'Normal';
}

function base64UrlEncode(string $data): string
{
    return rtrim(strtr(base64_encode($data), '+/', '-_'), '=');
}

function base64UrlDecode(string $data): string
{
    $pad = strlen($data) % 4;
    if ($pad) {
        $data .= str_repeat('=', 4 - $pad);
    }
    return base64_decode(strtr($data, '-_', '+/'));
}

function generateJwt(array $payload): string
{
    $header = ['typ' => 'JWT', 'alg' => 'HS256'];
    $payload['iat'] = time();
    $payload['exp'] = time() + JWT_EXPIRES;

    $segments = [
        base64UrlEncode(json_encode($header)),
        base64UrlEncode(json_encode($payload)),
    ];
    $sig = base64UrlEncode(
        hash_hmac('sha256', implode('.', $segments), JWT_SECRET, true)
    );
    $segments[] = $sig;

    return implode('.', $segments);
}

function decodeJwt(string $token): ?array
{
    $parts = explode('.', $token);
    if (count($parts) !== 3) {
        return null;
    }

    [$headerB64, $payloadB64, $sigB64] = $parts;

    $expectedSig = base64UrlEncode(
        hash_hmac('sha256', $headerB64 . '.' . $payloadB64, JWT_SECRET, true)
    );

    if (!hash_equals($expectedSig, $sigB64)) {
        return null;
    }

    $payload = json_decode(base64UrlDecode($payloadB64), true);
    if (!is_array($payload) || empty($payload['exp']) || $payload['exp'] < time()) {
        return null;
    }

    return $payload;
}

function requireAuth(): array
{
    $header = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if (!preg_match('/^Bearer\s+(.+)$/i', $header, $m)) {
        jsonResponse(['success' => false, 'message' => 'Authorization required'], 401);
    }

    $payload = decodeJwt(trim($m[1]));
    if (!$payload) {
        jsonResponse(['success' => false, 'message' => 'Invalid or expired token'], 401);
    }

    return $payload;
}
