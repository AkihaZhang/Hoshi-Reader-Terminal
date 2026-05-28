import unittest

from hoshi_terminal.reader import (
    Page,
    character_count,
    paginate,
    render_page,
    render_vertical,
    sentence_around,
    terminal_cell_width,
    vertical_cell,
)


class ReaderTests(unittest.TestCase):
    def test_paginate_returns_pages(self) -> None:
        pages = paginate("星 " * 200, width=20, lines_per_page=4)
        self.assertGreater(len(pages), 1)

    def test_character_count_ignores_whitespace(self) -> None:
        self.assertEqual(character_count("星 \n 読む"), 3)

    def test_vertical_renderer_has_content(self) -> None:
        rendered = render_vertical("端末で読む", rows=4)
        self.assertIn("端", rendered)

    def test_vertical_renderer_uses_terminal_cell_widths(self) -> None:
        self.assertEqual(terminal_cell_width("星"), 2)
        self.assertEqual(terminal_cell_width("あ"), 2)
        self.assertEqual(terminal_cell_width("｡"), 1)
        self.assertEqual(vertical_cell("。"), "｡ ")

    def test_reader_footer_splits_page_and_sasayaki_arrows(self) -> None:
        rendered = render_page("demo", Page(0, 0, 1, "本文"), 2)
        self.assertIn("←/→ 翻页", rendered)
        self.assertIn("↑/↓ Sasayaki", rendered)
        self.assertIn("Enter/Space 播放/暂停", rendered)
        self.assertNotIn("→/↓ 下一页", rendered)
        self.assertNotIn("←/↑ 上一页", rendered)
        self.assertNotIn("Enter/n", rendered)
        self.assertNotIn("p 上一页", rendered)
        self.assertNotIn("v 纵书", rendered)

    def test_sentence_around(self) -> None:
        text = "前の文。端末で読むと楽しい。次の文。"
        self.assertEqual(sentence_around(text, "読む"), "端末で読むと楽しい。")


if __name__ == "__main__":
    unittest.main()
