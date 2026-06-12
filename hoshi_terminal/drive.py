from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import json
import os
import time
import uuid
import webbrowser


DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
TTU_ROOT = "ttu-reader-data"


class DriveAuthError(RuntimeError):
    pass


class DriveAuthorizationRequired(DriveAuthError):
    pass


class DriveApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: dict[str, str]


@dataclass(frozen=True)
class DeviceCodePrompt:
    device_code: str
    user_code: str
    verification_url: str
    expires_in_seconds: int
    interval_seconds: int


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    parents: tuple[str, ...] = ()
    thumbnail_link: str | None = None


@dataclass(frozen=True)
class DriveSyncFiles:
    book_data: DriveFile | None = None
    cover: DriveFile | None = None
    progress: DriveFile | None = None
    statistics: DriveFile | None = None
    audio_book: DriveFile | None = None


Transport = Callable[[str, str, dict[str, str], bytes | None, float], HttpResponse]


def urllib_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> HttpResponse:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=int(response.status),
                body=response.read(),
                headers={str(key).lower(): str(value) for key, value in response.headers.items()},
            )
    except HTTPError as error:
        return HttpResponse(
            status=int(error.code),
            body=error.read(),
            headers={str(key).lower(): str(value) for key, value in error.headers.items()},
        )
    except (URLError, TimeoutError) as error:
        reason = getattr(error, "reason", error)
        raise DriveApiError(f"网络请求失败: {reason}") from error


class DriveCredentialStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, object]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(self.path)
        if os.name != "nt":
            self.path.chmod(0o600)

    def configure(self, client_id: str, client_secret: str) -> None:
        current = self.load()
        normalized_id = client_id.strip()
        normalized_secret = client_secret.strip()
        if (
            current.get("client_id") != normalized_id
            or current.get("client_secret") != normalized_secret
        ):
            current.pop("access_token", None)
            current.pop("refresh_token", None)
            current.pop("expires_at_ms", None)
        current["client_id"] = normalized_id
        current["client_secret"] = normalized_secret
        self.save(current)

    def clear_tokens(self) -> None:
        current = self.load()
        current.pop("access_token", None)
        current.pop("refresh_token", None)
        current.pop("expires_at_ms", None)
        self.save(current)

    def clear_access_token(self, token: str | None = None) -> None:
        current = self.load()
        if token is None or current.get("access_token") == token:
            current.pop("access_token", None)
            current.pop("expires_at_ms", None)
            self.save(current)


