from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from hoshi_terminal.audio import (
    AudioSource,
    LocalAudioEntry,
    LocalAudioRepository,
    LocalAudioSourceConfig,
    audio_sources_from_settings,
    default_local_audio_source_order,
    expand_audio_template,
    local_audio_url,
    parse_local_audio_url,
    read_local_audio_source_config,
    repair_local_audio_source_config,
    resolve_local_audio,
    write_local_audio_source_config,
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

    def test_local_audio_respects_custom_source_order(self) -> None:
        rows = [
            LocalAudioEntry("nhk16", "秋", "あき", "nhk.mp3"),
            LocalAudioEntry("forvo", "秋", "あき", "forvo.ogg"),
        ]

        match = resolve_local_audio("秋", "アキ", rows, source_order=["forvo", "nhk16"])

        self.assertEqual(match, LocalAudioEntry("forvo", "秋", "あき", "forvo.ogg"))

    def test_local_audio_url_round_trips(self) -> None:
        url = local_audio_url("nhk16", "audio/20180222111121.mp3")

        self.assertEqual(url, "hoshi-local-audio://nhk16/audio%2F20180222111121.mp3")
        self.assertEqual(parse_local_audio_url(url).file, "audio/20180222111121.mp3")

    def test_local_audio_repository_reads_android_db(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "android.db"
            with closing(sqlite3.connect(db_path)) as db:
                db.execute("CREATE TABLE entries(source TEXT, expression TEXT, reading TEXT, file TEXT)")
                db.execute("CREATE TABLE android(source TEXT, file TEXT, data BLOB)")
                db.execute("INSERT INTO entries VALUES ('nhk16', '星', 'ほし', 'audio/hoshi.mp3')")
                db.execute("INSERT INTO android VALUES ('nhk16', 'audio/hoshi.mp3', ?)", (b'audio',))
                db.commit()

            asset = LocalAudioRepository(db_path).resolve_asset("星", "ホシ")

        self.assertIsNotNone(asset)
        self.assertEqual(asset.data, b"audio")
        self.assertEqual(asset.source, "local:nhk16")

    def test_local_audio_repository_uses_android_source_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "android.db"
            config_path = Path(temp_dir) / "android_sources.json"
            with closing(sqlite3.connect(db_path)) as db:
                db.execute("CREATE TABLE entries(source TEXT, expression TEXT, reading TEXT, file TEXT)")
                db.execute("CREATE TABLE android(source TEXT, file TEXT, data BLOB)")
                db.execute("INSERT INTO entries VALUES ('nhk16', '秋', 'あき', 'audio/nhk.mp3')")
                db.execute("INSERT INTO entries VALUES ('forvo', '秋', 'あき', 'audio/forvo.ogg')")
                db.execute("INSERT INTO android VALUES ('nhk16', 'audio/nhk.mp3', ?)", (b'nhk',))
                db.execute("INSERT INTO android VALUES ('forvo', 'audio/forvo.ogg', ?)", (b'ogg',))
                db.commit()
            write_local_audio_source_config(config_path, LocalAudioSourceConfig(source_order=("forvo", "nhk16")))

            asset = LocalAudioRepository(db_path, config_path).resolve_asset("秋", "アキ")

        self.assertIsNotNone(asset)
        self.assertEqual(asset.data, b"ogg")
        self.assertEqual(asset.mime_type, "audio/ogg")
        self.assertEqual(asset.source, "local:forvo")

    def test_local_audio_source_config_repairs_like_android(self) -> None:
        config = LocalAudioSourceConfig(source_order=("forvo", "missing", "forvo"))

        repaired = repair_local_audio_source_config(config, ["nhk16", "forvo", "daijisen"])

        self.assertEqual(repaired.source_order, ("forvo", "nhk16", "daijisen"))
        self.assertEqual(default_local_audio_source_order(["forvo", "unknown", "nhk16"]), ["nhk16", "forvo", "unknown"])

    def test_local_audio_source_config_round_trips_android_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "android_sources.json"
            write_local_audio_source_config(config_path, LocalAudioSourceConfig(source_order=("forvo", "nhk16")))

            loaded = read_local_audio_source_config(config_path)

        self.assertEqual(loaded, LocalAudioSourceConfig(version=1, source_order=("forvo", "nhk16")))

    def test_audio_sources_decode_settings(self) -> None:
        sources = audio_sources_from_settings(
            {"audio_sources": '[{"name":"A","url":"https://a.test/?term={term}","enabled":false}]'}
        )

        self.assertEqual(sources, [AudioSource("A", "https://a.test/?term={term}", False, False)])


if __name__ == "__main__":
    unittest.main()
