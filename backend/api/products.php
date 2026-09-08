<?php
/**
 * GET    /backend/api/products.php
 * GET    /backend/api/products.php?id=1
 * POST   JSON: product_code, product_name, yolo_class_name
 * PUT    JSON: id + fields
 * DELETE ?id=1  (hard delete)
 */
require_once __DIR__ . '/../config/database.php';

handleCors();

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

try {
    $db = getDB();

    if ($method === 'GET') {
        if (!empty($_GET['id'])) {
            $stmt = $db->prepare("SELECT * FROM products WHERE id = ?");
            $stmt->execute([(int) $_GET['id']]);
            $row = $stmt->fetch();
            if (!$row) {
                jsonResponse(['success' => false, 'message' => 'Not found'], 404);
            }
            jsonResponse(['success' => true, 'data' => $row]);
        }

        $sql = "SELECT * FROM products WHERE 1=1";
        $params = [];

        if (!empty($_GET['q'])) {
            $sql .= " AND (
                product_name LIKE ?
                OR product_code LIKE ?
                OR yolo_class_name LIKE ?
            )";
            $term = '%' . $_GET['q'] . '%';
            $params[] = $term;
            $params[] = $term;
            $params[] = $term;
        }

        $sql .= " ORDER BY product_code ASC";
        $stmt = $db->prepare($sql);
        $stmt->execute($params);
        $rows = $stmt->fetchAll();

        jsonResponse(['success' => true, 'count' => count($rows), 'data' => $rows]);
    }

    if ($method === 'POST') {
        $in = getJsonInput();
        $code = trim($in['product_code'] ?? '');
        $name = trim($in['product_name'] ?? '');
        $yolo = trim($in['yolo_class_name'] ?? '');

        if ($code === '' || $name === '' || $yolo === '') {
            jsonResponse([
                'success' => false,
                'message' => 'product_code, product_name, yolo_class_name required',
            ], 400);
        }

        $stmt = $db->prepare("
            INSERT INTO products (product_code, product_name, yolo_class_name)
            VALUES (?, ?, ?)
        ");
        $stmt->execute([$code, $name, $yolo]);

        jsonResponse([
            'success' => true,
            'message' => 'Product created',
            'id' => (int) $db->lastInsertId(),
        ], 201);
    }

    if ($method === 'PUT') {
        $in = getJsonInput();
        $id = (int) ($in['id'] ?? $_GET['id'] ?? 0);
        if ($id <= 0) {
            jsonResponse(['success' => false, 'message' => 'id required'], 400);
        }

        $fields = [];
        $params = [];
        foreach (['product_code', 'product_name', 'yolo_class_name'] as $col) {
            if (array_key_exists($col, $in)) {
                $fields[] = "$col = ?";
                $params[] = trim((string) $in[$col]);
            }
        }

        if (!$fields) {
            jsonResponse(['success' => false, 'message' => 'No fields to update'], 400);
        }

        $params[] = $id;
        $stmt = $db->prepare("UPDATE products SET " . implode(', ', $fields) . " WHERE id = ?");
        $stmt->execute($params);

        jsonResponse(['success' => true, 'message' => 'Product updated']);
    }

    if ($method === 'DELETE') {
        $id = (int) ($_GET['id'] ?? 0);
        if ($id <= 0) {
            jsonResponse(['success' => false, 'message' => 'id required'], 400);
        }

        $stmt = $db->prepare("DELETE FROM products WHERE id = ?");
        $stmt->execute([$id]);

        jsonResponse(['success' => true, 'message' => 'Product deleted']);
    }

    jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
} catch (Throwable $e) {
    jsonResponse([
        'success' => false,
        'message' => 'Database error',
        'error' => $e->getMessage(),
    ], 500);
}
