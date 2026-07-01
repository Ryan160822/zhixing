import json
import unittest

from zxgk_tool.client import CourtClient, extract_captcha_id, parse_search_response


class ClientHelpersTest(unittest.TestCase):
    def test_court_client_ignores_environment_proxy_settings(self):
        client = CourtClient()
        self.assertFalse(client.session.trust_env)

    def test_extract_captcha_id_from_page(self):
        html = '<input id="captchaId" name="captchaId" type="hidden" value="abc123"/>'
        self.assertEqual(extract_captcha_id(html), "abc123")

    def test_extract_captcha_id_returns_none_when_missing(self):
        self.assertIsNone(extract_captcha_id("<html></html>"))

    def test_parse_search_response_empty_result(self):
        body = json.dumps([{"result": [], "totalSize": 0, "currentPage": 1}], ensure_ascii=False)
        parsed = parse_search_response(body)
        self.assertEqual(parsed.total_size, 0)
        self.assertEqual(parsed.rows, [])

    def test_parse_search_response_error_body_is_captcha_error(self):
        parsed = parse_search_response("error")
        self.assertEqual(parsed.error, "验证码错误或已过期")


if __name__ == "__main__":
    unittest.main()
