<?php
require_once __DIR__ . '/../config/repository.php';
handleCors();
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
try {
    $db = getDB();
    if (isset($_GET['id'])) {
        $id = filter_var($_GET['id'], FILTER_VALIDATE_INT, ['options' => ['min_range' => 1]]);
        if (!$id) throw new InvalidArgumentException('Invalid id');
        $stmt = $db->prepare('SELECT r.*, p.name AS planogram_name FROM detection_runs r LEFT JOIN planograms p ON p.id=r.planogram_id WHERE r.id = ?'); $stmt->execute([$id]);
        $run = $stmt->fetch();
        if (!$run) jsonResponse(['success' => false, 'message' => 'Not found'], 404);
        $stmt = $db->prepare('SELECT d.*, p.name AS region_name FROM detected_products d LEFT JOIN planogram_regions p ON p.planogram_id=d.planogram_id AND p.id=d.region_id WHERE d.detection_run_id = ? ORDER BY d.id');
        $stmt->execute([$id]); $run['products'] = $stmt->fetchAll();
        $stmt = $db->prepare('SELECT d.*, p.name AS region_name FROM detected_gaps d LEFT JOIN planogram_regions p ON p.planogram_id=d.planogram_id AND p.id=d.region_id WHERE d.detection_run_id = ? ORDER BY d.gap_number');
        $stmt->execute([$id]); $run['gaps'] = $stmt->fetchAll();
        $run['total_products'] = count($run['products']); $run['total_gaps'] = count($run['gaps']);
        $run['wrong_shelf_count'] = count(array_filter($run['products'], fn($product) => $product['placement_status'] === 'wrong-shelf'));
        $run['identified_gaps'] = count(array_filter($run['gaps'], fn($gap) => $gap['product_class'] !== null));
        $run['product_counts'] = array_count_values(array_column($run['products'], 'class_name'));
        jsonResponse(['success' => true, 'data' => $run]);
    }
    $limit = filter_var($_GET['limit'] ?? 20, FILTER_VALIDATE_INT, ['options' => ['min_range' => 1, 'max_range' => 100]]);
    $offset = filter_var($_GET['offset'] ?? 0, FILTER_VALIDATE_INT, ['options' => ['min_range' => 0]]);
    if ($limit === false || $offset === false) throw new InvalidArgumentException('Invalid pagination');
    $filter = $_GET['planogram_id'] ?? '';
    if ($filter !== '' && !preg_match('/^[a-f0-9]{32}$/D', $filter)) throw new InvalidArgumentException('Invalid planogram id');
    $where = $filter === '' ? '' : ' WHERE r.planogram_id = ?';
    $stmt = $db->prepare('SELECT r.*, pl.name AS planogram_name, (SELECT COUNT(*) FROM detected_products p WHERE p.detection_run_id=r.id) AS total_products, (SELECT COUNT(*) FROM detected_products p WHERE p.detection_run_id=r.id AND p.placement_status="wrong-shelf") AS wrong_shelf_count, (SELECT COUNT(*) FROM detected_gaps g WHERE g.detection_run_id=r.id) AS total_gaps FROM detection_runs r LEFT JOIN planograms pl ON pl.id=r.planogram_id' . $where . ' ORDER BY r.id DESC LIMIT ? OFFSET ?');
    $parameter = 1;
    if ($filter !== '') $stmt->bindValue($parameter++, $filter);
    $stmt->bindValue($parameter++, $limit, PDO::PARAM_INT); $stmt->bindValue($parameter, $offset, PDO::PARAM_INT); $stmt->execute();
    jsonResponse(['success' => true, 'data' => $stmt->fetchAll(), 'limit' => $limit, 'offset' => $offset]);
} catch (Throwable $error) { databaseApiError($error); }
