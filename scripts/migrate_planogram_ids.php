<?php
// Run once from the project root after taking a full mysqldump backup:
// php scripts/migrate_planogram_ids.php storage/backups/<backup>.sql
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit();
}
require_once __DIR__ . '/../backend/config/database.php';
$backup = $argv[1] ?? '';
if (!is_file($backup) || filesize($backup) < 1000) {
    throw new RuntimeException('Provide an existing full database SQL backup');
}
$db = getDB();
$db->exec("CREATE TABLE IF NOT EXISTS app_counters (
    name VARCHAR(50) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    next_value BIGINT UNSIGNED NOT NULL
) ENGINE=InnoDB");
$db->beginTransaction();
try {
    $db->exec("INSERT IGNORE INTO app_counters (name,next_value) VALUES ('planogram',1)");
    $next = (int) $db->query("SELECT next_value FROM app_counters WHERE name='planogram' FOR UPDATE")->fetchColumn();
    $plans = $db->query('SELECT id FROM planograms ORDER BY created_at,id FOR UPDATE')->fetchAll(PDO::FETCH_COLUMN);
    foreach ($plans as $id) {
        if (preg_match('/^P([0-9]+)$/D', $id, $match)) {
            $next = max($next, (int) $match[1] + 1);
        }
    }
    $mapping = [];
    foreach ($plans as $id) {
        if (preg_match('/^[a-f0-9]{32}$/D', $id)) {
            $mapping[$id] = sprintf('P%02d', $next++);
        } elseif (!preg_match('/^P(?:0[1-9]|[1-9][0-9]{1,17})$/D', $id)) {
            throw new RuntimeException('Unexpected plan ID: ' . $id);
        }
    }
    // All related keys are updated in this transaction. Reference image paths
    // stay unchanged, so existing image files do not need to be renamed.
    $db->exec('SET SESSION FOREIGN_KEY_CHECKS=0');
    foreach ($mapping as $old => $new) {
        foreach (['planograms' => 'id', 'planogram_regions' => 'planogram_id',
            'detection_runs' => 'planogram_id', 'detected_products' => 'planogram_id',
            'detected_gaps' => 'planogram_id'] as $table => $column) {
            $stmt = $db->prepare("UPDATE `$table` SET `$column`=? WHERE `$column`=?");
            $stmt->execute([$new, $old]);
        }
    }
    // Re-enabling FK checks does not validate existing rows: explicitly verify
    // every foreign key (including composite references) before committing.
    $keys = $db->query("SELECT TABLE_NAME,CONSTRAINT_NAME,COLUMN_NAME,
        REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY TABLE_NAME,CONSTRAINT_NAME,ORDINAL_POSITION")->fetchAll();
    $groups = [];
    foreach ($keys as $key) {
        $groups[$key['TABLE_NAME'] . '.' . $key['CONSTRAINT_NAME']][] = $key;
    }
    foreach ($groups as $name => $columns) {
        $join = $nonnull = [];
        foreach ($columns as $column) {
            $join[] = 'c.`' . $column['COLUMN_NAME'] . '`=p.`' . $column['REFERENCED_COLUMN_NAME'] . '`';
            $nonnull[] = 'c.`' . $column['COLUMN_NAME'] . '` IS NOT NULL';
        }
        $first = $columns[0];
        $sql = 'SELECT COUNT(*) FROM `' . $first['TABLE_NAME'] . '` c LEFT JOIN `'
            . $first['REFERENCED_TABLE_NAME'] . '` p ON ' . implode(' AND ', $join)
            . ' WHERE ' . implode(' AND ', $nonnull) . ' AND p.`' . $first['REFERENCED_COLUMN_NAME'] . '` IS NULL';
        if ((int) $db->query($sql)->fetchColumn() !== 0) {
            throw new RuntimeException('Broken foreign key: ' . $name);
        }
    }
    $stmt = $db->prepare("UPDATE app_counters SET next_value=? WHERE name='planogram'");
    $stmt->execute([$next]);
    if (file_put_contents($backup . '.planogram-ids.json', json_encode($mapping, JSON_PRETTY_PRINT)) === false) {
        throw new RuntimeException('Cannot save ID mapping');
    }
    $db->commit();
    echo json_encode(['mapping' => $mapping, 'next_id' => sprintf('P%02d', $next)], JSON_PRETTY_PRINT), "\n";
} catch (Throwable $error) {
    if ($db->inTransaction()) {
        $db->rollBack();
    }
    throw $error;
} finally {
    $db->exec('SET SESSION FOREIGN_KEY_CHECKS=1');
}
