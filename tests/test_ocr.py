from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from zxgk_tool.ocr import (
    AUTO_SUBMIT,
    MANUAL,
    CaptchaSolver,
    clean_captcha_text,
    decide_captcha_action,
    should_auto_attempt,
)


class FakeClassifier:
    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    def classification(self, _data: bytes) -> str:
        self.calls += 1
        return self.value


class CleanCaptchaTextTest(unittest.TestCase):
    def test_strips_symbols_and_spaces(self) -> None:
        self.assertEqual(clean_captcha_text("  a b#3d! "), "ab3d")

    def test_keeps_letters_and_digits(self) -> None:
        self.assertEqual(clean_captcha_text("X9y2"), "X9y2")


class CaptchaSolverTest(unittest.TestCase):
    def test_predict_uses_classifier_and_cleans(self) -> None:
        fake = FakeClassifier(" a1 b2 ")
        solver = CaptchaSolver(classifier_factory=lambda: fake)
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "c.png"
            img.write_bytes(b"bytes")
            self.assertEqual(solver.predict(img), "a1b2")
        self.assertEqual(fake.calls, 1)

    def test_classifier_is_lazy(self) -> None:
        created = []

        def factory():
            created.append(1)
            return FakeClassifier("ab12")

        solver = CaptchaSolver(classifier_factory=factory)
        self.assertEqual(created, [])  # 构造时不加载模型
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "c.png"
            img.write_bytes(b"bytes")
            solver.predict(img)
            solver.predict(img)
        self.assertEqual(created, [1])


class DecisionTest(unittest.TestCase):
    def test_auto_on_with_prediction_submits(self) -> None:
        self.assertEqual(decide_captcha_action(True, "ab12", 0), AUTO_SUBMIT)

    def test_auto_on_without_prediction_is_manual(self) -> None:
        self.assertEqual(decide_captcha_action(True, None, 0), MANUAL)

    def test_auto_off_is_manual(self) -> None:
        self.assertEqual(decide_captcha_action(False, "ab12", 0), MANUAL)

    def test_attempts_exhausted_is_manual(self) -> None:
        self.assertEqual(decide_captcha_action(True, "ab12", 5, max_attempts=5), MANUAL)

    def test_should_auto_attempt_boundary(self) -> None:
        self.assertTrue(should_auto_attempt(True, 4, 5))
        self.assertFalse(should_auto_attempt(True, 5, 5))
        self.assertFalse(should_auto_attempt(False, 0, 5))


if __name__ == "__main__":
    unittest.main()
