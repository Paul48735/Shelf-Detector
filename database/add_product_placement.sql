-- Run once on the existing database; existing results remain unchecked.
USE shelf_detection;
ALTER TABLE detected_products
  ADD COLUMN planogram_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  ADD COLUMN region_id VARCHAR(100) COLLATE utf8mb4_bin NULL,
  ADD COLUMN expected_class VARCHAR(100) COLLATE utf8mb4_bin NULL,
  ADD COLUMN placement_status ENUM('unchecked','correct','wrong-shelf','unmatched') NOT NULL DEFAULT 'unchecked',
  ADD COLUMN association_method ENUM('planogram','no-planogram','ambiguous-region','outside-planogram') NULL,
  ADD COLUMN overlap_ratio DECIMAL(5,4) NULL,
  ADD CONSTRAINT fk_product_run_plan FOREIGN KEY (detection_run_id,planogram_id)
    REFERENCES detection_runs(id,planogram_id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_product_region FOREIGN KEY (planogram_id,region_id,expected_class)
    REFERENCES planogram_regions(planogram_id,id,product_class) ON DELETE RESTRICT,
  ADD CONSTRAINT chk_product_placement CHECK (
    (placement_status = 'unchecked' AND expected_class IS NULL AND region_id IS NULL)
    OR (placement_status IN ('correct','wrong-shelf') AND planogram_id IS NOT NULL
      AND region_id IS NOT NULL AND expected_class IS NOT NULL
      AND association_method IS NOT NULL AND association_method = 'planogram'
      AND overlap_ratio IS NOT NULL AND overlap_ratio BETWEEN 0 AND 1
      AND ((placement_status = 'correct' AND class_name = expected_class)
        OR (placement_status = 'wrong-shelf' AND class_name <> expected_class)))
    OR (placement_status = 'unmatched' AND expected_class IS NULL AND region_id IS NULL
      AND overlap_ratio IS NULL AND association_method IS NOT NULL
      AND ((association_method = 'no-planogram' AND planogram_id IS NULL)
        OR (association_method IN ('ambiguous-region','outside-planogram') AND planogram_id IS NOT NULL)))
  );
