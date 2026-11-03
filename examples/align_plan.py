"""From bundle root: python examples/align_plan.py plan.json upload.jpg overlay.jpg"""

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai"))
from aruco_alignment import aruco_planogram

parser = argparse.ArgumentParser()
parser.add_argument("plan_json")
parser.add_argument("upload_image")
parser.add_argument("output_image")
args = parser.parse_args()
# plan: image=data:image/jpeg;base64,...; reference_width/height;
# shelves=[{points:[[x,y],...]}] with four normalized vertices per region.
plan = json.loads(Path(args.plan_json).read_text(encoding="utf-8"))
image = cv2.imdecode(np.fromfile(args.upload_image, np.uint8), cv2.IMREAD_COLOR)
if image is None:
    raise ValueError("Cannot decode upload image")
mapped, metadata = aruco_planogram(image, plan, preview=True)
overlay = image.copy()
for region in mapped["shelves"]:
    points = np.int32(np.asarray(region["points"]) * [image.shape[1], image.shape[0]])
    cv2.polylines(overlay, [points], True, (0, 255, 120), 3)
suffix = Path(args.output_image).suffix or ".jpg"
ok, encoded = cv2.imencode(suffix, overlay)
if not ok:
    raise ValueError("Cannot encode output image")
encoded.tofile(args.output_image)
print(json.dumps(metadata["quality"], indent=2))
