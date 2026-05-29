from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib import parse, request
from urllib.error import URLError
import hashlib
import json
import mimetypes
import sqlite3


DEFAULT_AUDIO_SOURCE_URL = "https://hoshi-reader.manhhaoo-do.workers.dev/?term={term}&reading={reading}"
LOCAL_AUDIO_URL = "http://localhost:8765/localaudio/get/?term={term}&reading={reading}"
LOCAL_AUDIO_SCHEME = "hoshi-local-audio"
DEFAULT_LOCAL_AUDIO_PATH = "Audio/android.db"
DEFAULT_LOCAL_AUDIO_SOURCES = [
    "nhk16",
    "daijisen",
    "shinmeikai8",
    "jpod",
    "jpod_alternate",
    "taas",
    "ozk5",
    "forvo",
    "forvo_ext",
    "forvo_ext2",
]


@dataclass(frozen=True)
class AudioSource:
    name: str
    url: str
    enabled: bool = True
    is_default: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "url": self.url, "enabled": self.enabled, "isDefault": self.is_default}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AudioSource":
        return cls(
            name=str(data.get("name", "")),
            url=str(data.get("url", "")),
            enabled=bool(data.get("enabled", data.get("isEnabled", True))),
            is_default=bool(data.get("isDefault", False)),
        )


@dataclass(frozen=True)
class LocalAudioEntry:
    source: str
    expression: str
    reading: str
    file: str


@dataclass(frozen=True)
class LocalAudioFile:
    source: str
    file: str


@dataclass(frozen=True)
class AudioAsset:
    filename: str
    data: bytes
    mime_type: str
    source: str


def default_audio_sources_json() -> str:
    return json.dumps([default_audio_source().to_dict()], ensure_ascii=False)


def default_audio_source() -> AudioSource:
    return AudioSource(name="Default", url=DEFAULT_AUDIO_SOURCE_URL, enabled=True, is_default=True)


def audio_sources_from_settings(settings: dict[str, str]) -> list[AudioSource]:
    raw = settings.get("audio_sources", "")
    if raw:
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            sources = [AudioSource.from_dict(item) for item in decoded if isinstance(item, dict)]
            sources = [source for source in sources if source.name and source.url]
            if sources:
                return sources
    return [default_audio_source()]


def expand_audio_template(template: str, term: str, reading: str) -> str:
    return template.replace("{term}", _url_encode(term)).replace("{reading}", _url_encode(reading))


def resolve_word_audio(term: str, reading: str, settings: dict[str, str], data_root: Path, timeout: float = 4.0) -> AudioAsset | None:
    if settings.get("audio_enable_local", "false").lower() == "true":
        local = LocalAudioRepository(Path(settings.get("audio_local_db_path") or data_root / DEFAULT_LOCAL_AUDIO_PATH))
        asset = local.resolve_asset(term, reading)
        if asset is not None:
            return asset
    for source in audio_sources_from_settings(settings):
        if not source.enabled:
            continue
        asset = _resolve_remote_source(source, term, reading, data_root, timeout=timeout)
        if asset is not None:
            return asset
    return None


