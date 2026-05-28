from pathlib import Path
import tempfile
import unittest

from hoshi_terminal.dictionary import DictionaryManager, deinflect, format_result_pages, format_results, paginate_lookup_text


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

    def test_lookup_scans_prefix_like_reader_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dictionary = root / "dict"
            dictionary.mkdir()
            (dictionary / "index.json").write_text('{"title":"Tiny"}', encoding="utf-8")
            (dictionary / "term_bank_1.json").write_text(
                '[["秋","あき","名詞","",0,["autumn"],1,"common"]]',
                encoding="utf-8",
            )
            manager = DictionaryManager(root / "entries.json")
            manager.import_yomitan(dictionary)
            results = manager.lookup("秋の空")
            rendered = format_results(results)

        self.assertEqual(results[0].term, "秋")
        self.assertIn("前方扫描", results[0].note)
        self.assertIn("▼ Tiny", rendered)
        self.assertIn("[common / 名詞]", rendered)

    def test_lookup_output_can_be_paginated(self) -> None:
        pages = paginate_lookup_text("one\ntwo\nthree\n\nfour\nfive", lines_per_page=3)
        self.assertEqual(len(pages), 2)
        self.assertIn("one", pages[0])
        self.assertIn("four", pages[1])

    def test_lookup_pagination_wraps_long_dictionary_lines(self) -> None:
        text = "1. 秋\n   ▼ Tiny\n      ・ " + "長い説明" * 24
        pages = paginate_lookup_text(text, lines_per_page=4, width=32)
        self.assertGreater(len(pages), 1)

    def test_formatted_results_can_be_paginated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dictionary = root / "dict"
            dictionary.mkdir()
            (dictionary / "index.json").write_text('{"title":"Tiny"}', encoding="utf-8")
            (dictionary / "term_bank_1.json").write_text(
                '[["星","ほし","","",0,["star one","star two","star three","star four"],1,""]]',
                encoding="utf-8",
            )
            manager = DictionaryManager(root / "entries.json")
            manager.import_yomitan(dictionary)
            pages = format_result_pages(manager.lookup("星"), lines_per_page=4)

        self.assertGreaterEqual(len(pages), 2)

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

    def test_import_term_frequency_and_pitch_dictionaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            term = root / "Term" / "tiny-term"
            frequency = root / "Frequency" / "tiny-frequency"
            pitch = root / "Pitch" / "tiny-pitch"
            term.mkdir(parents=True)
            frequency.mkdir(parents=True)
            pitch.mkdir(parents=True)
            (term / "index.json").write_text('{"title":"Tiny Term","revision":"1"}', encoding="utf-8")
            (term / "term_bank_1.json").write_text(
                '[["読む","よむ","","",0,["to read"],1,""]]',
                encoding="utf-8",
            )
            (frequency / "index.json").write_text('{"title":"Tiny Frequency","revision":"1"}', encoding="utf-8")
            (frequency / "term_meta_bank_1.json").write_text(
                '[["読む","freq",{"reading":"よむ","frequency":{"value":42,"displayValue":"42"}}],'
                '["秋","freq",{"frequency":2632,"displayValue":"2632"}]]',
                encoding="utf-8",
            )
            (pitch / "index.json").write_text('{"title":"Tiny Pitch","revision":"1"}', encoding="utf-8")
            (pitch / "term_meta_bank_1.json").write_text(
                '[["読む","pitch",{"reading":"よむ","pitches":[{"position":1}]}]]',
                encoding="utf-8",
            )

            manager = DictionaryManager(root / "entries.json")
            count = manager.import_yomitan(root)
            counts = manager.counts_by_type()
            results = manager.lookup("読みました")

        self.assertEqual(count, 4)
        self.assertEqual(counts["term"], 1)
        self.assertEqual(counts["frequency"], 2)
        self.assertEqual(counts["pitch"], 1)
        self.assertTrue(results)
        self.assertIn("Tiny Frequency", results[0].frequencies[0])
        self.assertIn("Tiny Pitch", results[0].pitches[0])

    def test_dictionary_priority_changes_lookup_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "Term" / "first"
            second = root / "Term" / "second"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "index.json").write_text('{"title":"First","revision":"1"}', encoding="utf-8")
            (first / "term_bank_1.json").write_text('[["星","ほし","","",0,["first"],1,""]]', encoding="utf-8")
            (second / "index.json").write_text('{"title":"Second","revision":"1"}', encoding="utf-8")
            (second / "term_bank_1.json").write_text('[["星","ほし","","",0,["second"],1,""]]', encoding="utf-8")

            manager = DictionaryManager(root / "entries.json")
            manager.import_yomitan(root)
            before = manager.lookup("星")
            manager.move_dictionary("term", 1, 0)
            after = manager.lookup("星")

        self.assertEqual(before[0].dictionary, "First")
        self.assertEqual(after[0].dictionary, "Second")


if __name__ == "__main__":
    unittest.main()
