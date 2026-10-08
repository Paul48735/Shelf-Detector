-- Run once on shelf_detection_v2 if database/add_planogram_views.sql was applied.
-- Planogram rows, reference images, regions, and detection history remain intact.
-- Preserve the old view label in each standalone plan name before removing it.
UPDATE planograms
SET name = CONCAT(LEFT(name, 75), ' · ', LEFT(view_name, 22))
WHERE group_id IS NOT NULL AND TRIM(view_name) <> '';

ALTER TABLE planograms
  DROP FOREIGN KEY fk_plan_group,
  DROP INDEX idx_plan_group_view,
  DROP COLUMN group_id,
  DROP COLUMN view_name;
