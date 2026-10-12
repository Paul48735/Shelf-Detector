<?php

require_once __DIR__ . '/../config/inference.php';
require_once __DIR__ . '/../config/repository.php';

handleInferenceCors();

if (!in_array(($_SERVER['REQUEST_METHOD'] ?? 'GET'), ['POST', 'PUT'], true)) {
    inferenceJsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}

try {
    $db = getDB();
    $requestedPlanId = trim((string) ($_SERVER['HTTP_X_PLANOGRAM_ID'] ?? ''));
    $plan = null;
    if ($requestedPlanId !== '') {
        if (!preg_match('/^[a-f0-9]{32}$/D', $requestedPlanId)) {
            inferenceJsonResponse(['success' => false, 'message' => 'รหัส Planogram ไม่ถูกต้อง'], 400);
        }
        $plan = loadPlan($db, $requestedPlanId, true);
        if ($plan === null) {
            inferenceJsonResponse(['success' => false, 'message' => 'ไม่พบ Planogram'], 404);
        }
    }
    $contentType = strtolower(explode(';', $_SERVER['CONTENT_TYPE'] ?? '')[0]);
    $tempFiles = [];
    $upload = static function (?array $file, string $label) {
        if (!$file || !isset($file['error']) || $file['error'] !== UPLOAD_ERR_OK) {
            throw new InvalidArgumentException($label . ': กรุณาเลือกไฟล์ภาพที่มีขนาดไม่เกิน 10 MB');
        }
        $size = (int) ($file['size'] ?? 0);
        if ($size <= 0 || $size > MAX_UPLOAD_SIZE) {
            throw new InvalidArgumentException($label . ': ไฟล์ต้องมีขนาดไม่เกิน 10 MB');
        }
        $extension = strtolower(pathinfo((string) ($file['name'] ?? ''), PATHINFO_EXTENSION));
        $info = @getimagesize($file['tmp_name'] ?? '');
        $mimeType = strtolower((string) ($info['mime'] ?? ''));
        if (
            !in_array($extension, ALLOWED_IMAGE_EXTENSIONS, true)
            || !in_array($mimeType, ALLOWED_IMAGE_MIME_TYPES, true)
        ) {
            throw new InvalidArgumentException($label . ': รองรับเฉพาะไฟล์ JPG, JPEG, PNG และ WEBP');
        }
        return [$file['tmp_name'], $mimeType, $extension];
    };

    if ($contentType === 'multipart/form-data') {
        [$imagePath, $mimeType, $extension] = $upload($_FILES['image'] ?? null, 'ภาพสำหรับตรวจ');
    } else {
        // รองรับไคลเอนต์เดิมที่ส่งภาพแบบ binary ตรงเข้ามา
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
        $imagePath = tempnam(sys_get_temp_dir(), 'shelf_');
        if ($imagePath === false) throw new RuntimeException('ไม่สามารถสร้างไฟล์ภาพชั่วคราวได้');
        $tempFiles[] = $imagePath;
        if (file_put_contents($imagePath, $imageBytes, LOCK_EX) !== strlen($imageBytes)) {
            throw new RuntimeException('ไม่สามารถเตรียมไฟล์ภาพเพื่อส่งให้ AI service ได้');
        }
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

    // CURLFile ใช้ได้ทั้งไฟล์ multipart ชั่วคราวของ PHP และไฟล์ชั่วคราวของ binary API เดิม
    try {
        $postFields = [
            'image' => new CURLFile($imagePath, $mimeType, 'upload.' . $extension),
            'product_confidence' => (string) $productConfidence,
            'gap_confidence' => (string) $gapConfidence,
            'planogram_id' => $requestedPlanId,
            'planogram' => json_encode($plan, JSON_THROW_ON_ERROR),
        ];
        if (array_key_exists('perspective_corners', $_POST)) {
            $postFields['perspective_corners'] = (string) $_POST['perspective_corners'];
        }
        [$statusCode, $response] = callAiService(
            AI_SERVICE_URL . '/predict',
            [CURLOPT_POST => true, CURLOPT_POSTFIELDS => $postFields]
        );
    } finally {
        foreach ($tempFiles as $tempFile) @unlink($tempFile);
    }
    if ($statusCode === 200 && !empty($response['success'])) {
        $resultPlanId = $response['planogram_id'] ?? null;
        if ($resultPlanId !== ($requestedPlanId === '' ? null : $requestedPlanId)) {
            inferenceJsonResponse(['success' => false, 'message' => 'ผลตรวจไม่ตรงกับ Planogram ที่เลือก'], 502);
        }
        // A failed alignment has no trustworthy Planogram coordinates. Persist
        // its visible detections as an unassociated run so product/gap rows
        // satisfy the no-planogram constraints and history stays honest.
        $savedPlanId = ($response['alignment']['status'] ?? null) === 'failed'
            ? null
            : ($requestedPlanId ?: null);
        $response['detection_run_id'] = saveDetection($db, $response, $savedPlanId);
    }
    inferenceJsonResponse($response, $statusCode ?: 502);
} catch (Throwable $error) {
    databaseApiError($error);
}
