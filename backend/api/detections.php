<?php
require_once __DIR__ . '/../config/repository.php';
handleCors();
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
try {
    $db = getDB();
    if (isset($_GET['id'])) {
        $id = filter_var($_GET['id'], FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
        if (!$id) throw new InvalidArgumentException('Invalid id');
        $stmt = $db->prepare('SELECT * FROM detection_runs WHERE id = ?'); $stmt->execute([$id]);
        $run = $stmt->fetch();
        if (!$run) jsonResponse(['success' => false, 'message' => 'Not found'], 404);
        $stmt = $db->prepare('SELECT * FROM detected_products WHERE detection_run_id = ? ORDER BY id');
        $stmt->execute([$id]); $run['products'] = $stmt->fetchAll();
        $stmt = $db->prepare('SELECT * FROM detected_gaps WHERE detection_run_id = ? ORDER BY gap_number');
        $stmt->execute([$id]); $run['gaps'] = $stmt->fetchAll();
        $run['total_products'] = count($run['products']); $run['total_gaps'] = count($run['gaps']);
        $run['identified_gaps'] = count(array_filter($run['gaps'], fn($gap) => $gap['product_class'] !== null));
        $run['product_counts'] = array_count_values(array_column($run['products'], 'class_name'));
        jsonResponse(['success' => true, 'data' => $run]);
    }
    $limit = filter_var($_GET['limit'] ?? 20, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 100]]);
    $offset = filter_var($_GET['offset'] ?? 0, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0]]);
    if ($limit === false || $offset === false) throw new InvalidArgumentException('Invalid pagination');
    $stmt = $db->prepare('SELECT r.*, (SELECT COUNT(*) FROM detected_products p WHERE p.detection_run_id=r.id) AS total_products, (SELECT COUNT(*) FROM detected_gaps g WHERE g.detection_run_id=r.id) AS total_gaps FROM detection_runs r ORDER BY r.id DESC LIMIT ? OFFSET ?');
    $stmt->bindValue(1, $limit, PDO::PARAM_INT); $stmt->bindValue(2, $offset, PDO::PARAM_INT); $stmt->execute();
    jsonResponse(['success' => true, 'data' => $stmt->fetchAll(), 'limit' => $limit, 'offset' => $offset]);
} catch (Throwable $error) { databaseApiError($error); }
