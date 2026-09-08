from collections import Counter
from pathlib import Path

import cv2
from ultralytics import YOLO


class ModelServiceError(RuntimeError):
    pass


class ShelfModelService:
    """ตรวจสินค้าทุกคลาส ตรวจ gap และจับคู่จากตำแหน่งในแถวเดียวกัน."""

    def __init__(self, product_model_path: Path, gap_model_path: Path):
        self.product_model_path = Path(product_model_path)
        self.gap_model_path = Path(gap_model_path)
        self._product_model = None
        self._gap_model = None

    @staticmethod
    def _load(path: Path, label: str):
        if not path.is_file():
            raise ModelServiceError(f"ไม่พบ {label}: {path}")
        try:
            return YOLO(str(path))
        except Exception as exc:
            raise ModelServiceError(f"โหลด {label} ไม่สำเร็จ: {exc}") from exc

    def _models(self):
        if self._product_model is None:
            self._product_model = self._load(
                self.product_model_path, "Product Model"
            )
        if self._gap_model is None:
            self._gap_model = self._load(self.gap_model_path, "Gap Model")
        return self._product_model, self._gap_model

    def class_names(self) -> list[str]:
        product_model, _ = self._models()
        return [
            str(product_model.names[index])
            for index in sorted(product_model.names)
        ]

    @staticmethod
    def _class_id(model, class_name: str) -> int:
        for class_id, name in model.names.items():
            if str(name) == class_name:
                return int(class_id)
        raise ModelServiceError(f"โมเดลไม่มีคลาส '{class_name}'")

    @staticmethod
    def _collect(result) -> list[dict]:
        detections = []
        if result.boxes is None:
            return detections
        for item in result.boxes:
            class_id = int(item.cls[0])
            box = tuple(float(value) for value in item.xyxy[0].cpu().tolist())
            detections.append(
                {
                    "class_name": str(result.names[class_id]),
                    "confidence": float(item.conf[0]),
                    "box": box,
                }
            )
        return detections

    @staticmethod
    def _center(box):
        x1, y1, x2, y2 = box
        return (x1 + x2) / 2, (y1 + y2) / 2

    @staticmethod
    def _vertical_overlap_ratio(first_box, second_box) -> float:
        _, ay1, _, ay2 = first_box
        _, by1, _, by2 = second_box
        overlap = max(0.0, min(ay2, by2) - max(ay1, by1))
        smaller_height = max(1.0, min(ay2 - ay1, by2 - by1))
        return overlap / smaller_height

    def _associate_gap(self, gap: dict, products: list[dict], frame_width: int):
        """หาแบรนด์ซ้าย/ขวาที่อยู่แถวเดียวกับ gap โดยไม่ใช้ ROI."""
        gx1, _, gx2, _ = gap["box"]
        gap_center_x, gap_center_y = self._center(gap["box"])
        max_distance = frame_width * 0.35
        left_candidates = []
        right_candidates = []

        for product in products:
            px1, _, px2, _ = product["box"]
            product_center_x, product_center_y = self._center(product["box"])
            vertical_overlap = self._vertical_overlap_ratio(
                gap["box"], product["box"]
            )
            average_height = max(
                1.0,
                (
                    (gap["box"][3] - gap["box"][1])
                    + (product["box"][3] - product["box"][1])
                ) / 2,
            )
            same_row = (
                vertical_overlap >= 0.25
                or abs(gap_center_y - product_center_y) <= average_height * 0.45
            )
            if not same_row:
                continue

            if product_center_x < gap_center_x:
                distance = max(0.0, gx1 - px2)
                if distance <= max_distance:
                    left_candidates.append((distance, product))
            else:
                distance = max(0.0, px1 - gx2)
                if distance <= max_distance:
                    right_candidates.append((distance, product))

        nearest_left = min(left_candidates, default=None, key=lambda item: item[0])
        nearest_right = min(right_candidates, default=None, key=lambda item: item[0])

        if nearest_left and nearest_right:
            left_distance, left_product = nearest_left
            right_distance, right_product = nearest_right
            if left_product["class_name"] == right_product["class_name"]:
                return left_product["class_name"], "both-sides", "high"

            closer, other = sorted(
                [nearest_left, nearest_right], key=lambda item: item[0]
            )
            # เมื่อสองฝั่งเป็นคนละสินค้า ต้องมีฝั่งหนึ่งใกล้กว่าชัดเจน
            if closer[0] + frame_width * 0.025 < other[0] * 0.65:
                return closer[1]["class_name"], "nearest-side", "medium"
            return None, "conflicting-neighbors", "low"

        nearest = nearest_left or nearest_right
        if nearest:
            return nearest[1]["class_name"], "one-side", "medium"
        return None, "no-neighbor", "low"

    @staticmethod
    def _draw_box(image, detection, color, label):
        x1, y1, x2, y2 = map(int, detection["box"])
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
        (text_width, text_height), _ = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.62, 2
        )
        label_top = max(0, y1 - text_height - 12)
        cv2.rectangle(
            image,
            (x1, label_top),
            (x1 + text_width + 12, y1),
            color,
            -1,
        )
        cv2.putText(
            image,
            label,
            (x1 + 6, max(text_height + 2, y1 - 7)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            (7, 18, 26),
            2,
            cv2.LINE_AA,
        )

    def detect_scene(
        self,
        image_path: Path,
        result_path: Path,
        product_confidence: float,
        gap_confidence: float,
    ) -> dict:
        product_model, gap_model = self._models()
        gap_class_id = self._class_id(gap_model, "gap")
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError("ไม่สามารถอ่านไฟล์ภาพที่อัปโหลดได้")

        try:
            product_result = product_model.predict(
                source=image,
                conf=product_confidence,
                verbose=False,
            )[0]
            gap_result = gap_model.predict(
                source=image,
                conf=gap_confidence,
                classes=[gap_class_id],
                verbose=False,
            )[0]
        except Exception as exc:
            raise ModelServiceError(f"ประมวลผลภาพไม่สำเร็จ: {exc}") from exc

        products = self._collect(product_result)
        raw_gaps = self._collect(gap_result)
        product_counts = dict(
            sorted(Counter(item["class_name"] for item in products).items())
        )

        annotated = image.copy()
        for product in products:
            self._draw_box(
                annotated,
                product,
                (41, 211, 163),
                f"{product['class_name']} {product['confidence']:.2f}",
            )

        gaps = []
        for index, gap in enumerate(raw_gaps, start=1):
            product_name, method, certainty = self._associate_gap(
                gap, products, image.shape[1]
            )
            gap_data = {
                "gap_number": index,
                "product_class": product_name,
                "confidence": round(gap["confidence"], 4),
                "association_method": method,
                "association_certainty": certainty,
                "box": [round(value, 2) for value in gap["box"]],
            }
            gaps.append(gap_data)
            gap_label = (
                f"GAP -> {product_name}" if product_name else "GAP -> UNKNOWN"
            )
            color = (0, 88, 255) if product_name else (120, 120, 120)
            self._draw_box(annotated, gap, color, gap_label)

        result_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(result_path), annotated):
            raise ModelServiceError("ไม่สามารถบันทึกภาพผลลัพธ์ได้")

        return {
            "products": [
                {
                    **item,
                    "confidence": round(item["confidence"], 4),
                    "box": [round(value, 2) for value in item["box"]],
                }
                for item in products
            ],
            "product_counts": product_counts,
            "total_products": len(products),
            "gaps": gaps,
            "total_gaps": len(gaps),
            "identified_gaps": sum(
                1 for item in gaps if item["product_class"] is not None
            ),
        }
