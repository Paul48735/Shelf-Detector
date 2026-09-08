from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRODUCT_MODEL_PATH = PROJECT_ROOT / "ai" / "models" / "bestProduct.pt"
GAP_MODEL_PATH = PROJECT_ROOT / "ai" / "models" / "bestGap.pt"

STORAGE_DIR = PROJECT_ROOT / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
RESULT_DIR = STORAGE_DIR / "results"

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024
DEFAULT_PRODUCT_CONFIDENCE = 0.50
DEFAULT_GAP_CONFIDENCE = 0.50
