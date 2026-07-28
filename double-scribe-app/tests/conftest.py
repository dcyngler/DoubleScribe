import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
for p in (ROOT, APP):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
