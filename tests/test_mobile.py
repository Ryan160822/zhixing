from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zxgk_tool.client import CaptchaChallenge, SearchResult
from zxgk_tool.mobile import DEFAULT_HOST, DEFAULT_PORT, MobileQueryService, server_config_from_env
from zxgk_tool.models import STATUS_DONE, STATUS_WAITING_CAPTCHA


class FakeClient:
    def __init__(self) -> None:
        self.fetch_count = 0

    def fetch_captcha(self, captcha_dir: Path, label: str) -> CaptchaChallenge:
        self.fetch_count += 1
        captcha_dir.mkdir(parents=True, exist_ok=True)
        path = captcha_dir / f"验证码_{label}_{self.fetch_count}.png"
        path.write_bytes(b"fake image")
        return CaptchaChallenge(f"captcha-{self.fetch_count}", path)

    def search(self, item, captcha: CaptchaChallenge, code: str) -> SearchResult:
        if code == "BAD":
            return SearchResult([], 0, "验证码错误或已过期")
        return SearchResult([], 0)


def fake_render(item, rows, output_dir: Path, date_text: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{item.name}_{date_text}.png"
    path.write_bytes(b"fake result")
    return path


class MobileQueryServiceTest(unittest.TestCase):
    def test_server_config_defaults_to_lucky_local_reverse_proxy_port(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(server_config_from_env(), (DEFAULT_HOST, DEFAULT_PORT))

    def test_server_config_reads_host_and_port_from_environment(self) -> None:
        with patch.dict("os.environ", {"ZXGK_HOST": "0.0.0.0", "ZXGK_PORT": "9001"}, clear=True):
            self.assertEqual(server_config_from_env(), ("0.0.0.0", 9001))

    def test_server_config_rejects_invalid_port(self) -> None:
        with patch.dict("os.environ", {"ZXGK_PORT": "abc"}, clear=True):
            with self.assertRaises(ValueError):
                server_config_from_env()

    def test_start_job_fetches_first_captcha_and_returns_empty_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MobileQueryService(
                client_factory=FakeClient,
                output_dir=Path(temp_dir) / "results",
                captcha_dir=Path(temp_dir) / "captchas",
                render_result=fake_render,
                today=lambda: "2026-05-16",
            )

            job = service.start_job("330000199001011234 张三\n某某建设有限公司")

            self.assertEqual(job["items"][0]["name"], "张三")
            self.assertEqual(job["items"][0]["status"], STATUS_WAITING_CAPTCHA)
            self.assertTrue(job["currentCaptcha"]["imageUrl"].startswith("/captcha/"))

    def test_submit_captcha_generates_result_and_advances_to_next_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MobileQueryService(
                client_factory=FakeClient,
                output_dir=Path(temp_dir) / "results",
                captcha_dir=Path(temp_dir) / "captchas",
                render_result=fake_render,
                today=lambda: "2026-05-16",
            )
            started = service.start_job("330000199001011234 张三\n某某建设有限公司")
            old_captcha = Path(temp_dir) / "captchas" / "验证码_张三_1.png"

            job = service.submit_captcha(started["id"], "ABCD")

            self.assertEqual(job["items"][0]["status"], STATUS_DONE)
            self.assertTrue(job["items"][0]["outputUrl"].startswith("/results/"))
            self.assertFalse(old_captcha.exists())
            self.assertEqual(job["items"][1]["status"], STATUS_WAITING_CAPTCHA)
            self.assertEqual(job["currentCaptcha"]["itemIndex"], 2)

    def test_refresh_captcha_replaces_existing_captcha_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MobileQueryService(
                client_factory=FakeClient,
                output_dir=Path(temp_dir) / "results",
                captcha_dir=Path(temp_dir) / "captchas",
                render_result=fake_render,
                today=lambda: "2026-05-16",
            )
            started = service.start_job("330000199001011234 张三")
            old_url = started["currentCaptcha"]["imageUrl"]
            old_captcha = Path(temp_dir) / "captchas" / "验证码_张三_1.png"

            job = service.refresh_captcha(started["id"])

            self.assertNotEqual(job["currentCaptcha"]["imageUrl"], old_url)
            self.assertFalse(old_captcha.exists())


if __name__ == "__main__":
    unittest.main()
