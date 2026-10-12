"""Exercise automatic ECC alignment and its failure behavior."""

import base64
import unittest

import cv2
import numpy as np

from alignment import AlignmentError, align_to_planogram


class ECCAlignmentTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(5)
        self.reference = rng.integers(25, 190, (480, 640, 3), dtype=np.uint8)
        self.reference = cv2.GaussianBlur(self.reference, (15, 15), 0)
        cv2.rectangle(self.reference, (25, 25), (615, 455), (40, 80, 120), 12)
        cv2.line(self.reference, (30, 238), (610, 238), (245, 245, 245), 16)
        encoded = base64.b64encode(cv2.imencode('.jpg', self.reference)[1]).decode()
        self.plan = {'image': 'data:image/jpeg;base64,' + encoded}

    def test_ecc_corrects_moderate_rotation_without_corners(self):
        rotation = cv2.getRotationMatrix2D((320, 240), 7, 1)
        photographed = cv2.warpAffine(self.reference, rotation, (640, 480))
        aligned, info = align_to_planogram(photographed, self.plan)
        self.assertEqual(info['method'], 'ecc_affine')
        self.assertEqual(aligned.shape, self.reference.shape)
        central = np.s_[70:410, 90:550]
        before = np.mean(np.abs(photographed[central].astype(float) - self.reference[central]))
        after = np.mean(np.abs(aligned[central].astype(float) - self.reference[central]))
        self.assertLess(after, before * .5)

    def test_unrelated_image_does_not_claim_planogram_alignment(self):
        unrelated = np.full_like(self.reference, 127)
        with self.assertRaises(AlignmentError):
            align_to_planogram(unrelated, self.plan)

    def test_wood_shelf_structure_survives_product_changes(self):
        reference = np.full((480, 640, 3), 205, np.uint8)
        wood = (120, 175, 215)
        cv2.rectangle(reference, (0, 0), (639, 34), wood, -1)
        cv2.rectangle(reference, (0, 0), (34, 479), wood, -1)
        cv2.rectangle(reference, (605, 0), (639, 479), wood, -1)
        cv2.rectangle(reference, (0, 220), (639, 259), wood, -1)
        cv2.rectangle(reference, (0, 445), (639, 479), wood, -1)
        stocked = reference.copy()
        cv2.rectangle(stocked, (80, 65), (240, 215), (20, 20, 230), -1)
        cv2.rectangle(stocked, (335, 65), (490, 215), (20, 175, 20), -1)
        cv2.rectangle(stocked, (70, 290), (260, 440), (210, 40, 20), -1)
        rotation = cv2.getRotationMatrix2D((320, 240), 9, 0.86)
        photographed = cv2.warpAffine(stocked, rotation, (640, 480),
                                      borderValue=(180, 180, 180))
        encoded = base64.b64encode(cv2.imencode('.jpg', reference)[1]).decode()
        aligned, info = align_to_planogram(photographed,
                                          {'image': 'data:image/jpeg;base64,' + encoded})
        self.assertEqual(info['status'], 'aligned')
        self.assertEqual(aligned.shape, reference.shape)
        self.assertGreater(info['score'], .6)


if __name__ == '__main__':
    unittest.main()
