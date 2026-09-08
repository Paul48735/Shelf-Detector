<?php

require_once __DIR__ . '/../config/inference.php';
require_once __DIR__ . '/../config/repository.php';

handleInferenceCors();

if (!in_array(($_SERVER['REQUEST_METHOD'] ?? 'GET'), ['POST', 'PUT'], true)) {
    inferenceJsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}

try {
    $db = getDB();
    $planId = trim((string) ($_SERVER['HTTP_X_PLANOGRAM_ID'] ?? ''));
    $plan = $planId === '' ? null : loadPlan($db, $planId, false);
    if ($planId !== '' && !$plan) inferenceJsonResponse(['success' => false, 'message' => 'ไม่พบ Planogram'], 404);
    // รับ binary image โดยตรง เพื่อไม่สร้างไฟล์ชั่วคราวซ้ำใน PHP
    $imageBytes = @file_get_contents('php://input');
    if ($imageBytes === false || $imageBytes === '') {
        inferenceJsonResponse(['success' => false, 'message' => 'กรุณาเลือกไฟล์ภาพ'], 400);
    }
    if (strlen($imageBytes) > MAX_UPLOAD_SIZE) {
        inferenceJsonResponse(['success' => false, 'message' => 'ไฟล์ต้องมีขนาดไม่เกิน 10 MB'], 400);
    }

    $extension = strtolower(trim($_SERVER['HTTP_X_FILE_EXTENSION'] ?? ''));
    $mimeType = strtolower(trim(explode(';', $_SERVER['CONTENT_TYPE'] ?? '')[0]));
    if (
        !in_array($extension, ALLOWED_IMAGE_EXTENSIONS, true)
        || !in_array($mimeType, ALLOWED_IMAGE_MIME_TYPES, true)
    ) {
        inferenceJsonResponse([
            'success' => false,
            'message' => 'รองรับเฉพาะไฟล์ JPG, JPEG, PNG และ WEBP',
        ], 400);
    }
    if (@getimagesizefromstring($imageBytes) === false) {
        inferenceJsonResponse(['success' => false, 'message' => 'ไฟล์ที่อัปโหลดไม่ใช่ภาพที่อ่านได้'], 400);
    }

    $productConfidence = filter_var(
        $_SERVER['HTTP_X_PRODUCT_CONFIDENCE'] ?? '0.5',
        FILTER_VALIDATE_FLOAT
    );
    $gapConfidence = filter_var(
        $_SERVER['HTTP_X_GAP_CONFIDENCE'] ?? '0.5',
        FILTER_VALIDATE_FLOAT
    );

    if (
        $productConfidence === false
        || $productConfidence < 0.01
        || $productConfidence > 1.0
        || $gapConfidence === false
        || $gapConfidence < 0.01
        || $gapConfidence > 1.0
    ) {
        inferenceJsonResponse([
            'success' => false,
            'message' => 'Confidence ต้องอยู่ระหว่าง 0.01 ถึง 1.00',
        ], 400);
    }

    $postFields = [
        'image' => new CURLStringFile(
            $imageBytes,
            'upload.' . $extension,
            $mimeType
        ),
        'product_confidence' => (string) $productConfidence,
        'gap_confidence' => (string) $gapConfidence,
        'planogram_id' => $planId,
        'planogram' => json_encode($plan, JSON_THROW_ON_ERROR),
    ];

    [$statusCode, $response] = callAiService(
        AI_SERVICE_URL . '/predict',
        [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $postFields]
    );
    if ($statusCode === 200 && !empty($response['success'])) {
        $response['detection_run_id'] = saveDetection($db, $response, $planId ?: null);
    }
    inferenceJsonResponse($response, $statusCode ?: 502);
} catch (Throwable $error) {
    databaseApiError($error);
}