class GoogleDeviceCodeAuthorizer:
    def __init__(
        self,
        store: DriveCredentialStore,
        transport: Transport = urllib_transport,
        device_code_url: str = DEVICE_CODE_URL,
        token_url: str = TOKEN_URL,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.transport = transport
        self.device_code_url = device_code_url
        self.token_url = token_url
        self.now = now

    def configure(self, client_id: str, client_secret: str) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise DriveAuthError("Google OAuth Client ID 和 Client Secret 不能为空。")
        self.store.configure(client_id, client_secret)

    def status(self) -> str:
        data = self.store.load()
        if not str(data.get("client_id", "")).strip() or not str(data.get("client_secret", "")).strip():
            return "missing_configuration"
        if not str(data.get("refresh_token", "")).strip():
            return "not_connected"
        return "connected"

    def request_device_code(self) -> DeviceCodePrompt:
        client_id, _ = self._client()
        response = self._post_form(
            self.device_code_url,
            {"client_id": client_id, "scope": DRIVE_FILE_SCOPE},
        )
        payload = self._json_response(response, "Google Drive 授权码请求失败。")
        verification_url = payload.get("verification_url") or payload.get("verification_uri")
        if not payload.get("device_code") or not payload.get("user_code") or not verification_url:
            raise DriveAuthError("Google 没有返回完整的设备授权码。")
        return DeviceCodePrompt(
            device_code=str(payload["device_code"]),
            user_code=str(payload["user_code"]),
            verification_url=str(verification_url),
            expires_in_seconds=int(payload.get("expires_in", 900)),
            interval_seconds=max(1, int(payload.get("interval", 5))),
        )

    def poll_authorization(self, prompt: DeviceCodePrompt) -> str:
        client_id, client_secret = self._client()
        response = self._post_form(
            self.token_url,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "device_code": prompt.device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        if response.status < 400:
            self._save_token_payload(self._decode_json(response.body))
            return "authorized"
        payload = self._decode_json(response.body)
        error = str(payload.get("error", ""))
        if error in {"authorization_pending", "slow_down"}:
            return error
        messages = {
            "access_denied": "Google Drive 授权被拒绝。",
            "expired_token": "Google Drive 设备授权码已过期。",
            "invalid_client": "OAuth 客户端无效；请使用“TV 和受限输入设备”类型的客户端。",
        }
        raise DriveAuthError(
            str(payload.get("error_description") or messages.get(error) or error or "Google Drive 授权失败。")
        )

    def authorize(
        self,
        on_prompt: Callable[[DeviceCodePrompt], None] | None = None,
        open_browser: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> DeviceCodePrompt:
        prompt = self.request_device_code()
        if on_prompt is not None:
            on_prompt(prompt)
        if open_browser:
            try:
                webbrowser.open(prompt.verification_url)
            except Exception:
                pass
        deadline = self.now() + prompt.expires_in_seconds
        interval = prompt.interval_seconds
        while self.now() < deadline:
            sleep(interval)
            try:
                result = self.poll_authorization(prompt)
            except DriveApiError:
                interval = min(60, max(prompt.interval_seconds, interval * 2))
                continue
            if result == "authorized":
                return prompt
            if result == "slow_down":
                interval += 5
        raise DriveAuthError("Google Drive 设备授权码已过期。")

    def access_token(self) -> str:
        data = self.store.load()
        token = str(data.get("access_token", "")).strip()
        expires_at = int(data.get("expires_at_ms", 0) or 0)
        if token and expires_at - int(self.now() * 1000) > 60_000:
            return token
        refresh_token = str(data.get("refresh_token", "")).strip()
        if not refresh_token:
            raise DriveAuthorizationRequired("请先连接 Google Drive。")
        client_id, client_secret = self._client()
        response = self._post_form(
            self.token_url,
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if response.status >= 400:
            payload = self._decode_json(response.body)
            if payload.get("error") == "invalid_grant":
                self.store.clear_tokens()
            raise DriveAuthError(
                str(payload.get("error_description") or payload.get("error") or "Google Drive 令牌刷新失败。")
            )
        payload = self._decode_json(response.body)
        self._save_token_payload(payload)
        return str(payload["access_token"])

    def disconnect(self) -> None:
        self.store.clear_tokens()

    def clear_access_token(self, token: str) -> None:
        self.store.clear_access_token(token)

    def _client(self) -> tuple[str, str]:
        data = self.store.load()
        client_id = str(data.get("client_id", "")).strip()
        client_secret = str(data.get("client_secret", "")).strip()
        if not client_id or not client_secret:
            raise DriveAuthorizationRequired("请先配置 Google OAuth Client ID 和 Client Secret。")
        return client_id, client_secret

    def _post_form(self, url: str, values: dict[str, str]) -> HttpResponse:
        return self.transport(
            "POST",
            url,
            {"Content-Type": "application/x-www-form-urlencoded"},
            urlencode(values).encode("utf-8"),
            15.0,
        )

    def _json_response(self, response: HttpResponse, fallback: str) -> dict[str, object]:
        payload = self._decode_json(response.body)
        if response.status >= 400:
            raise DriveAuthError(
                str(payload.get("error_description") or payload.get("error") or fallback)
            )
        return payload

    @staticmethod
    def _decode_json(body: bytes) -> dict[str, object]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_token_payload(self, payload: dict[str, object]) -> None:
        access_token = str(payload.get("access_token", "")).strip()
        if not access_token:
            raise DriveAuthError("Google 没有返回 access token。")
        current = self.store.load()
        current["access_token"] = access_token
        current["expires_at_ms"] = int(self.now() * 1000) + int(payload.get("expires_in", 3600)) * 1000
        refresh_token = str(payload.get("refresh_token", "")).strip()
        if refresh_token:
            current["refresh_token"] = refresh_token
        self.store.save(current)


class GoogleDriveClient:
    def __init__(
        self,
        authorizer: GoogleDeviceCodeAuthorizer,
        transport: Transport = urllib_transport,
        api_url: str = DRIVE_API_URL,
        upload_url: str = DRIVE_UPLOAD_URL,
    ) -> None:
        self.authorizer = authorizer
        self.transport = transport
        self.api_url = api_url.rstrip("/")
        self.upload_url = upload_url.rstrip("/")

    def find_root_folder(self) -> str:
        query = (
            f"trashed=false and 'root' in parents and mimeType='{FOLDER_MIME_TYPE}' "
            f"and name='{self._query_literal(TTU_ROOT)}'"
        )
        files = self.list_files(query, "files(id,name)")
        return files[0].id if files else self.create_folder(TTU_ROOT, "root")

    def ensure_book_folder(self, book_title: str, root_folder_id: str) -> str:
        from .sync import sanitize_ttu_filename

        title = sanitize_ttu_filename(book_title)
        query = (
            f"trashed=false and '{self._query_literal(root_folder_id)}' in parents and "
            f"mimeType='{FOLDER_MIME_TYPE}' and name='{self._query_literal(title)}'"
        )
        files = self.list_files(query, "files(id,name)")
        return files[0].id if files else self.create_folder(title, root_folder_id)

    def list_books(self, root_folder_id: str) -> list[DriveFile]:
        query = (
            f"trashed=false and '{self._query_literal(root_folder_id)}' in parents "
            f"and mimeType='{FOLDER_MIME_TYPE}'"
        )
        return self.list_files(query, "nextPageToken,files(id,name,thumbnailLink)")

    def list_sync_files(self, folder_id: str) -> DriveSyncFiles:
        query = (
            f"trashed=false and '{self._query_literal(folder_id)}' in parents "
            f"and mimeType != '{FOLDER_MIME_TYPE}'"
        )
        files = self.list_files(query, "nextPageToken,files(id,name,parents,thumbnailLink)")
        return DriveSyncFiles(
            book_data=self._latest(files, "bookdata_", 4),
            cover=next((item for item in files if item.name.startswith("cover_")), None),
            progress=self._latest(files, "progress_", 3),
            statistics=self._latest(files, "statistics_", 3),
            audio_book=self._latest(files, "audioBook_", 3),
        )

    def list_files(self, query: str, fields: str) -> list[DriveFile]:
        files: list[DriveFile] = []
        page_token: str | None = None
        while True:
            values = {"q": query, "fields": fields}
            if page_token:
                values["pageToken"] = page_token
            response = self._request("GET", f"{self.api_url}/files?{urlencode(values)}")
            payload = self._decode_json_response(response)
            for item in payload.get("files", []):
                if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
                    continue
                files.append(
                    DriveFile(
                        id=str(item["id"]),
                        name=str(item["name"]),
                        parents=tuple(str(parent) for parent in item.get("parents", []) if parent),
                        thumbnail_link=str(item["thumbnailLink"]) if item.get("thumbnailLink") else None,
                    )
                )
            page_token = str(payload.get("nextPageToken", "")).strip() or None
            if page_token is None:
                return files

    def create_folder(self, name: str, parent_id: str) -> str:
        payload = json.dumps(
            {"name": name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]},
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._request(
            "POST",
            f"{self.api_url}/files?fields=id",
            body=payload,
            content_type="application/json",
        )
        data = self._decode_json_response(response)
        if not data.get("id"):
            raise DriveApiError("Google Drive 创建目录后没有返回文件 ID。")
        return str(data["id"])

    def download_bytes(self, file_id: str) -> bytes:
        response = self._request(
            "GET",
            f"{self.api_url}/files/{quote(file_id, safe='')}?alt=media",
        )
        return response.body

    def download_json(self, file_id: str) -> object:
        try:
            return json.loads(self.download_bytes(file_id).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DriveApiError("Google Drive 同步文件不是有效 JSON。") from error

    def upload_json(
        self,
        folder_id: str,
        file_id: str | None,
        name: str,
        payload: object,
    ) -> None:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.upload_file(folder_id, file_id, name, content, "application/json")

    def upload_file(
        self,
        folder_id: str,
        file_id: str | None,
        name: str,
        content: bytes,
        content_type: str,
    ) -> None:
        boundary = f"hoshi-{uuid.uuid4().hex}"
        metadata: dict[str, object] = {"name": name}
        if file_id is None:
            metadata["parents"] = [folder_id]
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8")
            + json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            + f"\r\n--{boundary}\r\nContent-Type: {content_type}\r\n\r\n".encode("utf-8")
            + content
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        if file_id is None:
            url = f"{self.upload_url}/files?uploadType=multipart"
            method = "POST"
        else:
            url = f"{self.upload_url}/files/{quote(file_id, safe='')}?uploadType=multipart"
            method = "PATCH"
        self._request(
            method,
            url,
            body=body,
            content_type=f"multipart/related; boundary={boundary}",
        )

    def trash_file(self, file_id: str) -> None:
        self._request(
            "PATCH",
            f"{self.api_url}/files/{quote(file_id, safe='')}?fields=id,trashed",
            body=b'{"trashed":true}',
            content_type="application/json",
        )

    def _request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        content_type: str | None = None,
        retry: bool = True,
    ) -> HttpResponse:
        token = self.authorizer.access_token()
        headers = {"Authorization": f"Bearer {token}"}
        if content_type:
            headers["Content-Type"] = content_type
        response = self.transport(method, url, headers, body, 30.0)
        if response.status == 401 and retry:
            self.authorizer.clear_access_token(token)
            return self._request(method, url, body, content_type, retry=False)
        if response.status >= 400:
            raise DriveApiError(self._error_message(response), response.status)
        return response

    @staticmethod
    def _decode_json_response(response: HttpResponse) -> dict[str, object]:
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DriveApiError("Google Drive 返回了无效 JSON。", response.status) from error
        if not isinstance(payload, dict):
            raise DriveApiError("Google Drive 返回格式错误。", response.status)
        return payload

    @staticmethod
    def _error_message(response: HttpResponse) -> str:
        try:
            payload = json.loads(response.body.decode("utf-8"))
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if isinstance(error, str):
                return error
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return f"Google Drive 请求失败，HTTP {response.status}。"

    @staticmethod
    def _query_literal(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    @staticmethod
    def _latest(files: list[DriveFile], prefix: str, timestamp_index: int) -> DriveFile | None:
        candidates = [item for item in files if item.name.startswith(prefix)]
        if not candidates:
            return None

        def timestamp(item: DriveFile) -> int:
            try:
                return int(item.name.split("_")[timestamp_index])
            except (IndexError, ValueError):
                return -1

        return max(candidates, key=timestamp)
