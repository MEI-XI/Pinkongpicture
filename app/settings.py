import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def data_root():
    return Path(os.environ.get("PINKONG_DATA_DIR", PROJECT_ROOT / "data")).resolve()
