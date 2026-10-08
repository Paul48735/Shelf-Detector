import hashlib
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import app as api
import training
from training import TrainingManager


class ModelDeletionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.active = self.root / 'active.pt'
        self.active.write_bytes(b'active-model')
        for name, value in [('PRODUCT_MODEL_PATH', self.active),
                            ('TRAINING_IMAGES_DIR', self.root / 'images'),
                            ('TRAINING_JOBS_DIR', self.root / 'jobs'),
                            ('MODEL_ARCHIVE_DIR', self.root / 'archive')]:
            self.stack.enter_context(patch.object(training, name, value))
        self.manager = TrainingManager(lambda: ['a'])
        self.job_id = 'a' * 32
        self.candidate = self.root / 'jobs' / self.job_id / 'runs/finetune/weights/best.pt'
        self.candidate.parent.mkdir(parents=True)
        self.candidate.write_bytes(b'target-model')
        self.candidate.with_name('last.pt').write_bytes(b'last-epoch-model')
        self.manager._write_job({'id': self.job_id, 'status': 'completed',
                                 'created_at': '2026-01-01', 'candidate': str(self.candidate)})
        self.target_hash = hashlib.sha256(self.candidate.read_bytes()).hexdigest()
        self.backup = self.root / 'archive' / f'bestProduct-{self.target_hash}.pt'
        self.backup.write_bytes(self.candidate.read_bytes())
        self.original = self.root / 'archive' / ('bestProduct-' + 'b' * 16 + '.pt')
        self.original.write_bytes(b'original-model')

    def test_delete_removes_candidate_and_identical_backups_only(self):
        with patch.object(training, 'YOLO', return_value=SimpleNamespace(ckpt={})):
            result = self.manager.delete_model('job:' + self.job_id)
        self.assertEqual(result['model_id'], 'job:' + self.job_id)
        self.assertFalse(self.candidate.exists())
        self.assertFalse(self.backup.exists())
        self.assertFalse(self.candidate.with_name('last.pt').exists())
        self.assertEqual(self.original.read_bytes(), b'original-model')
        self.assertEqual(self.active.read_bytes(), b'active-model')
        self.assertEqual(self.manager.job(self.job_id)['status'], 'deleted')
        self.assertNotIn(self.target_hash, [row['model_hash'] for row in self.manager.list_models()])
        with self.assertRaises(ValueError):
            self.manager.select_model('job:' + self.job_id)

    def test_active_model_cannot_be_deleted(self):
        self.active.write_bytes(self.candidate.read_bytes())
        with self.assertRaises(ValueError):
            self.manager.delete_model('job:' + self.job_id)
        self.assertTrue(self.candidate.exists())
        self.assertTrue(self.backup.exists())

    def test_deleting_older_model_keeps_remaining_model_numbers(self):
        self.manager._write_job({'id': 'c' * 32, 'status': 'deleted',
                                 'created_at': '2025-01-01', 'candidate': None,
                                 'deleted_model_hash': 'd' * 64})
        current_candidate = self.root / 'jobs' / ('e' * 32) / 'runs/finetune/weights/best.pt'
        current_candidate.parent.mkdir(parents=True)
        current_candidate.write_bytes(self.active.read_bytes())
        self.manager._write_job({'id': 'e' * 32, 'status': 'activated',
                                 'created_at': '2027-01-01', 'candidate': str(current_candidate)})
        models = self.manager.list_models()
        self.assertEqual(models[0]['label'], 'โมเดลที่ Fine-tune 3')
        selected = next(row for row in models if row['id'] == 'job:' + self.job_id)
        self.assertEqual(selected['label'], 'โมเดลที่ Fine-tune 2')
        with patch.object(training, 'YOLO', return_value=SimpleNamespace(ckpt={})):
            self.manager.delete_model('job:' + self.job_id)
        self.assertEqual(self.manager.list_models()[0]['label'], 'โมเดลที่ Fine-tune 3')

    def test_source_of_retained_model_cannot_be_deleted(self):
        def load(path):
            ckpt = {'shelf_preservation': {'source_hash': self.target_hash}} if Path(path).resolve() == self.active.resolve() else {}
            return SimpleNamespace(ckpt=ckpt)
        with patch.object(training, 'YOLO', side_effect=load), self.assertRaises(ValueError):
            self.manager.delete_model('job:' + self.job_id)
        self.assertTrue(self.candidate.exists())
        self.assertTrue(self.backup.exists())
        self.assertEqual(self.manager.job(self.job_id)['status'], 'completed')

    def test_running_training_blocks_deletion(self):
        self.manager._write_job({'id': 'c' * 32, 'status': 'running'})
        with self.assertRaises(ValueError):
            self.manager.delete_model('job:' + self.job_id)
        self.assertTrue(self.candidate.exists())

    def test_original_archive_and_invalid_ids_cannot_be_deleted(self):
        for model_id in ['current', 'archive:' + 'b' * 16, 'job:../outside', None]:
            with self.subTest(model_id=model_id), self.assertRaises(ValueError):
                self.manager.delete_model(model_id)
        self.assertTrue(self.original.exists())

    def test_delete_endpoint_and_external_origin_protection(self):
        with patch.object(api, 'training_manager', self.manager), \
             patch.object(training, 'YOLO', return_value=SimpleNamespace(ckpt={})):
            client = api.app.test_client()
            body = {'model_id': 'job:' + self.job_id}
            response = client.post('/training/models/delete', json=body,
                                   headers={'Origin': 'https://example.com'})
            self.assertEqual(response.status_code, 403)
            self.assertTrue(self.candidate.exists())
            response = client.post('/training/models/delete', json=body)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json['success'])
            self.assertFalse(self.candidate.exists())
            response = client.post('/training/models/delete', json={'model_id': 'current'})
            self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
