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
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import torch
from ultralytics import YOLO
from PIL import Image, UnidentifiedImageError

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
                label = f"โมเดลที่ Fine-tune {fine_tune_number}"
                if model_hash == active_hash:
                    models[0]["label"] = label
                    continue
                if model_hash in seen_hashes:
                    continue
                seen_hashes.add(model_hash)
                models.append({
                    "id": f"job:{job_id}", "label": label,
                    "model_hash": model_hash, "current": False,
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

            candidate_model = YOLO(str(source))
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

    def start(self, epochs=30, target_class=None):
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
            model = YOLO(str(PRODUCT_MODEL_PATH))
            original_state = {
                name: value.detach().cpu().clone()
                for name, value in model.model.state_dict().items()
            }
            output_layers = self._class_output_layers(model.model)

            def freeze_to_selected_classes(trainer):
                layers = self._class_output_layers(trainer.model)
                for parameter in trainer.model.parameters():
                    parameter.requires_grad_(False)
                for _name, layer in layers:
                    if layer.out_channels != len(self.class_names()):
                        raise RuntimeError("จำนวนช่องคลาสของหัวตรวจจับไม่ตรงกับโมเดล")
                    for parameter in (layer.weight, layer.bias):
                        if parameter is None:
                            continue
                        parameter.requires_grad_(True)
                        mask = torch.zeros(
                            parameter.shape[0], dtype=parameter.dtype, device=parameter.device
                        )
                        mask[target_class_ids] = 1
                        mask = mask.reshape((-1,) + (1,) * (parameter.ndim - 1))
                        parameter.register_hook(lambda gradient, grad_mask=mask: gradient * grad_mask)

            def keep_batch_norm_frozen(trainer):
                for module in trainer.model.modules():
                    if isinstance(module, torch.nn.modules.batchnorm._BatchNorm):
                        module.eval()

            model.add_callback("on_pretrain_routine_end", freeze_to_selected_classes)
            model.add_callback("on_train_batch_start", keep_batch_norm_frozen)
            state = self._read_job(job_id)
            state.update({
                "target_classes": target_class_names,
                "message": "กำลังปรับเฉพาะคลาส " + ", ".join(target_class_names),
            })
            self._write_job(state)

            def on_epoch_end(trainer):
                current = int(trainer.epoch) + 1
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
                workers=0, patience=min(8, epochs), pretrained=True,
                project=str(job_dir / "runs"), name="finetune", exist_ok=True,
                plots=False, save=True, verbose=False,
            )
            candidate = job_dir / "runs" / "finetune" / "weights" / "best.pt"
            if not candidate.is_file():
                raise RuntimeError("การฝึกจบแล้วแต่ไม่พบไฟล์ best.pt")
            self._keep_only_selected_class_changes(model, original_state, output_layers, target_class_ids, candidate)
            state = self._read_job(job_id)
            state.update({
                "status": "completed", "progress": 100, "updated_at": utc_now(),
                "candidate": str(candidate),
                "message": "ฝึกเสร็จ ปรับเฉพาะคลาส " + ", ".join(target_class_names) + " แล้ว · ตรวจ metrics ก่อนเปิดใช้",
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

    @staticmethod
    def _class_output_layers(model):
        head = model.model[-1]
        branches = getattr(head, "cv3", None)
        if not branches:
            raise RuntimeError("โมเดลนี้ไม่รองรับการ Fine-tune แยกตามคลาส")
        module_names = {id(module): name for name, module in model.named_modules()}
        layers = []
        for branch in branches:
            layer = branch[-1]
            if not isinstance(layer, torch.nn.Conv2d):
                raise RuntimeError("โครงสร้างหัวคลาสของโมเดลไม่รองรับการ Fine-tune แยกคลาส")
            name = module_names.get(id(layer))
            if not name or layer.bias is None:
                raise RuntimeError("หาเลเยอร์ผลลัพธ์ของคลาสในโมเดลไม่พบ")
            layers.append((name, layer))
        return layers

    def _keep_only_selected_class_changes(self, model, original_state, output_layers, target_class_ids, candidate):
        trained_state = model.model.state_dict()
        output_keys = {
            f"{name}.{field}"
            for name, _layer in output_layers
            for field in ("weight", "bias")
        }
        merged_state = {}
        for name, original in original_state.items():
            if name not in trained_state:
                raise RuntimeError(f"โครงสร้างโมเดลเปลี่ยนระหว่างฝึก: {name}")
            restored = original.clone()
            if name in output_keys:
                trained = trained_state[name].detach().cpu()
                if trained.shape != restored.shape:
                    raise RuntimeError(f"ขนาดเลเยอร์คลาสเปลี่ยนระหว่างฝึก: {name}")
                restored[target_class_ids] = trained[target_class_ids]
            merged_state[name] = restored
        model.model.load_state_dict(merged_state, strict=True)

        # Ultralytics prefers the EMA entry when loading a checkpoint, so update both
        # checkpoint model entries after restoring every non-target weight.
        model.ckpt["ema"] = deepcopy(model.model).half()
        model.ckpt["model"] = None
        temporary = candidate.with_name(candidate.stem + ".selective.tmp.pt")
        try:
            model.save(temporary)
            temporary.replace(candidate)
        finally:
            temporary.unlink(missing_ok=True)

    def _build_dataset(self, job_dir, include_target_classes=False, target_class=None):
        with self._dataset_lock:
            manifests = []
            for path in TRAINING_IMAGES_DIR.glob("*.json"):
                row = json.loads(path.read_text(encoding="utf-8"))
                if row.get("annotations"):
                    manifests.append(row)
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
            random.Random(2026).shuffle(manifests)
            validation_count = max(1, round(len(manifests) * 0.2))
            validation_count = min(validation_count, len(manifests) - 1)
            split_rows = {
                "train": manifests[validation_count:],
                "val": manifests[:validation_count],
            }
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
