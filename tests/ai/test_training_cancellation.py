import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app as api
import training
from training import TrainingManager


class TrainingCancellationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.active = self.root / "Original-model.pt"
        self.active.write_bytes(b"unchanged-active-model")
        self.stack.enter_context(patch.multiple(
            training, PRODUCT_MODEL_PATH=self.active,
            TRAINING_IMAGES_DIR=self.root / "images",
            TRAINING_JOBS_DIR=self.root / "jobs",
            MODEL_ARCHIVE_DIR=self.root / "archive",
        ))
        self.manager = TrainingManager(lambda: ["a"])
        self.job_id = "a" * 32
        self.manager._write_job({
            "id": self.job_id, "status": "queued", "epochs": 5,
            "epoch": 0, "progress": 0, "candidate": None,
        })

    def test_queued_cancel_does_not_start_training(self):
        self.assertEqual(self.manager.cancel(self.job_id)["status"], "cancelling")
        with patch.object(self.manager, "_build_dataset") as build:
            self.manager._run(self.job_id, 5, "a")
        build.assert_not_called()
        self.assertEqual(self.manager.job(self.job_id)["status"], "cancelled")
        self.assertEqual(self.active.read_bytes(), b"unchanged-active-model")
        self.assertEqual(self.manager.cancel(self.job_id)["status"], "cancelled")

    def test_cancel_during_batch_cleans_partial_training_and_keeps_active_model(self):
        folder = self.root / "jobs" / self.job_id
        folder.mkdir()
        (folder / "dataset_summary.json").write_text(json.dumps({"splits": {}}))
        baseline, model = Mock(), Mock()
        baseline.val.return_value = SimpleNamespace(
            results_dict={"metrics/mAP50-95(B)": 0.2},
            box=SimpleNamespace(ap_class_index=[0], maps=[0.2]),
        )
        callbacks = {}
        model.add_callback.side_effect = lambda name, fn: callbacks.update({name: fn})

        def train(**_kwargs):
            weights = folder / "runs/finetune/weights"
            weights.mkdir(parents=True)
            (weights / "last.pt").write_bytes(b"partial-checkpoint")
            self.manager.cancel(self.job_id)
            with self.assertRaises(ValueError):
                self.manager.start(5)
            callbacks["on_train_batch_end"](SimpleNamespace(epoch=0))

        model.train.side_effect = train
        with patch.object(self.manager, "_build_dataset", return_value=(folder / "data.yaml", [0], ["a"])), patch.object(
            training, "YOLO", side_effect=[baseline, model]
        ), patch.object(training, "attach_preservation") as package:
            self.manager._run(self.job_id, 5, "a")
        package.assert_not_called()
        self.assertEqual(self.manager.job(self.job_id)["status"], "cancelled")
        self.assertIsNone(self.manager.job(self.job_id)["candidate"])
        self.assertFalse(folder.exists())
        self.assertEqual(self.active.read_bytes(), b"unchanged-active-model")
        self.assertEqual(self.manager.active_model_path, self.active.resolve())
        self.assertNotIn(self.job_id, self.manager._cancel_events)

    def test_cancel_endpoint_origin_and_terminal_job(self):
        with patch.object(api, "training_manager", self.manager):
            client = api.app.test_client()
            url = "/training/jobs/" + self.job_id + "/cancel"
            self.assertEqual(client.post(url, headers={"Origin": "https://outside.example"}).status_code, 403)
            self.assertEqual(self.manager.job(self.job_id)["status"], "queued")
            self.assertEqual(client.post(url).status_code, 202)
            self.assertEqual(client.post("/training/jobs/" + "b" * 32 + "/cancel").status_code, 404)
        self.manager._write_job({"id": self.job_id, "status": "completed"})
        with self.assertRaises(ValueError):
            self.manager.cancel(self.job_id)


if __name__ == "__main__":
    unittest.main()
