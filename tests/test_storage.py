from pathlib import Path
import tempfile
import unittest

from hoshi_terminal.storage import Library


class StorageTests(unittest.TestCase):
    def test_book_management_renames_marks_read_and_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            source.write_text("星を読む。\n次のページ。", encoding="utf-8")
            library = Library(root / "state")
            record = library.import_book(source, title="Old")
            library.add_highlight(record, "星を読む。", "note")

            self.assertTrue(library.rename_book(record.id, "New"))
            renamed = Library(root / "state")
            self.assertEqual(renamed.books[0].title, "New")
            self.assertEqual(renamed._state["highlights"][0]["title"], "New")

            self.assertTrue(renamed.mark_book_read(record.id))
            read = Library(root / "state")
            self.assertGreater(read.books[0].position, 0)

            stored = Path(read.books[0].stored_path)
            self.assertTrue(stored.exists())
            self.assertTrue(read.delete_book(record.id))
            deleted = Library(root / "state")
            self.assertEqual(deleted.books, [])
            self.assertFalse(stored.exists())
            self.assertEqual(deleted._state["highlights"], [])


if __name__ == "__main__":
    unittest.main()
