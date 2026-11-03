<?php
require_once __DIR__ . "/../config/inference.php";
handleInferenceCors();
if (($_SERVER["REQUEST_METHOD"] ?? "") !== "POST") {
    inferenceJsonResponse(["success" => false, "message" => "Method not allowed"], 405);
}
try {
    $body = file_get_contents("php://input", false, null, 0, MAX_UPLOAD_SIZE * 2 + 1);
    if ($body === false || strlen($body) > MAX_UPLOAD_SIZE * 2) {
        inferenceJsonResponse(["success" => false, "message" => "ภาพมีขนาดเกินกำหนด"], 413);
    }
    [$status, $response] = callAiService(AI_SERVICE_URL . "/aruco/reference", [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => ["Content-Type: application/json"],
    ]);
    inferenceJsonResponse($response, $status ?: 502);
} catch (Throwable $error) {
    error_log((string) $error);
    inferenceJsonResponse(["success" => false, "message" => "เชื่อมต่อ AI service ไม่สำเร็จ"], 502);
}
