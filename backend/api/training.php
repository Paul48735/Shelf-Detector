<?php
require_once __DIR__ . '/../config/inference.php';

function trainingOriginAllowed(): bool
{
    $origin = trim((string)($_SERVER['HTTP_ORIGIN'] ?? ''));
    if ($origin === '') return true;
    $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
    $expected = strtolower($scheme . '://' . ($_SERVER['HTTP_HOST'] ?? ''));
    return hash_equals($expected, strtolower($origin));
}

function trainingResponse(array $data, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Vary: Origin');
    if (trainingOriginAllowed() && !empty($_SERVER['HTTP_ORIGIN'])) {
        header('Access-Control-Allow-Origin: ' . $_SERVER['HTTP_ORIGIN']);
    }
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'OPTIONS') {
    if (!trainingOriginAllowed()) trainingResponse(['success' => false, 'message' => 'Invalid origin'], 403);
    header('Access-Control-Allow-Methods: GET, POST, PUT, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');
    http_response_code(204);
    exit;
}
if (!trainingOriginAllowed()) {
    trainingResponse(['success' => false, 'message' => 'Invalid origin'], 403);
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$action = $_GET['action'] ?? '';
$id = trim((string)($_GET['id'] ?? ''));

if ($id !== '' && !preg_match('/^[a-f0-9]{32}$/D', $id)) {
    trainingResponse(['success' => false, 'message' => 'รหัสข้อมูลไม่ถูกต้อง'], 400);
}

try {
    if ($method === 'GET') {
        $url = match ($action) {
            'classes' => AI_SERVICE_URL . '/training/classes',
            'images' => AI_SERVICE_URL . '/training/images',
            'models' => AI_SERVICE_URL . '/training/models',
            'image' => $id === '' ? '' : AI_SERVICE_URL . '/training/images/' . rawurlencode($id),
            'job' => AI_SERVICE_URL . '/training/jobs/' . ($id === '' ? 'latest' : rawurlencode($id)),
            default => '',
        };
        if ($url === '') trainingResponse(['success' => false, 'message' => 'ไม่พบคำสั่งที่ร้องขอ'], 404);
        [$status, $response] = callAiService($url);
        trainingResponse($response, $status ?: 502);
    }

    if ($method === 'POST' && in_array($action, ['image', 'pending-image'], true)) {
        $file = $_FILES['image'] ?? null;
        if (!$file || ($file['error'] ?? UPLOAD_ERR_NO_FILE) !== UPLOAD_ERR_OK) {
            throw new InvalidArgumentException('เลือกภาพสินค้าก่อนบันทึก');
        }
        $size = (int)($file['size'] ?? 0);
        $extension = strtolower(pathinfo((string)($file['name'] ?? ''), PATHINFO_EXTENSION));
        $imageInfo = @getimagesize($file['tmp_name'] ?? '');
        $mime = strtolower((string)($imageInfo['mime'] ?? ''));
        if ($size <= 0 || $size > MAX_UPLOAD_SIZE) {
            throw new InvalidArgumentException('ภาพต้องมีขนาดไม่เกิน 10 MB');
        }
        if (!in_array($extension, ALLOWED_IMAGE_EXTENSIONS, true)
            || !in_array($mime, ALLOWED_IMAGE_MIME_TYPES, true)) {
            throw new InvalidArgumentException('รองรับภาพ JPG, PNG และ WEBP');
        }
        $annotations = '[]';
        if ($action === 'image') {
            $annotations = (string)($_POST['annotations'] ?? '');
            if (!is_array(json_decode($annotations, true))) {
                throw new InvalidArgumentException('ข้อมูลกรอบสินค้าไม่ถูกต้อง');
            }
        }
        $fields = [
            'image' => new CURLFile($file['tmp_name'], $mime, 'training.' . $extension),
            'annotations' => $annotations,
        ];
        $aiPath = $action === 'pending-image' ? '/training/images/pending' : '/training/images';
        [$status, $response] = callAiService(
            AI_SERVICE_URL . $aiPath,
            [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $fields]
        );
        trainingResponse($response, $status ?: 502);
    }

    if ($method === 'PUT' && $action === 'annotations' && $id !== '') {
        $body = file_get_contents('php://input', false, null, 0, 256 * 1024 + 1);
        if ($body === false || strlen($body) > 256 * 1024) {
            trainingResponse(['success' => false, 'message' => 'ข้อมูลกรอบสินค้ามีขนาดเกินกำหนด'], 413);
        }
        [$status, $response] = callAiService(
            AI_SERVICE_URL . '/training/images/' . rawurlencode($id),
            [CURLOPT_CUSTOMREQUEST => 'PUT', CURLOPT_POSTFIELDS => $body,
                CURLOPT_HTTPHEADER => ['Content-Type: application/json']]
        );
        trainingResponse($response, $status ?: 502);
    }

    if ($method === 'POST' && $action === 'start') {
        $body = file_get_contents('php://input', false, null, 0, 16 * 1024 + 1);
        if ($body === false || strlen($body) > 16 * 1024) {
            trainingResponse(['success' => false, 'message' => 'คำขอไม่ถูกต้อง'], 413);
        }
        [$status, $response] = callAiService(
            AI_SERVICE_URL . '/training/jobs',
            [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body,
                CURLOPT_HTTPHEADER => ['Content-Type: application/json']]
        );
        trainingResponse($response, $status ?: 502);
    }

    if ($method === 'POST' && $action === 'activate' && $id !== '') {
        [$status, $response] = callAiService(
            AI_SERVICE_URL . '/training/jobs/' . rawurlencode($id) . '/activate',
            [CURLOPT_POST => true, CURLOPT_POSTFIELDS => '{}',
                CURLOPT_HTTPHEADER => ['Content-Type: application/json']]
        );
        trainingResponse($response, $status ?: 502);
    }

    if ($method === 'POST' && $action === 'activate-model') {
        $body = file_get_contents('php://input', false, null, 0, 16 * 1024 + 1);
        if ($body === false || strlen($body) > 16 * 1024) {
            trainingResponse(['success' => false, 'message' => 'คำขอไม่ถูกต้อง'], 413);
        }
        [$status, $response] = callAiService(
            AI_SERVICE_URL . '/training/models/activate',
            [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body,
                CURLOPT_HTTPHEADER => ['Content-Type: application/json']]
        );
        trainingResponse($response, $status ?: 502);
    }

    trainingResponse(['success' => false, 'message' => 'Method not allowed'], 405);
} catch (InvalidArgumentException $error) {
    trainingResponse(['success' => false, 'message' => $error->getMessage()], 400);
} catch (Throwable $error) {
    trainingResponse(['success' => false, 'message' => $error->getMessage()], 502);
}
