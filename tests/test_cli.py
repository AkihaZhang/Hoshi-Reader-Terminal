from pathlib import Path
from io import StringIO
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from hoshi_terminal.cli import (
    _chapter_marks_from_extracted,
    _chapter_mark_index_for_position,
    _find_book_for_input,
    _is_toc_command,
    interactive_loop,
    _language_name,
    _normalize_reader_key,
    _parse_page_number,
    _reader_highlights_panel,
    _reader_search_panel,
    _reader_toc_panel,
    _toc_initial_command,
    create_backup,
    main,
)
from hoshi_terminal.epub import Chapter, ExtractedBook
from hoshi_terminal.reader import Page
from hoshi_terminal.storage import Library


class CliTests(unittest.TestCase):
    def test_book_selection_accepts_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            library = Library(root / "state")
            first_record = library.import_book(first, title="First")
            second_record = library.import_book(second, title="Second")
            library.update_book_progress(first_record.id, 0, 1_700_000_000_000)
            library.update_book_progress(second_record.id, 0, 1_800_000_000_000)

            selected_first = _find_book_for_input(library, "1")
            selected_second = _find_book_for_input(library, "2")
            selected_recent = _find_book_for_input(library, None)

        self.assertIsNotNone(selected_first)
        self.assertIsNotNone(selected_second)
        self.assertIsNotNone(selected_recent)
        self.assertEqual(selected_first.title, "Second")
        self.assertEqual(selected_second.title, "First")
        self.assertEqual(selected_recent.title, "Second")

    def test_book_selection_respects_title_sort_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            zeta = root / "zeta.txt"
            alpha = root / "alpha.txt"
            zeta.write_text("zeta", encoding="utf-8")
            alpha.write_text("alpha", encoding="utf-8")
            library = Library(root / "state")
            library.import_book(zeta, title="Zeta")
            library.import_book(alpha, title="Alpha")
            library.set_setting("bookshelf_sort", "title")

            selected_first = _find_book_for_input(library, "1")

        self.assertIsNotNone(selected_first)
        self.assertEqual(selected_first.title, "Alpha")

    def test_language_names(self) -> None:
        self.assertEqual(_language_name("zh"), "简体中文")
        self.assertEqual(_language_name("en"), "English")
        self.assertEqual(_language_name("ja"), "简体中文")

    def test_reader_arrow_keys_are_commands(self) -> None:
        self.assertEqual(_normalize_reader_key("\x1b[C"), "right")
        self.assertEqual(_normalize_reader_key("\x1b[D"), "left")
        self.assertEqual(_normalize_reader_key("\n"), "")
        self.assertEqual(_normalize_reader_key(" "), "space")

    def test_chapter_marks_use_joined_book_offsets(self) -> None:
        book = ExtractedBook(
            title="Book",
            chapters=[
                Chapter("One", "abc"),
                Chapter("Two", "defg"),
            ],
        )

        self.assertEqual(_chapter_marks_from_extracted(book), [("One", 0), ("Two", 5)])

    def test_toc_panel_jumps_to_chapter_number(self) -> None:
        pages = [
            Page(0, 0, 49, "one"),
            Page(1, 50, 99, "two"),
            Page(2, 100, 149, "three"),
        ]
        marks = [("One", 0), ("Two", 50), ("Three", 100)]
        output = StringIO()

        with (
            patch("builtins.input", return_value="3"),
            patch("sys.stdout", output),
            patch.dict(os.environ, {"NO_COLOR": "1"}),
        ):
            index = _reader_toc_panel("Book", pages, 0, marks)

        self.assertEqual(index, 2)
        self.assertIn("目录", output.getvalue())
        self.assertIn("3. p3", output.getvalue())

    def test_toc_panel_accepts_prefilled_chapter_number(self) -> None:
        pages = [
            Page(0, 0, 49, "one"),
            Page(1, 50, 99, "two"),
            Page(2, 100, 149, "three"),
        ]
        marks = [("One", 0), ("Two", 50), ("Three", 100)]
        output = StringIO()

        with (
            patch("sys.stdout", output),
            patch.dict(os.environ, {"NO_COLOR": "1"}),
        ):
            index = _reader_toc_panel("Book", pages, 0, marks, initial_command="3")

        self.assertEqual(index, 2)
        self.assertIn("目录页", output.getvalue())

    def test_toc_shortcut_accepts_pasted_number(self) -> None:
        self.assertTrue(_is_toc_command("t"))
        self.assertTrue(_is_toc_command("c"))
        self.assertTrue(_is_toc_command("t3"))
        self.assertEqual(_toc_initial_command("t3"), "3")

    def test_reader_loop_opens_toc_and_jumps(self) -> None:
        pages = [
            Page(0, 0, 49, "one"),
            Page(1, 50, 99, "two"),
            Page(2, 100, 149, "three"),
        ]
        marks = [("One", 0), ("Two", 50), ("Three", 100)]
        output = StringIO()

        with (
            patch("hoshi_terminal.cli._read_reader_command", side_effect=["t", "q"]),
            patch("hoshi_terminal.cli._read_toc_command", return_value="2"),
            patch("sys.stdout", output),
            patch.dict(os.environ, {"NO_COLOR": "1"}),
        ):
            code = interactive_loop("Book", "one\ntwo\nthree", pages, record=None, start_page=0, chapter_marks=marks)

        text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("目录", text)
        self.assertIn("Book  第 2/3 页", text)

    def test_toc_active_mark_uses_current_position(self) -> None:
        marks = [("One", 0), ("Two", 50), ("Three", 100)]

        self.assertEqual(_chapter_mark_index_for_position(marks, 0), 0)
        self.assertEqual(_chapter_mark_index_for_position(marks, 75), 1)
        self.assertEqual(_chapter_mark_index_for_position(marks, 150), 2)

    def test_reader_search_panel_jumps_to_result_number(self) -> None:
        text = "alpha one\nbeta first\nmiddle\nbeta second"
        pages = [
            Page(0, 0, 18, "alpha one\nbeta first"),
            Page(1, 19, len(text), "middle\nbeta second"),
        ]
        output = StringIO()

        with (
            patch("builtins.input", return_value="2"),
            patch("sys.stdout", output),
            patch.dict(os.environ, {"NO_COLOR": "1"}),
        ):
            index = _reader_search_panel("Book", text, pages, 0, initial_query="beta")

        self.assertEqual(index, 1)
        self.assertIn("正文搜索", output.getvalue())
        self.assertIn("命中: 2", output.getvalue())

    def test_reader_loop_search_shortcut_jumps_to_result(self) -> None:
        text = "alpha one\nbeta first\nmiddle\nbeta second"
        pages = [
            Page(0, 0, 18, "alpha one\nbeta first"),
            Page(1, 19, len(text), "middle\nbeta second"),
        ]
        output = StringIO()

        with (
            patch("hoshi_terminal.cli._read_reader_command", side_effect=["f beta", "q"]),
            patch("hoshi_terminal.cli._read_search_command", return_value="2"),
            patch("sys.stdout", output),
            patch.dict(os.environ, {"NO_COLOR": "1"}),
        ):
            code = interactive_loop("Book", text, pages, record=None, start_page=0)

        self.assertEqual(code, 0)
        self.assertIn("正文搜索", output.getvalue())
        self.assertIn("Book  第 2/2 页", output.getvalue())

    def test_highlights_panel_jumps_to_saved_position(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            book = root / "book.txt"
            text = "alpha one\nbeta first\nmiddle\nbeta second"
            book.write_text(text, encoding="utf-8")
            library = Library(root / "state")
            record = library.import_book(book, title="Book")
            library.add_highlight(record, "beta second", "note", position=text.find("beta second"))
            pages = [
                Page(0, 0, 18, "alpha one\nbeta first"),
                Page(1, 19, len(text), "middle\nbeta second"),
            ]
            output = StringIO()

            with (
                patch("builtins.input", return_value="1"),
                patch("sys.stdout", output),
                patch.dict(os.environ, {"NO_COLOR": "1"}),
            ):
                index = _reader_highlights_panel(library, record, text, pages, 0)

        self.assertEqual(index, 1)
        self.assertIn("划线 / 备注", output.getvalue())
        self.assertIn("note", output.getvalue())

    def test_percent_goto_is_supported(self) -> None:
        self.assertEqual(_parse_page_number("1", 5), 0)
        self.assertEqual(_parse_page_number("50%", 5), 2)
        self.assertEqual(_parse_page_number("100%", 5), 4)

    def test_no_args_opens_menu(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            with (
                patch.dict(os.environ, {"HOSHI_TERMINAL_HOME": str(Path(temp_dir) / "state"), "NO_COLOR": "1"}),
                patch("builtins.input", return_value="0"),
                patch("sys.stdout", output),
            ):
                code = main([])

        self.assertEqual(code, 0)
        self.assertIn("Hoshi Reader", output.getvalue())
        self.assertIn("1. 书库", output.getvalue())

    def test_books_menu_uses_shelf_as_read_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            with (
                patch.dict(os.environ, {"HOSHI_TERMINAL_HOME": str(Path(temp_dir) / "state"), "NO_COLOR": "1"}),
                patch("builtins.input", side_effect=["1", "0", "0"]),
                patch("sys.stdout", output),
            ):
                code = main([])

        self.assertEqual(code, 0)
        text = output.getvalue()
        self.assertIn("1. 书架 / 阅读", text)
        self.assertNotIn("3. 阅读", text)

    def test_backup_is_created_outside_library_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = Library(root / "state")
            (library.root / "library.json").write_text("{}", encoding="utf-8")
            old_bad_backup = library.root / "hoshi-terminal-backup-old.zip"
            old_bad_backup.write_text("do not include", encoding="utf-8")

            archive = create_backup(library)

            self.assertTrue(archive.exists())
            self.assertNotEqual(archive.parent, library.root)
            self.assertIn("state-backups", str(archive.parent))
            with zipfile.ZipFile(archive) as backup:
                self.assertNotIn("hoshi-terminal-backup-old.zip", backup.namelist())


if __name__ == "__main__":
    unittest.main()
