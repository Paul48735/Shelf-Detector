import base64
import math
import uuid
import time

import cv2
import numpy as np


def text(value):
    return isinstance(value, str) and 0 < len(value.strip()) <= 100


def validate_plan(data, classes):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('รูปแบบ Planogram ไม่ถูกต้อง')
    if not text(data.get('name')):
        raise ValueError('กรุณาระบุชื่อแผน')
    image = data.get('image', '')
    try:
        if not isinstance(image, str) or not image.startswith('data:image/jpeg;base64,'):
            raise ValueError()
        raw = base64.b64decode(image.split(',', 1)[1], validate=True)
        frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError()
    except Exception as exc:
        raise ValueError('ภาพอ้างอิงไม่ถูกต้อง') from exc
    cleaned = validate_regions(data, classes)
    return {'version': 1, 'id': f'{time.time_ns():016x}' + uuid.uuid4().hex[16:], 'name': data['name'].strip(),
            'image': image, 'ratio': frame.shape[1] / frame.shape[0], 'shelves': cleaned}


def validate_regions(data, classes):
    shelves = data.get('shelves')
    if not isinstance(shelves, list) or not 1 <= len(shelves) <= 100:
        raise ValueError('ต้องมีพื้นที่ 1–100 พื้นที่')
    cleaned, ids = [], set()
    for shelf in shelves:
        if not isinstance(shelf, dict) or not all(text(shelf.get(k)) for k in ('id', 'name', 'product')):
            raise ValueError('ข้อมูลพื้นที่ไม่ครบ')
        if shelf['id'] in ids:
            raise ValueError('รหัสพื้นที่ซ้ำ')
        ids.add(shelf['id'])
        if shelf['product'].strip() not in classes:
            raise ValueError('ไม่พบคลาสสินค้าในโมเดล: ' + shelf['product'])
        target = shelf.get('target')
        if type(target) is not int or not 1 <= target <= 999:
            raise ValueError('จำนวนเป้าหมายต้องเป็นจำนวนเต็ม 1–999')
        points = shelf.get('points')
        if not isinstance(points, list) or len(points) != 4 or any(
            not isinstance(p, list) or len(p) != 2 or any(
                type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in p
            ) for p in points
        ):
            raise ValueError('พิกัดพื้นที่ไม่ถูกต้อง')
        polygon = np.array(points, dtype=np.float32)
        if not cv2.isContourConvex(polygon) or cv2.contourArea(polygon) < .0001:
            raise ValueError('กรอบพื้นที่ต้องไม่ไขว้กันและมีพื้นที่')
        cleaned.append({k: shelf[k].strip() for k in ('id', 'name', 'product')} | {'target': target, 'points': points})
    return cleaned


def match_gap(box, plan, width, height):
    if plan is None:
        return {'product_class': None, 'association_method': 'no-planogram', 'shelf_id': None, 'shelf_name': None}
    x1, y1, x2, y2 = box
    gap = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float32)
    area = max(0, x2 - x1) * max(0, y2 - y1)
    matches = []
    for shelf in plan['shelves']:
        polygon = np.array(shelf['points'], dtype=np.float32) * np.array([width, height], dtype=np.float32)
        overlap, _ = cv2.intersectConvexConvex(gap, polygon)
        ratio = float(overlap) / area if area else 0
        if ratio >= plan.get('overlap_threshold', .7):
            matches.append((shelf, ratio))
    if len(matches) != 1:
        return {'product_class': None, 'association_method': 'ambiguous-region' if matches else 'outside-planogram', 'shelf_id': None, 'shelf_name': None}
    shelf, ratio = matches[0]
    return {'product_class': shelf['product'], 'association_method': 'planogram',
            'shelf_id': shelf['id'], 'shelf_name': shelf['name'], 'overlap_ratio': round(ratio, 4)}


def validate_inference_plan(data, classes):
    if not isinstance(data, dict):
        raise ValueError('Invalid planogram')
    plan_id = data.get('id', '')
    if not isinstance(plan_id, str) or len(plan_id) != 32 or any(c not in '0123456789abcdef' for c in plan_id):
        raise ValueError('Invalid planogram id')
    ratio = data.get('ratio')
    threshold = data.get('overlap_threshold', .7)
    if type(ratio) not in (int, float) or not math.isfinite(ratio) or ratio <= 0:
        raise ValueError('Invalid planogram ratio')
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError('Invalid overlap threshold')
    return dict(data, shelves=validate_regions(data, classes))
