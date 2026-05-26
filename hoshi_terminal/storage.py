from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import csv
import json
import os
import platform
import shutil
import time
import uuid

from .epub import extract_book
from .reader import character_count


APP_NAME = "HoshiReaderTerminal"
DEFAULT_DICTIONARY_PATH = Path.home() / "Documents" / "辞書"
DEFAULT_SYNC_PATH = Path.home() / "Documents" / "HoshiReaderTerminalSync"
PROJECT_BOOK_PATH = Path("/Users/akihazhang/Documents/Codex/2026-05-26/https-github-com-manhhao-hoshi-reader/Hoshi-Reader-Terminal")


@dataclass
class BookRecord:
    id: str
    title: str
    source_path: str
    stored_path: str
    kind: str
    created_at: str
    last_access: str
    position: int = 0
    characters_read: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "BookRecord":
        return cls(
            id=str(data["id"]),
            title=str(data["title"]),
            source_path=str(data.get("source_path", "")),
            stored_path=str(data["stored_path"]),
            kind=str(data.get("kind", "")),
            created_at=str(data.get("created_at", "")),
            last_access=str(data.get("last_access", "")),
            position=int(data.get("position", 0)),
            characters_read=int(data.get("characters_read", 0)),
        )


@dataclass
class DailyStatistic:
    title: str
    date_key: str
    characters_read: int = 0
    reading_time: float = 0.0
    min_reading_speed: int = 0
    alt_min_reading_speed: int = 0
    last_reading_speed: int = 0
    max_reading_speed: int = 0
    last_statistic_modified: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "DailyStatistic":
        return cls(
            title=str(data["title"]),
            date_key=str(data["date_key"]),
            characters_read=int(data.get("characters_read", 0)),
            reading_time=float(data.get("reading_time", 0.0)),
            min_reading_speed=int(data.get("min_reading_speed", 0)),
            alt_min_reading_speed=int(data.get("alt_min_reading_speed", 0)),
            last_reading_speed=int(data.get("last_reading_speed", 0)),
            max_reading_speed=int(data.get("max_reading_speed", 0)),
            last_statistic_modified=int(data.get("last_statistic_modified", 0)),
        )


