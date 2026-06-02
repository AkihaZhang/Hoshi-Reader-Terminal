from pathlib import Path
import tempfile
import unittest

from hoshi_terminal.storage import Library


class StorageTests(unittest.TestCase):
    def test_removed_language_settings_fall_back_to_chinese(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            library = Library(Path(temp_dir) / "state")
            library.set_setting("language", "ja")

            reloaded = Library(Path(temp_dir) / "state")

            self.assertEqual(reloaded.settings["language"], "zh")

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

    def test_bookshelves_create_move_reorder_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.txt"
            second = root / "second.txt"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")
            library = Library(root / "state")
            first_record = library.import_book(first, title="First")
            second_record = library.import_book(second, title="Second")

            self.assertTrue(library.create_shelf("Novel"))
            self.assertTrue(library.create_shelf("Reading"))
            self.assertFalse(library.create_shelf("Novel"))
            self.assertTrue(library.move_book_to_shelf(first_record.id, "Novel"))
            self.assertTrue(library.move_book_to_shelf(second_record.id, "Reading"))
            self.assertEqual(library.shelf_for(first_record.id), "Novel")
            self.assertTrue(library.move_shelf(1, 0))
            self.assertEqual(library.shelves[0]["name"], "Reading")

            self.assertTrue(library.move_book_to_shelf(first_record.id, None))
            self.assertIsNone(library.shelf_for(first_record.id))
            self.assertTrue(library.delete_book(second_record.id))

            reloaded = Library(root / "state")
            self.assertNotIn(second_record.id, reloaded.shelves[0]["book_ids"])


if __name__ == "__main__":
    unittest.main()
