from pathlib import Path
import tempfile
import unittest

from hoshi_terminal.dictionary import DictionaryManager, deinflect


class DictionaryTests(unittest.TestCase):
    def test_deinflect_polite_past(self) -> None:
        candidates = dict(deinflect("読みました"))
        self.assertIn("読む", candidates)

    def test_import_yomitan_directory_and_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dictionary = root / "dict"
            dictionary.mkdir()
            (dictionary / "index.json").write_text('{"title":"Tiny"}', encoding="utf-8")
            (dictionary / "term_bank_1.json").write_text(
                '[["星","ほし","","",0,["star"],1,""]]',
                encoding="utf-8",
            )
            manager = DictionaryManager(root / "entries.json")
            count = manager.import_yomitan(dictionary)
            results = manager.lookup("星")

        self.assertEqual(count, 1)
        self.assertEqual(results[0].term, "星")
        self.assertEqual(results[0].definitions, ["star"])

    def test_lookup_deinflected_polite_form(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dictionary = root / "dict"
            dictionary.mkdir()
            (dictionary / "index.json").write_text('{"title":"Tiny"}', encoding="utf-8")
            (dictionary / "term_bank_1.json").write_text(
                '[["読む","よむ","","",0,["to read"],1,""]]',
                encoding="utf-8",
            )
            manager = DictionaryManager(root / "entries.json")
            manager.import_yomitan(dictionary)
            results = manager.lookup("読みました")

        self.assertTrue(any(result.term == "読む" for result in results))


if __name__ == "__main__":
    unittest.main()
