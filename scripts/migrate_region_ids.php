<?php
// CLI only. Back up first, then run: php scripts/migrate_region_ids.php <backup.sql>
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
$db->beginTransaction();
try {
    // Share the savePlan lock so a concurrent save cannot change the dataset.
    $db->query("SELECT next_value FROM app_counters WHERE name='planogram' FOR UPDATE")->fetchColumn();
    $rows = $db->query('SELECT planogram_id,id FROM planogram_regions ORDER BY planogram_id,id FOR UPDATE')->fetchAll();
    $next = $mapping = $counts = [];
    foreach (['planogram_regions','detected_products','detected_gaps'] as $table) {
        $counts[$table] = (int) $db->query("SELECT COUNT(*) FROM `$table`")->fetchColumn();
    }
    foreach ($rows as $row) {
        $plan = $row['planogram_id'];
        $next[$plan] = $next[$plan] ?? 1;
        if (preg_match('/^R(?:0[1-9]|[1-9][0-9]*)$/D', $row['id'])) {
            $next[$plan] = max($next[$plan], (int) substr($row['id'],1) + 1);
        }
    }
    $db->exec('SET SESSION FOREIGN_KEY_CHECKS=0');
    foreach ($rows as $row) {
        $plan = $row['planogram_id'];
        $old = $row['id'];
        if (preg_match('/^R(?:0[1-9]|[1-9][0-9]*)$/D', $old)) {
            continue;
        }
        $new = sprintf('R%02d', $next[$plan]++);
        $mapping[$plan][$old] = $new;
        foreach (['planogram_regions'=>'id', 'detected_products'=>'region_id', 'detected_gaps'=>'region_id'] as $table=>$column) {
            $stmt = $db->prepare("UPDATE `$table` SET `$column`=? WHERE planogram_id=? AND `$column`=?");
            $stmt->execute([$new,$plan,$old]);
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

    foreach ($counts as $table=>$count) {
        if ((int) $db->query("SELECT COUNT(*) FROM `$table`")->fetchColumn() !== $count) {
            throw new RuntimeException('Row count changed: ' . $table);
        }
    }
    if (file_put_contents($backup . '.region-ids.json', json_encode($mapping, JSON_PRETTY_PRINT)) === false) {
        throw new RuntimeException('Cannot save region ID mapping');
    }
    $db->commit();
    foreach ($mapping as $plan=>$regions) {
        echo $plan, ': migrated ', count($regions), " regions\n";
    }
    echo "PASS: row counts and all foreign keys preserved\n";
} catch (Throwable $error) {
    if ($db->inTransaction()) $db->rollBack();
    throw $error;
} finally {
    $db->exec('SET SESSION FOREIGN_KEY_CHECKS=1');
}
