<?php
if (PHP_SAPI !== 'cli') { http_response_code(404); exit; }
require_once __DIR__ . '/config/repository.php';
function verify(bool $condition, string $message): void {
    if (!$condition) throw new RuntimeException($message);
}
$db = getDB();
// Connection-local tables shadow the real tables; no production rows are changed.
foreach (['products','planograms','planogram_regions','detection_runs','detected_products','detected_gaps'] as $table) {
    $definition = $db->query("SHOW CREATE TABLE $table")->fetch(PDO::FETCH_NUM)[1];
    $definition = str_replace('CREATE TABLE', 'CREATE TEMPORARY TABLE', $definition);
    $definition = preg_replace('/^.*FOREIGN KEY.*\R/m', '', $definition);
    $definition = preg_replace('/,\s*\) ENGINE/', '\n) ENGINE', $definition);
    $db->exec($definition);
}
$id = bin2hex(random_bytes(16));
$bytes = base64_decode('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAIBAQEBAQIBAQECAgICAgQDAgICAgUEBAMEBgUGBgYFBgYGBwkIBgcJBwYGCAsICQoKCgoKBggLDAsKDAkKCgr/2wBDAQICAgICAgUDAwUKBwYHCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgr/wAARCAAKAAoDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD+f+iiigD/2Q==');
$plan = ['id'=>$id,'version'=>1,'name'=>'API test','image'=>'data:image/jpeg;base64,'.base64_encode($bytes),
    'shelves'=>[['id'=>'upper','name'=>'Upper','product'=>'test-a','target'=>3,'points'=>[[0,0],[1,0],[1,1],[0,1]]]]];
$imagePath = dirname(__DIR__) . '/storage/planograms/' . $id . '.jpg';
try {
    $db->exec("INSERT INTO products (product_code,product_name,yolo_class_name) VALUES ('test','Test','test-a')");
    savePlan($db, $plan);
    $loaded = loadPlan($db, $id);
    verify($loaded['shelves'][0]['product'] === 'test-a' && $loaded['ratio'] === 1, 'Plan round trip');
    verify(loadPlan($db, $id, false)['id'] === $id, 'Inference plan read');
    $result = ['input_image_path'=>'storage/uploads/test.jpg','result_image_path'=>'storage/results/test.jpg',
        'image_width'=>100,'image_height'=>100,'product_confidence'=>.5,'gap_confidence'=>.5,
        'product_model'=>'test','gap_model'=>'test',
        'products'=>[['class_name'=>'test-a','confidence'=>.9,'box'=>[1,1,10,10]]],
        'gaps'=>[['gap_number'=>1,'shelf_id'=>'upper','product_class'=>'test-a','confidence'=>.8,
            'association_method'=>'planogram','overlap_ratio'=>1,'box'=>[20,20,40,40]]]];
    $run = saveDetection($db, $result, $id);
    verify((int)$db->query('SELECT COUNT(*) FROM detected_gaps')->fetchColumn() === 1, 'Gap saved');
    verify((int)$db->query('SELECT COUNT(*) FROM detected_products')->fetchColumn() === 1, 'Product saved');
    $bad = $result; $bad['gaps'][] = $bad['gaps'][0];
    try { saveDetection($db, $bad, $id); throw new RuntimeException('Expected duplicate gap failure'); }
    catch (PDOException $expected) {}
    verify((int)$db->query('SELECT COUNT(*) FROM detection_runs')->fetchColumn() === 1, 'Failed run rolled back');
    verify((int)$db->query('SELECT COUNT(*) FROM detected_products')->fetchColumn() === 1, 'Failed products rolled back');
    $result['gaps'][0]['shelf_id'] = null; $result['gaps'][0]['product_class'] = null;
    $result['gaps'][0]['association_method'] = 'no-planogram'; unset($result['gaps'][0]['overlap_ratio']);
    saveDetection($db, $result, null);
    verify((int)$db->query('SELECT COUNT(*) FROM detected_gaps WHERE product_class IS NULL')->fetchColumn() === 1, 'Unknown gap saved');
    echo "PASS: plan round trip, detection save, unknown gap, transaction rollback\n";
} finally {
    if (is_file($imagePath)) unlink($imagePath);
}
