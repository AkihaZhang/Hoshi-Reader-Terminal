from pathlib import Path
import sqlite3
import tempfile
import unittest

from hoshi_terminal.audio import (
    AudioSource,
    LocalAudioEntry,
    LocalAudioRepository,
    audio_sources_from_settings,
    expand_audio_template,
    local_audio_url,
    parse_local_audio_url,
    resolve_local_audio,
)


class AudioTests(unittest.TestCase):
    def test_remote_template_replaces_term_and_reading_like_android(self) -> None:
        self.assertEqual(
            expand_audio_template("https://example.test/?term={term}&reading={reading}", "食べる", "たべ る"),
            "https://example.test/?term=%E9%A3%9F%E3%81%B9%E3%82%8B&reading=%E3%81%9F%E3%81%B9%20%E3%82%8B",
        )

    def test_local_audio_prefers_reading_then_default_source_order(self) -> None:
        match = resolve_local_audio(
            "食べる",
            "たべる",
            [
                LocalAudioEntry("nhk16", "食べる", "たべない", "wrong.mp3"),
                LocalAudioEntry("forvo", "食べる", "たべる", "right.mp3"),
            ],
        )

        self.assertEqual(match, LocalAudioEntry("forvo", "食べる", "たべる", "right.mp3"))

    def test_local_audio_url_round_trips(self) -> None:
        url = local_audio_url("nhk16", "audio/20180222111121.mp3")

        self.assertEqual(url, "hoshi-local-audio://nhk16/audio%2F20180222111121.mp3")
        self.assertEqual(parse_local_audio_url(url).file, "audio/20180222111121.mp3")

    def test_local_audio_repository_reads_android_db(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "android.db"
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE entries(source TEXT, expression TEXT, reading TEXT, file TEXT)")
                db.execute("CREATE TABLE android(source TEXT, file TEXT, data BLOB)")
                db.execute("INSERT INTO entries VALUES ('nhk16', '星', 'ほし', 'audio/hoshi.mp3')")
                db.execute("INSERT INTO android VALUES ('nhk16', 'audio/hoshi.mp3', ?)", (b'audio',))

            asset = LocalAudioRepository(db_path).resolve_asset("星", "ホシ")

        self.assertIsNotNone(asset)
        self.assertEqual(asset.data, b"audio")
        self.assertEqual(asset.source, "local:nhk16")

    def test_audio_sources_decode_settings(self) -> None:
        sources = audio_sources_from_settings(
            {"audio_sources": '[{"name":"A","url":"https://a.test/?term={term}","enabled":false}]'}
        )

        self.assertEqual(sources, [AudioSource("A", "https://a.test/?term={term}", False, False)])


if __name__ == "__main__":
    unittest.main()
