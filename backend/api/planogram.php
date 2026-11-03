<?php
require_once __DIR__ . "/../config/inference.php";
require_once __DIR__ . "/../config/repository.php";
handleInferenceCors();
$method = $_SERVER["REQUEST_METHOD"] ?? "GET";
if (!in_array($method, ["GET", "POST", "DELETE"], true)) {
    inferenceJsonResponse(["success" => false, "message" => "Method not allowed"], 405);
}
try {
    $db = getDB();
    if ($method === "GET") {
        if (isset($_GET["list"])) {
            $rows = $db
                ->query(
                    "SELECT id,name,created_at,reference_image_path FROM planograms ORDER BY created_at DESC,CAST(SUBSTRING(id,2) AS UNSIGNED) DESC LIMIT 1000",
                )
                ->fetchAll();
            $projectRoot = dirname(__DIR__, 2);
            $listed = [];
            $unavailableCount = 0;
            foreach ($rows as $row) {
                $row["image_available"] = is_file(
                    $projectRoot . "/" . $row["reference_image_path"],
                );
                if (!$row["image_available"]) {
                    ++$unavailableCount;
                }
                unset($row["reference_image_path"]);
                $listed[] = $row;
            }
            inferenceJsonResponse([
                "success" => true,
                "data" => $listed,
                "unavailable_count" => $unavailableCount,
            ]);
        }
        $plan = loadPlan($db, $_GET["id"] ?? null);
        if (isset($_GET["id"]) && !$plan) {
            inferenceJsonResponse(
                ["success" => false, "data" => null, "message" => "ไม่พบแผนที่ต้องการ"],
                404,
            );
        }
        inferenceJsonResponse(["success" => true, "data" => $plan]);
    }
    if ($method === "POST") {
        $body = file_get_contents("php://input", false, null, 0, MAX_UPLOAD_SIZE + 1);
        if ($body === false || strlen($body) > MAX_UPLOAD_SIZE) {
            inferenceJsonResponse(
                ["success" => false, "message" => "Planogram มีขนาดเกิน 10 MB"],
                413,
            );
        }
        $options = [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $body,
            CURLOPT_HTTPHEADER => ["Content-Type: application/json"],
        ];
    }
    if ($method === "DELETE") {
        $id = $_GET["id"] ?? "";
        if (!preg_match('/^P(?:0[1-9]|[1-9][0-9]{1,17})$/D', $id)) {
            inferenceJsonResponse(["success" => false, "message" => "รหัสแผนไม่ถูกต้อง"], 400);
        }
        if (!deletePlan($db, $id)) {
            inferenceJsonResponse(["success" => false, "message" => "ไม่พบแผนที่ต้องการลบ"], 404);
        }
        inferenceJsonResponse(["success" => true, "message" => "ลบแผนแล้ว"]);
    }
    [$status, $response] = callAiService(AI_SERVICE_URL . "/planogram/validate", $options);
    if ($status === 200 && !empty($response["success"])) {
        savePlan($db, $response["data"]);
    }
    inferenceJsonResponse($response, $status ?: 502);
} catch (Throwable $error) {
    databaseApiError($error);
}
