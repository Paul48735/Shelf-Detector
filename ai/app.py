import uuid
from pathlib import Path

import cv2
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from config import (
    ALLOWED_EXTENSIONS,
    DEFAULT_GAP_CONFIDENCE,
    DEFAULT_PRODUCT_CONFIDENCE,
    GAP_MODEL_PATH,
    MAX_FILE_SIZE,
    PRODUCT_MODEL_PATH,
    RESULT_DIR,
    UPLOAD_DIR,
)
from model_service import ModelServiceError, ShelfModelService


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE
model_service = ShelfModelService(PRODUCT_MODEL_PATH, GAP_MODEL_PATH)

# สร้างพื้นที่จัดเก็บเมื่อ service เริ่มทำงาน เพื่อให้ PHP ใช้เป็น upload temp ได้
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)


def error_response(message: str, status_code: int):
    return jsonify({"success": False, "message": message}), status_code


def parse_confidence(value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence ต้องเป็นตัวเลข") from exc
    if not 0.01 <= parsed <= 1.0:
        raise ValueError("confidence ต้องอยู่ระหว่าง 0.01 ถึง 1.00")
    return parsed


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.get("/health")
def health():
    missing_models = [
        str(path)
        for path in (PRODUCT_MODEL_PATH, GAP_MODEL_PATH)
        if not path.is_file()
    ]
    if missing_models:
        return error_response("ไม่พบไฟล์โมเดล: " + ", ".join(missing_models), 503)
    return jsonify(
        {
            "success": True,
            "message": "AI service is ready",
            "product_model": str(PRODUCT_MODEL_PATH),
            "gap_model": str(GAP_MODEL_PATH),
        }
    )


@app.get("/classes")
def classes():
    try:
        names = model_service.class_names()
        return jsonify({"success": True, "count": len(names), "data": names})
    except ModelServiceError as exc:
        return error_response(str(exc), 503)


@app.post("/predict")
def predict():
    image_file = request.files.get("image")
    if image_file is None or not image_file.filename:
        return error_response("กรุณาเลือกไฟล์ภาพ", 400)

    try:
        product_confidence = parse_confidence(
            request.form.get(
                "product_confidence", DEFAULT_PRODUCT_CONFIDENCE
            )
        )
        gap_confidence = parse_confidence(
            request.form.get("gap_confidence", DEFAULT_GAP_CONFIDENCE)
        )
    except ValueError as exc:
        return error_response(str(exc), 400)

    extension = Path(image_file.filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        return error_response("รองรับเฉพาะไฟล์ JPG, JPEG, PNG และ WEBP", 400)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    upload_path = UPLOAD_DIR / f"{file_id}{extension}"
    result_filename = f"{file_id}.jpg"
    result_path = RESULT_DIR / result_filename

    try:
        image_file.save(upload_path)
        # ตรวจเนื้อหาไฟล์จริง ไม่เชื่อเฉพาะนามสกุลจากผู้ใช้
        if cv2.imread(str(upload_path)) is None:
            upload_path.unlink(missing_ok=True)
            return error_response("ไฟล์ที่อัปโหลดไม่ใช่ภาพที่อ่านได้", 400)

        detection_result = model_service.detect_scene(
            upload_path,
            result_path,
            product_confidence,
            gap_confidence,
        )
    except ValueError as exc:
        return error_response(str(exc), 400)
    except ModelServiceError as exc:
        return error_response(str(exc), 503)

    return jsonify(
        {
            "success": True,
            "product_confidence": product_confidence,
            "gap_confidence": gap_confidence,
            **detection_result,
            "result_image_url": f"{request.host_url.rstrip('/')}/results/{result_filename}",
        }
    )


@app.get("/results/<path:filename>")
def result_image(filename):
    return send_from_directory(RESULT_DIR, filename)


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(_error):
    return error_response("ไฟล์มีขนาดเกิน 10 MB", 413)


@app.errorhandler(404)
def handle_not_found(_error):
    return error_response("ไม่พบ endpoint ที่ร้องขอ", 404)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
