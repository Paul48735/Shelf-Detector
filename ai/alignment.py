"""Project reference Planogram regions onto an unmodified uploaded image."""

import base64

import cv2
import numpy as np


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
        return reference_size(
            dict(
                plan,
                reference_width=int(frame.shape[1]),
                reference_height=int(frame.shape[0]),
            )
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("ไม่พบขนาดภาพอ้างอิง กรุณาเปิดและบันทึก Planogram ใหม่") from exc


def project_planogram(image, plan, matrix):
    """Apply a server-computed reference-to-upload matrix without touching pixels."""
    width, height = reference_size(plan)
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (3, 3):
        raise ValueError("เมทริกซ์จัดแนวไม่ถูกต้อง")
    if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12:
        raise ValueError("จุดอ้างอิงไม่สามารถสร้างการแปลงภาพได้ กรุณากำหนดใหม่")

    corners = np.array([[0, 0, 1], [width, 0, 1], [width, height, 1], [0, height, 1]])
    denominators = corners @ matrix[2]
    if not (np.all(denominators > 1e-6) or np.all(denominators < -1e-6)):
        raise ValueError("มุมทั้ง 4 ทำให้ภาพบิดกลับด้าน กรุณาตรวจว่าจับคู่จุดโครงตู้เดียวกัน")
    regions = []
    for region in plan.get("shelves", []):
        polygon = np.asarray(region["points"], dtype=np.float32)
        if (
            polygon.shape != (4, 2)
            or not np.isfinite(polygon).all()
            or not cv2.isContourConvex(polygon)
        ):
            raise ValueError("พื้นที่ Planogram ไม่ถูกต้อง กรุณาบันทึกแผนใหม่")
        polygon *= [width, height]
        projected = cv2.perspectiveTransform(polygon[None], matrix)[0]
        if not np.isfinite(projected).all():
            raise ValueError("แปลงพื้นที่ Planogram ไม่สำเร็จ กรุณาตรวจจุดอ้างอิง")

        projected /= [image.shape[1], image.shape[0]]
        regions.append(dict(region, points=projected.tolist()))
    return dict(plan, shelves=regions, coordinate_space="uploaded-image")
