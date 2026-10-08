import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from types import SimpleNamespace

import cv2
import numpy as np

import training
from training import TrainingManager, validate_annotations
import app as api


class TrainingTests(unittest.TestCase):
    def test_annotation_validation(self):
        valid = [{"class_name": "product-a", "box": [0.1, 0.2, 0.8, 0.9]}]
        self.assertEqual(validate_annotations(valid, ["product-a"]), valid)
        for invalid in [
            [],
            [{"class_name": "unknown", "box": [0, 0, 1, 1]}],
            [{"class_name": "product-a", "box": [0.8, 0.2, 0.1, 0.9]}],
            [{"class_name": "product-a", "box": [0, 0, float("nan"), 1]}],
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_annotations(invalid, ["product-a"])

    def test_images_round_trip_and_yolo_dataset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(training, "TRAINING_IMAGES_DIR", root / "images"), \
                 patch.object(training, "TRAINING_JOBS_DIR", root / "jobs"), \
                 patch.object(training, "MODEL_ARCHIVE_DIR", root / "archive"):
                manager = TrainingManager(lambda: ["product-a", "product-b"])
                for index in range(4):
                    encoded = cv2.imencode(".jpg", np.full((24, 32, 3), index * 30, dtype=np.uint8))[1].tobytes()
                    upload = io.BytesIO(encoded)
                    upload.filename = f"sample-{index}.jpg"
                    manager.save_image(upload, [
                        {"class_name": "product-a", "box": [0.1, 0.2, 0.8, 0.9]},
                        {"class_name": "product-b", "box": [0.2, 0.1, 0.4, 0.5]},
                    ])

                rows = manager.list_images()
                self.assertEqual(len(rows), 4)
                detail = manager.get_image(rows[0]["id"])
                self.assertEqual(len(detail["annotations"]), 2)
                self.assertTrue(base64.b64decode(detail["image"].split(",", 1)[1]))
                manager.update_annotations(rows[0]["id"], [
                    {"class_name": "product-b", "box": [0.2, 0.1, 0.4, 0.5]},
                ])

                job_root = root / "jobs" / "test-job"
                data_yaml = manager._build_dataset(job_root)
                self.assertIn('0: "product-a"', data_yaml.read_text(encoding="utf-8"))
                self.assertEqual(len(list((job_root / "dataset/images/train").glob("*.jpg"))), 3)
                self.assertEqual(len(list((job_root / "dataset/images/val").glob("*.jpg"))), 1)
                label = next((job_root / "dataset/labels/train").glob("*.txt"))
                self.assertIn(label.read_text(encoding="utf-8").split()[0], {"0", "1"})

    def test_split_keeps_target_and_replay_in_both_sets(self):
        rows = [{"id": str(index), "annotations": [{"class_name": name}
                for name in (["a", "b"] if index < 2 else ["a"])]} for index in range(10)]
        rows.append({"id": "rare", "annotations": [{"class_name": "rare"}]})
        splits = TrainingManager._split_dataset(rows, ["a"])
        self.assertEqual(splits, TrainingManager._split_dataset(rows, ["a"]))
        self.assertFalse({r["id"] for r in splits["train"]} & {r["id"] for r in splits["val"]})
        for split in splits.values():
            names = {item["class_name"] for row in split for item in row["annotations"]}
            self.assertTrue({"a", "b"}.issubset(names))
        self.assertIn("rare", {r["id"] for r in splits["train"]})

    def test_missing_detections_do_not_inherit_overall_map(self):
        results = SimpleNamespace(results_dict={"metrics/mAP50-95(B)": 0.8},
                                  box=SimpleNamespace(ap_class_index=[1], maps=[0.8, 0.8]))
        self.assertEqual(TrainingManager._evaluation_metrics(results, [0])["target/mAP50-95"], 0)
        self.assertEqual(TrainingManager._evaluation_metrics(results, [1])["target/mAP50-95"], 0.8)
        results.results_dict["metrics/mAP50-95(B)"] = float("nan")
        with self.assertRaises(RuntimeError):
            TrainingManager._evaluation_metrics(results, [1])

    def test_duplicate_images_cannot_leak_into_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(training, "TRAINING_IMAGES_DIR", root / "images"), \
                 patch.object(training, "TRAINING_JOBS_DIR", root / "jobs"), \
                 patch.object(training, "MODEL_ARCHIVE_DIR", root / "archive"):
                manager = TrainingManager(lambda: ["a"])
                for value in [0, 30, 60, 90, 0]:
                    upload = io.BytesIO(cv2.imencode(".jpg", np.full((24, 32, 3), value, dtype=np.uint8))[1].tobytes())
                    upload.filename = "sample.jpg"
                    manager.save_image(upload, [{"class_name": "a", "box": [0.1, 0.1, 0.9, 0.9]}])
                job_root = root / "jobs" / "dataset-test"
                manager._build_dataset(job_root, target_class="a")
                summary = json.loads((job_root / "dataset_summary.json").read_text())
                self.assertEqual(summary["unique_image_count"], 4)
                self.assertEqual(summary["duplicates_removed"], 1)
                images = list((job_root / "dataset/images").rglob("*.jpg"))
                self.assertEqual(len(images), 4)
                # A newer revision replaces shifted boxes rather than accumulating them.
                rows = manager.list_images()
                zeros = [r for r in rows if cv2.imread(str(root / "images" / manager._read_manifest(r["id"])["filename"])).max() == 0]
                manager.update_annotations(zeros[0]["id"], [{"class_name": "a", "box": [0.2, 0.2, 0.8, 0.8]}])
                revised_root = root / "jobs" / "revision"
                manager._build_dataset(revised_root, target_class="a")
                labels = list((revised_root / "dataset/labels").rglob("*.txt"))
                self.assertEqual(len(labels), 4)
                self.assertEqual(sum("0.60000000 0.60000000" in label.read_text() for label in labels), 1)

    def test_duplicate_labels_merge_classes_and_use_latest_revision(self):
        first = {"id": "first", "created_at": "2026-01-01", "annotations": [
            {"class_name": "a", "box": [0.0, 0.0, 0.4, 0.8]},
        ]}
        revision = {"id": "second", "created_at": "2026-01-02", "annotations": [
            {"class_name": "a", "box": [0.01, 0.01, 0.41, 0.81]},
        ]}
        other_class = {"id": "third", "created_at": "2026-01-03", "annotations": [
            {"class_name": "b", "box": [0.6, 0.0, 1.0, 0.8]},
        ]}
        merged = TrainingManager._merge_duplicate_labels([other_class, first, revision])
        self.assertEqual(merged["annotations"], revision["annotations"] + other_class["annotations"])
        self.assertEqual(first["annotations"][0]["box"], [0.0, 0.0, 0.4, 0.8])
        # Updating an old upload must win over a newer creation date.
        first["updated_at"] = "2026-01-04"
        merged = TrainingManager._merge_duplicate_labels([first, revision, other_class])
        self.assertEqual(merged["annotations"], first["annotations"] + other_class["annotations"])

    def test_duplicate_same_object_with_different_classes_is_rejected(self):
        rows = [{"id": name, "annotations": [
            {"class_name": name, "box": [0.1, 0.1, 0.9, 0.9]},
        ]} for name in ["a", "b"]]
        with self.assertRaisesRegex(ValueError, "a.*b"):
            TrainingManager._merge_duplicate_labels(rows)

    def test_job_evaluates_saved_best_checkpoint_and_keeps_active_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            active = root / "active.pt"
            active.write_bytes(b"original-model")
            with patch.object(training, "TRAINING_IMAGES_DIR", root / "images"), \
                 patch.object(training, "TRAINING_JOBS_DIR", root / "jobs"), \
                 patch.object(training, "MODEL_ARCHIVE_DIR", root / "archive"), \
                 patch.object(training, "PRODUCT_MODEL_PATH", active):
                manager = TrainingManager(lambda: ["a"])
                for value in [0, 30, 60, 90]:
                    upload = io.BytesIO(cv2.imencode(".jpg", np.full((24, 32, 3), value, dtype=np.uint8))[1].tobytes())
                    upload.filename = "sample.jpg"
                    manager.save_image(upload, [{"class_name": "a", "box": [0.1, 0.1, 0.9, 0.9]}])
                job_id = "a" * 32
                manager._write_job({"id": job_id, "status": "queued", "epochs": 5})
                candidate = root / "jobs" / job_id / "runs/finetune/weights/best.pt"
                def result(score):
                    return SimpleNamespace(results_dict={"metrics/mAP50-95(B)": score},
                                           box=SimpleNamespace(ap_class_index=[0], maps=[score]))
                baseline_model, source_model, best_model = Mock(), Mock(), Mock()
                baseline_model.val.return_value = result(0.2)
                best_model.val.return_value = result(0.4)
                def train(**kwargs):
                    candidate.parent.mkdir(parents=True)
                    candidate.write_bytes(b"best-model")
                source_model.train.side_effect = train
                with patch.object(training, "attach_preservation", return_value={"version": 1}) as package, \
                     patch.object(training, "YOLO", side_effect=[baseline_model, source_model, best_model]) as loader:
                    manager._run(job_id, 5, "a")
                state = manager._read_job(job_id)
                self.assertEqual(state["status"], "completed")
                package.assert_called_once_with(candidate, root / "jobs" / job_id / "source.pt", ["a"], root / "archive")
                self.assertEqual(state["metrics_scope"], "target_specialist")
                self.assertEqual(state["baseline_metrics"]["target/mAP50-95"], 0.2)
                self.assertEqual(state["metrics"]["target/mAP50-95"], 0.4)
                self.assertTrue(state["comparison"]["improved"])
                self.assertEqual(loader.call_args_list[2].args[0], str(candidate))
                self.assertEqual(baseline_model.val.call_args.kwargs["data"], best_model.val.call_args.kwargs["data"])
                self.assertEqual(active.read_bytes(), b"original-model")
                self.assertFalse((root / "jobs" / job_id / "source.pt").exists())

    def test_training_upload_endpoint_saves_annotated_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(training, "TRAINING_IMAGES_DIR", root / "images"), \
                 patch.object(training, "TRAINING_JOBS_DIR", root / "jobs"), \
                 patch.object(training, "MODEL_ARCHIVE_DIR", root / "archive"):
                manager = TrainingManager(lambda: ["product-a"])
                encoded = cv2.imencode(".jpg", np.zeros((24, 32, 3), dtype=np.uint8))[1].tobytes()
                with patch.object(api, "training_manager", manager):
                    image = io.BytesIO(encoded)
                    response = api.app.test_client().post(
                        "/training/images",
                        data={
                            "image": (image, "training.jpg"),
                            "annotations": json.dumps([
                                {"class_name": "product-a", "box": [0.1, 0.1, 0.9, 0.9]},
                            ]),
                        },
                        content_type="multipart/form-data",
                    )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json["data"]["annotation_count"], 1)

    def test_training_endpoint_rejects_external_browser_origin(self):
        response = api.app.test_client().get(
            "/training/images", headers={"Origin": "https://example.com"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_training_endpoint_allows_local_browser_origin(self):
        response = api.app.test_client().get(
            "/training/images", headers={"Origin": "http://localhost:8080"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:8080")


if __name__ == "__main__":
    unittest.main()
