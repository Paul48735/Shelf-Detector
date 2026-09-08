-- MariaDB 10.4 (XAMPP). Import into a new/empty shelf_detection database.
-- This is a fresh schema, not a migration for existing tables.
-- Store images as files; store their relative paths here.
CREATE DATABASE IF NOT EXISTS shelf_detection
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE shelf_detection;

CREATE TABLE products (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  product_code VARCHAR(50) NOT NULL UNIQUE,
  product_name VARCHAR(100) NOT NULL,
  yolo_class_name VARCHAR(100) COLLATE utf8mb4_bin NOT NULL UNIQUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Each save creates a new immutable plan version (time-ordered ID from Python).
-- Keep versions referenced by detection_runs; do not overwrite their regions.
CREATE TABLE planograms (
  id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  schema_version SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  reference_image_path VARCHAR(500) NOT NULL,
  reference_width INT UNSIGNED NOT NULL,
  reference_height INT UNSIGNED NOT NULL,
  overlap_threshold DECIMAL(5,4) NOT NULL DEFAULT 0.7000,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_plan_dimensions CHECK (reference_width > 0 AND reference_height > 0),
  CONSTRAINT chk_plan_overlap CHECK (overlap_threshold > 0 AND overlap_threshold <= 1),
  INDEX idx_plan_created (created_at)
) ENGINE=InnoDB;

-- Frontend shelves[].id and gap.shelf_id are REGION identifiers, not stock shelf IDs.
-- Coordinates are normalized 0..1, in order around a convex four-corner polygon.
-- The application must also validate convexity and reject crossing edges.
CREATE TABLE planogram_regions (
  planogram_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
  name VARCHAR(100) NOT NULL,
  product_id INT UNSIGNED NULL,
  product_class VARCHAR(100) COLLATE utf8mb4_bin NOT NULL COMMENT 'Class snapshot at plan save time',
  target_quantity SMALLINT UNSIGNED NOT NULL,
  x1 DECIMAL(10,8) NOT NULL, y1 DECIMAL(10,8) NOT NULL,
  x2 DECIMAL(10,8) NOT NULL, y2 DECIMAL(10,8) NOT NULL,
  x3 DECIMAL(10,8) NOT NULL, y3 DECIMAL(10,8) NOT NULL,
  x4 DECIMAL(10,8) NOT NULL, y4 DECIMAL(10,8) NOT NULL,
  PRIMARY KEY (planogram_id, id),
  UNIQUE KEY uq_region_class (planogram_id, id, product_class),
  CONSTRAINT fk_region_plan FOREIGN KEY (planogram_id) REFERENCES planograms(id) ON DELETE RESTRICT,
  CONSTRAINT fk_region_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
  CONSTRAINT chk_region_target CHECK (target_quantity BETWEEN 1 AND 999),
  CONSTRAINT chk_region_coordinates CHECK (
    x1 BETWEEN 0 AND 1 AND y1 BETWEEN 0 AND 1 AND
    x2 BETWEEN 0 AND 1 AND y2 BETWEEN 0 AND 1 AND
    x3 BETWEEN 0 AND 1 AND y3 BETWEEN 0 AND 1 AND
    x4 BETWEEN 0 AND 1 AND y4 BETWEEN 0 AND 1)
) ENGINE=InnoDB;

-- One row per successfully completed image detection.
-- Save this row and all detected items in one transaction.
CREATE TABLE detection_runs (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  planogram_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  input_image_path VARCHAR(500) NOT NULL,
  result_image_path VARCHAR(500) NOT NULL,
  image_width INT UNSIGNED NOT NULL,
  image_height INT UNSIGNED NOT NULL,
  product_confidence DECIMAL(5,4) NOT NULL,
  gap_confidence DECIMAL(5,4) NOT NULL,
  product_model VARCHAR(255) NOT NULL COMMENT 'Model version or file hash',
  gap_model VARCHAR(255) NOT NULL COMMENT 'Model version or file hash',
  detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_run_plan (id, planogram_id),
  INDEX idx_run_date (detected_at),
  CONSTRAINT fk_run_plan FOREIGN KEY (planogram_id) REFERENCES planograms(id) ON DELETE RESTRICT,
  CONSTRAINT chk_run_dimensions CHECK (image_width > 0 AND image_height > 0),
  CONSTRAINT chk_run_confidence CHECK (
    product_confidence BETWEEN 0.01 AND 1 AND gap_confidence BETWEEN 0.01 AND 1)
) ENGINE=InnoDB;

-- Bounding boxes are pixel coordinates in the input image, not normalized coordinates.
CREATE TABLE detected_products (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  detection_run_id BIGINT UNSIGNED NOT NULL,
  product_id INT UNSIGNED NULL,
  class_name VARCHAR(100) COLLATE utf8mb4_bin NOT NULL COMMENT 'Actual class returned by product model',
  confidence DECIMAL(5,4) NOT NULL,
  x1 DECIMAL(12,4) NOT NULL, y1 DECIMAL(12,4) NOT NULL,
  x2 DECIMAL(12,4) NOT NULL, y2 DECIMAL(12,4) NOT NULL,
  INDEX idx_detected_product_class (detection_run_id, class_name),
  CONSTRAINT fk_detected_product_run FOREIGN KEY (detection_run_id) REFERENCES detection_runs(id) ON DELETE CASCADE,
  CONSTRAINT fk_detected_product_catalog FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
  CONSTRAINT chk_detected_product_confidence CHECK (confidence BETWEEN 0 AND 1),
  CONSTRAINT chk_detected_product_box CHECK (x1 >= 0 AND y1 >= 0 AND x2 > x1 AND y2 > y1)
) ENGINE=InnoDB;

CREATE TABLE detected_gaps (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  detection_run_id BIGINT UNSIGNED NOT NULL,
  gap_number INT UNSIGNED NOT NULL,
  planogram_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  region_id VARCHAR(100) COLLATE utf8mb4_bin NULL COMMENT 'gap.shelf_id in current response',
  product_class VARCHAR(100) COLLATE utf8mb4_bin NULL COMMENT 'Expected class from plan; NULL when unmatched',
  confidence DECIMAL(5,4) NOT NULL COMMENT 'Gap detection confidence, not class confidence',
  association_method ENUM('planogram','no-planogram','ambiguous-region','outside-planogram') NOT NULL,
  overlap_ratio DECIMAL(5,4) NULL,
  x1 DECIMAL(12,4) NOT NULL, y1 DECIMAL(12,4) NOT NULL,
  x2 DECIMAL(12,4) NOT NULL, y2 DECIMAL(12,4) NOT NULL,
  UNIQUE KEY uq_gap_number (detection_run_id, gap_number),
  CONSTRAINT fk_gap_run FOREIGN KEY (detection_run_id) REFERENCES detection_runs(id) ON DELETE CASCADE,
  CONSTRAINT fk_gap_run_plan FOREIGN KEY (detection_run_id, planogram_id)
    REFERENCES detection_runs(id, planogram_id) ON DELETE CASCADE,
  CONSTRAINT fk_gap_region_class FOREIGN KEY (planogram_id, region_id, product_class)
    REFERENCES planogram_regions(planogram_id, id, product_class) ON DELETE RESTRICT,
  CONSTRAINT chk_gap_number CHECK (gap_number > 0),
  CONSTRAINT chk_gap_confidence CHECK (confidence BETWEEN 0 AND 1),
  CONSTRAINT chk_gap_box CHECK (x1 >= 0 AND y1 >= 0 AND x2 > x1 AND y2 > y1),
  CONSTRAINT chk_gap_association CHECK (
    (association_method = 'planogram' AND planogram_id IS NOT NULL
      AND region_id IS NOT NULL AND product_class IS NOT NULL
      AND overlap_ratio IS NOT NULL AND overlap_ratio BETWEEN 0 AND 1)
    OR
    (association_method = 'no-planogram' AND planogram_id IS NULL
      AND region_id IS NULL AND product_class IS NULL AND overlap_ratio IS NULL)
    OR
    (association_method IN ('ambiguous-region','outside-planogram') AND planogram_id IS NOT NULL
      AND region_id IS NULL AND product_class IS NULL AND overlap_ratio IS NULL))
) ENGINE=InnoDB;

-- Derive total_products, product_counts, total_gaps and identified_gaps from item rows.
-- Do not use gap count as missing item quantity or detected front items as total stock.
-- Save matching planogram_id on every gap of a run, including unmatched gaps.

INSERT INTO products (product_code, product_name, yolo_class_name) VALUES
('PRD-001', 'Taokaenoi Seaweed', 'Taokaenoi-g'),
('PRD-002', 'Campus', 'campus'),
('PRD-003', 'Coenae', 'coenae'),
('PRD-004', 'Fanta', 'fanta'),
('PRD-005', 'Glico CC', 'glico-cc'),
('PRD-006', 'Honey Stars', 'honey-stars'),
('PRD-007', 'Kato O', 'kato-o'),
('PRD-008', 'Kato P', 'kato-p'),
('PRD-009', 'Koala', 'koala'),
('PRD-010', 'Kohkae R', 'kohkae-r'),
('PRD-011', 'Koko Krunch', 'koko-krunch'),
('PRD-012', 'Lactasoy', 'lactasoy'),
('PRD-013', 'Lay Nori', 'lay-nori'),
('PRD-014', 'Lotus', 'lotus'),
('PRD-015', 'M100', 'm100'),
('PRD-016', 'Mama Keaw Wan', 'mama-kealwan'),
('PRD-017', 'Mama Tom Yum', 'mama-tomyam'),
('PRD-018', 'Oichi', 'oichi'),
('PRD-019', 'Oreo', 'oreo'),
('PRD-020', 'Papica', 'papica'),
('PRD-021', 'Paty Y', 'paty-y'),
('PRD-022', 'Pepsi', 'pepsi'),
('PRD-023', 'Pocky', 'pocky'),
('PRD-024', 'Quick', 'quick'),
('PRD-025', 'Semon', 'semon'),
('PRD-026', 'Sponsor', 'sponsor'),
('PRD-027', 'Tily', 'tily'),
('PRD-028', 'Water Vitamin', 'water-vitamin'),
('PRD-029', 'Yanyan R', 'yanyan-r'),
('PRD-030', 'Yanyan Y', 'yanyan-y');
