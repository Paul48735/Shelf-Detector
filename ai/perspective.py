"""Optional four-corner shelf rectification for existing Planogram coordinates."""

import base64
import math

import cv2
import numpy as np

from alignment import AlignmentError, _reference_image


def validate_corners(corners):
    """Validate normalized TL, TR, BR, BL source corners."""
    if not isinstance(corners, list) or len(corners) != 4 or any(
        not isinstance(point, list) or len(point) != 2 or any(
            type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1
            for value in point
        ) for point in corners
    ):
        raise AlignmentError('กรุณากำหนดมุมชั้นวาง 4 จุดตามลำดับ บนซ้าย บนขวา ล่างขวา ล่างซ้าย')
    points = np.asarray(corners, np.float32)
    if not cv2.isContourConvex(points) or cv2.contourArea(points) < .15:
        raise AlignmentError('มุมทั้ง 4 ต้องล้อมพื้นที่ชั้นวางและไม่ไขว้กัน')
    tl, tr, br, bl = points
    if not (tl[0] < tr[0] and bl[0] < br[0] and tl[1] < bl[1] and tr[1] < br[1]):
        raise AlignmentError('กรุณาเรียงมุมเป็น บนซ้าย → บนขวา → ล่างขวา → ล่างซ้าย')
    if min(float(np.linalg.norm(points[i] - points[(i + 1) % 4])) for i in range(4)) < .22:
        raise AlignmentError('กรอบชั้นวางเล็กเกินไป กรุณาเลือกมุมรอบชั้นวางทั้งตู้')
    return points


def _line_intersection(first, second):
    x1, y1, x2, y2 = first
    x3, y3, x4, y4 = second
    a = np.array([[x2 - x1, x3 - x4], [y2 - y1, y3 - y4]], np.float64)
    if abs(np.linalg.det(a)) < 1e-5:
        return None
    t, _ = np.linalg.solve(a, [x3 - x1, y3 - y1])
    return np.array([x1 + t * (x2 - x1), y1 + t * (y2 - y1)])


def _contour_candidate(edges, width, height):
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < .35 * width * height:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, .025 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        points = polygon.reshape(4, 2).astype(np.float32)
        sums = points.sum(axis=1)
        differences = points[:, 0] - points[:, 1]
        ordered = points[[np.argmin(sums), np.argmax(differences),
                          np.argmax(sums), np.argmin(differences)]]
        try:
            validate_corners((ordered / [width, height]).tolist())
        except AlignmentError:
            continue
        candidates.append((area / (width * height), ordered))
    return max(candidates, key=lambda item: item[0]) if candidates else None


def _line_candidate(edges, width, height):
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 70,
                            minLineLength=round(min(width, height) * .38),
                            maxLineGap=round(min(width, height) * .06))
    if lines is None:
        return None
    horizontal, vertical = [], []
    for raw in lines.reshape(-1, 4):
        x1, y1, x2, y2 = map(float, raw)
        dx, dy = x2 - x1, y2 - y1
        angle = abs(math.degrees(math.atan2(dy, dx)))
        length = math.hypot(dx, dy)
        if angle <= 35 and abs(dx) > .38 * width:
            y_mid = y1 + (width / 2 - x1) * dy / dx
            horizontal.append((y_mid, length, (x1, y1, x2, y2)))
        elif angle >= 55 and abs(dy) > .38 * height:
            x_mid = x1 + (height / 2 - y1) * dx / dy
            vertical.append((x_mid, length, (x1, y1, x2, y2)))
    top = [item for item in horizontal if item[0] < .3 * height]
    bottom = [item for item in horizontal if item[0] > .7 * height]
    left = [item for item in vertical if item[0] < .3 * width]
    right = [item for item in vertical if item[0] > .7 * width]
    if not all((top, bottom, left, right)):
        return None
    # Prefer long structural edges among the outermost candidates.
    top_line = min(top, key=lambda item: item[0] - .08 * item[1])[2]
    bottom_line = max(bottom, key=lambda item: item[0] + .08 * item[1])[2]
    left_line = min(left, key=lambda item: item[0] - .08 * item[1])[2]
    right_line = max(right, key=lambda item: item[0] + .08 * item[1])[2]
    intersections = [_line_intersection(top_line, left_line),
                     _line_intersection(top_line, right_line),
                     _line_intersection(bottom_line, right_line),
                     _line_intersection(bottom_line, left_line)]
    if any(point is None for point in intersections):
        return None
    points = np.asarray(intersections, np.float32)
    if np.any(points < 0) or np.any(points[:, 0] > width) or np.any(points[:, 1] > height):
        return None
    try:
        validate_corners((points / [width, height]).tolist())
    except AlignmentError:
        return None
    return float(cv2.contourArea(points) / (width * height)), points


