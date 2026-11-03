-- Run once on an existing shelf_detection_v2 database after deploying the code change.
ALTER TABLE planogram_regions
  DROP CONSTRAINT chk_region_target,
  DROP COLUMN target_quantity;
