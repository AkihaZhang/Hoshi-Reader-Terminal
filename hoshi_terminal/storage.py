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
from .anki import DEFAULT_LAPIS_FIELD_MAPPINGS, DEFAULT_LAPIS_FIELD_ORDER
from .audio import DEFAULT_LOCAL_AUDIO_PATH, DEFAULT_LOCAL_AUDIO_SOURCE_CONFIG_PATH, default_audio_sources_json


APP_NAME = "HoshiReaderTerminal"
DEFAULT_DICTIONARY_PATH = Path.home() / "Documents" / "辞書"
DEFAULT_SYNC_PATH = Path.home() / "Documents" / "HoshiReaderTerminalSync"


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
    progress_modified_at: int = 0

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
            progress_modified_at=_progress_modified_at(data),
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
    def shelves(self) -> list[dict[str, object]]:
        raw = self._state.setdefault("shelves", [])
        if not isinstance(raw, list):
            raw = []
            self._state["shelves"] = raw
        shelves: list[dict[str, object]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            book_ids = item.get("book_ids", item.get("bookIds", []))
            if not isinstance(book_ids, list):
                book_ids = []
            shelves.append({"name": name, "book_ids": [str(book_id) for book_id in book_ids]})
        return shelves

    @property
    def settings(self) -> dict[str, str]:
        raw = self._state.setdefault("settings", {})
        if not isinstance(raw, dict):
            raw = {}
            self._state["settings"] = raw
        raw.setdefault("dictionary_path", str(DEFAULT_DICTIONARY_PATH))
        raw.setdefault("book_path", str(Path.cwd()))
        raw.setdefault("sync_path", str(DEFAULT_SYNC_PATH))
        raw.setdefault("sync_provider", "google_drive")
        if raw.get("sync_provider") not in {"google_drive", "local"}:
            raw["sync_provider"] = "google_drive"
        raw.setdefault("sync_statistics", "true")
        raw.setdefault("sync_statistics_mode", "merge")
        if raw.get("sync_statistics_mode") not in {"merge", "replace"}:
            raw["sync_statistics_mode"] = "merge"
        raw.setdefault("sync_audiobook", "true")
        raw.setdefault("sync_upload_books", "true")
        raw.setdefault("ankiconnect_url", "http://127.0.0.1:8765")
        if raw.get("anki_template_version") != "lapis-v1":
            if raw.get("anki_deck", "Hoshi Reader Terminal") == "Hoshi Reader Terminal":
                raw["anki_deck"] = "Mining"
            if raw.get("anki_model", "Basic") == "Basic":
                raw["anki_model"] = "Lapis"
            raw["anki_field_mappings"] = json.dumps(DEFAULT_LAPIS_FIELD_MAPPINGS, ensure_ascii=False)
            raw["anki_template_version"] = "lapis-v1"
        raw.setdefault("anki_deck", "Mining")
        raw.setdefault("anki_model", "Lapis")
        raw.setdefault("anki_front_field", "Front")
        raw.setdefault("anki_back_field", "Back")
        raw.setdefault("anki_field_mappings", json.dumps(DEFAULT_LAPIS_FIELD_MAPPINGS, ensure_ascii=False))
        raw.setdefault("anki_tag", "hoshi")
        raw.setdefault("anki_mode", "both")
        raw.setdefault("anki_allow_duplicates", "false")
        raw.setdefault("anki_duplicate_scope", "collection")
        if raw.get("anki_duplicate_scope") not in {"collection", "deck", "deckroot"}:
            raw["anki_duplicate_scope"] = "collection"
        raw.setdefault("anki_check_all_models", "false")
        raw.setdefault("anki_force_sync", "false")
        raw.setdefault("audio_sources", default_audio_sources_json())
        raw.setdefault("audio_enable_local", "false")
        raw.setdefault("audio_local_db_path", str(self.root / DEFAULT_LOCAL_AUDIO_PATH))
        raw.setdefault("audio_local_source_config_path", str(self.root / DEFAULT_LOCAL_AUDIO_SOURCE_CONFIG_PATH))
        raw.setdefault("reader_vertical", "false")
        raw.setdefault("reader_width", "0")
        raw.setdefault("reader_lines", "0")
        raw.setdefault("bookshelf_show_reading", "false")
        raw.setdefault("bookshelf_sort", "recent")
        if raw.get("bookshelf_sort") not in {"recent", "title"}:
            raw["bookshelf_sort"] = "recent"
        raw.setdefault("dictionary_max_results", "16")
        raw.setdefault("dictionary_scan_length", "16")
        raw.setdefault("sasayaki_seek_step", "5")
        raw.setdefault("language", "zh")
        if raw.get("language") not in {"zh", "en"}:
            raw["language"] = "zh"
        return {str(key): str(value) for key, value in raw.items()}

    def set_setting(self, key: str, value: str | Path) -> None:
        settings = self._state.setdefault("settings", {})
        if key in {"book_path", "dictionary_path", "sync_path", "audio_local_db_path", "audio_local_source_config_path"}:
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
        imported, skipped, failed = self.import_books_detailed(paths)
        if failed:
            path, message = failed[0]
            raise RuntimeError(f"{path}: {message}")
        return imported, skipped

    def import_books_detailed(self, paths: list[Path]) -> tuple[list[BookRecord], list[Path], list[tuple[Path, str]]]:
        imported: list[BookRecord] = []
        skipped: list[Path] = []
        failed: list[tuple[Path, str]] = []
        known_sources = {book.source_path for book in self.books}
        for path in paths:
            source = path.expanduser().resolve()
            if str(source) in known_sources:
                skipped.append(source)
                continue
            try:
                record = self.import_book(source)
            except Exception as exc:
                failed.append((source, str(exc)))
                continue
            else:
                imported.append(record)
                known_sources.add(str(source))
        return imported, skipped, failed

    def rename_book(self, book_id: str, title: str) -> bool:
        title = title.strip()
        if not title:
            return False
        for item in self._state.setdefault("books", []):
            if item.get("id") == book_id:
                old_title = str(item.get("title", ""))
                item["title"] = title
                item["last_access"] = _now()
                for highlight in self._state.setdefault("highlights", []):
                    if highlight.get("book_id") == book_id or highlight.get("title") == old_title:
                        highlight["title"] = title
                for statistic in self._state.setdefault("statistics", []):
                    if statistic.get("title") == old_title:
                        statistic["title"] = title
                self._save_state()
                return True
        return False

    def delete_book(self, book_id: str) -> bool:
        books = self._state.setdefault("books", [])
        remaining: list[dict[str, object]] = []
        removed: dict[str, object] | None = None
        for item in books:
            if item.get("id") == book_id:
                removed = item
            else:
                remaining.append(item)
        if removed is None:
            return False
        self._state["books"] = remaining
        self._state["highlights"] = [
            item for item in self._state.setdefault("highlights", []) if item.get("book_id") != book_id
        ]
        sasayaki = self._state.setdefault("sasayaki", {})
        if isinstance(sasayaki, dict):
            sasayaki.pop(book_id, None)
        for shelf in self._state.setdefault("shelves", []):
            if isinstance(shelf, dict):
                book_ids = shelf.get("book_ids", shelf.get("bookIds", []))
                if isinstance(book_ids, list):
                    shelf["book_ids"] = [item for item in book_ids if item != book_id]
        stored_path = Path(str(removed.get("stored_path", ""))).expanduser()
        if stored_path.exists() and stored_path.is_file():
            stored_path.unlink()
        self._save_state()
        return True

    def mark_book_read(self, book_id: str) -> bool:
        for item in self._state.setdefault("books", []):
            if item.get("id") != book_id:
                continue
            record = BookRecord.from_dict(item)
            try:
                _, text = self.load_record_text(record)
            except Exception:
                total = max(int(item.get("position", 0)), int(item.get("characters_read", 0)))
            else:
                total = character_count(text)
            item["position"] = total
            item["characters_read"] = max(total, int(item.get("characters_read", 0)))
            item["last_access"] = _now()
            self._save_state()
            return True
        return False

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
        return record.title or extracted.title, extracted.text

    def touch_progress(self, record: BookRecord, position: int, characters_delta: int, seconds: float) -> None:
        books = self._state.setdefault("books", [])
        for item in books:
            if item.get("id") == record.id:
                item["position"] = max(0, position)
                item["characters_read"] = int(item.get("characters_read", 0)) + max(0, characters_delta)
                item["last_access"] = _now()
                item["progress_modified_at"] = int(time.time() * 1000)
                break
        self.add_statistic(record.title, characters_delta, seconds)
        self._save_state()

    def update_book_progress(self, book_id: str, position: int, timestamp_ms: int | None = None) -> None:
        books = self._state.setdefault("books", [])
        for item in books:
            if item.get("id") == book_id:
                item["position"] = max(0, int(position))
                item["last_access"] = _from_unix_ms(timestamp_ms) if timestamp_ms else _now()
                item["progress_modified_at"] = int(timestamp_ms or time.time() * 1000)
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

    def replace_statistics_for_title(self, title: str, statistics: list[DailyStatistic]) -> None:
        retained = [
            item
            for item in self._state.setdefault("statistics", [])
            if str(item.get("title", "")) != title
        ]
        retained.extend(asdict(item) for item in statistics if item.title == title)
        self._state["statistics"] = retained
        self._save_state()

    def add_highlight(self, record: BookRecord, text: str, note: str, position: int = 0, color: str = "yellow") -> None:
        highlights = self._state.setdefault("highlights", [])
        highlights.append(
            {
                "book_id": record.id,
                "title": record.title,
                "text": text[:500],
                "note": note,
                "position": max(0, int(position)),
                "color": color,
                "created_at": _now(),
            }
        )
        self._save_state()

    def highlights_for(self, record: BookRecord) -> list[dict[str, object]]:
        return [
            item
            for item in self._state.setdefault("highlights", [])
            if isinstance(item, dict) and (item.get("book_id") == record.id or item.get("title") == record.title)
        ]

    def create_shelf(self, name: str) -> bool:
        cleaned = name.strip()
        if not cleaned:
            return False
        shelves = self.shelves
        if any(str(shelf.get("name")) == cleaned for shelf in shelves):
            return False
        shelves.append({"name": cleaned, "book_ids": []})
        self._state["shelves"] = shelves
        self._save_state()
        return True

    def delete_shelf(self, name: str) -> bool:
        cleaned = name.strip()
        shelves = self.shelves
        next_shelves = [shelf for shelf in shelves if str(shelf.get("name")) != cleaned]
        if len(next_shelves) == len(shelves):
            return False
        self._state["shelves"] = next_shelves
        self._save_state()
        return True

    def move_shelf(self, from_index: int, to_index: int) -> bool:
        shelves = self.shelves
        if from_index < 0 or from_index >= len(shelves):
            return False
        shelf = shelves.pop(from_index)
        shelves.insert(max(0, min(to_index, len(shelves))), shelf)
        self._state["shelves"] = shelves
        self._save_state()
        return True

    def move_book_to_shelf(self, book_id: str, shelf_name: str | None) -> bool:
        if not any(book.id == book_id for book in self.books):
            return False
        cleaned = shelf_name.strip() if shelf_name else None
        shelves = self.shelves
        for shelf in shelves:
            book_ids = [item for item in shelf.get("book_ids", []) if item != book_id]
            shelf["book_ids"] = book_ids
        if cleaned:
            target = next((shelf for shelf in shelves if shelf.get("name") == cleaned), None)
            if target is None:
                target = {"name": cleaned, "book_ids": []}
                shelves.append(target)
            book_ids = list(target.get("book_ids", []))
            if book_id not in book_ids:
                book_ids.append(book_id)
            target["book_ids"] = book_ids
        self._state["shelves"] = shelves
        self._save_state()
        return True

    def shelf_for(self, book_id: str) -> str | None:
        for shelf in self.shelves:
            if book_id in shelf.get("book_ids", []):
                return str(shelf.get("name"))
        return None

    def sasayaki_for(self, record: BookRecord) -> dict[str, object] | None:
        records = self._state.setdefault("sasayaki", {})
        if not isinstance(records, dict):
            return None
        item = records.get(record.id)
        return item if isinstance(item, dict) else None

    def set_sasayaki(self, record: BookRecord, data: dict[str, object]) -> None:
        records = self._state.setdefault("sasayaki", {})
        if not isinstance(records, dict):
            records = {}
            self._state["sasayaki"] = records
        records[record.id] = data
        self._save_state()

    def mine_card(self, word: str, sentence: str = "", note: str = "", fields: dict[str, str] | None = None) -> Path:
        fields = fields or {
            "Expression": word,
            "MainDefinition": note,
            "Sentence": sentence,
            "IsWordAndSentenceCard": "x",
        }
        header = [field for field in DEFAULT_LAPIS_FIELD_ORDER if field in fields]
        header += [field for field in fields if field not in header]
        header += ["CreatedAt", "Source"]
        target = self._card_csv_for_header(header)
        exists = target.exists()
        with target.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if not exists:
                writer.writerow(header)
            writer.writerow([fields.get(field, "") for field in header[:-2]] + [_now(), "Hoshi Reader Terminal"])
        return target

    def _card_csv_for_header(self, header: list[str]) -> Path:
        if not self.cards_file.exists():
            return self.cards_file
        try:
            with self.cards_file.open("r", encoding="utf-8", newline="") as handle:
                existing = next(csv.reader(handle), [])
        except (OSError, StopIteration):
            return self.cards_file
        if existing == header:
            return self.cards_file
        if existing == ["word", "sentence", "note", "created_at", "source"]:
            return self.cards_file.with_name("mined_cards_lapis.csv")
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
        state.setdefault("shelves", [])
        state.setdefault("sasayaki", {})
        state.setdefault("settings", {})
        return state

    def _save_state(self) -> None:
        with self.state_file.open("w", encoding="utf-8") as handle:
            json.dump(self._state, handle, ensure_ascii=False, indent=2)


def _progress_modified_at(data: dict[str, object]) -> int:
    stored = int(data.get("progress_modified_at", 0) or 0)
    if stored > 0 or int(data.get("position", 0) or 0) <= 0:
        return stored
    try:
        return int(datetime.fromisoformat(str(data.get("last_access", ""))).timestamp() * 1000)
    except ValueError:
        return 0


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
