"""Run from the project root: python scripts/generate_aruco.py."""

from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai"))
from aruco_alignment import dictionary, MARKER_IDS


def generate(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for marker_id in MARKER_IDS:
        marker = cv2.aruco.generateImageMarker(dictionary(), marker_id, 600)
        # White quiet zone is part of the printable image. Black square = 60 mm.
        marker = cv2.copyMakeBorder(
            marker, 100, 100, 100, 100, cv2.BORDER_CONSTANT, value=255
        )
        if not cv2.imwrite(str(destination / f"marker-{marker_id}.png"), marker):
            raise RuntimeError("Cannot write marker image")


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "assets" / "aruco")
    print("Generated DICT_4X4_50 markers 0, 1, 2, 3 in assets/aruco")
