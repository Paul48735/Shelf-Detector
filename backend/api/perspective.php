<?php

require_once __DIR__ . '/../config/inference.php';
require_once __DIR__ . '/../config/repository.php';

handleInferenceCors();
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    inferenceJsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}

try {
    $planId = trim((string) ($_POST['planogram_id'] ?? ''));
    if (!preg_match('/^[a-f0-9]{32}$/D', $planId)) {
        inferenceJsonResponse(['success' => false, 'message' => 'กรุณาเลือก Planogram'], 400);
    }
    $plan = loadPlan(getDB(), $planId, true);
    if ($plan === null) {
        inferenceJsonResponse(['success' => false, 'message' => 'ไม่พบ Planogram'], 404);
    }
    $file = $_FILES['image'] ?? null;
    if (!$file || ($file['error'] ?? null) !== UPLOAD_ERR_OK
        || ($file['size'] ?? 0) <= 0 || $file['size'] > MAX_UPLOAD_SIZE) {
        inferenceJsonResponse(['success' => false, 'message' => 'กรุณาเลือกภาพขนาดไม่เกิน 10 MB'], 400);
    }
    $extension = strtolower(pathinfo((string) $file['name'], PATHINFO_EXTENSION));
    $info = @getimagesize($file['tmp_name']);
    $mime = strtolower((string) ($info['mime'] ?? ''));
    if (!in_array($extension, ALLOWED_IMAGE_EXTENSIONS, true)
        || !in_array($mime, ALLOWED_IMAGE_MIME_TYPES, true)) {
        inferenceJsonResponse(['success' => false, 'message' => 'รองรับเฉพาะ JPG, PNG และ WEBP'], 400);
    }
    $fields = [
        'image' => new CURLFile($file['tmp_name'], $mime, 'upload.' . $extension),
        'planogram_id' => $planId,
        'planogram' => json_encode($plan, JSON_THROW_ON_ERROR),
    ];
    if (array_key_exists('corners', $_POST)) {
        $fields['corners'] = (string) $_POST['corners'];
    }
    [$status, $response] = callAiService(
        AI_SERVICE_URL . '/perspective/preview',
        [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $fields]
    );
    inferenceJsonResponse($response, $status ?: 502);
} catch (Throwable $error) {
    databaseApiError($error);
}