class LocalAudioRepository:
    def __init__(self, db_file: str | Path) -> None:
        self.db_file = Path(db_file).expanduser()

    def resolve_asset(self, term: str, reading: str) -> AudioAsset | None:
        entry = self.find_audio(term, reading)
        if entry is None:
            return None
        data = self.load_audio(LocalAudioFile(source=entry.source, file=entry.file))
        if data is None:
            return None
        return AudioAsset(
            filename=_audio_filename(data, entry.file),
            data=data,
            mime_type=mime_type_for_path(entry.file),
            source=f"local:{entry.source}",
        )

    def find_audio(self, term: str, reading: str) -> LocalAudioEntry | None:
        if not self.db_file.is_file():
            return None
        normalized_reading = katakana_to_hiragana(reading)
        rows: list[LocalAudioEntry] = []
        try:
            with sqlite3.connect(self.db_file) as db:
                if normalized_reading:
                    cursor = db.execute(
                        """
                        SELECT source, expression, reading, file
                        FROM entries
                        WHERE (expression = ? OR reading = ?) AND lower(file) LIKE '%.mp3'
                        """,
                        (term, normalized_reading),
                    )
                else:
                    cursor = db.execute(
                        """
                        SELECT source, expression, reading, file
                        FROM entries
                        WHERE expression = ? AND lower(file) LIKE '%.mp3'
                        """,
                        (term,),
                    )
                rows = [
                    LocalAudioEntry(
                        source=str(row[0]),
                        expression=str(row[1]),
                        reading=str(row[2] or ""),
                        file=str(row[3]),
                    )
                    for row in cursor.fetchall()
                ]
        except sqlite3.Error:
            return None
        return resolve_local_audio(term, normalized_reading, rows)

    def load_audio(self, audio_file: LocalAudioFile) -> bytes | None:
        if not self.db_file.is_file():
            return None
        try:
            with sqlite3.connect(self.db_file) as db:
                row = db.execute(
                    "SELECT data FROM android WHERE source = ? AND file = ? LIMIT 1",
                    (audio_file.source, audio_file.file),
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        data = row[0]
        return bytes(data) if data is not None else None


def resolve_local_audio(term: str, reading: str, rows: list[LocalAudioEntry]) -> LocalAudioEntry | None:
    normalized_reading = katakana_to_hiragana(reading)

    def sort_key(entry: LocalAudioEntry) -> tuple[int, int]:
        reading_rank = 0 if normalized_reading and entry.reading == normalized_reading else 1
        try:
            source_rank = DEFAULT_LOCAL_AUDIO_SOURCES.index(entry.source)
        except ValueError:
            source_rank = 2**31 - 1
        return reading_rank, source_rank

    candidates = [
        row
        for row in rows
        if (row.expression == term or (row.reading and row.reading == normalized_reading))
        and row.file.lower().endswith(".mp3")
    ]
    return sorted(candidates, key=sort_key)[0] if candidates else None


def local_audio_url(source: str, file: str) -> str:
    return f"{LOCAL_AUDIO_SCHEME}://{_url_encode(source)}/{_url_encode(file)}"


def parse_local_audio_url(url: str) -> LocalAudioFile | None:
    prefix = f"{LOCAL_AUDIO_SCHEME}://"
    if not url.startswith(prefix):
        return None
    tail = url[len(prefix) :]
    source, separator, file = tail.partition("/")
    if not separator or not source or not file:
        return None
    return LocalAudioFile(source=parse.unquote(source), file=parse.unquote(file))


def katakana_to_hiragana(text: str) -> str:
    return "".join(chr(ord(char) - 0x60) if "\u30a1" <= char <= "\u30f6" else char for char in text)


def mime_type_for_path(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    if guessed:
        return guessed
    suffix = Path(path).suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix in {".m4a", ".m4b"}:
        return "audio/mp4"
    if suffix == ".aac":
        return "audio/aac"
    if suffix == ".wav":
        return "audio/wav"
    return "application/octet-stream"


def _resolve_remote_source(
    source: AudioSource,
    term: str,
    reading: str,
    data_root: Path,
    timeout: float,
) -> AudioAsset | None:
    url = expand_audio_template(source.url, term, reading)
    local_file = parse_local_audio_url(url)
    if local_file is not None:
        data = LocalAudioRepository(data_root / DEFAULT_LOCAL_AUDIO_PATH).load_audio(local_file)
        if data is None:
            return None
        return AudioAsset(_audio_filename(data, local_file.file), data, mime_type_for_path(local_file.file), source.name)

    body, content_type = _fetch_bytes(url, timeout=timeout)
    if body is None:
        return None
    listed = _audio_urls_from_response(body)
    if listed:
        for audio_url in listed:
            local_file = parse_local_audio_url(audio_url)
            if local_file is not None:
                data = LocalAudioRepository(data_root / DEFAULT_LOCAL_AUDIO_PATH).load_audio(local_file)
                if data is not None:
                    return AudioAsset(_audio_filename(data, local_file.file), data, mime_type_for_path(local_file.file), source.name)
                continue
            audio_body, audio_type = _fetch_bytes(audio_url, timeout=timeout)
            if audio_body:
                return AudioAsset(
                    _audio_filename(audio_body, audio_url),
                    audio_body,
                    audio_type or mime_type_for_path(audio_url),
                    source.name,
                )
        return None
    if content_type and content_type.startswith("audio/"):
        return AudioAsset(_audio_filename(body, url), body, content_type.split(";", 1)[0], source.name)
    return None


def _audio_urls_from_response(body: bytes) -> list[str]:
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, dict):
        return []
    raw_sources = decoded.get("audioSources")
    if not isinstance(raw_sources, list):
        return []
    urls: list[str] = []
    for item in raw_sources:
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            urls.append(str(item["url"]))
    return urls


def _fetch_bytes(url: str, timeout: float) -> tuple[bytes | None, str]:
    try:
        with request.urlopen(url, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.read(), content_type.split(";", 1)[0].strip().lower()
    except (OSError, URLError, ValueError):
        return None, ""


def _audio_filename(data: bytes, source_path: str) -> str:
    digest = hashlib.sha1(data).hexdigest()[:16]
    suffix = Path(parse.urlparse(source_path).path).suffix.lower()
    if suffix not in {".mp3", ".aac", ".m4a", ".m4b", ".wav", ".ogg"}:
        suffix = ".mp3"
    return f"hoshi_audio_{digest}{suffix}"


def _url_encode(value: str) -> str:
    return parse.quote(value, safe="")
