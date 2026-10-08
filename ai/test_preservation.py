import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import preservation
from preservation import ProductDetector, merge_detections, file_hash


def detection(name, box, confidence=0.8):
    return dict(class_name=name, box=box, confidence=confidence)


class PreservationTests(unittest.TestCase):
    def test_overconfident_target_cannot_relabel_existing_products(self):
        original = [detection('Lays', (0, 0, 20, 40)), detection('Pepsi', (30, 0, 50, 40))]
        tuned = [detection('Taokaenoi', (0, 0, 20, 40), 0.99),
                 detection('Taokaenoi', (30, 0, 50, 40), 0.99),
                 detection('Taokaenoi', (60, 0, 80, 40), 0.9),
                 detection('wrong-old-class', (90, 0, 100, 40))]
        result = merge_detections(original, tuned, ['Taokaenoi'])
        self.assertEqual(result[:2], original)
        self.assertEqual(result[2:], [tuned[2]])

    def test_target_replaces_duplicate_and_falls_back_when_specialist_misses(self):
        original = [detection('target', (0, 0, 20, 40)), detection('target', (30, 0, 50, 40))]
        tuned = [detection('target', (1, 0, 21, 40), 0.95), detection('target', (0, 0, 20, 40), 0.9)]
        result = merge_detections(original, tuned, ['target'])
        self.assertEqual(result, [original[1], tuned[0]])
        self.assertEqual(merge_detections(original, [], ['target']), original)

    def test_oversized_target_cannot_swallow_old_products(self):
        original = [detection('old', (10, 10, 20, 20))]
        tuned = [detection('target', (0, 0, 100, 100), 0.99)]
        self.assertEqual(merge_detections(original, tuned, ['target']), original)

    def test_loading_preserves_source_chain_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source.pt'
            source.write_bytes(b'original-checkpoint')
            source_hash = file_hash(source)
            archived = root / f'bestProduct-{source_hash}.pt'
            source.rename(archived)
            base = SimpleNamespace(names={0: 'old', 1: 'target'}, ckpt={})
            adapter = SimpleNamespace(names=base.names, ckpt={preservation.METADATA_KEY: {
                'version': 1, 'source_hash': source_hash, 'target_classes': ['target'],
            }})
            with patch.object(preservation, 'YOLO', side_effect=[adapter, base]):
                loaded = ProductDetector(root / 'active.pt', root)
            self.assertEqual(loaded.targets, ['target'])
            self.assertEqual(loaded.base.model, base)
            archived.write_bytes(b'changed')
            with patch.object(preservation, 'YOLO', return_value=adapter), self.assertRaisesRegex(ValueError, 'ต้นทาง'):
                ProductDetector(root / 'active.pt', root)

    def test_invalid_source_path_is_rejected(self):
        model = SimpleNamespace(names={0: 'a'}, ckpt={preservation.METADATA_KEY: {
            'version': 1, 'source_hash': '../outside', 'target_classes': ['a'],
        }})
        with patch.object(preservation, 'YOLO', return_value=model), self.assertRaises(ValueError):
            ProductDetector('active.pt', '.')

    def test_predict_uses_base_and_filters_specialist_classes(self):
        def box(class_id, coordinates, confidence):
            import torch
            return SimpleNamespace(cls=[class_id], conf=[confidence], xyxy=torch.tensor([coordinates]))
        detector = ProductDetector.__new__(ProductDetector)
        detector.names = {0: 'old', 1: 'target'}
        detector.targets = ['target']
        detector.base = Mock()
        detector.base.predict_detections.return_value = [detection('old', (0, 0, 10, 10))]
        detector.model = Mock()
        detector.model.predict.return_value = [SimpleNamespace(names=detector.names, boxes=[
            box(1, (0, 0, 10, 10), .99), box(1, (20, 0, 30, 10), .9),
        ])]
        image = object()
        result = detector.predict_detections(image, .5)
        self.assertEqual([item['class_name'] for item in result], ['old', 'target'])
        self.assertEqual(detector.model.predict.call_args.kwargs['classes'], [1])
        detector.base.predict_detections.assert_called_once_with(image, .5)


if __name__ == '__main__':
    unittest.main()
