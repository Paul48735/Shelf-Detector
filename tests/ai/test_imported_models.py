import tempfile
import json
import os
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import training
from training import TrainingManager


class ImportedModelTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.active = self.root / "bestProduct.pt"
        self.active.write_bytes(b"original")
        self.stack.enter_context(
            patch.multiple(
                training,
                PRODUCT_MODEL_PATH=self.active,
                TRAINING_IMAGES_DIR=self.root / "images",
                TRAINING_JOBS_DIR=self.root / "jobs",
                MODEL_ARCHIVE_DIR=self.root / "archive",
            )
        )
        self.service = Mock()
        self.manager = TrainingManager(lambda: ["a"], self.service)
        self.imported = self.root / "imported" / "bestProductFinetune-1.pt"
        self.imported.parent.mkdir()
        self.imported.write_bytes(b"imported-model")
        self.model_id = "imported:" + self.imported.name

    def test_list_uses_original_filename_without_activating(self):
        row = next(r for r in self.manager.list_models() if r["id"] == self.model_id)
        self.assertEqual(row["label"], self.imported.name)
        self.assertFalse(row["current"])
        self.assertFalse(row.get("deletable", False))
        self.assertEqual(self.active.read_bytes(), b"original")

    def test_legacy_history_moves_and_remains_readable_after_restart(self):
        job_id = "e" * 32
        old = self.root / "jobs" / (job_id + ".json")
        original = {"id": job_id, "status": "failed", "message": "previous result"}
        old.write_text(json.dumps(original))
        restarted = TrainingManager(lambda: ["a"], self.service)
        self.assertFalse(old.exists())
        self.assertTrue((restarted.history_dir / old.name).is_file())
        self.assertEqual(restarted.job(job_id), original)
        self.assertEqual(restarted.job()["id"], job_id)
        self.assertEqual(TrainingManager(lambda: ["a"]).job(job_id), original)

    def test_conflicting_legacy_history_is_not_overwritten(self):
        job_id = "e" * 32
        self.manager._write_job({"id": job_id, "status": "failed", "message": "new"})
        old = self.root / "jobs" / (job_id + ".json")
        old.write_text(json.dumps({"id": job_id, "status": "failed", "message": "old"}))
        with self.assertRaises(ValueError):
            TrainingManager(lambda: ["a"])
        self.assertTrue(old.exists())
        self.assertEqual(self.manager.job(job_id)["message"], "new")

    def test_selection_loads_imported_file_directly_and_survives_restart(self):
        with patch.object(
            training, "ProductDetector", return_value=SimpleNamespace(names={0: "a"})
        ):
            self.manager.select_model(self.model_id)
        self.assertEqual(self.active.read_bytes(), b"original")
        self.assertEqual(self.manager.active_model_path, self.imported.resolve())
        self.assertEqual(self.manager.list_models()[0]["label"], self.imported.name)
        self.service.reload_product_model.assert_called_once_with(self.imported.resolve())
        self.assertFalse(list((self.root / "archive").glob("*.pt")))
        restarted = TrainingManager(lambda: ["a"], self.service)
        self.assertEqual(restarted.active_model_path, self.imported.resolve())

    def test_active_job_does_not_override_imported_filename(self):
        self.active.write_bytes(self.imported.read_bytes())
        candidate = self.root / "jobs" / ("a" * 32) / "best.pt"
        candidate.parent.mkdir()
        candidate.write_bytes(self.imported.read_bytes())
        self.manager._write_job(
            {
                "id": "a" * 32,
                "status": "completed",
                "created_at": "2026-01-01",
                "candidate": str(candidate),
            }
        )
        models = self.manager.list_models()
        self.assertEqual(models[0]["label"], self.imported.name)
        self.assertEqual(len(models), 1)

    def test_paths_outside_import_directory_are_rejected(self):
        for filename in ("../bestProduct.pt", "/tmp/model.pt", "missing.pt"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.manager._model_source("imported:" + filename)
        (self.imported.parent / "outside.pt").symlink_to(self.active)
        with self.assertRaises(ValueError):
            self.manager._model_source("imported:outside.pt")

    def test_backups_hidden_and_original_remains_selectable(self):
        archive = self.root / "archive"
        original = archive / ("bestProduct-" + "a" * 64 + ".pt")
        original.write_bytes(b"original")
        os.utime(original, (1, 1))
        backup = archive / ("bestProduct-" + "b" * 64 + ".pt")
        backup.write_bytes(b"internal-backup")
        os.utime(backup, (2, 2))
        models = self.manager.list_models()
        self.assertEqual(len(models), 2)
        self.assertFalse(any(row["id"].startswith("archive:") for row in models))
        self.active.write_bytes(self.imported.read_bytes())
        models = self.manager.list_models()
        original_row = next(row for row in models if row["id"].startswith("archive:"))
        self.assertEqual(
            original_row["label"],
            "Original-model.pt",
        )
        self.assertEqual(len(models), 2)
        self.assertEqual(backup.read_bytes(), b"internal-backup")

    def test_missing_dependency_does_not_replace_active_model(self):
        with patch.object(
            training, "ProductDetector", side_effect=ValueError("Missing source")
        ):
            with self.assertRaises(ValueError):
                self.manager.select_model(self.model_id)
        self.assertEqual(self.active.read_bytes(), b"original")
        self.service.reload_product_model.assert_not_called()

    def test_failed_selection_save_restores_loaded_path(self):
        previous = self.manager.active_model_path
        with patch.object(training, "ProductDetector", return_value=SimpleNamespace(names={0: "a"})), patch.object(
            self.manager, "_save_selection", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                self.manager.select_model(self.model_id)
        self.assertEqual(self.manager.active_model_path, previous)
        self.assertEqual(self.service.reload_product_model.call_args_list[-1].args, (previous,))
        self.assertEqual(self.active.read_bytes(), b"original")

    def test_missing_selected_file_is_reported_after_restart(self):
        with patch.object(training, "ProductDetector", return_value=SimpleNamespace(names={0: "a"})):
            self.manager.select_model(self.model_id)
        self.imported.unlink()
        with self.assertRaises(ValueError):
            TrainingManager(lambda: ["a"])

    def test_model_service_failed_load_keeps_previous_model(self):
        from model_service import ShelfModelService, ModelServiceError
        service = ShelfModelService(self.active, self.root / "gap.pt")
        previous_model = object()
        service._product_model = previous_model
        with patch("model_service.ProductDetector", side_effect=ValueError("broken model")):
            with self.assertRaises(ModelServiceError):
                service.reload_product_model(self.imported)
        self.assertEqual(service.product_model_path, self.active)
        self.assertIs(service._product_model, previous_model)

    def test_saved_number_survives_removing_older_job_records(self):
        for job_id, number in [("c" * 32, 4), ("d" * 32, None)]:
            candidate = self.root / "jobs" / job_id / "best.pt"
            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(job_id.encode())
            state = {
                "id": job_id,
                "status": "completed",
                "created_at": job_id,
                "candidate": str(candidate),
            }
            if number:
                state["fine_tune_number"] = number
            self.manager._write_job(state)
        rows = {row["id"]: row for row in self.manager.list_models()}
        self.assertEqual(rows["job:" + "c" * 32]["label"], "fine-tune-v4.pt")
        self.assertEqual(rows["job:" + "d" * 32]["label"], "fine-tune-v5.pt")

    def test_new_model_continues_from_retained_models_after_deletion(self):
        self.manager._write_job({
            "id": "b" * 32, "status": "deleted", "created_at": "2025-01-01",
            "fine_tune_number": 5, "deleted_model_hash": "e" * 64,
        })
        for job_id, number in [("c" * 32, 1), ("d" * 32, None)]:
            candidate = self.root / "jobs" / job_id / "best.pt"
            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(job_id.encode())
            self.manager._write_job({
                "id": job_id, "status": "completed", "created_at": job_id,
                "candidate": str(candidate), "fine_tune_number": number,
            })
        rows = {row["id"]: row for row in self.manager.list_models()}
        self.assertEqual(rows["job:" + "d" * 32]["label"], "fine-tune-v2.pt")
        self.manager._name_trained_models()
        self.assertEqual(self.manager.job("d" * 32)["model_filename"], "fine-tune-v2.pt")
        self.assertEqual(self.manager.job("b" * 32)["fine_tune_number"], 5)
        self.assertEqual(
            TrainingManager(lambda: ["a"]).job("d" * 32)["model_filename"],
            "fine-tune-v2.pt",
        )

    def test_new_model_starts_at_one_when_all_previous_models_were_deleted(self):
        self.manager._write_job({
            "id": "b" * 32, "status": "deleted", "created_at": "2025-01-01",
            "fine_tune_number": 5, "deleted_model_hash": "e" * 64,
        })
        job_id = "c" * 32
        candidate = self.root / "jobs" / job_id / "best.pt"
        candidate.parent.mkdir(parents=True)
        candidate.write_bytes(b"new-model")
        self.manager._write_job({
            "id": job_id, "status": "completed", "created_at": "2026-01-01",
            "candidate": str(candidate),
        })
        row = next(row for row in self.manager.list_models() if row["id"] == "job:" + job_id)
        self.assertEqual(row["label"], "fine-tune-v1.pt")
        self.manager._name_trained_models()
        self.assertEqual(self.manager.job(job_id)["model_filename"], "fine-tune-v1.pt")

    def test_checkpoint_rename_preserves_bytes_and_is_stable_after_restart(self):
        job_id = "f" * 32
        checkpoint = self.root / "jobs" / job_id / "weights" / "best.pt"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"trained-checkpoint-with-source-metadata")
        expected_hash = self.manager._file_hash(checkpoint)
        self.manager._write_job({
            "id": job_id, "created_at": "2026-01-01", "status": "completed",
            "candidate": str(checkpoint), "fine_tune_number": 4,
        })
        self.manager._name_trained_models()
        renamed = checkpoint.with_name("fine-tune-v4.pt")
        self.assertFalse(checkpoint.exists())
        self.assertEqual(self.manager._file_hash(renamed), expected_hash)
        self.assertEqual(self.manager.job(job_id)["candidate"], str(renamed.resolve()))
        restarted = TrainingManager(lambda: ["a"], self.service)
        self.assertEqual(restarted.job(job_id)["model_filename"], renamed.name)
        self.assertEqual(self.manager._file_hash(renamed), expected_hash)
        self.assertEqual(self.active.read_bytes(), b"original")
        with patch.object(training, "ProductDetector", return_value=SimpleNamespace(names={0: "a"})):
            result = restarted.select_model("job:" + job_id)
        self.assertEqual(result["model_filename"], renamed.name)
        self.assertEqual(restarted.active_model_path, renamed.resolve())
        self.assertEqual(self.active.read_bytes(), b"original")

    def test_explicit_original_takes_priority_over_oldest_archive(self):
        original = self.root / "original" / "bestProduct.pt"
        original.parent.mkdir()
        original.write_bytes(b"replacement-original")
        archive = self.root / "archive" / ("bestProduct-" + "a" * 64 + ".pt")
        archive.write_bytes(b"obsolete-original")
        os.utime(archive, (1, 1))
        models = self.manager.list_models()
        rows = [row for row in models if row["label"] == "Original-model.pt"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "original")
        self.assertEqual(rows[0]["model_hash"], self.manager._file_hash(original))
        self.assertFalse(any(row["id"].startswith("archive:") for row in models))
        with patch.object(
            training, "ProductDetector", return_value=SimpleNamespace(names={0: "a"})
        ):
            self.manager.select_model("original")
            self.assertEqual(self.manager.active_model_path, original.resolve())
            self.assertEqual(self.active.read_bytes(), b"original")
            self.assertEqual(self.manager.list_models()[0]["label"], "Original-model.pt")
            self.manager.select_model(self.model_id)
            self.manager.select_model("original")
        self.assertEqual(self.manager.active_model_path, original.resolve())
        self.assertEqual(self.active.read_bytes(), b"original")
        self.assertEqual(archive.read_bytes(), b"obsolete-original")
        self.assertEqual(self.service.reload_product_model.call_count, 3)

    def test_imported_model_protects_its_source_from_deletion(self):
        job_id = "b" * 32
        candidate = (
            self.root / "jobs" / job_id / "runs" / "finetune" / "weights" / "best.pt"
        )
        candidate.parent.mkdir(parents=True)
        candidate.write_bytes(b"source-model")
        source_hash = self.manager._file_hash(candidate)
        self.manager._write_job(
            {
                "id": job_id,
                "status": "completed",
                "created_at": "2026-01-01",
                "candidate": str(candidate),
            }
        )

        def load(path):
            metadata = (
                {"source_hash": source_hash}
                if Path(path).resolve() == self.imported.resolve()
                else {}
            )
            return SimpleNamespace(ckpt={"shelf_preservation": metadata})

        with patch.object(training, "YOLO", side_effect=load):
            with self.assertRaises(ValueError):
                self.manager.delete_model("job:" + job_id)
        self.assertTrue(candidate.exists())


if __name__ == "__main__":
    unittest.main()
