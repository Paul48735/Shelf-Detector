<?php
require_once __DIR__ . '/../config/repository.php';
handleCors();
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
try {
    $db = getDB();
    if ($method === 'GET') {
        if (isset($_GET['id'])) {
            $stmt = $db->prepare('SELECT * FROM products WHERE id = ?');
            $stmt->execute([$_GET['id']]);
            $row = $stmt->fetch();
            jsonResponse(['success' => (bool)$row, 'data' => $row ?: null], $row ? 200 : 404);
        }
        $stmt = $db->prepare('SELECT * FROM products WHERE product_name LIKE ? OR yolo_class_name LIKE ? ORDER BY id DESC LIMIT 100');
        $term = '%' . ($_GET['q'] ?? '') . '%';
        $stmt->execute([$term, $term]);
        jsonResponse(['success' => true, 'data' => $stmt->fetchAll()]);
    }
    if (!in_array($method, ['POST', 'PUT', 'DELETE'], true)) jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
    $input = json_decode(file_get_contents('php://input') ?: '{}', true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($input)) throw new InvalidArgumentException('Expected JSON object');
    $id = filter_var($input['id'] ?? $_GET['id'] ?? null, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
    if ($method !== 'POST' && !$id) throw new InvalidArgumentException('id required');
    if ($method === 'DELETE') {
        $stmt = $db->prepare('DELETE FROM products WHERE id = ?');
        $stmt->execute([$id]);
        jsonResponse(['success' => $stmt->rowCount() > 0], $stmt->rowCount() ? 200 : 404);
    }
    $fields = [];
    $values = [];
    foreach (['product_code' => 50, 'product_name' => 100, 'yolo_class_name' => 100] as $field => $max) {
        if ($method === 'PUT' && !array_key_exists($field, $input)) continue;
        $value = $input[$field] ?? null;
        if (!is_string($value) || trim($value) === '' || mb_strlen(trim($value), 'UTF-8') > $max) throw new InvalidArgumentException('Invalid ' . $field);
        $fields[] = $field; $values[] = trim($value);
    }
    if (!$fields) throw new InvalidArgumentException('No fields to update');
    if ($method === 'POST') {
        $stmt = $db->prepare('INSERT INTO products (product_code,product_name,yolo_class_name) VALUES (?,?,?)');
        $stmt->execute($values);
        jsonResponse(['success' => true, 'id' => (int)$db->lastInsertId()], 201);
    }
    $stmt = $db->prepare('SELECT id FROM products WHERE id = ?'); $stmt->execute([$id]);
    if (!$stmt->fetch()) jsonResponse(['success' => false, 'message' => 'Not found'], 404);
    $stmt = $db->prepare('UPDATE products SET ' . implode(',', array_map(fn($field) => "$field = ?", $fields)) . ' WHERE id = ?');
    $stmt->execute(array_merge($values, [$id]));
    jsonResponse(['success' => true, 'id' => $id]);
} catch (Throwable $error) { databaseApiError($error); }
