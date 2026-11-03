<?php
require_once __DIR__ . "/database.php";

class MissingPlanogramImageException extends RuntimeException {}

function loadPlan(PDO $db, ?string $id = null, bool $withImage = true): ?array
{
    if ($id !== null && !preg_match('/^P(?:0[1-9]|[1-9][0-9]{1,17})$/D', $id)) {
        throw new InvalidArgumentException("Invalid planogram id");
    }
    $stmt = $db->prepare(
        $id === null
            ? "SELECT * FROM planograms ORDER BY created_at DESC, CAST(SUBSTRING(id,2) AS UNSIGNED) DESC"
            : "SELECT * FROM planograms WHERE id = ?",
    );
    $stmt->execute($id === null ? [] : [$id]);
    $row = null;
    foreach ($stmt as $candidate) {
        if ($withImage) {
            $candidatePath = dirname(__DIR__, 2) . "/" . $candidate["reference_image_path"];
            if (!is_file($candidatePath)) {
                if ($id !== null) {
                    throw new MissingPlanogramImageException(
                        "รูปอ้างอิงของแผนนี้หายไป กรุณาสร้างแผนใหม่",
                    );
                }
                continue;
            }
        }
        $row = $candidate;
        break;
    }
    if (!$row) {
        return null;
    }
    $plan = [
        "id" => $row["id"],
        "version" => (int) $row["schema_version"],
        "name" => $row["name"],
        "ratio" => $row["reference_width"] / $row["reference_height"],
        "reference_width" => (int) $row["reference_width"],
        "reference_height" => (int) $row["reference_height"],
        "overlap_threshold" => (float) $row["overlap_threshold"],
        "shelves" => [],
    ];
    if ($withImage) {
        $path = dirname(__DIR__, 2) . "/" . $row["reference_image_path"];
        $image = file_get_contents($path);
        if ($image === false) {
            throw new MissingPlanogramImageException(
                "อ่านรูปอ้างอิงของแผนไม่สำเร็จ กรุณาสร้างแผนใหม่",
            );
        }
        $plan["image"] = "data:image/jpeg;base64," . base64_encode($image);
    }
    $stmt = $db->prepare("SELECT * FROM planogram_regions WHERE planogram_id = ? ORDER BY id");
    $stmt->execute([$row["id"]]);
    foreach ($stmt as $region) {
        $points = [];
        for ($i = 1; $i <= 4; $i++) {
            $points[] = [(float) $region["x" . $i], (float) $region["y" . $i]];
        }
        $plan["shelves"][] = [
            "id" => $region["id"],
            "name" => $region["name"],
            "product" => $region["product_class"],
            "points" => $points,
        ];
    }
    return $plan;
}

function catalogId(PDO $db, string $class): ?int
{
    $stmt = $db->prepare("SELECT id FROM products WHERE yolo_class_name = ?");
    $stmt->execute([$class]);
    $id = $stmt->fetchColumn();
    return $id === false ? null : (int) $id;
}

