"""Automatic shelf alignment using OpenCV ECC and an affine warp."""

import base64

import cv2
import numpy as np


class AlignmentError(ValueError):
    pass


def _reference_image(plan):
    try:
        raw = base64.b64decode(plan['image'].split(',', 1)[1], validate=True)
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AlignmentError('ภาพอ้างอิงของ Planogram ไม่ถูกต้อง') from exc
    if image is None:
        raise AlignmentError('อ่านภาพอ้างอิงของ Planogram ไม่ได้')
    return image


def _prepare(image, size):
    gray = cv2.cvtColor(cv2.resize(image, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    # Blur packaging detail while retaining the broad shelf structure.
    return cv2.GaussianBlur(gray, (7, 7), 1.5)


def _wood_structure(image, size):
    """Use visible beige shelf panels when packaging changes defeat grayscale ECC.

    The binary map is deliberately optional: it is only useful for wooden
    shelves like the project's reference images, never as a universal signal.
    """
    resized = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    wood = cv2.inRange(hsv, (4, 10, 75), (27, 165, 255))
    return cv2.GaussianBlur(wood, (21, 21), 5), float(np.count_nonzero(wood)) / wood.size


def _valid_polygon(matrix, source_size, target_size):
    width, height = target_size
    source_width, source_height = source_size
    # A source image may have a different pixel resolution from the reference.
    linear = (np.diag([1 / source_width, 1 / source_height]) @ matrix[:, :2]
              @ np.diag([width, height]))
    scales = np.linalg.svd(linear, compute_uv=False)
    if not np.isfinite(matrix).all() or np.linalg.det(linear) <= 0 or min(scales) < .65 or max(scales) > 1.5:
        return None
    source_corners = np.float32([[0, 0], [source_width - 1, 0],
                                 [source_width - 1, source_height - 1], [0, source_height - 1]])
    valid = cv2.transform(source_corners[None], cv2.invertAffineTransform(matrix))[0]
    frame = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    coverage, _ = cv2.intersectConvexConvex(valid, frame)
    return valid if coverage / (width * height) >= .7 else None


def _ecc_candidate(template, moving, work_size, threshold):
    work_width, work_height = work_size
    center = ((work_width - 1) / 2, (work_height - 1) / 2)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5)
    best = None
    for angle in (0, -8, 8, -16, 16):
        initial = cv2.getRotationMatrix2D(center, angle, 1).astype(np.float32)
        try:
            score, matrix = cv2.findTransformECC(template, moving, initial,
                                                  cv2.MOTION_AFFINE, criteria, None, 5)
        except cv2.error:
            continue
        if not np.isfinite(score) or score < threshold or _valid_polygon(matrix, work_size, work_size) is None:
            continue
        if best is None or score > best[0]:
            best = (float(score), matrix)
    return best


def align_to_planogram(image, plan):
    """Align the uploaded image to Planogram coordinates without user-selected corners."""
    reference = _reference_image(plan)
    target_height, target_width = reference.shape[:2]
    source_height, source_width = image.shape[:2]
    if min(source_height, source_width, target_height, target_width) < 80:
        raise AlignmentError('ภาพเล็กเกินไปสำหรับจัดแนว')
    if abs((source_width / source_height) / (target_width / target_height) - 1) > .35:
        raise AlignmentError('สัดส่วนภาพต่างจากภาพอ้างอิงมากเกินไป')

    scale = min(1.0, 640 / max(target_width, target_height))
    work_width, work_height = max(80, round(target_width * scale)), max(80, round(target_height * scale))
    work_size = (work_width, work_height)
    best = _ecc_candidate(_prepare(reference, work_size), _prepare(image, work_size),
                          work_size, .55)
    signal = 'grayscale'
    if best is None:
        reference_wood, reference_coverage = _wood_structure(reference, work_size)
        source_wood, source_coverage = _wood_structure(image, work_size)
        if reference_coverage >= .12 and source_coverage >= .12:
            best = _ecc_candidate(reference_wood, source_wood, work_size, .60)
            signal = 'wood_structure'
    if best is None:
        raise AlignmentError('ECC จัดแนวภาพกับ Planogram ไม่ได้อย่างมั่นใจ กรุณาถ่ายภาพชั้นวางให้เห็นขอบชัดขึ้น')

    score, small_matrix = best
    source_scale = np.diag([source_width / work_width, source_height / work_height, 1.0])
    target_scale = np.diag([work_width / target_width, work_height / target_height, 1.0])
    full_matrix = (source_scale @ np.vstack([small_matrix, [0, 0, 1]]) @ target_scale)[:2].astype(np.float32)
    valid = _valid_polygon(full_matrix, (source_width, source_height), (target_width, target_height))
    if valid is None:
        raise AlignmentError('ECC ได้การแปลงภาพที่คลาดเคลื่อนเกินไป')
    aligned = cv2.warpAffine(image, full_matrix, (target_width, target_height),
                             flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_CONSTANT)
    return aligned, {'status': 'aligned', 'method': 'ecc_affine', 'signal': signal,
                     'score': round(score, 4), 'valid_polygon': valid.tolist()}
