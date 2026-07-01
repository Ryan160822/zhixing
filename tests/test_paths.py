from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zxgk_tool import paths


class PathsTest(unittest.TestCase):
    def test_captcha_dir_dev_is_project_runtime(self) -> None:
        with patch.object(paths, "is_frozen", return_value=False):
            self.assertEqual(paths.captcha_dir(), paths.PROJECT_ROOT / ".runtime" / "captchas")

    def test_captcha_dir_frozen_is_tempdir(self) -> None:
        with patch.object(paths, "is_frozen", return_value=True):
            expected = Path(tempfile.gettempdir()) / "zxgk_captchas"
            self.assertEqual(paths.captcha_dir(), expected)

    def test_temp_results_dir_exists_after_call(self) -> None:
        d = paths.temp_results_dir()
        self.assertTrue(d.exists())
        self.assertEqual(d.name, "zxgk_results")


if __name__ == "__main__":
    unittest.main()
