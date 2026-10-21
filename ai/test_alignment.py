import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

import app as api
from alignment import align_image, validate_corners
from planogram import validate_plan


class AlignmentTests(unittest.TestCase):
    def setUp(self):
        self.reference = np.full((240, 320, 3), 220, np.uint8)
        cv2.rectangle(self.reference, (35, 40), (95, 105), (20, 190, 60), -1)
        cv2.rectangle(self.reference, (185, 140), (280, 200), (170, 60, 20), -1)
        cv2.line(self.reference, (20, 120), (300, 120), (30, 30, 30), 3)
        self.ref_points = np.float32([[30, 25], [290, 25], [290, 210], [30, 210]])
        self.query_points = np.float32([[60, 35], [390, 60], [360, 320], [30, 270]])
        self.query = cv2.warpPerspective(self.reference,
            cv2.getPerspectiveTransform(self.ref_points, self.query_points), (440, 360))
        self.points = (self.query_points / [439, 359]).tolist()
        self.plan = {'version': 1, 'id': 'a' * 32, 'name': 'Test', 'ratio': 320 / 240,
                     'reference_width': 320, 'reference_height': 240,
                     'alignment_points': (self.ref_points / [319, 239]).tolist(),
                     'shelves': [{'id': 'shelf', 'name': 'Upper', 'product': 'a', 'target': 1,
                                  'points': [[0, 0], [1, 0], [1, 1], [0, 1]]}]}

    def jpeg(self, image):
        return cv2.imencode('.jpg', image)[1].tobytes()

    def test_maps_to_actual_inset_reference_points_and_reference_size(self):
        aligned, metadata = align_image(self.query, self.plan, self.points)
        self.assertTrue(metadata['applied'])
        self.assertEqual(aligned.shape, self.reference.shape)
        self.assertLess(np.abs(aligned[30:205, 35:285].astype(float)
                               - self.reference[30:205, 35:285]).mean(), 4)
        mapped = cv2.perspectiveTransform(self.query_points[None], np.array(metadata['matrix']))[0]
        np.testing.assert_allclose(mapped, self.ref_points, atol=0.001)

    def test_no_points_returns_identical_input_even_for_legacy_or_no_plan(self):
        for plan in (None, {}, self.plan):
            for points in (None, []):
                aligned, metadata = align_image(self.query, plan, points)
                self.assertIs(aligned, self.query)
                self.assertEqual(metadata, {'applied': False})

    def test_invalid_points_are_rejected_without_silent_fallback(self):
        for points in (self.points[:3], [[0, 0]] * 4,
                       [[0, 0], [1, 1], [1, 0], [0, 1]],
                       [[0, 0], [0, 1], [1, 1], [1, 0]],
                       [[0, 0], [1, 0], [1, float('nan')], [0, 1]], 'bad'):
            with self.subTest(points=points), self.assertRaises(ValueError):
                validate_corners(points)
        with self.assertRaises(ValueError):
            align_image(self.query, dict(self.plan, alignment_points=[]), self.points)
        with self.assertRaises(ValueError):
            align_image(self.query, None, self.points)

    def test_saved_plan_keeps_reference_points_and_legacy_remains_optional(self):
        data = dict(self.plan, image='data:image/jpeg;base64,' + base64.b64encode(self.jpeg(self.reference)).decode())
        saved = validate_plan(data, ['a'])
        self.assertEqual(saved['reference_width'], 320)
        np.testing.assert_allclose(saved['alignment_points'], self.plan['alignment_points'])
        data.pop('alignment_points')
        self.assertEqual(validate_plan(data, ['a'])['alignment_points'], [])
        data['alignment_points'] = self.points[:2]
        with self.assertRaises(ValueError):
            validate_plan(data, ['a'])

    def test_preview_and_predict_use_same_transform_while_preserving_original(self):
        jpeg = self.jpeg(self.query)
        def body(points):
            return {'image': (io.BytesIO(jpeg), 'upload.jpg'), 'planogram_id': self.plan['id'],
                    'planogram': json.dumps(self.plan), 'alignment_points': json.dumps(points)}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(api, 'UPLOAD_DIR', Path(directory)), \
             patch.object(api, 'RESULT_DIR', Path(directory)), \
             patch.object(api.model_service, 'class_names', return_value=['a']), \
             patch.object(api, 'model_version', return_value='hash'), \
             patch.object(api.model_service, 'detect_scene', return_value={'products': [], 'gaps': []}) as detect:
            client = api.app.test_client()
            preview = client.post('/alignment/preview', data=body(self.points))
            self.assertEqual(preview.status_code, 200, preview.json)
            self.assertFalse(list(Path(directory).iterdir()))  # Preview creates no saved run/files.
            response = client.post('/predict', data=body(self.points))
            self.assertEqual(response.status_code, 200, response.json)
            aligned = cv2.imread(str(detect.call_args.args[0]))
            self.assertEqual(aligned.shape, self.reference.shape)
            expected, _ = align_image(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR), self.plan, self.points)
            np.testing.assert_array_equal(aligned, expected)
            self.assertTrue(response.json['alignment']['applied'])
            original = Path(directory) / Path(response.json['input_image_path']).name
            self.assertEqual(original.read_bytes(), jpeg)
            self.assertNotEqual(original, detect.call_args.args[0])
            self.assertEqual(response.json['alignment']['matrix'], preview.json['alignment']['matrix'])

            response = client.post('/predict', data=body([]))
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json['alignment']['applied'])
            self.assertEqual(cv2.imread(str(detect.call_args.args[0])).shape, self.query.shape)
            self.assertIsNone(response.json['aligned_image_url'])

            detect.reset_mock()
            response = client.post('/predict', data=body(self.points[:2]))
            self.assertEqual(response.status_code, 400)
            detect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
