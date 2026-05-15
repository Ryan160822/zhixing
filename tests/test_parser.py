import unittest

from zxgk_tool.parser import parse_batch_lines


class ParseBatchLinesTest(unittest.TestCase):
    def test_detects_person_when_id_card_is_first(self):
        items = parse_batch_lines("330000199001011234 张三")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "person")
        self.assertEqual(items[0].name, "张三")
        self.assertEqual(items[0].card_num, "330000199001011234")
        self.assertIsNone(items[0].error)

    def test_detects_person_when_id_card_is_last(self):
        items = parse_batch_lines("李四 33000019880505222X")
        self.assertEqual(items[0].kind, "person")
        self.assertEqual(items[0].name, "李四")
        self.assertEqual(items[0].card_num, "33000019880505222X")

    def test_detects_company_when_no_id_card_exists(self):
        items = parse_batch_lines("某某建设有限公司")
        self.assertEqual(items[0].kind, "company")
        self.assertEqual(items[0].name, "某某建设有限公司")
        self.assertEqual(items[0].card_num, "")

    def test_marks_id_only_line_as_error(self):
        items = parse_batch_lines("330000199001011234")
        self.assertEqual(items[0].kind, "person")
        self.assertEqual(items[0].status, "输入错误")
        self.assertEqual(items[0].error, "缺少姓名")

    def test_ignores_blank_lines_and_preserves_order(self):
        text = "\n330000199001011234 张三\n\n某某建设有限公司\n"
        items = parse_batch_lines(text)
        self.assertEqual([item.name for item in items], ["张三", "某某建设有限公司"])


if __name__ == "__main__":
    unittest.main()
