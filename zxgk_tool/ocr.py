from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

MAX_AUTO_ATTEMPTS = 5

AUTO_SUBMIT = "auto_submit"
MANUAL = "manual"

_ALNUM = re.compile(r"[^A-Za-z0-9]")


def clean_captcha_text(raw: str) -> str:
    return _ALNUM.sub("", raw or "")


def _default_classifier():
    import ddddocr  # 仅在打包态/装了 ddddocr 时可用

    return ddddocr.DdddOcr(show_ad=False)


class CaptchaSolver:
    def __init__(self, classifier_factory: Callable[[], object] | None = None) -> None:
        self._factory = classifier_factory or _default_classifier
        self._classifier = None

    def _get(self):
        if self._classifier is None:
            self._classifier = self._factory()
        return self._classifier

    def predict(self, image_path: Path) -> str:
        raw = self._get().classification(image_path.read_bytes())
        return clean_captcha_text(raw)
