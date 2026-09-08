<?php
require_once __DIR__ . '/../config/inference.php';
require_once __DIR__ . '/../config/repository.php';
handleInferenceCors();
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if (!in_array($method, ['GET', 'POST'], true)) {
    inferenceJsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}
try {
    $db = getDB();
    if ($method === 'GET') {
        if (isset($_GET['list'])) {
            $rows = $db->query('SELECT id,name,created_at FROM planograms ORDER BY created_at DESC,id DESC LIMIT 100')->fetchAll();
            inferenceJsonResponse(['success' => true, 'data' => $rows]);
        }
        $plan = loadPlan($db, $_GET['id'] ?? null);
        inferenceJsonResponse(['success' => true, 'data' => $plan], isset($_GET['id']) && !$plan ? 404 : 200);
    }
    if ($method === 'POST') {
        $body = file_get_contents('php://input', false, null, 0, MAX_UPLOAD_SIZE + 1);
        if ($body === false || strlen($body) > MAX_UPLOAD_SIZE) {
            inferenceJsonResponse(['success' => false, 'message' => 'Planogram มีขนาดเกิน 10 MB'], 413);
        }
        $options = [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $body,
            CURLOPT_HTTPHEADER => ['Content-Type: application/json']];
    }
    [$status, $response] = callAiService(AI_SERVICE_URL . '/planogram/validate', $options);
    if ($status === 200 && !empty($response['success'])) savePlan($db, $response['data']);
    inferenceJsonResponse($response, $status ?: 502);
} catch (Throwable $error) {
    databaseApiError($error);
}
