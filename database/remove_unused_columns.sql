-- Apply once to the legacy shelf_detection_v2 schema after backing it up.
-- The current application uses standalone plans and detects the uploaded image
-- directly; it no longer reads or writes these three legacy columns.
USE shelf_detection_v2;

-- Preserve the old view label before removing multi-view metadata.
UPDATE planograms
SET name = CONCAT(LEFT(name, 75), ' · ', LEFT(view_name, 22))
WHERE group_id IS NOT NULL AND TRIM(view_name) <> '';

ALTER TABLE planograms
  DROP FOREIGN KEY fk_plan_group,
  DROP INDEX idx_plan_group_view,
  DROP COLUMN group_id,
  DROP COLUMN view_name;

ALTER TABLE detection_runs
  DROP COLUMN original_image_path;
