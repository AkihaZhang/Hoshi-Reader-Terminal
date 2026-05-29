import unittest

import hoshi_terminal.anki as anki
from hoshi_terminal.audio import AudioAsset


class AnkiTests(unittest.TestCase):
    def test_add_note_uses_lapis_defaults_and_stores_audio(self) -> None:
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
                model="Lapis",
                field_mappings=dict(anki.DEFAULT_LAPIS_FIELD_MAPPINGS),
                tag="hoshi",
                mode="both",
            )
            note_id = anki.add_note(
                settings,
                "星",
                sentence="星を読む。",
                note="star",
                reading="ほし",
                word_audio=AudioAsset("hoshi_audio.mp3", b"audio", "audio/mpeg", "test"),
                sentence_audio_path="",
            )
        finally:
            anki.invoke = original

        self.assertEqual(note_id, 123)
        self.assertEqual(calls[0], ("createDeck", {"deck": "Deck"}))
        self.assertEqual(calls[1][0], "storeMediaFile")
        self.assertIn("data", calls[1][1])
        self.assertIn("note", calls[2][1])
        note = calls[2][1]["note"]
        self.assertIsInstance(note, dict)
        self.assertEqual(note["deckName"], "Deck")
        fields = note["fields"]
        self.assertEqual(fields["Expression"], "星")
        self.assertEqual(fields["ExpressionReading"], "ほし")
        self.assertEqual(fields["ExpressionAudio"], "[sound:hoshi_audio.mp3]")
        self.assertEqual(fields["MainDefinition"], "star")
        self.assertEqual(fields["Sentence"], "<b>星</b>を読む。")
        self.assertEqual(fields["IsWordAndSentenceCard"], "x")

    def test_settings_defaults_to_android_lapis_mapping(self) -> None:
        settings = anki.settings_from_dict({})

        self.assertEqual(settings.deck, "Mining")
        self.assertEqual(settings.model, "Lapis")
        self.assertEqual(settings.field_mappings["ExpressionAudio"], "{audio}")
        self.assertEqual(settings.field_mappings["SentenceAudio"], "{sasayaki-audio}")


if __name__ == "__main__":
    unittest.main()
