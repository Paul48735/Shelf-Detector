from collections import Counter
from pathlib import Path
import threading

import cv2
from ultralytics import YOLO
from alignment import AlignmentError, align_to_planogram
from perspective import correct_perspective
from preservation import ProductDetector
from config import MODEL_ARCHIVE_DIR
from planogram import match_product, split_gap_by_plan
from PIL import Image, ImageDraw, ImageFont
import numpy as np


class ModelServiceError(RuntimeError):
    pass


class ShelfModelService:
    """ตรวจสินค้าและจับคู่ gap กับพื้นที่ Planogram เท่านั้น."""

    def __init__(self, product_model_path: Path, gap_model_path: Path):
        self.product_model_path = Path(product_model_path)
        self.gap_model_path = Path(gap_model_path)
        self._product_model = None
        self._gap_model = None
        self._model_lock = threading.RLock()

    @staticmethod
    def _load(path: Path, label: str):
        if not path.is_file():
            raise ModelServiceError(f"ไม่พบ {label}: {path}")
        try:
            return YOLO(str(path))
        except Exception as exc:
            raise ModelServiceError(f"โหลด {label} ไม่สำเร็จ: {exc}") from exc

    def _load_product(self):
        try:
            return ProductDetector(self.product_model_path, MODEL_ARCHIVE_DIR)
        except Exception as exc:
            raise ModelServiceError(f"โหลด Product Model ไม่สำเร็จ: {exc}") from exc

    def _models(self):
        with self._model_lock:
            if self._product_model is None:
                self._product_model = self._load_product()
            if self._gap_model is None:
                self._gap_model = self._load(self.gap_model_path, "Gap Model")
            return self._product_model, self._gap_model

    def reload_product_model(self):
        with self._model_lock:
            self._product_model = self._load_product()

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
    def _draw_box(image, detection, color, label):
        scale = max(1.0, image.shape[1] / 1400)
        x1, y1, x2, y2 = map(int, detection["box"])
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.shape[1] - 1, x2), min(image.shape[0] - 1, y2)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, max(4, round(5 * scale)))
        if 'ผิด shelf' in label:
            font_path = Path('C:/Windows/Fonts/tahoma.ttf')
            if font_path.is_file():
                canvas = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                painter = ImageDraw.Draw(canvas)
                font = ImageFont.truetype(str(font_path), round(24 * scale))
                lines = label.split(' | ')
                line_bboxes = [painter.textbbox((0, 0), line, font=font) for line in lines]
                line_heights = [max(1, bbox[3] - bbox[1]) for bbox in line_bboxes]
                line_widths = [bbox[2] - bbox[0] for bbox in line_bboxes]
                total_height = sum(line_heights) + 4 * (len(lines) - 1)
                top = max(0, min(y1 - total_height, image.shape[0] - total_height))
                width = min(image.shape[1], max(line_widths) + 8)
                left = max(0, min(x1, image.shape[1] - width))
                painter.rectangle((left, top, left + width, top + total_height), fill=tuple(reversed(color)))
                y = top
                for i, line in enumerate(lines):
                    painter.text((left + 4, y), line, font=font, fill='white')
                    y += line_heights[i] + 4
                image[:] = cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)
                return
            label = label.replace('ผิด shelf', 'WRONG SHELF')
        (text_width, text_height), _ = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.9 * scale, max(2, round(1.5 * scale))
        )
        label_top = max(0, y1 - text_height - 10)
        label_left = max(0, min(x1, image.shape[1] - text_width - 8))
        cv2.rectangle(
            image,
            (label_left, label_top),
            (label_left + text_width + 8, label_top + text_height + 10),
            color,
            -1,
        )
        cv2.putText(
            image,
            label,
            (label_left + 4, label_top + text_height + 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9 * scale,
            (255, 255, 255),
            max(2, round(1.5 * scale)),
            cv2.LINE_AA,
        )

    def detect_scene(
        self,
        image_path: Path,
        result_path: Path,
        product_confidence: float,
        gap_confidence: float,
        plan=None,
        perspective_corners=None,
    ) -> dict:
        product_model, gap_model = self._models()
        gap_class_id = self._class_id(gap_model, "gap")
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError("ไม่สามารถอ่านไฟล์ภาพที่อัปโหลดได้")

        alignment = None
        comparison_plan = plan
        if plan:
            try:
                if perspective_corners is not None:
                    image, alignment = correct_perspective(image, plan, perspective_corners)
                else:
                    image, alignment = align_to_planogram(image, plan)
            except AlignmentError as exc:
                if perspective_corners is not None:
                    raise
                comparison_plan = None
                alignment = {"status": "failed", "reason": str(exc)}

        try:
            if isinstance(product_model, ProductDetector):
                products = product_model.predict_detections(image, product_confidence)
            else:
                products = self._collect(product_model.predict(
                    source=image, conf=product_confidence, verbose=False,
                )[0])
            gap_result = gap_model.predict(
                source=image,
                conf=gap_confidence,
                classes=[gap_class_id],
                verbose=False,
            )[0]
        except Exception as exc:
            raise ModelServiceError(f"ประมวลผลภาพไม่สำเร็จ: {exc}") from exc

        raw_gaps = self._collect(gap_result)
        if alignment and alignment.get("valid_polygon"):
            valid_area = np.asarray(alignment["valid_polygon"], dtype=np.float32)

            def mostly_visible(detection):
                x1, y1, x2, y2 = detection["box"]
                rectangle = np.float32([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
                area = max(0, x2 - x1) * max(0, y2 - y1)
                overlap, _ = cv2.intersectConvexConvex(rectangle, valid_area)
                return area > 0 and overlap / area >= .9

            products = [item for item in products if mostly_visible(item)]
            raw_gaps = [item for item in raw_gaps if mostly_visible(item)]
        product_counts = dict(
            sorted(Counter(item["class_name"] for item in products).items())
        )

        annotated = image.copy()
        products_by_region = {}
        for product in products:
            association = match_product(product['box'], comparison_plan, image.shape[1], image.shape[0])
            expected = association['expected_class']
            status = 'unmatched' if expected is None else ('correct' if product['class_name'] == expected else 'wrong-shelf')
            product.update(expected_class=expected, region_id=association['shelf_id'],
                           shelf_name=association['shelf_name'], placement_status=status,
                           association_method=association['association_method'],
                           overlap_ratio=association.get('overlap_ratio'))
            if association['shelf_id'] is not None:
                products_by_region.setdefault(association['shelf_id'], []).append(product)
            if status == 'wrong-shelf':
                label = (f"ผิด shelf | Found: {product['class_name']} {product['confidence']:.2f}"
                         f" | Expected: {expected}")
                color = (0, 0, 230)
            elif status == 'correct':
                label = f"{product['class_name']} {product['confidence']:.2f}"
                color = (41, 211, 163)
            else:
                label = f"{product['class_name']} {product['confidence']:.2f}"
                color = (0, 190, 255)
            self._draw_box(annotated, product, color, label)

        gaps = []
        for gap in raw_gaps:
            product_names = []
            visible = False
            for box, association in split_gap_by_plan(gap["box"], comparison_plan, image.shape[1], image.shape[0]):
                # A detected product takes precedence over empty space in the same plan region.
                if association['shelf_id'] in products_by_region:
                    continue
                product_name = association["product_class"]
                gap_data = {
                    "gap_number": len(gaps) + 1,
                    **association,
                    "confidence": round(gap["confidence"], 4),
                    "box": [round(value, 2) for value in box],
                }
                gaps.append(gap_data)
                visible = True
                if product_name is not None and product_name not in product_names:
                    product_names.append(product_name)
            if visible:
                label = "GAP" + (" -> " + ", ".join(product_names) if product_names else "")
                self._draw_box(annotated, gap, (0, 88, 255), label)

        result_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(result_path), annotated):
            raise ModelServiceError("ไม่สามารถบันทึกภาพผลลัพธ์ได้")

        return {
            "planogram_id": plan["id"] if plan else None,
            "alignment": alignment,
            "image_width": image.shape[1],
            "image_height": image.shape[0],
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
            "wrong_shelf_count": sum(p['placement_status'] == 'wrong-shelf' for p in products),
            "gaps": gaps,
            "total_gaps": len(gaps),
            "identified_gaps": sum(
                1 for item in gaps if item["product_class"] is not None
            ),
        }
