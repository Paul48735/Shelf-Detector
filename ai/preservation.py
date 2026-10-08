"""Keep the source detector immutable while adding a target-class specialist."""
import hashlib
import re
import shutil
import uuid
from pathlib import Path

from ultralytics import YOLO


METADATA_KEY = "shelf_preservation"


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def attach_preservation(candidate, source, target_classes, archive_dir):
    """Archive the complete source (including previous adapters) before packaging."""
    candidate, source, archive_dir = map(Path, (candidate, source, archive_dir))
    source_hash = file_hash(source)
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = archive_dir / f"bestProduct-{source_hash}.pt"
    if archived.exists():
        if file_hash(archived) != source_hash:
            raise ValueError("ไฟล์โมเดลต้นทางที่เก็บสำรองไม่ตรงกับ hash")
    else:
        temporary = archived.with_name(f".{archived.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copy2(source, temporary)
            temporary.replace(archived)
        finally:
            temporary.unlink(missing_ok=True)
    model = YOLO(str(candidate))
    source_model = ProductDetector(source, archive_dir)
    if model.names != source_model.names:
        raise ValueError("คลาสของโมเดลใหม่ไม่ตรงกับโมเดลต้นทาง")
    targets = sorted(set(target_classes))
    if not targets or not set(targets).issubset(set(model.names.values())):
        raise ValueError("คลาสที่จะเสริมไม่ถูกต้อง")
    model.ckpt[METADATA_KEY] = {
        "version": 1, "source_hash": source_hash, "target_classes": targets,
    }
    # YOLO loading prefers ema, so avoid retaining a stale EMA entry on save.
    model.ckpt["ema"] = None
    temporary = candidate.with_name(f".{candidate.stem}.{uuid.uuid4().hex}.pt")
    try:
        model.save(str(temporary))
        temporary.replace(candidate)
    finally:
        temporary.unlink(missing_ok=True)
    return model.ckpt[METADATA_KEY]


def overlaps(first, second):
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
    first_area = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    second_area = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = first_area + second_area - intersection
    return (intersection / union >= 0.3 if union else False) or (
        intersection / min(first_area, second_area) >= 0.6 if min(first_area, second_area) else False
    )


def merge_detections(original, tuned, target_classes):
    """Keep every non-target detection; a specialist may only update its targets."""
    targets = set(target_classes)
    protected = [item for item in original if item["class_name"] not in targets]
    additions = [item for item in tuned if item["class_name"] in targets and not any(
        overlaps(item["box"], old["box"]) for old in protected
    )]
    additions.sort(key=lambda item: item["confidence"], reverse=True)
    accepted = []
    for item in additions:
        if not any(overlaps(item["box"], other["box"]) for other in accepted):
            accepted.append(item)
    # If the specialist misses a previously detected target, retain the source result.
    retained = [item for item in original if item["class_name"] in targets and not any(
        overlaps(item["box"], other["box"]) for other in accepted
    )]
    return protected + retained + accepted


class ProductDetector:
    def __init__(self, path, archive_dir, ancestors=()):
        path, archive_dir = Path(path), Path(archive_dir)
        resolved = str(path.resolve())
        if resolved in ancestors or len(ancestors) >= 32:
            raise ValueError("โมเดลต้นทางอ้างอิงวนซ้ำหรือซ้อนกันมากเกินไป")
        self.model = YOLO(str(path))
        self.names = self.model.names
        self.base = None
        self.targets = []
        metadata = (self.model.ckpt or {}).get(METADATA_KEY)
        if metadata is None:
            return
        if not isinstance(metadata, dict) or metadata.get("version") != 1:
            raise ValueError("ข้อมูลการรักษาโมเดลเดิมไม่ถูกต้อง")
        source_hash = metadata.get("source_hash", "")
        targets = metadata.get("target_classes")
        if not isinstance(source_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", source_hash):
            raise ValueError("รหัสโมเดลต้นทางไม่ถูกต้อง")
        if not isinstance(targets, list) or not targets or any(
            not isinstance(name, str) or name not in self.names.values() for name in targets
        ):
            raise ValueError("คลาสที่จะเสริมไม่ถูกต้อง")
        source = archive_dir / f"bestProduct-{source_hash}.pt"
        if not source.is_file() or file_hash(source) != source_hash:
            raise ValueError("ไม่พบโมเดลต้นทางที่ถูกต้องสำหรับรักษาคลาสเดิม")
        self.base = ProductDetector(source, archive_dir, (*ancestors, resolved))
        if self.base.names != self.names:
            raise ValueError("คลาสของโมเดลต้นทางไม่ตรงกัน")
        self.targets = targets

    def predict_detections(self, image, confidence):
        kwargs = dict(source=image, conf=confidence, verbose=False)
        if self.base is not None:
            kwargs["classes"] = [index for index, name in self.names.items() if name in self.targets]
        result = self.model.predict(**kwargs)[0]
        tuned = []
        if result.boxes is not None:
            for box in result.boxes:
                class_id = int(box.cls[0])
                tuned.append({
                    "class_name": str(result.names[class_id]),
                    "confidence": float(box.conf[0]),
                    "box": tuple(float(value) for value in box.xyxy[0].cpu().tolist()),
                })
        if self.base is None:
            return tuned
        return merge_detections(self.base.predict_detections(image, confidence), tuned, self.targets)