def detect_shelf_corners(image):
    """Propose four outer shelf corners; never silently trust a weak proposal."""
    height, width = image.shape[:2]
    scale = min(1.0, 900 / max(width, height))
    work = cv2.resize(image, (round(width * scale), round(height * scale)),
                      interpolation=cv2.INTER_AREA)
    h, w = work.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(work, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.Canny(gray, 50, 140)
    contour = _contour_candidate(edges, w, h)
    lines = _line_candidate(edges, w, h)
    candidate, method = (contour, 'contour') if contour and (not lines or contour[0] >= lines[0]) else (lines, 'shelf_lines')
    if candidate is None:
        return {'corners': None, 'confidence': 0.0, 'status': 'needs_review',
                'reason': 'หาขอบชั้นวางครบ 4 ด้านไม่พบ กรุณากดมุมบนภาพเอง'}
    area_ratio, points = candidate
    normalized = (points / [w, h]).tolist()
    # Geometry is only a heuristic; even a large rectangle may be a wall or
    # an interior shelf. Always require a visual confirmation before inference.
    confidence = round(min(.95, max(0.0, (area_ratio - .35) / .55)), 3)
    return {'corners': normalized, 'confidence': confidence,
            'status': 'needs_review',
            'method': method,
            'reason': ('พบกรอบชั้นวางที่คาดว่าใช่ กรุณาตรวจ 4 จุดและยืนยันก่อนตรวจ'
                       if confidence >= .75 else
                       'มุมที่พบยังไม่มั่นใจ กรุณาตรวจและแก้ 4 จุดก่อนตรวจ')}


def correct_perspective(image, plan, corners):
    """Map selected outer shelf corners onto the reference image frame."""
    source = validate_corners(corners)
    reference = _reference_image(plan)
    source_height, source_width = image.shape[:2]
    target_height, target_width = reference.shape[:2]
    source_pixels = source * [source_width - 1, source_height - 1]
    target_pixels = np.float32([[0, 0], [target_width - 1, 0],
                                [target_width - 1, target_height - 1], [0, target_height - 1]])
    matrix = cv2.getPerspectiveTransform(source_pixels.astype(np.float32), target_pixels)
    if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-10:
        raise AlignmentError('คำนวณการปรับ perspective จากมุมที่เลือกไม่ได้')
    source_frame = np.float32([[[0, 0]], [[source_width - 1, 0]],
                               [[source_width - 1, source_height - 1]], [[0, source_height - 1]]])
    valid_polygon = cv2.perspectiveTransform(source_frame, matrix).reshape(4, 2)
    if not np.isfinite(valid_polygon).all() or not cv2.isContourConvex(valid_polygon):
        raise AlignmentError('การปรับภาพบิดผิดรูป กรุณาแก้มุมทั้ง 4 จุด')
    corrected = cv2.warpPerspective(image, matrix, (target_width, target_height),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return corrected, {'status': 'aligned', 'method': 'perspective_four_corners',
                       'valid_polygon': valid_polygon.tolist()}


def preview_data_url(image):
    success, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 78])
    if not success:
        raise AlignmentError('สร้างภาพตัวอย่างที่ปรับมุมแล้วไม่ได้')
    return 'data:image/jpeg;base64,' + base64.b64encode(encoded).decode('ascii')
