from pathlib import Path
import json
import tempfile
import unittest

from hoshi_terminal.storage import Library
from hoshi_terminal.sync import sanitize_ttu_filename, sync_library


class SyncTests(unittest.TestCase):
    def test_sanitize_ttu_filename_matches_hoshi_rules(self) -> None:
        self.assertEqual(sanitize_ttu_filename('a/b?c*d. '), "a%2Fb%3Fc~ttu-star~d.~ttu-spc~")
        self.assertEqual(sanitize_ttu_filename("Title."), "Title~ttu-dend~")
        self.assertEqual(sanitize_ttu_filename("Title "), "Title~ttu-spc~")

    def test_export_and_import_progress_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            source.write_text("abcdefg", encoding="utf-8")
            library = Library(root / "state")
            library.set_setting("sync_path", root / "sync")
            record = library.import_book(source, title="Book")
            library.update_book_progress(record.id, 4, 1_700_000_000_000)

            export_messages = sync_library(library, "export")
            progress_files = list((root / "sync" / "ttu-reader-data" / "Book").glob("progress_*.json"))
            self.assertTrue(any("已导出进度" in message for message in export_messages))
            self.assertEqual(len(progress_files), 1)
            with progress_files[0].open("r", encoding="utf-8") as handle:
                exported = json.load(handle)
            self.assertEqual(exported["exploredCharCount"], 4)

            library.update_book_progress(record.id, 0, 1_000)
            import_messages = sync_library(library, "import")
            reloaded = Library(root / "state")

        self.assertTrue(any("已导入进度" in message for message in import_messages))
        self.assertEqual(reloaded.books[0].position, 4)


if __name__ == "__main__":
    unittest.main()
