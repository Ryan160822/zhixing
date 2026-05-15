import tempfile
import unittest
from pathlib import Path

from PIL import Image

from zxgk_tool.models import QueryItem
from zxgk_tool.renderer import make_result_filename, render_result_png


class RendererTest(unittest.TestCase):
    def test_make_result_filename_removes_path_unsafe_characters(self):
        item = QueryItem(1, "某/某:公司", "company", "某/某:公司")
        filename = make_result_filename(item, "2026-05-15")
        self.assertEqual(filename, "某_某_公司_被执行人查询结果_2026-05-15.png")

    def test_render_empty_result_creates_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = QueryItem(1, "330000199001011234 张三", "person", "张三", "330000199001011234")
            out = render_result_png(item, [], Path(tmp), "2026-05-15")
            self.assertTrue(out.exists())
            with Image.open(out) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1400, 980))

    def test_render_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            item = QueryItem(1, "某某建设有限公司", "company", "某某建设有限公司")
            first = render_result_png(item, [], Path(tmp), "2026-05-15")
            second = render_result_png(item, [], Path(tmp), "2026-05-15")
            self.assertNotEqual(first, second)
            self.assertTrue(second.name.endswith("_2.png"))


if __name__ == "__main__":
    unittest.main()
