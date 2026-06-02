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
                force_sync=True,
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
        self.assertEqual(note["options"], {"allowDuplicate": False, "duplicateScope": "collection"})
        fields = note["fields"]
        self.assertEqual(fields["Expression"], "星")
        self.assertEqual(fields["ExpressionReading"], "ほし")
        self.assertEqual(fields["ExpressionAudio"], "[sound:hoshi_audio.mp3]")
        self.assertEqual(fields["MainDefinition"], "star")
        self.assertEqual(fields["Sentence"], "<b>星</b>を読む。")
        self.assertEqual(fields["IsWordAndSentenceCard"], "x")
        self.assertEqual(calls[3], ("sync", {}))

    def test_settings_defaults_to_android_lapis_mapping(self) -> None:
        settings = anki.settings_from_dict({})

        self.assertEqual(settings.deck, "Mining")
        self.assertEqual(settings.model, "Lapis")
        self.assertEqual(settings.field_mappings["ExpressionAudio"], "{audio}")
        self.assertEqual(settings.field_mappings["SentenceAudio"], "{sasayaki-audio}")

    def test_duplicate_options_support_deckroot_and_all_models(self) -> None:
        settings = anki.AnkiSettings(
            url="",
            deck="Mining::Novel",
            model="Lapis",
            field_mappings={"Expression": "{expression}"},
            tag="hoshi",
            mode="both",
            duplicate_scope="deckroot",
            check_duplicates_across_all_models=True,
        )

        self.assertEqual(
            anki.duplicate_options(settings),
            {
                "allowDuplicate": False,
                "duplicateScope": "deck",
                "duplicateScopeOptions": {"deckName": "Mining", "checkChildren": True, "checkAllModels": True},
            },
        )

    def test_is_duplicate_uses_can_add_notes_with_error_detail(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        def fake_invoke(url: str, action: str, params: dict[str, object], timeout: float = 1.5) -> object:
            calls.append((action, params))
            return [{"canAdd": False, "error": "duplicate"}]

        original = anki.invoke
        anki.invoke = fake_invoke
        try:
            settings = anki.AnkiSettings("", "Deck", "Lapis", {"Expression": "{expression}"}, "hoshi", "both")
            duplicate = anki.is_duplicate(settings, "星")
        finally:
            anki.invoke = original

        self.assertTrue(duplicate)
        self.assertEqual(calls[0][0], "canAddNotesWithErrorDetail")

    def test_fetch_note_types_and_lapis_selection(self) -> None:
        def fake_invoke(url: str, action: str, params: dict[str, object], timeout: float = 1.5) -> object:
            if action == "modelNames":
                return ["Basic", "My Lapis"]
            if action == "modelFieldNames":
                if params["modelName"] == "My Lapis":
                    return ["Expression", "Sentence", "MainDefinition", "Unused"]
                return ["Front", "Back"]
            raise AssertionError(action)

        original = anki.invoke
        anki.invoke = fake_invoke
        try:
            note_types = anki.fetch_note_types("http://127.0.0.1:8765")
        finally:
            anki.invoke = original

        selected = anki.select_note_type_after_fetch(note_types, "Missing")
        self.assertIsNotNone(selected)
        self.assertEqual(selected.name, "My Lapis")
        self.assertEqual(
            anki.lapis_default_mappings_for_fields(selected.fields),
            {"Expression": "{expression}", "Sentence": "{sentence}", "MainDefinition": "{glossary-first}"},
        )


if __name__ == "__main__":
    unittest.main()
