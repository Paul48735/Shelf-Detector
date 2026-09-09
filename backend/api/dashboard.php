<?php
require_once __DIR__ . '/../config/repository.php';
handleCors();
if ($_SERVER['REQUEST_METHOD'] !== 'GET') {
    jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
}
try {
    $db = getDB();

    $productsStmt = $db->query('SELECT id, product_code, product_name, yolo_class_name FROM products ORDER BY product_name');
    $allProducts = $productsStmt->fetchAll();

    $latestRun = $db->query('SELECT id, detected_at FROM detection_runs ORDER BY detected_at DESC LIMIT 1')->fetch();

    $detectedMap = [];
    $lowConfidenceClasses = [];
    if ($latestRun) {
        $stmt = $db->prepare('SELECT class_name, confidence FROM detected_products WHERE detection_run_id = ?');
        $stmt->execute([$latestRun['id']]);
        foreach ($stmt as $row) {
            $class = $row['class_name'];
            $detectedMap[$class] = ($detectedMap[$class] ?? 0) + 1;
            if ((float) $row['confidence'] < 0.5) {
                $lowConfidenceClasses[$class] = true;
            }
        }
    }

    $inStock = [];
    $lowStock = [];
    $outOfStock = [];
    foreach ($allProducts as $product) {
        $class = $product['yolo_class_name'];
        if (!isset($detectedMap[$class])) {
            $outOfStock[] = [
                'id' => $product['id'],
                'product_code' => $product['product_code'],
                'product_name' => $product['product_name'],
                'yolo_class_name' => $class,
            ];
            continue;
        }
        $entry = [
            'id' => $product['id'],
            'product_code' => $product['product_code'],
            'product_name' => $product['product_name'],
            'yolo_class_name' => $class,
            'count' => $detectedMap[$class],
            'low_confidence' => isset($lowConfidenceClasses[$class]),
        ];
        if ($entry['low_confidence']) {
            $lowStock[] = $entry;
        } else {
            $inStock[] = $entry;
        }
    }

    jsonResponse([
        'success' => true,
        'data' => [
            'latest_run_at' => $latestRun ? $latestRun['detected_at'] : null,
            'total_products' => count($allProducts),
            'in_stock_count' => count($inStock),
            'low_stock_count' => count($lowStock),
            'out_of_stock_count' => count($outOfStock),
            'in_stock' => $inStock,
            'low_stock' => $lowStock,
            'out_of_stock' => $outOfStock,
        ],
    ]);
} catch (Throwable $error) {
    databaseApiError($error);
}
