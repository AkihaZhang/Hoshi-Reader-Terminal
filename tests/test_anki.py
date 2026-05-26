import unittest

import hoshi_terminal.anki as anki


class AnkiTests(unittest.TestCase):
    def test_add_note_wraps_payload_for_ankiconnect(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_invoke(url: str, action: str, params: dict[str, object], timeout: float = 1.5) -> object:
            calls.append((action, params))
            if action == "addNote":
                return 123
            return None

        original = anki.invoke
        anki.invoke = fake_invoke
        try:
            settings = anki.AnkiSettings(
                url="http://127.0.0.1:8765",
                deck="Deck",
                model="Basic",
                front_field="Front",
                back_field="Back",
                tag="hoshi",
                mode="both",
            )
            note_id = anki.add_note(settings, "星", sentence="星を読む。")
        finally:
            anki.invoke = original

        self.assertEqual(note_id, 123)
        self.assertEqual(calls[0], ("createDeck", {"deck": "Deck"}))
        self.assertIn("note", calls[1][1])
        note = calls[1][1]["note"]
        self.assertIsInstance(note, dict)
        self.assertEqual(note["deckName"], "Deck")
        self.assertEqual(note["fields"], {"Front": "星", "Back": "星を読む。"})


if __name__ == "__main__":
    unittest.main()
