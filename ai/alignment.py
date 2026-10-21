"""Optional manual four-pair registration into the reference image coordinates."""
import base64

import cv2
import numpy as np


def validate_corners(points, label="จุดอ้างอิง"):
    if not isinstance(points, list) or len(points) != 4:
        raise ValueError(f"{label}: ต้องกำหนดให้ครบ 4 จุด หรือไม่กำหนดเลยเพื่อข้ามการจัดแนว")
    if any(not isinstance(p, list) or len(p) != 2 or any(
        type(v) not in (int, float) or not np.isfinite(v) or not 0 <= v <= 1
        for v in p
    ) for p in points):
        raise ValueError(f"{label}: พิกัดต้องอยู่ภายในภาพ")
    polygon = np.array(points, dtype=np.float32)
    # In image coordinates TL -> TR -> BR -> BL has positive signed area.
    if (not cv2.isContourConvex(polygon)
            or cv2.contourArea(polygon, oriented=True) < 0.002
            or min(np.linalg.norm(polygon - np.roll(polygon, 1, axis=0), axis=1)) < 0.01):
        raise ValueError(f"{label}: เลือก บนซ้าย → บนขวา → ล่างขวา → ล่างซ้าย รอบกรอบที่ไม่ไขว้กันและไม่เล็กเกินไป")
    return polygon.tolist()


def reference_size(plan):
    width, height = plan.get("reference_width"), plan.get("reference_height")
    if type(width) is int and type(height) is int and width > 1 and height > 1:
        if width * height > 40_000_000 or max(width, height) > 16000:
            raise ValueError("ภาพ Planogram มีความละเอียดสูงเกินไปสำหรับจัดแนว")
        return width, height
    # Also accept an older plan payload which includes the reference JPEG.
    try:
        raw = base64.b64decode(plan["image"].split(",", 1)[1], validate=True)
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError()
        return reference_size(dict(plan, reference_width=int(frame.shape[1]), reference_height=int(frame.shape[0])))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("ไม่พบขนาดภาพอ้างอิง กรุณาเปิดและบันทึก Planogram ใหม่") from exc


def align_image(image, plan, points):
    """No selected points means an exact bypass, including legacy/no-plan requests."""
    if points is None or points == []:
        return image, {"applied": False}
    if not isinstance(plan, dict):
        raise ValueError("เลือก Planogram ก่อนจัดแนวภาพ")
    source = np.array(validate_corners(points, "ภาพอัปโหลด"), np.float32)
    target = np.array(validate_corners(plan.get("alignment_points"), "ภาพ Planogram"), np.float32)
    width, height = reference_size(plan)
    source *= np.array([image.shape[1] - 1, image.shape[0] - 1], np.float32)
    target *= np.array([width - 1, height - 1], np.float32)
    matrix = cv2.getPerspectiveTransform(source, target)
    if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12:
        raise ValueError("จุดอ้างอิงไม่สามารถสร้างการแปลงภาพได้ กรุณากำหนดใหม่")
    # Do not extrapolate through a projective horizon crossing the input image.
    corners = np.array([[0, 0, 1], [image.shape[1] - 1, 0, 1],
                        [image.shape[1] - 1, image.shape[0] - 1, 1], [0, image.shape[0] - 1, 1]])
    denominators = corners @ matrix[2]
    if not (np.all(denominators > 1e-6) or np.all(denominators < -1e-6)):
        raise ValueError("มุมทั้ง 4 ทำให้ภาพบิดกลับด้าน กรุณาตรวจว่าจับคู่จุดโครงตู้เดียวกัน")
    aligned = cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_LINEAR)
    mask = cv2.warpPerspective(np.full(image.shape[:2], 255, np.uint8), matrix,
                               (width, height), flags=cv2.INTER_NEAREST)
    coverage = float(np.count_nonzero(mask)) / (width * height)
    if coverage < 0.1:
        raise ValueError("ภาพหลังจัดแนวมีส่วนที่มองเห็นน้อยเกินไป กรุณาตรวจจุดอ้างอิง")
    return aligned, {"applied": True, "source_points": points,
                     "reference_points": plan["alignment_points"],
                     "matrix": matrix.tolist(), "coverage": round(coverage, 4)}
