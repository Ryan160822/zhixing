from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zxgk_tool.app import ZxgkApp
from zxgk_tool.client import CaptchaChallenge, SearchResult
from zxgk_tool.models import QueryItem, STATUS_CAPTCHA_ERROR, STATUS_DONE, STATUS_PENDING


class DummyBoolVar:
    def __init__(self, value: bool = False) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = value


class DummyVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


class DummyEntry:
    def __init__(self) -> None:
        self.deleted = False
        self.focused = False

    def delete(self, _start, _end=None) -> None:
        self.deleted = True

    def focus_set(self) -> None:
        self.focused = True


class DummyLabel:
    def configure(self, **_kwargs) -> None:
        pass


class DesktopCaptchaReuseTest(unittest.TestCase):
    def make_app(self, items: list[QueryItem], auto: bool = False) -> ZxgkApp:
        app = ZxgkApp.__new__(ZxgkApp)
        app.items = items
        app.current_item = items[0]
        app.current_captcha = None
        app.current_predicted = None
        app.batch_output_path = None
        app.busy = True
        app.auto_var = DummyBoolVar(auto)
        app.auto_attempts = 0
        app.output_paths = []
        app.status_var = DummyVar()
        app.current_label_var = DummyVar()
        app.captcha_entry = DummyEntry()
        app.captcha_label = DummyLabel()
        app.save_button = DummyLabel()
        app._render_queue = lambda: None
        app._update_save_button = lambda: None
        return app

    def test_successful_submit_reuses_captcha_and_code_for_next_pending_item(self) -> None:
        items = [
            QueryItem(1, "330000199001011234 张三", "person", "张三", "330000199001011234"),
            QueryItem(2, "某某建设有限公司", "company", "某某建设有限公司"),
        ]
        app = self.make_app(items)
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            captcha_path = Path(temp_dir) / "captcha.png"
            captcha_path.write_bytes(b"fake image")
            captcha = CaptchaChallenge("captcha-1", captcha_path)
            app.current_captcha = captcha

            with patch("zxgk_tool.app.render_result_png", return_value=Path(temp_dir) / "result.png"):
                app._submit_with_captcha = lambda item, captcha_arg, code: calls.append((item, captcha_arg, code))
                app._handle_search_done(items[0], captcha, SearchResult([], 0), "ABCD")

            self.assertEqual(items[0].status, STATUS_DONE)
            self.assertEqual(items[1].status, STATUS_PENDING)
            self.assertEqual(app.current_item, items[1])
            self.assertEqual(app.current_captcha, captcha)
            self.assertEqual(app.current_label_var.value, "当前：某某建设有限公司")
            self.assertEqual(calls, [(items[1], captcha, "ABCD")])
            self.assertTrue(captcha_path.exists())

    def test_final_success_deletes_reused_captcha(self) -> None:
        items = [
            QueryItem(1, "330000199001011234 张三", "person", "张三", "330000199001011234", status=STATUS_DONE),
            QueryItem(2, "某某建设有限公司", "company", "某某建设有限公司"),
        ]
        app = self.make_app(items)
        app.current_item = items[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            captcha_path = Path(temp_dir) / "captcha.png"
            captcha_path.write_bytes(b"fake image")
            captcha = CaptchaChallenge("captcha-1", captcha_path)
            app.current_captcha = captcha

            with patch("zxgk_tool.app.render_result_png", return_value=Path(temp_dir) / "result.png"):
                app._handle_search_done(items[1], captcha, SearchResult([], 0), "ABCD")

            self.assertEqual(items[1].status, STATUS_DONE)
            self.assertIsNone(app.current_item)
            self.assertIsNone(app.current_captcha)
            self.assertFalse(captcha_path.exists())

    def test_captcha_error_stops_on_current_item_without_advancing(self) -> None:
        items = [
            QueryItem(1, "330000199001011234 张三", "person", "张三", "330000199001011234"),
            QueryItem(2, "某某建设有限公司", "company", "某某建设有限公司"),
        ]
        app = self.make_app(items)
        with tempfile.TemporaryDirectory() as temp_dir:
            captcha_path = Path(temp_dir) / "captcha.png"
            captcha_path.write_bytes(b"fake image")
            captcha = CaptchaChallenge("captcha-1", captcha_path)
            app.current_captcha = captcha
            app._submit_with_captcha = lambda *_args: self.fail("should not continue after captcha error")

            app._handle_search_done(items[0], captcha, SearchResult([], 0, "验证码错误或已过期"), "ABCD")

            self.assertEqual(items[0].status, STATUS_CAPTCHA_ERROR)
            self.assertEqual(items[1].status, STATUS_PENDING)
            self.assertEqual(app.current_item, items[0])
            self.assertEqual(app.current_captcha, captcha)
            self.assertTrue(captcha_path.exists())


class AutoSolveTest(unittest.TestCase):
    def make_app(self, auto: bool, attempts: int):
        app = ZxgkApp.__new__(ZxgkApp)
        items = [QueryItem(1, "x", "company", "某公司")]
        app.items = items
        app.current_item = items[0]
        app.current_captcha = None
        app.current_predicted = "ab12"
        app.batch_output_path = None
        app.busy = True
        app.auto_var = DummyBoolVar(auto)
        app.auto_attempts = attempts
        app.output_paths = []
        app.status_var = DummyVar()
        app.current_label_var = DummyVar()
        app.captcha_entry = DummyEntry()
        app.captcha_label = DummyLabel()
        app.save_button = DummyLabel()
        app._render_queue = lambda: None
        app._update_save_button = lambda: None
        return app, items

    def test_auto_error_refetches_new_captcha(self) -> None:
        app, items = self.make_app(auto=True, attempts=2)
        fetched = []
        app._fetch_captcha_for = lambda item: fetched.append(item)
        with tempfile.TemporaryDirectory() as d:
            cap_path = Path(d) / "c.png"
            cap_path.write_bytes(b"x")
            captcha = CaptchaChallenge("c1", cap_path)
            app.current_captcha = captcha
            app._handle_search_done(items[0], captcha, SearchResult([], 0, "验证码错误或已过期"), "ab12")
            self.assertEqual(fetched, [items[0]])
            self.assertIsNone(app.current_captcha)
            self.assertFalse(cap_path.exists())

    def test_auto_error_falls_back_to_manual_after_max(self) -> None:
        app, items = self.make_app(auto=True, attempts=5)
        app._fetch_captcha_for = lambda item: self.fail("should not refetch after max")
        with tempfile.TemporaryDirectory() as d:
            cap_path = Path(d) / "c.png"
            cap_path.write_bytes(b"x")
            captcha = CaptchaChallenge("c1", cap_path)
            app.current_captcha = captcha
            app._handle_search_done(items[0], captcha, SearchResult([], 0, "验证码错误或已过期"), "ab12")
            self.assertTrue(app.captcha_entry.focused)
            self.assertTrue(cap_path.exists())


if __name__ == "__main__":
    unittest.main()
