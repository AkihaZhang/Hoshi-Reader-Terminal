import unittest

from hoshi_terminal.reader import character_count, paginate, render_vertical, sentence_around


class ReaderTests(unittest.TestCase):
    def test_paginate_returns_pages(self) -> None:
        pages = paginate("星 " * 200, width=20, lines_per_page=4)
        self.assertGreater(len(pages), 1)

    def test_character_count_ignores_whitespace(self) -> None:
        self.assertEqual(character_count("星 \n 読む"), 3)

    def test_vertical_renderer_has_content(self) -> None:
        rendered = render_vertical("端末で読む", rows=4)
        self.assertIn("端", rendered)

    def test_sentence_around(self) -> None:
        text = "前の文。端末で読むと楽しい。次の文。"
        self.assertEqual(sentence_around(text, "読む"), "端末で読むと楽しい。")


if __name__ == "__main__":
    unittest.main()
