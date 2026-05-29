import unittest
import os

from hoshi_terminal.reader import (
    Page,
    character_count,
    highlight_sentence,
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
        rendered = render_page("book", Page(0, 0, 1, "本文"), 2)
        self.assertIn("←/→ 翻页", rendered)
        self.assertIn("↑/↓ Sasayaki", rendered)
        self.assertIn("Enter/Space 播放/暂停", rendered)
        self.assertNotIn("→/↓ 下一页", rendered)
        self.assertNotIn("←/↑ 上一页", rendered)
        self.assertNotIn("Enter/n", rendered)
        self.assertNotIn("p 上一页", rendered)
        self.assertNotIn("v 纵书", rendered)

    def test_reader_highlights_sasayaki_sentence_in_plain_text(self) -> None:
        previous = os.environ.get("FORCE_COLOR")
        previous_no_color = os.environ.get("NO_COLOR")
        previous_term = os.environ.get("TERM")
        os.environ["FORCE_COLOR"] = "1"
        os.environ.pop("NO_COLOR", None)
        os.environ["TERM"] = "xterm-256color"
        try:
            rendered = highlight_sentence("私は星を読んだ。", "星を読んだ")
        finally:
            if previous is None:
                os.environ.pop("FORCE_COLOR", None)
            else:
                os.environ["FORCE_COLOR"] = previous
            if previous_no_color is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = previous_no_color
            if previous_term is None:
                os.environ.pop("TERM", None)
            else:
                os.environ["TERM"] = previous_term

        self.assertIn("星を読んだ", rendered)
        self.assertNotEqual(rendered, "私は星を読んだ。")

    def test_reader_highlights_filtered_sasayaki_sentence(self) -> None:
        rendered = highlight_sentence("私は「星」を、読んだ。", "星を読んだ")

        self.assertIn("「星」を、読んだ", rendered)

    def test_sentence_around(self) -> None:
        text = "前の文。端末で読むと楽しい。次の文。"
        self.assertEqual(sentence_around(text, "読む"), "端末で読むと楽しい。")


if __name__ == "__main__":
    unittest.main()
