import base64
import hashlib
import io
import json
import logging
import math
import random
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO
from PIL import Image, UnidentifiedImageError

from preservation import attach_preservation, ProductDetector, METADATA_KEY
from config import MODEL_ARCHIVE_DIR, PRODUCT_MODEL_PATH, TRAINING_IMAGES_DIR, TRAINING_JOBS_DIR


LOGGER = logging.getLogger(__name__)
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
MAX_ANNOTATIONS_PER_IMAGE = 300
MIN_TRAINING_IMAGES = 4
MAX_IMAGE_PIXELS = 40_000_000


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_annotations(value, classes):
    if not isinstance(value, list) or not value:
        raise ValueError("วาดกรอบสินค้าอย่างน้อย 1 กรอบก่อนบันทึก")
    if len(value) > MAX_ANNOTATIONS_PER_IMAGE:
        raise ValueError("ภาพหนึ่งภาพมีกรอบสินค้าได้ไม่เกิน 300 กรอบ")
    cleaned = []
    for annotation in value:
        if not isinstance(annotation, dict):
            raise ValueError("ข้อมูลกรอบสินค้าไม่ถูกต้อง")
        class_name = annotation.get("class_name")
        box = annotation.get("box")
        if class_name not in classes:
            raise ValueError("เลือกคลาสสินค้าจากรายการที่ระบบแสดง")
        if not isinstance(box, list) or len(box) != 4:
            raise ValueError("กรอบสินค้าต้องมีพิกัด 4 ค่า")
        if any(type(number) not in (int, float) or not math.isfinite(number) for number in box):
            raise ValueError("พิกัดกรอบสินค้าไม่ถูกต้อง")
        x1, y1, x2, y2 = map(float, box)
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError("กรอบสินค้าต้องอยู่ภายในภาพ")
        cleaned.append({"class_name": class_name, "box": [x1, y1, x2, y2]})
    return cleaned


