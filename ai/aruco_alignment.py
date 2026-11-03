"""Four fixed, coplanar ArUco markers register a saved reference to an upload."""

import base64
import copy
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict

import cv2
import numpy as np

from alignment import project_planogram, reference_size

DICTIONARY = "DICT_4X4_50"
MARKER_IDS = (0, 1, 2, 3)  # top-left, top-right, bottom-right, bottom-left
_previews = OrderedDict()
_lock = threading.Lock()
PREVIEW_TTL = 900


def _key(image, plan):
    digest = hashlib.sha256(
        json.dumps(plan, sort_keys=True, ensure_ascii=True).encode()
    )
    digest.update(str(image.shape).encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


def _reference(plan):
    try:
        raw = base64.b64decode(plan["image"].split(",", 1)[1], validate=True)
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or (image.shape[1], image.shape[0]) != reference_size(plan):
            raise ValueError()
        return image
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError("อ่านภาพอ้างอิง Planogram ไม่ได้ กรุณาบันทึกแผนใหม่") from exc


def dictionary():
    if not hasattr(cv2, "aruco") or not hasattr(cv2.aruco, "ArucoDetector"):
        raise ValueError(
            "OpenCV เวอร์ชันนี้ไม่มี ArUcoDetector กรุณาติดตั้งตาม ai/requirements.txt"
        )
    return cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)


def detect_markers(image, label="ภาพ"):
    marker_dictionary = dictionary()
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(marker_dictionary, params)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    found = {}
    for marker, marker_id in zip(corners, [] if ids is None else ids.ravel()):
        marker_id = int(marker_id)
        if marker_id not in MARKER_IDS:
            continue
        if marker_id in found:
            raise ValueError(
                f"{label}: พบ ArUco ID {marker_id} ซ้ำ กรุณาใช้ ID 0, 1, 2, 3 อย่างละใบ"
            )
        found[marker_id] = np.float32(marker).reshape(4, 2)
    missing = [i for i in MARKER_IDS if i not in found]
    if missing:
        raise ValueError(
            f"{label}: อ่าน ArUco ไม่ครบ ขาด ID {missing}  กรุณาถ่ายให้เห็นป้ายพร้อมขอบขาวครบทั้ง 4 ใบ"
        )
    centers = np.float32([found[i].mean(axis=0) for i in MARKER_IDS])
    area = cv2.contourArea(centers, oriented=True)
    if not cv2.isContourConvex(centers) or area < 0.1 * image.shape[0] * image.shape[1]:
        raise ValueError(
            f"{label}: ป้ายต้องกระจายรอบชั้นวางตามลำดับ 0 บนซ้าย → 1 บนขวา → 2 ล่างขวา → 3 ล่างซ้าย"
        )
    return found


def marker_metadata(markers, image):
    size = np.float32([image.shape[1], image.shape[0]])
    return [{"id": i, "points": (markers[i] / size).tolist()} for i in MARKER_IDS]


def inspect_reference(data):
    if not isinstance(data, str) or not data.startswith("data:image/"):
        raise ValueError("กรุณาเลือกภาพอ้างอิงก่อนตรวจ ArUco")
    try:
        raw = base64.b64decode(data.split(",", 1)[1], validate=True)
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError()
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError()
    except (ValueError, IndexError, TypeError) as exc:
        raise ValueError("อ่านภาพอ้างอิงไม่สำเร็จ") from exc
    markers = detect_markers(image, "ภาพอ้างอิง")
    annotated = image.copy()
    cv2.aruco.drawDetectedMarkers(
        annotated, [markers[i][None] for i in MARKER_IDS], np.int32(MARKER_IDS)[:, None]
    )
    encoded = cv2.imencode(".jpg", annotated)[1]
    return {
        "dictionary": DICTIONARY,
        "markers": marker_metadata(markers, image),
        "preview_image": "data:image/jpeg;base64," + base64.b64encode(encoded).decode(),
    }