function savePlan(PDO $db, array &$plan): void
{
    $bytes = base64_decode(explode(",", $plan["image"], 2)[1], true);
    $size = $bytes === false ? false : getimagesizefromstring($bytes);
    if (!$size) {
        throw new InvalidArgumentException("Invalid reference image");
    }
    // Each new plan version owns its region IDs, starting at R01.
    foreach ($plan["shelves"] as $index => &$region) {
        $region["id"] = sprintf("R%02d", $index + 1);
    }
    unset($region);
    // Allocate inside the same transaction: concurrent saves lock this counter
    // row, and deleting a plan never causes its number to be reused.
    $db->beginTransaction();
    $path = null;
    try {
        $stmt = $db->prepare("SELECT next_value FROM app_counters WHERE name = 'planogram' FOR UPDATE");
        $stmt->execute();
        $number = $stmt->fetchColumn();
        if ($number === false || (int) $number < 1 || (int) $number >= PHP_INT_MAX) {
            throw new RuntimeException("Invalid planogram counter; run the database migration");
        }
        $db->exec("UPDATE app_counters SET next_value = next_value + 1 WHERE name = 'planogram'");
        $plan["id"] = sprintf("P%02d", (int) $number);
        $relative = "storage/planograms/" . $plan["id"] . ".jpg";
        $path = dirname(__DIR__, 2) . "/" . $relative;
        if (!is_dir(dirname($path)) && !mkdir(dirname($path), 0775, true)) {
            throw new RuntimeException("Cannot create image directory");
        }
        if (file_put_contents($path, $bytes, LOCK_EX) !== strlen($bytes)) {
            throw new RuntimeException("Cannot save reference image");
        }
        $stmt = $db->prepare(
            "INSERT INTO planograms (id,name,schema_version,reference_image_path,reference_width,reference_height) VALUES (?,?,?,?,?,?)",
        );
        $stmt->execute([
            $plan["id"],
            $plan["name"],
            $plan["version"],
            $relative,
            $size[0],
            $size[1],
        ]);
        $stmt = $db->prepare(
            "INSERT INTO planogram_regions (planogram_id,id,name,product_id,product_class,x1,y1,x2,y2,x3,y3,x4,y4) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        );
        foreach ($plan["shelves"] as $region) {
            $coordinates = array_merge(...$region["points"]);
            $stmt->execute(
                array_merge(
                    [
                        $plan["id"],
                        $region["id"],
                        $region["name"],
                        catalogId($db, $region["product"]),
                        $region["product"],
                    ],
                    $coordinates,
                ),
            );
        }
        $db->commit();
    } catch (Throwable $error) {
        if ($db->inTransaction()) {
            $db->rollBack();
        }
        if ($path !== null && is_file($path)) {
            unlink($path);
        }
        throw $error;
    }
}

function deletePlan(PDO $db, string $id): bool
{
    if (!preg_match('/^P(?:0[1-9]|[1-9][0-9]{1,17})$/D', $id)) {
        throw new InvalidArgumentException("Invalid planogram id");
    }
    $stmt = $db->prepare("SELECT reference_image_path FROM planograms WHERE id = ?");
    $stmt->execute([$id]);
    $relativePath = $stmt->fetchColumn();
    if ($relativePath === false) {
        return false;
    }

    $stmt = $db->prepare("SELECT COUNT(*) FROM detection_runs WHERE planogram_id = ?");
    $stmt->execute([$id]);
    if ((int) $stmt->fetchColumn() > 0) {
        throw new DomainException("แผนนี้มีประวัติการตรวจอ้างอิงอยู่ จึงลบไม่ได้");
    }

    $db->beginTransaction();
    try {
        $stmt = $db->prepare("DELETE FROM planogram_regions WHERE planogram_id = ?");
        $stmt->execute([$id]);
        $stmt = $db->prepare("DELETE FROM planograms WHERE id = ?");
        $stmt->execute([$id]);
        $db->commit();
    } catch (Throwable $error) {
        if ($db->inTransaction()) {
            $db->rollBack();
        }
        throw $error;
    }

    $path = dirname(__DIR__, 2) . "/" . $relativePath;
    if (is_file($path)) {
        @unlink($path);
    }
    return true;
}

function saveDetection(PDO $db, array $result, ?string $planId): int
{
    $db->beginTransaction();
    try {
        $stmt = $db->prepare(
            "INSERT INTO detection_runs (planogram_id,input_image_path,result_image_path,image_width,image_height,product_confidence,gap_confidence,product_model,gap_model) VALUES (?,?,?,?,?,?,?,?,?)",
        );
        $stmt->execute([
            $planId,
            $result["input_image_path"],
            $result["result_image_path"],
            $result["image_width"],
            $result["image_height"],
            $result["product_confidence"],
            $result["gap_confidence"],
            $result["product_model"],
            $result["gap_model"],
        ]);
        $id = (int) $db->lastInsertId();
        $stmt = $db->prepare(
            "INSERT INTO detected_products (detection_run_id,product_id,class_name,confidence,x1,y1,x2,y2,planogram_id,region_id,expected_class,placement_status,association_method,overlap_ratio) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        );
        foreach ($result["products"] as $item) {
            $stmt->execute(
                array_merge(
                    [
                        $id,
                        catalogId($db, $item["class_name"]),
                        $item["class_name"],
                        $item["confidence"],
                    ],
                    $item["box"],
                    [
                        $planId,
                        $item["region_id"] ?? null,
                        $item["expected_class"] ?? null,
                        $item["placement_status"] ?? "unchecked",
                        $item["association_method"] ?? null,
                        $item["overlap_ratio"] ?? null,
                    ],
                ),
            );
        }
        $stmt = $db->prepare(
            "INSERT INTO detected_gaps (detection_run_id,gap_number,planogram_id,region_id,product_class,confidence,association_method,overlap_ratio,x1,y1,x2,y2) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        );
        foreach ($result["gaps"] as $item) {
            $stmt->execute(
                array_merge(
                    [
                        $id,
                        $item["gap_number"],
                        $planId,
                        $item["shelf_id"],
                        $item["product_class"],
                        $item["confidence"],
                        $item["association_method"],
                        $item["overlap_ratio"] ?? null,
                    ],
                    $item["box"],
                ),
            );
        }
        $db->commit();
        return $id;
    } catch (Throwable $error) {
        if ($db->inTransaction()) {
            $db->rollBack();
        }
        throw $error;
    }
}

function clearDetectionHistory(PDO $db, string $projectRoot): array
{
    $db->beginTransaction();
    try {
        $runs = $db
            ->query("SELECT input_image_path, result_image_path FROM detection_runs")
            ->fetchAll();
        $deletedRuns = (int) $db->exec("DELETE FROM detection_runs");
        $db->commit();
    } catch (Throwable $error) {
        if ($db->inTransaction()) {
            $db->rollBack();
        }
        throw $error;
    }

    // ALTER TABLE commits implicitly in MySQL, so reset only after the delete commits.
    $runNumberReset = false;
    try {
        $db->exec("ALTER TABLE detection_runs AUTO_INCREMENT = 1");
        $runNumberReset = true;
    } catch (Throwable $error) {
        error_log("Cannot reset detection run numbering: " . $error->getMessage());
    }

    $deletedFiles = 0;
    $failedFiles = 0;
    $paths = [];
    foreach ($runs as $run) {
        $paths[$run["input_image_path"]] = true;
        $paths[$run["result_image_path"]] = true;
        if (
            preg_match(
                '~^storage/results/([a-f0-9]{32})\.jpg$~D',
                $run["result_image_path"],
                $match,
            )
        ) {
            $paths["storage/results/" . $match[1] . "-aligned.png"] = true;
        }
    }
    foreach (array_keys($paths) as $relative) {
        // Only files created for detection runs may be removed; planogram images stay intact.
        if (
            !preg_match(
                '~^storage/(uploads|results)/[a-f0-9]{32}\.(jpg|jpeg|png|webp)$~iD',
                $relative,
            ) &&
            !preg_match('~^storage/results/[a-f0-9]{32}-aligned\.png$~iD', $relative)
        ) {
            ++$failedFiles;
            continue;
        }
        $path = $projectRoot . "/" . $relative;
        if (!is_file($path)) {
            continue;
        }
        if (@unlink($path)) {
            ++$deletedFiles;
        } else {
            ++$failedFiles;
        }
    }

    return [
        "deleted_runs" => $deletedRuns,
        "deleted_files" => $deletedFiles,
        "failed_files" => $failedFiles,
        "run_number_reset" => $runNumberReset,
    ];
}

function databaseApiError(Throwable $error): void
{
    if ($error instanceof DomainException) {
        jsonResponse(["success" => false, "message" => $error->getMessage()], 409);
    }
    if ($error instanceof MissingPlanogramImageException) {
        jsonResponse(["success" => false, "message" => $error->getMessage()], 410);
    }
    if ($error instanceof InvalidArgumentException || $error instanceof JsonException) {
        jsonResponse(["success" => false, "message" => $error->getMessage()], 400);
    }
    if ($error instanceof PDOException && $error->getCode() === "23000") {
        jsonResponse(
            ["success" => false, "message" => "ข้อมูลซ้ำหรือขัดกับความสัมพันธ์ในฐานข้อมูล"],
            409,
        );
    }
    error_log((string) $error);
    jsonResponse(
        ["success" => false, "message" => "ดำเนินการไม่สำเร็จ ตรวจสอบฐานข้อมูลและ server log"],
        500,
    );
}
