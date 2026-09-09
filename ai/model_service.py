from collections import Counter
from pathlib import Path

import cv2
from ultralytics import YOLO
from planogram import match_gap
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
    def _draw_box(image, detection, color, label):
        x1, y1, x2, y2 = map(int, detection["box"])
        scale = max(1.0, image.shape[1] / 1400)
        padding = round(14 * scale)
        x1, y1 = max(0, x1 - padding), max(0, y1 - padding)
        x2, y2 = min(image.shape[1] - 1, x2 + padding), min(image.shape[0] - 1, y2 + padding)
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
    ) -> dict:
        product_model, gap_model = self._models()
        gap_class_id = self._class_id(gap_model, "gap")
        image = cv2.imread(str(image_path))
        if image is None:
            raise ValueError("ไม่สามารถอ่านไฟล์ภาพที่อัปโหลดได้")

        if plan and abs((image.shape[1] / image.shape[0]) / plan['ratio'] - 1) > .02:
            raise ValueError('สัดส่วนภาพไม่ตรงกับ Planogram กรุณาใช้ภาพจากมุมกล้องเดิม')

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
            association = match_gap(product['box'], plan, image.shape[1], image.shape[0])
            expected = association['product_class']
            status = 'unmatched' if expected is None else ('correct' if product['class_name'] == expected else 'wrong-shelf')
            product.update(expected_class=expected, region_id=association['shelf_id'],
                           shelf_name=association['shelf_name'], placement_status=status,
                           association_method=association['association_method'],
                           overlap_ratio=association.get('overlap_ratio'))
            color = (41, 211, 163) if status == 'correct' else (0, 0, 230) if status == 'wrong-shelf' else (0, 190, 255)
            label = f"{product['class_name']} {product['confidence']:.2f}"
            if status == 'wrong-shelf':
                label = f"ผิด shelf | Found: {product['class_name']} | Expected: {expected}"
            elif status == 'unmatched':
                label += ' [UNMATCHED]'
            self._draw_box(
                annotated,
                product,
                color,
                label,
            )

        gaps = []
        for index, gap in enumerate(raw_gaps, start=1):
            association = match_gap(gap["box"], plan, image.shape[1], image.shape[0])
            product_name = association["product_class"]
            gap_data = {
                "gap_number": index,
                **association,
                "confidence": round(gap["confidence"], 4),
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
            "planogram_id": plan["id"] if plan else None,
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
