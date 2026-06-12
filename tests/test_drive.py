from pathlib import Path
from urllib.parse import parse_qs
import json
import tempfile
import unittest

from hoshi_terminal.drive import (
    DeviceCodePrompt,
    DriveCredentialStore,
    GoogleDeviceCodeAuthorizer,
    GoogleDriveClient,
    HttpResponse,
)


class QueueTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        self.requests.append((method, url, headers, body))
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {url}")
        return self.responses.pop(0)


def response(status: int, payload: object) -> HttpResponse:
    return HttpResponse(status, json.dumps(payload).encode("utf-8"), {})


class DriveTests(unittest.TestCase):
    def test_device_code_authorization_saves_refresh_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DriveCredentialStore(Path(temp_dir) / "auth.json")
            transport = QueueTransport(
                [
                    response(
                        200,
                        {
                            "device_code": "device",
                            "user_code": "ABCD-EFGH",
                            "verification_url": "https://example.test/device",
                            "expires_in": 900,
                            "interval": 1,
                        },
                    ),
                    response(400, {"error": "authorization_pending"}),
                    response(
                        200,
                        {
                            "access_token": "access",
                            "refresh_token": "refresh",
                            "expires_in": 3600,
                        },
                    ),
                ]
            )
            authorizer = GoogleDeviceCodeAuthorizer(
                store,
                transport=transport,
                device_code_url="https://example.test/device-code",
                token_url="https://example.test/token",
                now=lambda: 1000.0,
            )
            authorizer.configure("client", "secret")
            shown: list[DeviceCodePrompt] = []
            sleeps: list[float] = []

            prompt = authorizer.authorize(
                on_prompt=shown.append,
                open_browser=False,
                sleep=sleeps.append,
            )

            self.assertEqual(prompt.user_code, "ABCD-EFGH")
            self.assertEqual(shown, [prompt])
            self.assertEqual(sleeps, [1, 1])
            self.assertEqual(authorizer.status(), "connected")
            self.assertEqual(authorizer.access_token(), "access")
            saved = store.load()
            self.assertEqual(saved["refresh_token"], "refresh")
            self.assertEqual(parse_qs(transport.requests[0][3].decode())["scope"], [
                "https://www.googleapis.com/auth/drive.file"
            ])

    def test_expired_access_token_is_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DriveCredentialStore(Path(temp_dir) / "auth.json")
            store.save(
                {
                    "client_id": "client",
                    "client_secret": "secret",
                    "access_token": "expired",
                    "refresh_token": "refresh",
                    "expires_at_ms": 1,
                }
            )
            transport = QueueTransport(
                [response(200, {"access_token": "new-access", "expires_in": 3600})]
            )
            authorizer = GoogleDeviceCodeAuthorizer(
                store,
                transport=transport,
                token_url="https://example.test/token",
                now=lambda: 1000.0,
            )

            token = authorizer.access_token()

            self.assertEqual(token, "new-access")
            form = parse_qs(transport.requests[0][3].decode())
            self.assertEqual(form["grant_type"], ["refresh_token"])
            self.assertEqual(store.load()["refresh_token"], "refresh")

    def test_drive_client_finds_root_and_selects_latest_sync_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DriveCredentialStore(Path(temp_dir) / "auth.json")
            store.save(
                {
                    "client_id": "client",
                    "client_secret": "secret",
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_at_ms": 9_999_999_999_999,
                }
            )
            transport = QueueTransport(
                [
                    response(200, {"files": [{"id": "root-id", "name": "ttu-reader-data"}]}),
                    response(
                        200,
                        {
                            "files": [
                                {"id": "old", "name": "progress_1_6_100_0.1.json"},
                                {"id": "new", "name": "progress_1_6_200_0.2.json"},
                                {"id": "stats", "name": "statistics_1_6_150_1.json"},
                                {"id": "audio", "name": "audioBook_1_6_175_12.0.json"},
                                {"id": "book", "name": "bookdata_1_6_10_180_100.zip"},
                            ]
                        },
                    ),
                ]
            )
            authorizer = GoogleDeviceCodeAuthorizer(store, transport=transport)
            drive = GoogleDriveClient(
                authorizer,
                transport=transport,
                api_url="https://example.test/drive",
                upload_url="https://example.test/upload",
            )

            root_id = drive.find_root_folder()
            files = drive.list_sync_files("book-folder")

            self.assertEqual(root_id, "root-id")
            self.assertEqual(files.progress.id, "new")
            self.assertEqual(files.statistics.id, "stats")
            self.assertEqual(files.audio_book.id, "audio")
            self.assertEqual(files.book_data.id, "book")

    def test_drive_upload_updates_existing_file_with_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = DriveCredentialStore(Path(temp_dir) / "auth.json")
            store.save(
                {
                    "client_id": "client",
                    "client_secret": "secret",
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_at_ms": 9_999_999_999_999,
                }
            )
            transport = QueueTransport([response(200, {"id": "progress-id"})])
            authorizer = GoogleDeviceCodeAuthorizer(store, transport=transport)
            drive = GoogleDriveClient(
                authorizer,
                transport=transport,
                api_url="https://example.test/drive",
                upload_url="https://example.test/upload",
            )

            drive.upload_json("folder", "progress-id", "progress_1_6_10_0.5.json", {"progress": 0.5})

            method, url, headers, body = transport.requests[0]
            self.assertEqual(method, "PATCH")
            self.assertIn("/files/progress-id?uploadType=multipart", url)
            self.assertIn("multipart/related", headers["Content-Type"])
            self.assertIn(b'"name":"progress_1_6_10_0.5.json"', body)


if __name__ == "__main__":
    unittest.main()
