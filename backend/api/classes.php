<?php

require_once __DIR__ . '/../config/inference.php';

handleInferenceCors();

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    inferenceJsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}

try {
    [$statusCode, $response] = callAiService(AI_SERVICE_URL . '/classes');
    inferenceJsonResponse($response, $statusCode ?: 502);
} catch (Throwable $error) {
    inferenceJsonResponse([
        'success' => false,
        'message' => $error->getMessage(),
    ], 502);
}