def estimate_matrix(reference, image):
    source = detect_markers(reference, "ภาพ Planogram")
    target = detect_markers(image, "ภาพอัปโหลด")
    a = np.concatenate([source[i] for i in MARKER_IDS])
    b = np.concatenate([target[i] for i in MARKER_IDS])
    threshold = max(2.0, max(image.shape[:2]) * 0.002)
    matrix, mask = cv2.findHomography(a, b, cv2.USAC_MAGSAC, threshold)
    if matrix is None or mask is None or not np.isfinite(matrix).all():
        raise ValueError("คำนวณการแปลงจาก ArUco ไม่สำเร็จ")
    inliers = mask.reshape(4, 4).astype(bool)
    error = np.linalg.norm(cv2.perspectiveTransform(a[None], matrix)[0] - b, axis=1)
    center_fallback = (
        np.any(inliers.sum(axis=1) < 3) or np.quantile(error, 0.9) > threshold * 2
    )
    relative_error = 0.0
    if center_fallback:

        matrix = cv2.getPerspectiveTransform(
            marker_centers(source), marker_centers(target)
        )
        try:
            inverse = np.linalg.inv(matrix)
            forward = cv2.perspectiveTransform(a[None], matrix)[0]
            backward = cv2.perspectiveTransform(b[None], inverse)[0]
            errors_forward = np.linalg.norm(forward - b, axis=1).reshape(4, 4)
            errors_backward = np.linalg.norm(backward - a, axis=1).reshape(4, 4)
            target_sides = marker_sides(target)
            source_sides = marker_sides(source)
            relative_by_marker = np.maximum(
                errors_forward / target_sides[:, None],
                errors_backward / source_sides[:, None],
            ).max(axis=1)
            relative_error = float(relative_by_marker.max())
        except (np.linalg.LinAlgError, cv2.error) as exc:
            raise ValueError("คำนวณการแปลงจากกึ่งกลาง ArUco ไม่สำเร็จ") from exc
        # Report corner disagreement without rejecting by its magnitude.
        # Invalid numeric transforms still cannot produce usable polygons.
        if not np.isfinite(relative_error):
            raise ValueError("คำนวณความคลาดเคลื่อน ArUco ไม่ได้ กรุณาตรวจภาพและป้าย")
        error = errors_forward.ravel()
    return matrix, {
        "markers": marker_metadata(target, image),
        "reference_markers": marker_metadata(source, reference),
        "warning": (
            "ใช้กึ่งกลางป้าย 4 ใบประมาณการจัดแนว เพราะมุมกระดาษไม่ตรงกันทั้งหมด กรุณาตรวจกรอบ Planogram ก่อน Detect"
            if center_fallback
            else ""
        ),
        "quality": {
            "matches": 4 if center_fallback else 16,
            "inliers": 4 if center_fallback else int(inliers.sum()),
            "fit": "marker-centers" if center_fallback else "marker-corners",
            "max_corner_relative_error": round(relative_error, 4),
            "median_error_px": round(float(np.median(error)), 3),
        },
    }


def marker_centers(markers):
    centers = []
    for marker_id in MARKER_IDS:
        corners = np.c_[markers[marker_id], np.ones(4)]
        center = np.cross(
            np.cross(corners[0], corners[2]), np.cross(corners[1], corners[3])
        )
        if not np.isfinite(center).all() or abs(center[2]) < 1e-9:
            raise ValueError("รูปทรง ArUco เสื่อมสภาพ กรุณาถ่ายภาพใหม่ให้ป้ายชัด")
        centers.append(center[:2] / center[2])
    return np.float32(centers)


def marker_sides(markers):
    return np.maximum(
        1.0,
        np.float32(
            [
                np.median(
                    np.linalg.norm(np.roll(markers[i], -1, axis=0) - markers[i], axis=1)
                )
                for i in MARKER_IDS
            ]
        ),
    )


def aruco_planogram(image, plan, token=None, preview=False):
    if not isinstance(plan, dict):
        raise ValueError("เลือก Planogram ที่ถ่ายหลังติด ArUco ก่อน")
    key = _key(image, plan)
    with _lock:
        now = time.monotonic()
        for old in list(_previews):
            if now - _previews[old]["time"] > PREVIEW_TTL:
                del _previews[old]
        if preview:
            matrix, metadata = estimate_matrix(_reference(plan), image)
            projected = project_planogram(image, plan, matrix)
            token = uuid.uuid4().hex
            metadata.update(
                applied=True,
                mode="planogram-to-image",
                method="aruco",
                dictionary=DICTIONARY,
                matrix_direction="reference-to-upload",
                matrix=matrix.tolist(),
                preview_token=token,
            )
            entry = {
                "time": time.monotonic(),
                "key": key,
                "matrix": matrix,
                "metadata": metadata,
            }
            _previews[token] = entry
            while len(_previews) > 16:
                _previews.popitem(last=False)
        else:
            entry = _previews.get(token)
            if entry is None or entry["key"] != key:
                raise ValueError(
                    "กรุณาจัดแนว ArUco และตรวจกรอบใหม่ก่อน Detect (ตัวอย่างหมดอายุหรือภาพ/แผนเปลี่ยน)"
                )
            projected = project_planogram(image, plan, entry["matrix"])
        return projected, copy.deepcopy(entry["metadata"])
