import uuid
import json
import hashlib
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import cv2
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

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
from planogram import validate_inference_plan, validate_plan
from training import TrainingManager


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE * 2 + 128 * 1024
model_service = ShelfModelService(PRODUCT_MODEL_PATH, GAP_MODEL_PATH)
training_manager = TrainingManager(model_service.class_names, model_service)

@lru_cache(maxsize=4)
def model_hash(path, modified, size):
    with open(path, 'rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def model_version(path):
    stat = path.stat()
    return model_hash(str(path), stat.st_mtime_ns, stat.st_size)

# สร้างพื้นที่จัดเก็บเมื่อ service เริ่มทำงาน เพื่อให้ PHP ใช้เป็น upload temp ได้
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
RESULT_DIR.mkdir(parents=True, exist_ok=True)


def error_response(message: str, status_code: int):
    return jsonify({"success": False, "message": message}), status_code


def is_local_browser_origin(origin: str) -> bool:
    try:
        parsed = urlparse(origin)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and parsed.hostname.lower() in {"localhost", "127.0.0.1"}
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


@app.before_request
def protect_training_endpoints():
    origin = request.headers.get("Origin", "")
    if request.path.startswith("/training/") and origin and not is_local_browser_origin(origin):
        return error_response("ไม่อนุญาตคำขอจากเว็บไซต์นี้", 403)


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
    origin = request.headers.get("Origin", "")
    if origin and is_local_browser_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
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


@app.get("/training/classes")
def training_classes():
    try:
        names = model_service.class_names()
        return jsonify({"success": True, "count": len(names), "data": names})
    except ModelServiceError as exc:
        return error_response(str(exc), 503)


@app.get("/training/images")
def training_images():
    return jsonify({"success": True, "data": training_manager.list_images()})


@app.post("/training/images/pending")
def add_pending_training_image():
    try:
        saved = training_manager.save_image(request.files.get("image"), [], allow_unlabeled=True)
        return jsonify({"success": True, "data": saved}), 201
    except ValueError as exc:
        return error_response(str(exc), 400)
    except ModelServiceError as exc:
        return error_response(str(exc), 503)


@app.post("/training/images")
def add_training_image():
    image_file = request.files.get("image")
    try:
        annotations = json.loads(request.form.get("annotations", "null"))
        saved = training_manager.save_image(image_file, annotations)
        return jsonify({"success": True, "data": saved}), 201
    except (ValueError, json.JSONDecodeError) as exc:
        return error_response(str(exc), 400)
    except ModelServiceError as exc:
        return error_response(str(exc), 503)


@app.get("/training/images/<image_id>")
def get_training_image(image_id):
    try:
        return jsonify({"success": True, "data": training_manager.get_image(image_id)})
    except ValueError as exc:
        return error_response(str(exc), 400)
    except FileNotFoundError as exc:
        return error_response(str(exc), 404)


@app.put("/training/images/<image_id>")
def update_training_image(image_id):
    try:
        body = request.get_json(silent=True) or {}
        saved = training_manager.update_annotations(image_id, body.get("annotations"))
        return jsonify({"success": True, "data": saved})
    except ValueError as exc:
        return error_response(str(exc), 400)
    except FileNotFoundError as exc:
        return error_response(str(exc), 404)
    except ModelServiceError as exc:
        return error_response(str(exc), 503)


@app.delete("/training/images/<image_id>")
def delete_training_image(image_id):
    try:
        return jsonify({"success": True, "data": training_manager.delete_image(image_id)})
    except ValueError as exc:
        return error_response(str(exc), 400)
    except FileNotFoundError as exc:
        return error_response(str(exc), 404)


@app.get("/training/jobs/latest")
def latest_training_job():
    return jsonify({"success": True, "data": training_manager.job()})


@app.get("/training/models")
def training_models():
    try:
        return jsonify({"success": True, "data": training_manager.list_models()})
    except (OSError, ModelServiceError) as exc:
        return error_response(str(exc), 503)


@app.get("/training/jobs/<job_id>")
def get_training_job(job_id):
    try:
        return jsonify({"success": True, "data": training_manager.job(job_id)})
    except ValueError as exc:
        return error_response(str(exc), 400)
    except FileNotFoundError as exc:
        return error_response(str(exc), 404)


@app.post("/training/jobs")
def start_training_job():
    try:
        body = request.get_json(silent=True) or {}
        state = training_manager.start(body.get("epochs", 60), body.get("target_class"))
        return jsonify({"success": True, "data": state}), 202
    except ValueError as exc:
        return error_response(str(exc), 400)


@app.post("/training/jobs/<job_id>/activate")
def activate_training_job(job_id):
    try:
        state = training_manager.activate(job_id)
        model_hash.cache_clear()
        return jsonify({"success": True, "data": state})
    except ValueError as exc:
        return error_response(str(exc), 400)
    except FileNotFoundError as exc:
        return error_response(str(exc), 404)
    except (OSError, ModelServiceError) as exc:
        return error_response(str(exc), 500)


@app.post("/training/models/activate")
def activate_selected_model():
    try:
        body = request.get_json(silent=True) or {}
        result = training_manager.select_model(body.get("model_id"))
        model_hash.cache_clear()
        return jsonify({"success": True, "data": result})
    except ValueError as exc:
        return error_response(str(exc), 400)
    except FileNotFoundError as exc:
        return error_response(str(exc), 404)
    except (OSError, ModelServiceError) as exc:
        return error_response(str(exc), 500)


@app.post("/training/models/delete")
def delete_training_model():
    try:
        body = request.get_json(silent=True) or {}
        return jsonify({"success": True, "data": training_manager.delete_model(body.get("model_id"))})
    except ValueError as exc:
        return error_response(str(exc), 400)
    except FileNotFoundError as exc:
        return error_response(str(exc), 404)
    except OSError as exc:
        return error_response(str(exc), 500)


@app.post("/predict")
def predict():
    image_file = request.files.get("image")
    if image_file is None or not image_file.filename:
        return error_response("กรุณาเลือกไฟล์ภาพ", 400)

    try:
        plan_id = request.form.get('planogram_id', '').strip()
        raw_plan = request.form.get('planogram', 'null')
        plan = json.loads(raw_plan)
        if plan_id and (not isinstance(plan, dict) or plan.get('id') != plan_id):
            return error_response('แผนถูกเปลี่ยนหรือไม่พบ กรุณาโหลดหน้าใหม่และเลือกแผนอีกครั้ง', 409)
        if plan is not None and not plan_id:
            return error_response('กรุณาระบุรหัส Planogram', 400)
        if plan is not None:
            plan = validate_inference_plan(plan, model_service.class_names())
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
    upload_id = uuid.uuid4().hex
    upload_path = UPLOAD_DIR / f"{upload_id}{extension}"
    result_filename = f"{uuid.uuid4().hex}.jpg"
    result_path = RESULT_DIR / result_filename
    cleanup_paths = {upload_path, result_path}

    try:
        image_file.save(upload_path)
        if upload_path.stat().st_size > MAX_FILE_SIZE:
            upload_path.unlink(missing_ok=True)
            return error_response("ไฟล์ภาพต้องมีขนาดไม่เกิน 10 MB", 413)
        # ตรวจเนื้อหาไฟล์จริง ไม่เชื่อเฉพาะนามสกุลจากผู้ใช้
        image = cv2.imread(str(upload_path))
        if image is None:
            upload_path.unlink(missing_ok=True)
            return error_response("ไฟล์ที่อัปโหลดไม่ใช่ภาพที่อ่านได้", 400)
        detection_result = model_service.detect_scene(
            upload_path, result_path, product_confidence, gap_confidence, plan
        )
    except ValueError as exc:
        for path in cleanup_paths:
            path.unlink(missing_ok=True)
        return error_response(str(exc), 400)
    except ModelServiceError as exc:
        for path in cleanup_paths:
            path.unlink(missing_ok=True)
        return error_response(str(exc), 503)
    except Exception:
        for path in cleanup_paths:
            path.unlink(missing_ok=True)
        raise

    return jsonify(
        {
            "success": True,
            "product_confidence": product_confidence,
            "gap_confidence": gap_confidence,
            **detection_result,
            "input_image_path": f"storage/uploads/{upload_path.name}",
            "result_image_path": f"storage/results/{result_filename}",
            "product_model": model_version(PRODUCT_MODEL_PATH),
            "gap_model": model_version(GAP_MODEL_PATH),
            "result_image_url": f"{request.host_url.rstrip('/')}/results/{result_filename}",
        }
    )


@app.get("/results/<path:filename>")
def result_image(filename):
    return send_from_directory(RESULT_DIR, filename)


@app.post('/planogram/validate')
def planogram():
    try:
        plan = validate_plan(request.get_json(silent=True), model_service.class_names())
        return jsonify(success=True, data=plan)
    except ValueError as exc:
        return error_response(str(exc), 400)
    except (OSError, ModelServiceError) as exc:
        return error_response(str(exc), 503)


@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(_error):
    return error_response("ไฟล์อัปโหลดมีขนาดรวมเกินขีดจำกัด", 413)


@app.errorhandler(404)
def handle_not_found(_error):
    return error_response("ไม่พบ endpoint ที่ร้องขอ", 404)


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    if isinstance(error, HTTPException):
        return error_response(error.description, error.code or 500)
    app.logger.exception("Unhandled AI service request failure")
    return error_response("AI service ประมวลผลไม่สำเร็จ กรุณาตรวจ terminal log", 500)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8001, debug=False)