class Library:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir()
        self.books_dir = self.root / "books"
        self.state_file = self.root / "library.json"
        self.dictionary_file = self.root / "dictionaries.json"
        self.cards_file = self.root / "mined_cards.csv"
        self.root.mkdir(parents=True, exist_ok=True)
        self.books_dir.mkdir(parents=True, exist_ok=True)
        self._state = self._load_state()

    @property
    def books(self) -> list[BookRecord]:
        return [BookRecord.from_dict(item) for item in self._state.get("books", [])]

    @property
    def statistics(self) -> list[DailyStatistic]:
        return [DailyStatistic.from_dict(item) for item in self._state.get("statistics", [])]

    @property
    def settings(self) -> dict[str, str]:
        raw = self._state.setdefault("settings", {})
        if not isinstance(raw, dict):
            raw = {}
            self._state["settings"] = raw
        raw.setdefault("dictionary_path", str(DEFAULT_DICTIONARY_PATH))
        raw.setdefault("book_path", str(PROJECT_BOOK_PATH if PROJECT_BOOK_PATH.exists() else Path.cwd()))
        raw.setdefault("sync_path", str(DEFAULT_SYNC_PATH))
        raw.setdefault("ankiconnect_url", "http://127.0.0.1:8765")
        raw.setdefault("anki_deck", "Hoshi Reader Terminal")
        raw.setdefault("anki_model", "Basic")
        raw.setdefault("anki_front_field", "Front")
        raw.setdefault("anki_back_field", "Back")
        raw.setdefault("anki_tag", "hoshi-terminal")
        raw.setdefault("anki_mode", "both")
        raw.setdefault("reader_vertical", "false")
        return {str(key): str(value) for key, value in raw.items()}

    def set_setting(self, key: str, value: str | Path) -> None:
        settings = self._state.setdefault("settings", {})
        if key in {"book_path", "dictionary_path", "sync_path"}:
            settings[key] = str(Path(value).expanduser())
        else:
            settings[key] = str(value)
        self._save_state()

    def import_book(self, path: str | Path, title: str | None = None) -> BookRecord:
        source = Path(path).expanduser().resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        extracted = extract_book(source)
        book_id = str(uuid.uuid4())[:8]
        suffix = source.suffix.lower() or ".txt"
        stored = self.books_dir / f"{book_id}{suffix}"
        shutil.copy2(source, stored)
        now = _now()
        record = BookRecord(
            id=book_id,
            title=title or extracted.title,
            source_path=str(source),
            stored_path=str(stored),
            kind=suffix.lstrip("."),
            created_at=now,
            last_access=now,
        )
        self._state.setdefault("books", []).append(asdict(record))
        self._save_state()
        return record

    def import_books(self, paths: list[Path]) -> tuple[list[BookRecord], list[Path]]:
        imported: list[BookRecord] = []
        skipped: list[Path] = []
        known_sources = {book.source_path for book in self.books}
        for path in paths:
            source = path.expanduser().resolve()
            if str(source) in known_sources:
                skipped.append(source)
                continue
            record = self.import_book(source)
            imported.append(record)
            known_sources.add(str(source))
        return imported, skipped

    def find_book(self, query: str | None) -> BookRecord | None:
        books = self.books
        if not books:
            return None
        if query is None:
            return max(books, key=lambda book: book.last_access)
        lowered = query.lower()
        for book in books:
            if book.id.startswith(lowered):
                return book
        exact = [book for book in books if book.title.lower() == lowered]
        if exact:
            return exact[0]
        fuzzy = [book for book in books if lowered in book.title.lower()]
        if fuzzy:
            return fuzzy[0]
        return None

    def load_record_text(self, record: BookRecord) -> tuple[str, str]:
        extracted = extract_book(Path(record.stored_path))
        return extracted.title or record.title, extracted.text

    def touch_progress(self, record: BookRecord, position: int, characters_delta: int, seconds: float) -> None:
        books = self._state.setdefault("books", [])
        for item in books:
            if item.get("id") == record.id:
                item["position"] = max(0, position)
                item["characters_read"] = int(item.get("characters_read", 0)) + max(0, characters_delta)
                item["last_access"] = _now()
                break
        self.add_statistic(record.title, characters_delta, seconds)
        self._save_state()

    def update_book_progress(self, book_id: str, position: int, timestamp_ms: int | None = None) -> None:
        books = self._state.setdefault("books", [])
        for item in books:
            if item.get("id") == book_id:
                item["position"] = max(0, int(position))
                item["last_access"] = _from_unix_ms(timestamp_ms) if timestamp_ms else _now()
                break
        self._save_state()

    def add_statistic(self, title: str, characters_delta: int, seconds: float) -> None:
        if characters_delta <= 0 and seconds <= 0:
            return
        date_key = datetime.now().strftime("%Y-%m-%d")
        stats = self._state.setdefault("statistics", [])
        current = None
        for item in stats:
            if item.get("date_key") == date_key and item.get("title") == title:
                current = item
                break
        if current is None:
            current = asdict(DailyStatistic(title=title, date_key=date_key))
            stats.append(current)
        current["characters_read"] = int(current.get("characters_read", 0)) + max(0, characters_delta)
        current["reading_time"] = float(current.get("reading_time", 0.0)) + max(0.0, seconds)
        minutes = max(float(current["reading_time"]) / 60.0, 1 / 60)
        speed = int(int(current["characters_read"]) / minutes)
        previous_min = int(current.get("min_reading_speed", 0))
        current["last_reading_speed"] = speed
        current["min_reading_speed"] = speed if previous_min == 0 else min(previous_min, speed)
        current["alt_min_reading_speed"] = current["min_reading_speed"]
        current["max_reading_speed"] = max(int(current.get("max_reading_speed", 0)), speed)
        current["last_statistic_modified"] = int(time.time() * 1000)

    def statistics_for_title(self, title: str) -> list[DailyStatistic]:
        return [item for item in self.statistics if item.title == title]

    def merge_statistics(self, statistics: list[DailyStatistic]) -> None:
        if not statistics:
            return
        state_stats = self._state.setdefault("statistics", [])
        by_key: dict[tuple[str, str], dict[str, object]] = {}
        for item in state_stats:
            by_key[(str(item.get("title", "")), str(item.get("date_key", "")))] = item
        for statistic in statistics:
            key = (statistic.title, statistic.date_key)
            existing = by_key.get(key)
            if existing is None:
                item = asdict(statistic)
                state_stats.append(item)
                by_key[key] = item
                continue
            if statistic.last_statistic_modified > int(existing.get("last_statistic_modified", 0)):
                existing.update(asdict(statistic))
        self._save_state()

    def add_highlight(self, record: BookRecord, text: str, note: str) -> None:
        highlights = self._state.setdefault("highlights", [])
        highlights.append(
            {
                "book_id": record.id,
                "title": record.title,
                "text": text[:500],
                "note": note,
                "created_at": _now(),
            }
        )
        self._save_state()

    def mine_card(self, word: str, sentence: str = "", note: str = "") -> Path:
        exists = self.cards_file.exists()
        with self.cards_file.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if not exists:
                writer.writerow(["word", "sentence", "note", "created_at", "source"])
            writer.writerow([word, sentence, note, _now(), "Hoshi Reader Terminal"])
        return self.cards_file

    def _load_state(self) -> dict[str, object]:
        if not self.state_file.exists():
            return {"books": [], "statistics": [], "highlights": []}
        with self.state_file.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            return {"books": [], "statistics": [], "highlights": []}
        state.setdefault("books", [])
        state.setdefault("statistics", [])
        state.setdefault("highlights", [])
        state.setdefault("settings", {})
        return state

    def _save_state(self) -> None:
        with self.state_file.open("w", encoding="utf-8") as handle:
            json.dump(self._state, handle, ensure_ascii=False, indent=2)


def data_dir() -> Path:
    override = os.environ.get("HOSHI_TERMINAL_HOME")
    if override:
        return Path(override).expanduser().resolve()
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "hoshi-reader-terminal"
    return Path.home() / ".local" / "share" / "hoshi-reader-terminal"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _from_unix_ms(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000).isoformat(timespec="seconds")


def summarize_text_progress(position: int, text: str) -> str:
    total = max(1, character_count(text))
    percent = min(100.0, max(0.0, position / total * 100))
    return f"{percent:5.1f}%"
