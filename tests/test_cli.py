from pathlib import Path
import tempfile
import unittest
import zipfile

from hoshi_terminal.cli import _find_book_for_input, _language_name, create_backup
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

    def test_language_names(self) -> None:
        self.assertEqual(_language_name("zh"), "简体中文")
        self.assertEqual(_language_name("en"), "English")
        self.assertEqual(_language_name("ja"), "日本語")

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
