<?php
/**
 * GET    /backend/api/shelves.php
 * GET    /backend/api/shelves.php?id=1   (+ inventory)
 * POST   create shelf | assign | unassign | update_threshold
 * PUT    update shelf / inventory threshold+capacity
 * DELETE ?id=1
 *
 * Assign:
 *   { "action":"assign", "shelf_id":1, "product_id":2, "quantity":0, "capacity":8, "low_stock_threshold":2 }
 * Unassign:
 *   { "action":"unassign", "shelf_id":1, "product_id":2 }
 * Update threshold on inventory row:
 *   { "action":"update_inventory", "inventory_id":1, "capacity":8, "low_stock_threshold":2, "quantity":3 }
 */
require_once __DIR__ . '/../config/database.php';

handleCors();

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

try {
    $db = getDB();

    if ($method === 'GET') {
        if (!empty($_GET['id'])) {
            $stmt = $db->prepare("SELECT * FROM shelves WHERE id = ?");
            $stmt->execute([(int) $_GET['id']]);
            $shelf = $stmt->fetch();
            if (!$shelf) {
                jsonResponse(['success' => false, 'message' => 'Not found'], 404);
            }

            $inv = $db->prepare("
                SELECT
                    si.id AS inventory_id,
                    si.product_id,
                    p.product_code,
                    p.product_name,
                    p.yolo_class_name,
                    si.quantity,
                    si.capacity,
                    si.low_stock_threshold,
                    si.last_detected_at,
                    si.updated_at
                FROM shelf_inventory si
                JOIN products p ON p.id = si.product_id
                WHERE si.shelf_id = ?
                ORDER BY p.product_name
            ");
            $inv->execute([(int) $_GET['id']]);
            $items = $inv->fetchAll();

            foreach ($items as &$item) {
                $item['stock_status'] = calcStockStatus(
                    (int) $item['quantity'],
                    (int) $item['low_stock_threshold'],
                    (int) $item['capacity']
                );
                $item['fill_percent'] = ((int) $item['capacity'] > 0)
                    ? round(((int) $item['quantity'] / (int) $item['capacity']) * 100, 1)
                    : 0;
            }
            unset($item);

            $shelf['inventory'] = $items;
            jsonResponse(['success' => true, 'data' => $shelf]);
        }

        $rows = $db->query("SELECT * FROM shelves ORDER BY shelf_code ASC")->fetchAll();
        jsonResponse(['success' => true, 'count' => count($rows), 'data' => $rows]);
    }

    if ($method === 'POST') {
        $in = getJsonInput();
        $action = $in['action'] ?? 'create';

        if ($action === 'assign') {
            $shelfId = (int) ($in['shelf_id'] ?? 0);
            $productId = (int) ($in['product_id'] ?? 0);
            $qty = (int) ($in['quantity'] ?? 0);
            $capacity = (int) ($in['capacity'] ?? 8);
            $threshold = (int) ($in['low_stock_threshold'] ?? 2);

            if ($shelfId <= 0 || $productId <= 0) {
                jsonResponse(['success' => false, 'message' => 'shelf_id and product_id required'], 400);
            }

            $stmt = $db->prepare("
                INSERT INTO shelf_inventory
                    (shelf_id, product_id, quantity, capacity, low_stock_threshold)
                VALUES (?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    quantity = VALUES(quantity),
                    capacity = VALUES(capacity),
                    low_stock_threshold = VALUES(low_stock_threshold)
            ");
            $stmt->execute([
                $shelfId,
                $productId,
                max(0, $qty),
                max(1, $capacity),
                max(0, $threshold),
            ]);

            jsonResponse(['success' => true, 'message' => 'Product assigned to shelf']);
        }

        if ($action === 'unassign') {
            $shelfId = (int) ($in['shelf_id'] ?? 0);
            $productId = (int) ($in['product_id'] ?? 0);
            if ($shelfId <= 0 || $productId <= 0) {
                jsonResponse(['success' => false, 'message' => 'shelf_id and product_id required'], 400);
            }
            $stmt = $db->prepare(
                "DELETE FROM shelf_inventory WHERE shelf_id = ? AND product_id = ?"
            );
            $stmt->execute([$shelfId, $productId]);
            jsonResponse(['success' => true, 'message' => 'Product removed from shelf']);
        }

        if ($action === 'update_inventory') {
            $invId = (int) ($in['inventory_id'] ?? 0);
            if ($invId <= 0) {
                jsonResponse(['success' => false, 'message' => 'inventory_id required'], 400);
            }

            $fields = [];
            $params = [];
            foreach (['quantity', 'capacity', 'low_stock_threshold'] as $col) {
                if (array_key_exists($col, $in)) {
                    $fields[] = "$col = ?";
                    $params[] = (int) $in[$col];
                }
            }
            if (!$fields) {
                jsonResponse(['success' => false, 'message' => 'No fields to update'], 400);
            }

            $params[] = $invId;
            $stmt = $db->prepare(
                "UPDATE shelf_inventory SET " . implode(', ', $fields) . " WHERE id = ?"
            );
            $stmt->execute($params);
            jsonResponse(['success' => true, 'message' => 'Inventory updated']);
        }

        $code = trim($in['shelf_code'] ?? '');
        $name = trim($in['shelf_name'] ?? '');
        if ($code === '' || $name === '') {
            jsonResponse(['success' => false, 'message' => 'shelf_code and shelf_name required'], 400);
        }

        $stmt = $db->prepare(
            "INSERT INTO shelves (shelf_code, shelf_name) VALUES (?, ?)"
        );
        $stmt->execute([$code, $name]);

        jsonResponse([
            'success' => true,
            'message' => 'Shelf created',
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
        foreach (['shelf_code', 'shelf_name'] as $col) {
            if (array_key_exists($col, $in)) {
                $fields[] = "$col = ?";
                $params[] = trim((string) $in[$col]);
            }
        }
        if (!$fields) {
            jsonResponse(['success' => false, 'message' => 'No fields to update'], 400);
        }

        $params[] = $id;
        $stmt = $db->prepare("UPDATE shelves SET " . implode(', ', $fields) . " WHERE id = ?");
        $stmt->execute($params);

        jsonResponse(['success' => true, 'message' => 'Shelf updated']);
    }

    if ($method === 'DELETE') {
        $id = (int) ($_GET['id'] ?? 0);
        if ($id <= 0) {
            jsonResponse(['success' => false, 'message' => 'id required'], 400);
        }
        $stmt = $db->prepare("DELETE FROM shelves WHERE id = ?");
        $stmt->execute([$id]);
        jsonResponse(['success' => true, 'message' => 'Shelf deleted']);
    }

    jsonResponse(['success' => false, 'message' => 'Method not allowed'], 405);
} catch (Throwable $e) {
    jsonResponse([
        'success' => false,
        'message' => 'Database error',
        'error' => $e->getMessage(),
    ], 500);
}
