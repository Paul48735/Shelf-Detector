import base64
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from planogram import match_gap, validate_plan
from model_service import ShelfModelService
import app as api


class PlanogramTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((100, 100, 3), dtype=np.uint8)
        self.jpeg = cv2.imencode('.jpg', self.frame)[1].tobytes()
        self.data = {'version': 1, 'name': 'Test', 'ratio': 1,
                     'image': 'data:image/jpeg;base64,' + base64.b64encode(self.jpeg).decode(),
                     'shelves': [{'id': 'upper', 'name': 'Upper', 'product': 'product-a', 'target': 3,
                                  'points': [[0, 0], [1, 0], [1, .5], [0, .5]]},
                                 {'id': 'lower', 'name': 'Lower', 'product': 'product-b', 'target': 3,
                                  'points': [[0, .5], [1, .5], [1, 1], [0, 1]]}]}
        self.plan = validate_plan(self.data, ['product-a', 'product-b'])

    def test_regions_and_ambiguity(self):
        self.assertEqual(match_gap([10, 10, 30, 30], self.plan, 100, 100)['product_class'], 'product-a')
        self.assertEqual(match_gap([10, 60, 30, 80], self.plan, 100, 100)['product_class'], 'product-b')
        self.assertIsNone(match_gap([10, 40, 30, 60], self.plan, 100, 100)['product_class'])
        self.assertIsNone(match_gap([10, 10, 30, 30], None, 100, 100)['product_class'])
        self.assertEqual(match_gap([20, 20, 60, 60], self.plan, 200, 200)['product_class'], 'product-a')
        self.plan['shelves'].append(copy.deepcopy(self.plan['shelves'][0]))
        self.assertEqual(match_gap([10, 10, 30, 30], self.plan, 100, 100)['association_method'], 'ambiguous-region')

    def test_validation(self):
        for key, value in [('product', 'unknown'), ('target', -1), ('points', [[0, 0], [1, 1], [1, 0], [0, 1]])]:
            data = copy.deepcopy(self.data)
            data['shelves'][0][key] = value
            with self.assertRaises(ValueError):
                validate_plan(data, ['product-a', 'product-b'])

    def test_database_plan_payload_and_validation_route(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(api.model_service, 'class_names', return_value=['product-a', 'product-b']):
            client = api.app.test_client()
            response = client.post('/planogram/validate', json=self.data)
            self.assertEqual(response.status_code, 200)
            saved = response.json['data']
            saved.pop('image')
            response = client.post('/predict', data={'image': (io.BytesIO(self.jpeg), 'test.jpg'), 'planogram_id': 'stale'})
            self.assertEqual(response.status_code, 409)
            with patch.object(api, 'UPLOAD_DIR', Path(directory)), patch.object(api, 'RESULT_DIR', Path(directory)), patch.object(api.model_service, 'detect_scene', return_value={'gaps': []}) as detect, patch.object(api, 'model_version', return_value='hash'):
                response = client.post('/predict', data={'image': (io.BytesIO(self.jpeg), 'test.jpg'), 'planogram_id': saved['id'], 'planogram': json.dumps(saved)})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(detect.call_args.args[-1], saved)
                self.assertIn('input_image_path', response.json)
            saved['shelves'][0]['points'] = []
            response = client.post('/predict', data={'image': (io.BytesIO(self.jpeg), 'test.jpg'), 'planogram_id': saved['id'], 'planogram': json.dumps(saved)})
            self.assertEqual(response.status_code, 400)

    def test_detection_uses_plan_not_neighbors(self):
        service = ShelfModelService(Path('unused'), Path('unused'))
        model = Mock(names={0: 'gap'})
        model.predict.return_value = [Mock()]
        product = {'class_name': 'product-b', 'confidence': .9, 'box': (0, 0, 10, 30)}
        gap = {'class_name': 'gap', 'confidence': .8, 'box': (10, 10, 30, 30)}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.jpg'
            result = Path(directory) / 'result.jpg'
            cv2.imwrite(str(source), self.frame)
            for plan, expected in [(self.plan, 'product-a'), (None, None)]:
                with patch.object(service, '_models', return_value=(model, model)), patch.object(service, '_collect', side_effect=[[product], [gap]]):
                    payload = service.detect_scene(source, result, .5, .5, plan)
                    self.assertEqual(payload['gaps'][0]['product_class'], expected)
                    self.assertEqual(payload['identified_gaps'], int(expected is not None))
                    self.assertEqual(payload['products'][0]['placement_status'], 'wrong-shelf' if plan else 'unmatched')
                    self.assertEqual(payload['wrong_shelf_count'], int(plan is not None))
                    self.assertIsNotNone(cv2.imread(str(result)))
            for class_name, box, expected_status in [
                ('product-a', (10, 10, 30, 30), 'correct'),
                ('product-b', (10, 10, 30, 30), 'wrong-shelf'),
                ('product-a', (10, 40, 30, 60), 'unmatched'),
            ]:
                item = dict(product, class_name=class_name, box=box)
                with patch.object(service, '_models', return_value=(model, model)), patch.object(service, '_collect', side_effect=[[item], []]):
                    payload = service.detect_scene(source, result, .5, .5, self.plan)
                    self.assertEqual(payload['products'][0]['placement_status'], expected_status)
                    self.assertEqual(payload['total_gaps'], 0)
            wrong_ratio = dict(self.plan, ratio=2)
            with patch.object(service, '_models', return_value=(model, model)), self.assertRaises(ValueError):
                service.detect_scene(source, result, .5, .5, wrong_ratio)


if __name__ == '__main__':
    unittest.main()
