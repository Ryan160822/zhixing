from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def captcha_dir() -> Path:
    if is_frozen():
        return Path(tempfile.gettempdir()) / "zxgk_captchas"
    return PROJECT_ROOT / ".runtime" / "captchas"


def temp_results_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "zxgk_results"
    d.mkdir(parents=True, exist_ok=True)
    return d
