import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
_root = str(ROOT_DIR)
if _root not in sys.path:
    sys.path.insert(0, _root)


def ensure_project_root() -> Path:
    return ROOT_DIR
