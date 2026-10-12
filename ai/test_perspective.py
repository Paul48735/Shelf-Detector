import base64
import io
import json
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import app as api
from alignment import AlignmentError
from perspective import correct_perspective, detect_shelf_corners, validate_corners
from planogram import validate_plan


class PerspectiveTests(unittest.TestCase):
    def setUp(self):
        self.reference = np.full((360, 480, 3), 190, np.uint8)
        for x, color in ((30, (35, 35, 210)), (200, (35, 210, 35)), (365, (210, 35, 35))):
            cv2.rectangle(self.reference, (x, 70), (x + 80, 230), color, -1)
        cv2.line(self.reference, (0, 260), (479, 260), (30, 30, 30), 10)
        encoded = cv2.imencode('.jpg', self.reference)[1].tobytes()
        self.plan = validate_plan({
            'version': 1, 'name': 'Synthetic shelf', 'ratio': 480 / 360,
            'image': 'data:image/jpeg;base64,' + base64.b64encode(encoded).decode(),
            'shelves': [{'id': 'top', 'name': 'Top', 'product': 'product-a', 'target': 3,
                         'points': [[0, 0], [1, 0], [1, 1], [0, 1]]}],
        }, ['product-a'])

    def test_four_corners_recover_synthetic_shelf_geometry(self):
        destination = np.float32([[52, 33], [431, 10], [456, 332], [25, 347]])
        source = np.float32([[0, 0], [479, 0], [479, 359], [0, 359]])
        tilted = cv2.warpPerspective(
            self.reference, cv2.getPerspectiveTransform(source, destination), (480, 360))
        corrected, alignment = correct_perspective(
            tilted, self.plan, (destination / [479, 359]).tolist())
        self.assertEqual(corrected.shape, self.reference.shape)
        self.assertEqual(alignment['method'], 'perspective_four_corners')
        self.assertLess(np.abs(corrected[25:-25].astype(int) -
                               self.reference[25:-25].astype(int)).mean(), 8)

    def test_blank_image_requests_manual_corners_and_invalid_quad_is_rejected(self):
        blank = np.zeros((360, 480, 3), np.uint8)
        proposed = detect_shelf_corners(blank)
        self.assertEqual(proposed['status'], 'needs_review')
        self.assertIsNone(proposed['corners'])
        with self.assertRaises(AlignmentError):
            validate_corners([[0, 0], [1, 1], [1, 0], [0, 1]])

    def test_preview_allows_manual_corners_when_auto_detection_fails(self):
        blank = np.zeros((360, 480, 3), np.uint8)
        encoded = cv2.imencode('.jpg', blank)[1].tobytes()
        client = api.app.test_client()
        fields = {'image': (io.BytesIO(encoded), 'blank.jpg'),
                  'planogram_id': self.plan['id'],
                  'planogram': json.dumps(self.plan)}
        with patch.object(api.model_service, 'class_names', return_value=['product-a']):
            response = client.post('/perspective/preview', data=fields)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['data']['status'], 'needs_review')
            self.assertIsNone(response.json['data']['corners'])
            fields['image'] = (io.BytesIO(encoded), 'blank.jpg')
            fields['corners'] = json.dumps([[0, 0], [1, 0], [1, 1], [0, 1]])
            response = client.post('/perspective/preview', data=fields)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['data']['method'], 'user_selected')
            self.assertTrue(response.json['data']['corrected_image'].startswith('data:image/jpeg;base64,'))


if __name__ == '__main__':
    unittest.main()