class TrainingManager:
    def __init__(self, class_names, model_service=None):
        self.class_names = class_names
        self.model_service = model_service
        self._lock = threading.RLock()
        self._dataset_lock = threading.RLock()
        self._thread = None
        TRAINING_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        TRAINING_JOBS_DIR.mkdir(parents=True, exist_ok=True)
        MODEL_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        self._recover_interrupted_job()

    def _manifest_path(self, image_id):
        if not isinstance(image_id, str) or not ID_PATTERN.fullmatch(image_id):
            raise ValueError("รหัสภาพไม่ถูกต้อง")
        return TRAINING_IMAGES_DIR / f"{image_id}.json"

    def _read_manifest(self, image_id):
        path = self._manifest_path(image_id)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError("ไม่พบภาพชุดฝึก") from exc
        if not isinstance(manifest, dict) or manifest.get("id") != image_id:
            raise ValueError("ข้อมูลภาพชุดฝึกไม่ถูกต้อง")
        return manifest

    @staticmethod
    def _atomic_json(path, value):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _save_manifest(self, manifest):
        self._atomic_json(self._manifest_path(manifest["id"]), manifest)

    def list_images(self):
        with self._dataset_lock:
            images = []
            for path in TRAINING_IMAGES_DIR.glob("*.json"):
                try:
                    row = json.loads(path.read_text(encoding="utf-8"))
                    counts = {}
                    for item in row.get("annotations", []):
                        counts[item["class_name"]] = counts.get(item["class_name"], 0) + 1
                    images.append({
                        "id": row["id"],
                        "filename": row.get("display_name", row["filename"]),
                        "created_at": row["created_at"],
                        "width": row["width"],
                        "height": row["height"],
                        "annotation_count": len(row.get("annotations", [])),
                        "class_counts": counts,
                    })
                except (OSError, ValueError, KeyError, TypeError):
                    LOGGER.exception("Skipping invalid training manifest: %s", path.name)
            images.sort(key=lambda row: row["created_at"], reverse=True)
            return images

    def get_image(self, image_id):
        with self._dataset_lock:
            manifest = self._read_manifest(image_id)
            image_path = TRAINING_IMAGES_DIR / manifest["filename"]
            try:
                encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            except OSError as exc:
                raise FileNotFoundError("ไม่พบไฟล์ภาพชุดฝึก") from exc
            suffix = image_path.suffix.lower()
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[suffix]
            return {
                **manifest,
                "filename": manifest.get("display_name", manifest["filename"]),
                "image": f"data:{mime};base64,{encoded}",
            }

    def save_image(self, image_file, annotations, allow_unlabeled=False):
        if not image_file or not image_file.filename:
            raise ValueError("เลือกไฟล์ภาพก่อนบันทึก")
        extension = Path(image_file.filename).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise ValueError("รองรับภาพ JPG, PNG และ WEBP")
        image_bytes = image_file.read()
        if not image_bytes or len(image_bytes) > 10 * 1024 * 1024:
            raise ValueError("ภาพต้องมีขนาดไม่เกิน 10 MB")
        try:
            with Image.open(io.BytesIO(image_bytes)) as source_image:
                width, height = source_image.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise ValueError("ภาพมีความละเอียดสูงเกินไป")
                source_image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("ไฟล์ที่เลือกอ่านเป็นภาพไม่ได้") from exc
        frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("ไฟล์ที่เลือกอ่านเป็นภาพไม่ได้")
        cleaned = [] if allow_unlabeled and annotations == [] else validate_annotations(annotations, self.class_names())
        image_id = uuid.uuid4().hex
        filename = f"{image_id}{extension}"
        image_path = TRAINING_IMAGES_DIR / filename
        manifest_path = self._manifest_path(image_id)
        manifest = {
            "id": image_id,
            "filename": filename,
            "display_name": Path(image_file.filename).name[:120] or filename,
            "created_at": utc_now(),
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
            "annotations": cleaned,
        }
        with self._dataset_lock:
            temporary = image_path.with_suffix(image_path.suffix + ".tmp")
            try:
                temporary.write_bytes(image_bytes)
                temporary.replace(image_path)
                self._save_manifest(manifest)
            except Exception:
                temporary.unlink(missing_ok=True)
                image_path.unlink(missing_ok=True)
                manifest_path.unlink(missing_ok=True)
                raise
        return self._summary(manifest)

    def update_annotations(self, image_id, annotations):
        cleaned = validate_annotations(annotations, self.class_names())
        with self._dataset_lock:
            manifest = self._read_manifest(image_id)
            manifest["annotations"] = cleaned
            manifest["updated_at"] = utc_now()
            self._save_manifest(manifest)
        return self._summary(manifest)

    @staticmethod
    def _summary(manifest):
        counts = {}
        for item in manifest["annotations"]:
            counts[item["class_name"]] = counts.get(item["class_name"], 0) + 1
        return {
            "id": manifest["id"], "filename": manifest.get("display_name", manifest["filename"]),
            "created_at": manifest["created_at"], "width": manifest["width"],
            "height": manifest["height"], "annotation_count": len(manifest["annotations"]),
            "class_counts": counts,
        }

    def job(self, job_id=None):
        with self._lock:
            state = self._read_job(job_id) if job_id else self._latest_job()
            return state

    @staticmethod
    def _file_hash(path):
        digest = hashlib.sha256()
        with Path(path).open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def list_models(self):
        with self._lock:
            active_hash = self._file_hash(PRODUCT_MODEL_PATH)
            models = [{
                "id": "current", "label": "โมเดลเดิม",
                "model_hash": active_hash, "current": True,
            }]
            seen_hashes = {active_hash}

            job_files = list(TRAINING_JOBS_DIR.glob("*.json"))
            completed_jobs = []
            for job_file in job_files:
                try:
                    state = json.loads(job_file.read_text(encoding="utf-8"))
                    if state.get("id") != job_file.stem or not ID_PATTERN.fullmatch(str(state.get("id", ""))):
                        continue
                    # Deleted jobs retain their place in the sequence so deleting
                    # an older model never renames the models that remain.
                    if state.get("status") == "deleted" and re.fullmatch(
                        r"[a-f0-9]{64}", str(state.get("deleted_model_hash", ""))
                    ):
                        completed_jobs.append((str(state.get("created_at", "")), state["id"], None))
                        continue
                    if state.get("status") not in {"completed", "activated"} or not state.get("candidate"):
                        continue
                    candidate = Path(state["candidate"]).resolve()
                    if TRAINING_JOBS_DIR.resolve() not in candidate.parents or not candidate.is_file():
                        continue
                    model_hash = self._file_hash(candidate)
                    completed_jobs.append((str(state.get("created_at", "")), state["id"], model_hash))
                except (OSError, ValueError, KeyError, TypeError):
                    LOGGER.exception("Skipping invalid training job model: %s", job_file.name)
            completed_jobs.sort(key=lambda row: (row[0], row[1]))
            for fine_tune_number, (_created, job_id, model_hash) in enumerate(completed_jobs, start=1):
                if model_hash is None:
                    continue
                label = f"โมเดลที่ Fine-tune {fine_tune_number}"
                if model_hash == active_hash:
                    models[0]["label"] = label
                    continue
                if model_hash in seen_hashes:
                    continue
                seen_hashes.add(model_hash)
                models.append({
                    "id": f"job:{job_id}", "label": label,
                    "model_hash": model_hash, "current": False, "deletable": True,
                })

            archive_files = sorted(
                MODEL_ARCHIVE_DIR.glob("bestProduct-*.pt"),
                key=lambda path: path.stat().st_mtime_ns,
            )
            backup_number = 0
            for archive in archive_files:
                archive_id = archive.stem.removeprefix("bestProduct-")
                if not re.fullmatch(r"(?:[a-f0-9]{16}|[a-f0-9]{64})", archive_id):
                    continue
                if not archive.is_file():
                    continue
                model_hash = self._file_hash(archive)
                if model_hash in seen_hashes:
                    continue
                seen_hashes.add(model_hash)
                if archive == archive_files[0]:
                    label = "โมเดลเดิม"
                else:
                    backup_number += 1
                    label = f"โมเดลสำรอง {backup_number}"
                models.append({
                    "id": f"archive:{archive_id}",
                    "label": label,
                    "model_hash": model_hash, "current": False,
                })
            return models

    def _model_source(self, model_id):
        if model_id == "current":
            return PRODUCT_MODEL_PATH, None
        if isinstance(model_id, str) and re.fullmatch(r"job:[a-f0-9]{32}", model_id):
            job_id = model_id.split(":", 1)[1]
            state = self._read_job(job_id)
            if state.get("status") not in {"completed", "activated"} or not state.get("candidate"):
                raise ValueError("งานนี้ยังไม่มีโมเดลที่ผ่านการฝึก")
            candidate = Path(state["candidate"]).resolve()
            if TRAINING_JOBS_DIR.resolve() not in candidate.parents or not candidate.is_file():
                raise ValueError("ไม่พบไฟล์โมเดลที่ฝึกเสร็จ")
            return candidate, state
        if isinstance(model_id, str) and re.fullmatch(r"archive:(?:[a-f0-9]{16}|[a-f0-9]{64})", model_id):
            suffix = model_id.split(":", 1)[1]
            archive = (MODEL_ARCHIVE_DIR / f"bestProduct-{suffix}.pt").resolve()
            if MODEL_ARCHIVE_DIR.resolve() not in archive.parents or not archive.is_file():
                raise FileNotFoundError("ไม่พบไฟล์โมเดลสำรอง")
            return archive, None
        raise ValueError("ไม่พบโมเดลที่เลือก")

    def select_model(self, model_id):
        with self._lock:
            source, state = self._model_source(model_id)
            if model_id == "current":
                return {
                    "model_id": "current", "active_model": self._file_hash(PRODUCT_MODEL_PATH),
                    "message": "โมเดลนี้กำลังใช้งานอยู่แล้ว",
                }

            candidate_model = ProductDetector(source, MODEL_ARCHIVE_DIR)
            candidate_names = [str(candidate_model.names[index]) for index in sorted(candidate_model.names)]
            if candidate_names != self.class_names():
                raise ValueError("คลาสในโมเดลที่เลือกไม่ตรงกับโมเดลปัจจุบัน")
            del candidate_model

            active_hash = self._file_hash(PRODUCT_MODEL_PATH)
            selected_hash = self._file_hash(source)
            if selected_hash != active_hash:
                archive_path = MODEL_ARCHIVE_DIR / f"bestProduct-{active_hash[:16]}.pt"
                if archive_path.exists() and self._file_hash(archive_path) != active_hash:
                    archive_path = MODEL_ARCHIVE_DIR / f"bestProduct-{active_hash}.pt"
                if not archive_path.exists():
                    shutil.copy2(PRODUCT_MODEL_PATH, archive_path)
                temporary = PRODUCT_MODEL_PATH.with_name(f".{PRODUCT_MODEL_PATH.name}.{uuid.uuid4().hex}.tmp")
                try:
                    shutil.copy2(source, temporary)
                    temporary.replace(PRODUCT_MODEL_PATH)
                    if self.model_service:
                        self.model_service.reload_product_model()
                except Exception:
                    temporary.unlink(missing_ok=True)
                    restore = PRODUCT_MODEL_PATH.with_name(f".{PRODUCT_MODEL_PATH.name}.{uuid.uuid4().hex}.restore")
                    shutil.copy2(archive_path, restore)
                    restore.replace(PRODUCT_MODEL_PATH)
                    if self.model_service:
                        self.model_service.reload_product_model()
                    raise

            if state is not None:
                state.update({
                    "status": "activated", "updated_at": utc_now(),
                    "message": "เปิดใช้โมเดลแล้ว", "active_model": selected_hash,
                })
                self._write_job(state)
            return {
                "model_id": model_id, "active_model": selected_hash,
                "message": "เปิดใช้โมเดลที่เลือกแล้ว",
            }

    def delete_model(self, model_id):
        with self._lock:
            if not isinstance(model_id, str) or not re.fullmatch(r"job:[a-f0-9]{32}", model_id):
                raise ValueError("ลบได้เฉพาะโมเดลที่ Fine-tune และไม่ได้ใช้งานอยู่")
            source, state = self._model_source(model_id)
            selected_hash = self._file_hash(source)
            if selected_hash == self._file_hash(PRODUCT_MODEL_PATH):
                raise ValueError("ลบโมเดลที่กำลังใช้งานไม่ได้ กรุณาเปิดใช้โมเดลอื่นก่อน")
            jobs = [json.loads(path.read_text(encoding="utf-8"))
                    for path in TRAINING_JOBS_DIR.glob("*.json")]
            if any(row.get("status") in {"queued", "running"} for row in jobs):
                raise ValueError("รอให้การ Fine-tune เสร็จก่อนลบโมเดล")
            job_dir = (TRAINING_JOBS_DIR / state["id"]).resolve()
            if source.parent != job_dir / "runs" / "finetune" / "weights":
                raise ValueError("ตำแหน่งไฟล์โมเดลของงานไม่ถูกต้อง")
            # Check every retained checkpoint, including legacy archives whose
            # dependencies may not be recorded in the job JSON.
            checkpoints = {PRODUCT_MODEL_PATH.resolve()}
            checkpoints.update(path.resolve() for path in MODEL_ARCHIVE_DIR.glob("*.pt"))
            checkpoints.update(path.resolve() for path in TRAINING_JOBS_DIR.rglob("*.pt"))
            aliases = {path for path in checkpoints if self._file_hash(path) == selected_hash}
            for path in checkpoints - aliases:
                model = YOLO(str(path))
                metadata = (model.ckpt or {}).get(METADATA_KEY) or {}
                if metadata.get("source_hash") == selected_hash:
                    raise ValueError("ลบไม่ได้ โมเดลนี้เป็นต้นทางของโมเดลอื่นที่ยังเก็บอยู่")
                del model
            # Keep the job record and metrics; delete its model artifacts and
            # identical backups so the deleted model does not reappear in the picker.
            source.unlink()
            for path in aliases - {source}:
                if MODEL_ARCHIVE_DIR.resolve() in path.parents:
                    path.unlink()
            for row in jobs:
                candidate = Path(row.get("candidate") or "").resolve()
                if candidate == source or candidate in aliases:
                    if candidate != source and candidate.is_file():
                        candidate.unlink()
                    row.update(status="deleted", candidate=None, deleted_model_hash=selected_hash,
                               message="ลบโมเดลที่ Fine-tune แล้ว")
                    self._write_job(row)
            # The final-epoch checkpoint is not selectable and is no longer useful.
            source.with_name("last.pt").unlink(missing_ok=True)
            return {"model_id": model_id, "message": "ลบโมเดลที่ Fine-tune แล้ว"}

    def start(self, epochs=60, target_class=None):
        if type(epochs) is not int or not 5 <= epochs <= 100:
            raise ValueError("จำนวน epochs ต้องอยู่ระหว่าง 5 ถึง 100")
        with self._lock:
            latest = self._latest_job()
            if latest and latest["status"] in {"queued", "running"}:
                raise ValueError("มีงาน Fine-tune กำลังทำงานอยู่แล้ว")
            with self._dataset_lock:
                images = self.list_images()
                available_classes = self.class_names()
                if target_class is None:
                    labeled_classes = {
                        name for row in images for name in row["class_counts"]
                    }
                    if len(labeled_classes) == 1:
                        target_class = next(iter(labeled_classes))
                    else:
                        raise ValueError("เลือกคลาสเป้าหมายที่จะ Fine-tune ก่อน")
                if not isinstance(target_class, str) or target_class not in available_classes:
                    raise ValueError("เลือกคลาสเป้าหมายจากรายการคลาสของโมเดล")
                target_images = [
                    row for row in images if row["class_counts"].get(target_class, 0) > 0
                ]
                if len(target_images) < MIN_TRAINING_IMAGES:
                    raise ValueError(
                        f"คลาส {target_class} ต้องมีภาพที่ติดป้ายอย่างน้อย {MIN_TRAINING_IMAGES} ภาพ"
                    )
            job_id = uuid.uuid4().hex
            state = {
                "id": job_id, "status": "queued", "created_at": utc_now(),
                "updated_at": utc_now(), "epoch": 0, "epochs": epochs,
                "progress": 0, "image_count": len(target_images),
                "target_class": target_class, "target_classes": [target_class], "metrics": {},
                "message": "รอเริ่ม Fine-tune", "candidate": None,
            }
            self._write_job(state)
            self._thread = threading.Thread(
                target=self._run, args=(job_id, epochs, target_class), daemon=True
            )
            self._thread.start()
            return state

    def activate(self, job_id):
        self.select_model(f"job:{job_id}")
        return self._read_job(job_id)

    def _run(self, job_id, epochs, target_class):
        state = self._read_job(job_id)
        state.update({"status": "running", "updated_at": utc_now(), "message": "กำลังเตรียมชุดข้อมูล"})
        self._write_job(state)
        try:
            job_dir = TRAINING_JOBS_DIR / job_id
            data_yaml, target_class_ids, target_class_names = self._build_dataset(
                job_dir, include_target_classes=True, target_class=target_class
            )
            # Training and baseline must use the same source even if the user
            # switches the active detector while the background job is running.
            source_model = job_dir / "source.pt"
            with self._lock:
                shutil.copy2(PRODUCT_MODEL_PATH, source_model)
            baseline_model = YOLO(str(source_model))
            validation_args = dict(
                data=str(data_yaml), imgsz=640, batch=4, workers=0,
                plots=False, verbose=False, split="val", max_det=300,
            )
            baseline = self._evaluation_metrics(baseline_model.val(
                **validation_args, project=str(job_dir / "evaluation"), name="baseline"
            ), target_class_ids)
            # Validation can fuse Conv/BatchNorm for inference. Reload unfused
            # checkpoint weights so training retains its original BatchNorm state.
            del baseline_model
            model = YOLO(str(source_model))
            state = self._read_job(job_id)
            state.update({
                "target_classes": target_class_names, "baseline_metrics": baseline,
                "training_strategy": "protected_target_adapter",
                "dataset": json.loads((job_dir / "dataset_summary.json").read_text(encoding="utf-8")),
                "message": "กำลังฝึกคลาสเป้าหมาย · เก็บโมเดลต้นทางเพื่อรักษาสินค้าคลาสอื่น",
            })
            self._write_job(state)

            def on_epoch_end(trainer):
                current = min(epochs, int(trainer.epoch) + 1)
                metrics = {}
                for key, value in getattr(trainer, "metrics", {}).items():
                    try:
                        metrics[key] = round(float(value), 5)
                    except (TypeError, ValueError):
                        continue
                current_state = self._read_job(job_id)
                current_state.update({
                    "status": "running", "epoch": current, "progress": round(current / epochs * 100),
                    "updated_at": utc_now(), "metrics": metrics,
                    "message": f"ฝึก epoch {current}/{epochs}",
                })
                self._write_job(current_state)

            model.add_callback("on_fit_epoch_end", on_epoch_end)
            model.train(
                data=str(data_yaml), epochs=epochs, imgsz=640, batch=4,
                workers=0, patience=min(20, epochs), pretrained=True,
                optimizer="AdamW", lr0=0.0001, lrf=0.1, cos_lr=True,
                warmup_epochs=min(3, epochs / 5), warmup_bias_lr=0.0001,
                weight_decay=0.0005, freeze=None, seed=2026, deterministic=True,
                mosaic=0.3, close_mosaic=min(10, epochs // 5), mixup=0.0,
                degrees=3.0, translate=0.05, scale=0.2,
                fliplr=0.0, flipud=0.0, hsv_h=0.01, hsv_s=0.3, hsv_v=0.25,
                project=str(job_dir / "runs"), name="finetune", exist_ok=True,
                plots=False, save=True, verbose=False,
            )
            candidate = job_dir / "runs" / "finetune" / "weights" / "best.pt"
            if not candidate.is_file():
                raise RuntimeError("การฝึกจบแล้วแต่ไม่พบไฟล์ best.pt")
            preservation = attach_preservation(candidate, source_model, target_class_names, MODEL_ARCHIVE_DIR)
            # Metrics below evaluate the specialist; deployed inference also uses
            # the immutable source model to protect every non-target detection.
            # Evaluate the actual saved best checkpoint, not the final epoch.
            candidate_model = YOLO(str(candidate))
            metrics = self._evaluation_metrics(candidate_model.val(
                **validation_args, project=str(job_dir / "evaluation"), name="candidate"
            ), target_class_ids)
            target_delta = metrics["target/mAP50-95"] - baseline["target/mAP50-95"]
            overall_delta = metrics["metrics/mAP50-95(B)"] - baseline["metrics/mAP50-95(B)"]
            improved = target_delta > 0 and overall_delta >= -0.01
            state = self._read_job(job_id)
            state.update({
                "status": "completed", "progress": 100, "updated_at": utc_now(),
                "candidate": str(candidate), "metrics": metrics,
                "source_model_hash": self._file_hash(source_model),
                "preservation": preservation, "metrics_scope": "target_specialist",
                "comparison": {
                    "target_map_delta": round(target_delta, 5),
                    "overall_map_delta": round(overall_delta, 5),
                    "improved": improved,
                },
                "message": ("ฝึกเสร็จ · เก็บโมเดลเดิมและเสริมคลาสเป้าหมาย ตรวจผลก่อนเปิดใช้" if improved
                            else "ฝึกเสร็จ · ยังไม่ยืนยันว่าดีกว่าโมเดลเดิม ควรเพิ่มข้อมูลและตรวจผลก่อนเปิดใช้"),
            })
            self._write_job(state)
        except Exception as exc:
            LOGGER.exception("Fine-tune job %s failed", job_id)
            try:
                state = self._read_job(job_id)
                state.update({
                    "status": "failed", "updated_at": utc_now(),
                    "message": f"Fine-tune ไม่สำเร็จ: {exc}",
                })
                self._write_job(state)
            except Exception:
                LOGGER.exception("Could not save failed training job state")
        finally:
            shutil.rmtree(TRAINING_JOBS_DIR / job_id / "dataset", ignore_errors=True)
            (TRAINING_JOBS_DIR / job_id / "source.pt").unlink(missing_ok=True)

    @staticmethod
    def _evaluation_metrics(results, target_class_ids):
        metrics = {}
        for key, value in results.results_dict.items():
            number = float(value)
            if not math.isfinite(number):
                raise RuntimeError("คะแนน validation ไม่ใช่ค่าที่วัดได้")
            metrics[key] = round(number, 5)
        # Ultralytics fills missing classes in maps with the overall score.
        # A target with no evaluated detections must score zero, not that fallback.
        evaluated_ids = {int(index) for index in results.box.ap_class_index}
        metrics["target/mAP50-95"] = round(float(np.mean([
            results.box.maps[index] if index in evaluated_ids else 0.0
            for index in target_class_ids
        ])), 5)
        if not math.isfinite(metrics["target/mAP50-95"]):
            raise RuntimeError("คะแนนคลาสเป้าหมายไม่ถูกต้อง")
        return metrics

    def _build_dataset(self, job_dir, include_target_classes=False, target_class=None):
        with self._dataset_lock:
            manifests = []
            for path in TRAINING_IMAGES_DIR.glob("*.json"):
                row = json.loads(path.read_text(encoding="utf-8"))
                if row.get("annotations"):
                    manifests.append({**row, "_revision_ns": path.stat().st_mtime_ns})
            manifests.sort(key=lambda row: row["id"])
            if len(manifests) < MIN_TRAINING_IMAGES:
                raise ValueError(f"ต้องมีภาพที่ติดป้ายแล้วอย่างน้อย {MIN_TRAINING_IMAGES} ภาพ")
            class_names = self.class_names()
            class_to_id = {name: index for index, name in enumerate(class_names)}
            target_class_names = [target_class] if target_class else sorted({
                annotation["class_name"]
                for row in manifests
                for annotation in row["annotations"]
            })
            if any(name not in class_to_id for name in target_class_names):
                raise ValueError("ไม่พบคลาสเป้าหมายในโมเดลปัจจุบัน")
            target_class_ids = sorted(class_to_id[name] for name in target_class_names)
            # Group identical pixels before splitting. Repeated uploads can be
            # revised labels or labels for different products in the same image.
            groups = {}
            duplicate_count = 0
            for row in manifests:
                source = TRAINING_IMAGES_DIR / row["filename"]
                frame = cv2.imread(str(source))
                if frame is None:
                    raise ValueError(f"อ่านภาพ {row['filename']} ไม่ได้")
                annotations = validate_annotations(row["annotations"], class_names)
                digest = hashlib.sha256(str(frame.shape).encode() + frame.tobytes()).hexdigest()
                if digest in groups:
                    duplicate_count += 1
                groups.setdefault(digest, []).append({**row, "annotations": annotations})
            manifests = [self._merge_duplicate_labels(rows) for rows in groups.values()]
            targets = [row for row in manifests if any(
                item["class_name"] in target_class_names for item in row["annotations"]
            )]
            if len(targets) < MIN_TRAINING_IMAGES:
                raise ValueError(f"ต้องมีภาพคลาสเป้าหมายที่ไม่ซ้ำกันอย่างน้อย {MIN_TRAINING_IMAGES} ภาพ")
            split_rows = self._split_dataset(manifests, target_class_names)
            summary = {
                "unique_image_count": len(manifests), "duplicates_removed": duplicate_count,
                "duplicate_policy": "latest_labels_per_class",
                "splits": {split: {
                    "image_count": len(rows),
                    "class_image_counts": {name: sum(any(
                        item["class_name"] == name for item in row["annotations"]
                    ) for row in rows) for name in class_names},
                } for split, rows in split_rows.items()},
                "warnings": [],
            }
            if len(targets) < 30:
                summary["warnings"].append("ภาพเป้าหมายน้อยกว่า 30 ภาพ คะแนนอาจแปรปรวน ควรเพิ่มภาพจากหลายมุมและแสง")
            missing = [name for name in class_names if not summary["splits"]["train"]["class_image_counts"][name]]
            if missing:
                summary["warnings"].append("ตัวเสริมไม่มีภาพฝึกของคลาส: " + ", ".join(missing) + " · ใช้โมเดลต้นทางตรวจคลาสอื่น")
            unmeasured = [name for name in class_names if not summary["splits"]["val"]["class_image_counts"][name]]
            if unmeasured:
                summary["warnings"].append("ไม่มีภาพ validation ของคลาส: " + ", ".join(unmeasured))
            summary["splits"]["train"]["image_ids"] = [row["id"] for row in split_rows["train"]]
            summary["splits"]["val"]["image_ids"] = [row["id"] for row in split_rows["val"]]
            job_dir.mkdir(parents=True, exist_ok=True)
            self._atomic_json(job_dir / "dataset_summary.json", summary)
            dataset_root = job_dir / "dataset"
            for split, rows in split_rows.items():
                image_dir = dataset_root / "images" / split
                label_dir = dataset_root / "labels" / split
                image_dir.mkdir(parents=True, exist_ok=True)
                label_dir.mkdir(parents=True, exist_ok=True)
                for row in rows:
                    source = TRAINING_IMAGES_DIR / row["filename"]
                    if not source.is_file():
                        raise ValueError(f"ไม่พบภาพ {row['filename']}")
                    shutil.copy2(source, image_dir / row["filename"])
                    lines = []
                    for annotation in row["annotations"]:
                        class_id = class_to_id.get(annotation["class_name"])
                        if class_id is None:
                            raise ValueError(f"ไม่พบคลาส {annotation['class_name']}")
                        x1, y1, x2, y2 = annotation["box"]
                        center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
                        width, height = x2 - x1, y2 - y1
                        lines.append(f"{class_id} {center_x:.8f} {center_y:.8f} {width:.8f} {height:.8f}")
                    label_path = label_dir / f"{Path(row['filename']).stem}.txt"
                    label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            yaml_names = "\n".join(f"  {index}: {json.dumps(name, ensure_ascii=False)}" for index, name in enumerate(class_names))
            data_yaml = dataset_root / "data.yaml"
            data_yaml.write_text(
                f"path: {json.dumps(str(dataset_root))}\n"
                "train: images/train\nval: images/val\n"
                f"names:\n{yaml_names}\n",
                encoding="utf-8",
            )
            if include_target_classes:
                return data_yaml, target_class_ids, target_class_names
            return data_yaml

    @staticmethod
    def _merge_duplicate_labels(rows):
        # Treat the latest labeling of each class as its complete revision.
        # Combine classes, but never accumulate slightly shifted boxes for the
        # same product from successive uploads. Do not modify saved manifests.
        ordered = sorted(rows, key=lambda row: (
            row.get("updated_at", row.get("created_at", "")),
            row.get("_revision_ns", 0),
            row.get("created_at", ""), row["id"],
        ))
        by_class = {}
        for row in ordered:
            class_labels = {}
            for item in row["annotations"]:
                class_labels.setdefault(item["class_name"], []).append(item)
            by_class.update(class_labels)
        annotations = [item for name in sorted(by_class) for item in by_class[name]]
        for index, item in enumerate(annotations):
            for other in annotations[index + 1:]:
                if item["class_name"] == other["class_name"]:
                    continue
                ax1, ay1, ax2, ay2 = item["box"]
                bx1, by1, bx2, by2 = other["box"]
                intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
                union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
                if union > 0 and intersection / union >= 0.8:
                    image_ids = ", ".join(row["id"][:8] for row in ordered)
                    raise ValueError(
                        f"ภาพซ้ำ {image_ids} มีกรอบเดียวกันติดป้าย {item['class_name']} และ {other['class_name']} กรุณาแก้คลาสให้ตรงกัน"
                    )
        return {**ordered[-1], "annotations": annotations}

    @staticmethod
    def _split_dataset(manifests, target_class_names):
        """Seeded multilabel split, retaining training examples of rare classes."""
        rows = list(manifests)
        random.Random(2026).shuffle(rows)
        labels = {row["id"]: {item["class_name"] for item in row["annotations"]} for row in rows}
        counts = {}
        for names in labels.values():
            for name in names:
                counts[name] = counts.get(name, 0) + 1
        remaining = dict(counts)
        validation = []
        covered = set()
        desired = max(1, round(len(rows) * 0.2))
        # Cover target and other classes with at least two independent images.
        priorities = list(target_class_names) + sorted(counts, key=lambda name: counts[name])
        for name in priorities:
            if name in covered or counts.get(name, 0) < 2:
                continue
            candidates = [row for row in rows if row not in validation and name in labels[row["id"]]
                          and all(remaining[item] > 1 for item in labels[row["id"]])]
            if candidates:
                chosen = max(candidates, key=lambda row: len(labels[row["id"]] - covered))
                validation.append(chosen)
                covered.update(labels[chosen["id"]])
                for item in labels[chosen["id"]]:
                    remaining[item] -= 1
        for row in rows:
            if len(validation) >= desired:
                break
            if row not in validation and all(remaining[name] > 1 for name in labels[row["id"]]):
                validation.append(row)
                for name in labels[row["id"]]:
                    remaining[name] -= 1
        if not validation or not set(target_class_names).issubset(
            set().union(*(labels[row["id"]] for row in validation))
        ):
            raise ValueError("แบ่ง validation ที่มีคลาสเป้าหมายและเหลือภาพฝึกทุกคลาสไม่ได้ กรุณาเพิ่มภาพที่หลากหลาย")
        train = [row for row in rows if row not in validation]
        if not train:
            raise ValueError("ไม่มีภาพเหลือสำหรับฝึก")
        return {"train": train, "val": validation}

    def _job_path(self, job_id):
        if not isinstance(job_id, str) or not ID_PATTERN.fullmatch(job_id):
            raise ValueError("รหัสงานไม่ถูกต้อง")
        return TRAINING_JOBS_DIR / f"{job_id}.json"

    def _read_job(self, job_id):
        try:
            return json.loads(self._job_path(job_id).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError("ไม่พบงาน Fine-tune") from exc

    def _write_job(self, state):
        state["updated_at"] = utc_now()
        self._atomic_json(self._job_path(state["id"]), state)

    def _latest_job(self):
        jobs = sorted(TRAINING_JOBS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
        return json.loads(jobs[0].read_text(encoding="utf-8")) if jobs else None

    def _recover_interrupted_job(self):
        with self._lock:
            state = self._latest_job()
            if state and state.get("status") in {"queued", "running"}:
                state.update({
                    "status": "interrupted", "updated_at": utc_now(),
                    "message": "AI service รีสตาร์ตระหว่าง Fine-tune; โมเดลใช้งานเดิมยังไม่เปลี่ยน",
                })
                self._write_job(state)
