from pathlib import Path
from io import BytesIO
import json
import tempfile
import unittest
import zipfile

from hoshi_terminal.drive import DriveFile, DriveSyncFiles
from hoshi_terminal.storage import Library
from hoshi_terminal.sync import (
    export_ttu_bookdata,
    import_google_drive_book,
    sanitize_ttu_filename,
    sync_google_drive,
    sync_library,
    ttu_bookdata_to_epub,
)


class FakeDrive:
    def __init__(self) -> None:
        self.files = DriveSyncFiles()
        self.downloads: dict[str, object] = {}
        self.uploads: list[tuple[str, str | None, str, object]] = []
        self.binary_uploads: list[tuple[str, str | None, str, bytes, str]] = []

    def find_root_folder(self) -> str:
        return "root"

    def ensure_book_folder(self, book_title: str, root_folder_id: str) -> str:
        return f"folder:{book_title}"

    def list_sync_files(self, folder_id: str) -> DriveSyncFiles:
        return self.files

    def download_json(self, file_id: str) -> object:
        return self.downloads[file_id]

    def upload_json(
        self,
        folder_id: str,
        file_id: str | None,
        name: str,
        payload: object,
    ) -> None:
        self.uploads.append((folder_id, file_id, name, payload))

    def upload_file(
        self,
        folder_id: str,
        file_id: str | None,
        name: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self.binary_uploads.append((folder_id, file_id, name, content, content_type))

    def download_bytes(self, file_id: str) -> bytes:
        value = self.downloads[file_id]
        if not isinstance(value, bytes):
            raise AssertionError(f"{file_id} is not bytes")
        return value


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

    def test_google_drive_export_includes_progress_stats_audio_and_bookdata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            source.write_text("abcdefg", encoding="utf-8")
            library = Library(root / "state")
            record = library.import_book(source, title="Book")
            library.update_book_progress(record.id, 4, 1_700_000_000_000)
            library.add_statistic("Book", 4, 10)
            library.set_sasayaki(record, {"playback": {"lastPosition": 12.5, "rate": 1.0, "delay": 0.0}})
            drive = FakeDrive()

            messages = sync_google_drive(library, "export", client=drive)

            self.assertTrue(any("已上传到 Google Drive" in message for message in messages))
            names = [item[2] for item in drive.uploads]
            self.assertTrue(any(name.startswith("progress_1_6_") for name in names))
            self.assertTrue(any(name.startswith("statistics_1_6_") for name in names))
            self.assertTrue(any(name.startswith("audioBook_1_6_") for name in names))
            self.assertEqual(len(drive.binary_uploads), 1)
            self.assertTrue(drive.binary_uploads[0][2].startswith("bookdata_1_6_"))
            self.assertEqual(drive.binary_uploads[0][4], "application/zip")

    def test_google_drive_import_updates_progress_statistics_and_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            source.write_text("abcdefghij", encoding="utf-8")
            library = Library(root / "state")
            record = library.import_book(source, title="Book")
            drive = FakeDrive()
            drive.files = DriveSyncFiles(
                progress=DriveFile("progress", "progress_1_6_1800000000000_0.6.json"),
                statistics=DriveFile("stats", "statistics_1_6_1800000000000_6.json"),
                audio_book=DriveFile("audio", "audioBook_1_6_1800000000000_42.5.json"),
            )
            drive.downloads = {
                "progress": {
                    "dataId": 0,
                    "exploredCharCount": 6,
                    "progress": 0.6,
                    "lastBookmarkModified": 1_800_000_000_000,
                },
                "stats": [
                    {
                        "title": "Book",
                        "dateKey": "2026-06-12",
                        "charactersRead": 6,
                        "readingTime": 30.0,
                        "lastStatisticModified": 1_800_000_000_000,
                    }
                ],
                "audio": {
                    "title": "Book",
                    "playbackPosition": 42.5,
                    "lastAudioBookModified": 1_800_000_000_000,
                },
            }

            messages = sync_google_drive(library, "import", client=drive, upload_books=False)
            reloaded = Library(root / "state")

            self.assertTrue(any("已从 Google Drive 导入" in message for message in messages))
            self.assertEqual(reloaded.books[0].position, 6)
            self.assertEqual(reloaded.statistics_for_title("Book")[0].characters_read, 6)
            playback = reloaded.sasayaki_for(reloaded.books[0])["playback"]
            self.assertEqual(playback["lastPosition"], 42.5)

    def test_google_drive_auto_does_not_treat_fresh_import_as_newer_bookmark(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            source.write_text("abcdefghij", encoding="utf-8")
            library = Library(root / "state")
            library.import_book(source, title="Book")
            drive = FakeDrive()
            drive.files = DriveSyncFiles(
                progress=DriveFile("progress", "progress_1_6_1700000000000_0.7.json")
            )
            drive.downloads["progress"] = {
                "dataId": 0,
                "exploredCharCount": 7,
                "progress": 0.7,
                "lastBookmarkModified": 1_700_000_000_000,
            }

            messages = sync_google_drive(library, "auto", client=drive, upload_books=False)

            self.assertTrue(any("已从 Google Drive 导入" in message for message in messages))
            self.assertEqual(library.books[0].position, 7)
            self.assertFalse(drive.uploads)

    def test_bookdata_archive_matches_ttu_staticdata_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            source.write_text("第一行\n第二行", encoding="utf-8")
            library = Library(root / "state")
            record = library.import_book(source, title="Book")

            name, content = export_ttu_bookdata(record)

            self.assertTrue(name.startswith("bookdata_1_6_"))
            with zipfile.ZipFile(BytesIO(content)) as archive:
                self.assertEqual(archive.namelist(), ["staticdata.json"])
                static_data = json.loads(archive.read("staticdata.json"))
            self.assertEqual(static_data["title"], "Book")
            self.assertIn("ttu-book-html-wrapper", static_data["elementHtml"])
            self.assertEqual(static_data["sections"][0]["reference"], "ttu-chapter-1")

    def test_bookdata_round_trip_can_be_imported_from_google_drive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "book.txt"
            source.write_text("第一行\n第二行", encoding="utf-8")
            source_library = Library(root / "source-state")
            source_record = source_library.import_book(source, title="Remote Book")
            _, archive = export_ttu_bookdata(source_record)
            title, epub = ttu_bookdata_to_epub(archive)
            with zipfile.ZipFile(BytesIO(epub)) as converted:
                self.assertIn("OEBPS/content.xhtml", converted.namelist())
                self.assertIn("OEBPS/content.opf", converted.namelist())

            target_library = Library(root / "target-state")
            drive = FakeDrive()
            drive.files = DriveSyncFiles(
                book_data=DriveFile("bookdata", "bookdata_1_6_6_200_100.zip"),
                progress=DriveFile("progress", "progress_1_6_1800000000000_0.5.json"),
            )
            drive.downloads["bookdata"] = archive
            drive.downloads["progress"] = {
                "dataId": 0,
                "exploredCharCount": 3,
                "progress": 0.5,
                "lastBookmarkModified": 1_800_000_000_000,
            }
            imported = import_google_drive_book(
                target_library,
                DriveFile("folder", "Remote Book"),
                drive,
            )

            self.assertEqual(title, "Remote Book")
            self.assertEqual(imported.title, "Remote Book")
            self.assertEqual(target_library.books[0].position, 3)
            _, imported_text = target_library.load_record_text(imported)
            self.assertIn("第一行", imported_text)
            self.assertIn("第二行", imported_text)


if __name__ == "__main__":
    unittest.main()
