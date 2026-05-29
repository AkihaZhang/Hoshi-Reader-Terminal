from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator
import json
import re
import sqlite3
import textwrap
import zipfile

from .terminal import BOLD, CYAN, DIM, GREEN, MAGENTA, RESET, YELLOW, ansi_enabled, rgb, style


DICTIONARY_TYPES = ("term", "frequency", "pitch")
IMPORT_CHUNK_SIZE = 10_000
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TYPE_LABELS = {
    "term": "Term / 释义",
    "frequency": "Frequency / 频率",
    "pitch": "Pitch / 音高",
}


@dataclass(frozen=True)
class LookupResult:
    term: str
    reading: str
    definitions: list[str]
    dictionary: str
    matched: str
    note: str = ""
    frequencies: list[str] = field(default_factory=list)
    pitches: list[str] = field(default_factory=list)
    definition_tags: list[str] = field(default_factory=list)
    term_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DictionaryInfo:
    id: int
    title: str
    type: str
    source_path: str
    revision: str
    enabled: bool
    priority: int
    entry_count: int


class DictionaryManager:
    def __init__(self, data_file: Path) -> None:
        self.data_file = data_file
        self.db_file = data_file.with_suffix(".sqlite3")
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_legacy_json()

    def import_yomitan(self, path: str | Path) -> int:
        source = Path(path).expanduser()
        if source.is_dir() and not (source / "index.json").exists():
            count = 0
            for candidate in find_yomitan_sources(source):
                if candidate.resolve() == source.resolve():
                    continue
                count += self.import_yomitan(candidate)
            return count

        if source.is_dir() and (source / "index.json").exists():
            return self._import_source(source, _DirectoryReader(source))
        if source.is_file() and source.suffix.lower() == ".zip":
            return self._import_source(source, _ZipReader(source))
        raise ValueError("词典必须是 Yomitan zip 文件或目录")

    def lookup(self, word: str, limit: int = 16, scan_length: int = 16) -> list[LookupResult]:
        needle = word.strip()
        if not needle:
            return []

        candidates: list[tuple[str, str]] = []
        for query, query_note in _lookup_queries(needle, scan_length):
            candidates.append((query, query_note))
            for base, note in deinflect(query):
                if base != query:
                    combined = note if query_note == "exact" else f"{query_note} / {note}"
                    candidates.append((base, combined))

        results: list[LookupResult] = []
        seen: set[tuple[str, str, str]] = set()
        with self._connect() as db:
            for candidate, note in candidates:
                for row in self._lookup_term_rows(db, candidate, limit):
                    key = (str(row["term"]), str(row["reading"]), str(row["dictionary"]))
                    if key in seen:
                        continue
                    seen.add(key)
                    term = str(row["term"])
                    reading = str(row["reading"] or "")
                    results.append(
                        LookupResult(
                            term=term,
                            reading=reading,
                            definitions=json.loads(str(row["definitions"] or "[]")),
                            dictionary=str(row["dictionary"]),
                            matched=candidate,
                            note="" if note == "exact" else note,
                            definition_tags=_split_tags(str(row["definition_tags"] or "")),
                            term_tags=_split_tags(str(row["term_tags"] or "")),
                            frequencies=self._lookup_frequency_rows(db, term, reading),
                            pitches=self._lookup_pitch_rows(db, term, reading),
                        )
                    )
                    if len(results) >= limit:
                        return results

            if not results:
                frequencies = self._lookup_frequency_rows(db, needle, "")
                pitches = self._lookup_pitch_rows(db, needle, "")
                if frequencies or pitches:
                    results.append(
                        LookupResult(
                            term=needle,
                            reading="",
                            definitions=[],
                            dictionary="频率 / 音高",
                            matched=needle,
                            frequencies=frequencies,
                            pitches=pitches,
                        )
                    )
        return results

    def dictionaries(self, dict_type: str | None = None) -> list[DictionaryInfo]:
        where = ""
        params: tuple[object, ...] = ()
        if dict_type:
            where = "WHERE type = ?"
            params = (dict_type,)
        with self._connect() as db:
            rows = db.execute(
                f"""
                SELECT id, title, type, source_path, revision, enabled, priority, entry_count
                FROM dictionaries
                {where}
                ORDER BY type, priority, title COLLATE NOCASE
                """,
                params,
            ).fetchall()
        return [
            DictionaryInfo(
                id=int(row["id"]),
                title=str(row["title"]),
                type=str(row["type"]),
                source_path=str(row["source_path"] or ""),
                revision=str(row["revision"] or ""),
                enabled=bool(row["enabled"]),
                priority=int(row["priority"]),
                entry_count=int(row["entry_count"] or 0),
            )
            for row in rows
        ]

    def entry_count(self) -> int:
        with self._connect() as db:
            row = db.execute("SELECT COALESCE(SUM(entry_count), 0) AS count FROM dictionaries").fetchone()
        return int(row["count"] if row else 0)

    def counts_by_type(self) -> dict[str, int]:
        counts = {dict_type: 0 for dict_type in DICTIONARY_TYPES}
        with self._connect() as db:
            rows = db.execute("SELECT type, COALESCE(SUM(entry_count), 0) AS count FROM dictionaries GROUP BY type").fetchall()
        for row in rows:
            counts[str(row["type"])] = int(row["count"])
        return counts

    def set_enabled(self, dict_id: int, enabled: bool) -> None:
        with self._connect() as db:
            db.execute("UPDATE dictionaries SET enabled = ? WHERE id = ?", (1 if enabled else 0, dict_id))

    def move_dictionary(self, dict_type: str, from_index: int, to_index: int) -> None:
        dict_type = normalize_dictionary_type(dict_type)
        items = self.dictionaries(dict_type)
        if not items or from_index < 0 or from_index >= len(items):
            raise ValueError("词典序号无效")
        moved = items.pop(from_index)
        items.insert(max(0, min(to_index, len(items))), moved)
        with self._connect() as db:
            for priority, item in enumerate(items):
                db.execute("UPDATE dictionaries SET priority = ? WHERE id = ?", (priority, item.id))

    def _import_source(self, source: Path, reader: "_YomitanReader") -> int:
        index = reader.index()
        dictionary_name = str(index.get("title") or index.get("name") or source.stem)
        revision = str(index.get("revision") or "")
        type_hint = infer_dictionary_type(source, dictionary_name)
        already_imported = self._imported_types(dictionary_name)
        total = 0
        for dict_type, rows in reader.iter_records(dictionary_name, type_hint):
            if dict_type in already_imported:
                continue
            total += self._insert_records(
                dict_type=dict_type,
                title=dictionary_name,
                revision=revision,
                source_path=str(source),
                rows=rows,
            )
        return total

    def _insert_records(
        self,
        dict_type: str,
        title: str,
        revision: str,
        source_path: str,
        rows: Iterable[dict[str, object]],
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        with self._connect() as db:
            existing = db.execute(
                "SELECT id, entry_count FROM dictionaries WHERE title = ? AND type = ?",
                (title, dict_type),
            ).fetchone()
            if existing:
                dictionary_id = int(existing["id"])
                previous_count = int(existing["entry_count"] or 0)
            else:
                priority = self._next_priority(db, dict_type)
                cursor = db.execute(
                    """
                    INSERT INTO dictionaries(title, type, source_path, revision, enabled, priority, entry_count, imported_at)
                    VALUES (?, ?, ?, ?, 1, ?, 0, ?)
                    """,
                    (title, dict_type, source_path, revision, priority, datetime.now().isoformat(timespec="seconds")),
                )
                dictionary_id = int(cursor.lastrowid)
                previous_count = 0

            if dict_type == "term":
                db.executemany(
                    """
                    INSERT INTO entries(dictionary_id, term, reading, definitions, definition_tags, term_tags, rules)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            dictionary_id,
                            str(row["term"]),
                            str(row.get("reading", "")),
                            json.dumps(row.get("definitions", []), ensure_ascii=False),
                            str(row.get("definition_tags", "")),
                            str(row.get("term_tags", "")),
                            str(row.get("rules", "")),
                        )
                        for row in rows
                    ),
                )
            elif dict_type == "frequency":
                db.executemany(
                    """
                    INSERT INTO frequencies(dictionary_id, term, reading, display, value)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            dictionary_id,
                            str(row["term"]),
                            str(row.get("reading", "")),
                            str(row.get("display", "")),
                            str(row.get("value", "")),
                        )
                        for row in rows
                    ),
                )
            elif dict_type == "pitch":
                db.executemany(
                    """
                    INSERT INTO pitches(dictionary_id, term, reading, summary)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        (
                            dictionary_id,
                            str(row["term"]),
                            str(row.get("reading", "")),
                            str(row.get("summary", "")),
                        )
                        for row in rows
                    ),
                )
            db.execute(
                "UPDATE dictionaries SET entry_count = ?, source_path = ?, revision = ? WHERE id = ?",
                (previous_count + len(rows), source_path, revision, dictionary_id),
            )
        return len(rows)

    def _lookup_term_rows(self, db: sqlite3.Connection, word: str, limit: int) -> list[sqlite3.Row]:
        return db.execute(
            """
            SELECT e.term, e.reading, e.definitions, e.definition_tags, e.term_tags, e.rules, d.title AS dictionary
            FROM entries e
            JOIN dictionaries d ON d.id = e.dictionary_id
            WHERE d.enabled = 1
              AND d.type = 'term'
              AND (e.term = ? OR e.reading = ?)
            ORDER BY d.priority, e.rowid
            LIMIT ?
            """,
            (word, word, limit),
        ).fetchall()

    def _lookup_frequency_rows(self, db: sqlite3.Connection, term: str, reading: str, limit: int = 8) -> list[str]:
        rows = db.execute(
            """
            SELECT d.title AS dictionary, f.reading, f.display, f.value
            FROM frequencies f
            JOIN dictionaries d ON d.id = f.dictionary_id
            WHERE d.enabled = 1
              AND d.type = 'frequency'
              AND f.term = ?
              AND (f.reading = '' OR ? = '' OR f.reading = ?)
            ORDER BY d.priority, f.rowid
            LIMIT ?
            """,
            (term, reading, reading, limit),
        ).fetchall()
        return [_format_aux_row(row) for row in rows]

    def _lookup_pitch_rows(self, db: sqlite3.Connection, term: str, reading: str, limit: int = 8) -> list[str]:
        rows = db.execute(
            """
            SELECT d.title AS dictionary, p.reading, p.summary AS display
            FROM pitches p
            JOIN dictionaries d ON d.id = p.dictionary_id
            WHERE d.enabled = 1
              AND d.type = 'pitch'
              AND p.term = ?
              AND (p.reading = '' OR ? = '' OR p.reading = ?)
            ORDER BY d.priority, p.rowid
            LIMIT ?
            """,
            (term, reading, reading, limit),
        ).fetchall()
        return [_format_aux_row(row) for row in rows]

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS dictionaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    type TEXT NOT NULL,
                    source_path TEXT DEFAULT '',
                    revision TEXT DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL DEFAULT 0,
                    entry_count INTEGER NOT NULL DEFAULT 0,
                    imported_at TEXT DEFAULT '',
                    UNIQUE(title, type)
                );
                CREATE TABLE IF NOT EXISTS entries (
                    dictionary_id INTEGER NOT NULL,
                    term TEXT NOT NULL,
                    reading TEXT NOT NULL DEFAULT '',
                    definitions TEXT NOT NULL,
                    definition_tags TEXT NOT NULL DEFAULT '',
                    term_tags TEXT NOT NULL DEFAULT '',
                    rules TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(dictionary_id) REFERENCES dictionaries(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS frequencies (
                    dictionary_id INTEGER NOT NULL,
                    term TEXT NOT NULL,
                    reading TEXT NOT NULL DEFAULT '',
                    display TEXT NOT NULL DEFAULT '',
                    value TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(dictionary_id) REFERENCES dictionaries(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS pitches (
                    dictionary_id INTEGER NOT NULL,
                    term TEXT NOT NULL,
                    reading TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(dictionary_id) REFERENCES dictionaries(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_entries_term ON entries(term);
                CREATE INDEX IF NOT EXISTS idx_entries_reading ON entries(reading);
                CREATE INDEX IF NOT EXISTS idx_frequencies_term ON frequencies(term);
                CREATE INDEX IF NOT EXISTS idx_frequencies_reading ON frequencies(reading);
                CREATE INDEX IF NOT EXISTS idx_pitches_term ON pitches(term);
                CREATE INDEX IF NOT EXISTS idx_pitches_reading ON pitches(reading);
                """
            )
            self._ensure_column(db, "entries", "definition_tags", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "entries", "term_tags", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "entries", "rules", "TEXT NOT NULL DEFAULT ''")

    def _migrate_legacy_json(self) -> None:
        if not self.data_file.exists():
            return
        with self._connect() as db:
            has_rows = db.execute("SELECT 1 FROM dictionaries LIMIT 1").fetchone()
        if has_rows:
            return
        try:
            loaded = json.loads(self.data_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(loaded, list):
            return
        rows = [
            {
                "term": str(entry["term"]),
                "reading": str(entry.get("reading", "")),
                "definitions": [str(item) for item in entry.get("definitions", [])],
            }
            for entry in loaded
            if isinstance(entry, dict) and entry.get("term")
        ]
        if rows:
            self._insert_records("term", "旧版导入词典", "", str(self.data_file), rows)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_file)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _next_priority(db: sqlite3.Connection, dict_type: str) -> int:
        row = db.execute("SELECT COALESCE(MAX(priority), -1) + 1 AS priority FROM dictionaries WHERE type = ?", (dict_type,)).fetchone()
        return int(row["priority"] if row else 0)

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {str(row["name"]) for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _imported_types(self, title: str) -> set[str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT type FROM dictionaries WHERE title = ? AND entry_count > 0",
                (title,),
            ).fetchall()
        return {str(row["type"]) for row in rows}


class _YomitanReader:
    def index(self) -> dict[str, object]:
        raise NotImplementedError

    def iter_records(self, dictionary_name: str, type_hint: str) -> Iterable[tuple[str, list[dict[str, object]]]]:
        for name, bank in self.bank_items("term_bank_"):
            if not isinstance(bank, list):
                continue
            dict_type = "pitch" if type_hint == "pitch" else "term"
            parser = _parse_pitch_bank_row if dict_type == "pitch" else _parse_term_bank_row
            records: list[dict[str, object]] = []
            for row in bank:
                parsed = parser(row, dictionary_name)
                if parsed:
                    records.append(parsed)
                if len(records) >= IMPORT_CHUNK_SIZE:
                    yield dict_type, records
                    records = []
            if records:
                yield dict_type, records
        for name, bank in self.bank_items("term_meta_bank_"):
            if not isinstance(bank, list):
                continue
            grouped: dict[str, list[dict[str, object]]] = {"frequency": [], "pitch": []}
            for row in bank:
                parsed_type, parsed = _parse_term_meta_bank_row(row)
                if parsed_type and parsed:
                    grouped[parsed_type].append(parsed)
                    if len(grouped[parsed_type]) >= IMPORT_CHUNK_SIZE:
                        yield parsed_type, grouped[parsed_type]
                        grouped[parsed_type] = []
            for dict_type, rows in grouped.items():
                if rows:
                    yield dict_type, rows

    def bank_items(self, prefix: str) -> Iterable[tuple[str, object]]:
        raise NotImplementedError


class _DirectoryReader(_YomitanReader):
    def __init__(self, root: Path) -> None:
        self.root = root

    def index(self) -> dict[str, object]:
        data = _read_json(self.root / "index.json", default={})
        return data if isinstance(data, dict) else {}

    def bank_items(self, prefix: str) -> Iterable[tuple[str, object]]:
        for bank_path in sorted(self.root.glob(f"{prefix}*.json"), key=_natural_key):
            yield bank_path.name, _read_json(bank_path, default=[])


class _ZipReader(_YomitanReader):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.archive = zipfile.ZipFile(path)
        self.names = self.archive.namelist()
        self.base = self._base_path()

    def index(self) -> dict[str, object]:
        index_name = f"{self.base}/index.json" if self.base else "index.json"
        data = json.loads(self.archive.read(index_name))
        return data if isinstance(data, dict) else {}

    def bank_items(self, prefix: str) -> Iterable[tuple[str, object]]:
        names = [
            name
            for name in self.names
            if _zip_parent(name) == self.base and Path(name).name.startswith(prefix) and Path(name).name.endswith(".json")
        ]
        for name in sorted(names, key=lambda item: _natural_key(Path(item).name)):
            yield Path(name).name, json.loads(self.archive.read(name))

    def _base_path(self) -> str:
        for name in self.names:
            if Path(name).name == "index.json":
                parent = Path(name).parent.as_posix()
                return "" if parent == "." else parent
        return ""


def deinflect(word: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    polite_rules = [
        ("ませんでした", "礼貌否定过去式"),
        ("ました", "礼貌过去式"),
        ("ません", "礼貌否定形"),
        ("ます", "礼貌形"),
    ]
    for suffix, note in polite_rules:
        if word.endswith(suffix) and len(word) > len(suffix):
            results.extend(_polite_stem_forms(word[: -len(suffix)], note))

    rules = [
        ("ない", "る", "否定形"),
        ("なかった", "る", "否定过去式"),
        ("した", "する", "する过去式"),
        ("して", "する", "するて形"),
        ("って", "う", "て形"),
        ("った", "う", "过去式"),
        ("んだ", "む", "过去式"),
        ("いた", "く", "过去式"),
        ("いだ", "ぐ", "过去式"),
        ("した", "す", "过去式"),
        ("た", "る", "过去式"),
        ("て", "る", "て形"),
    ]
    for suffix, replacement, note in rules:
        if word.endswith(suffix) and len(word) > len(suffix):
            results.append((word[: -len(suffix)] + replacement, note))
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for candidate, note in results:
        if candidate not in seen:
            seen.add(candidate)
            deduped.append((candidate, note))
    return deduped


def normalize_dictionary_type(raw: str) -> str:
    normalized = raw.strip().lower()
    aliases = {
        "1": "term",
        "term": "term",
        "terms": "term",
        "释义": "term",
        "词典": "term",
        "辞典": "term",
        "2": "frequency",
        "freq": "frequency",
        "frequency": "frequency",
        "频率": "frequency",
        "3": "pitch",
        "pitch": "pitch",
        "音高": "pitch",
        "声调": "pitch",
    }
    result = aliases.get(normalized)
    if result is None:
        raise ValueError("词典类型必须是 term / frequency / pitch")
    return result


def infer_dictionary_type(source: Path, dictionary_name: str) -> str:
    parts = " ".join((*source.parts[-3:], dictionary_name)).lower()
    if "frequency" in parts or "[freq" in parts or "freq]" in parts or "频率" in parts:
        return "frequency"
    if "pitch" in parts or "[pitch" in parts or "accent" in parts or "アクセント" in parts or "発音" in parts or "音高" in parts:
        return "pitch"
    return "term"


def format_results(results: list[LookupResult]) -> str:
    if not results:
        return style("没有命中。", DIM)
    blocks: list[str] = []
    for index, group in enumerate(_group_lookup_results(results), start=1):
        first = group[0]
        heading = f"{style(str(index) + '.', DIM)} {style(first.term, BOLD)}"
        if first.reading and first.reading != first.term:
            heading += f" {style(first.reading, YELLOW)}"
        if first.note:
            heading += f"  {style(first.note, DIM)}"
        lines = [heading]

        frequencies = _unique(item for result in group for item in result.frequencies)
        pitches = _unique(item for result in group for item in result.pitches)
        if frequencies:
            lines.append(f"   {style('频率', MAGENTA)} " + " ".join(_aux_badge(item, "frequency") for item in frequencies[:10]))
        if pitches:
            lines.append(f"   {style('音高', CYAN)} " + " ".join(_aux_badge(item, "pitch") for item in pitches[:8]))
        lines.append(style(f"   操作  a {first.term} 制卡    /{first.term} 递归查词", DIM))

        by_dictionary: dict[str, list[LookupResult]] = {}
        for result in group:
            by_dictionary.setdefault(result.dictionary, []).append(result)
        for dictionary, entries in by_dictionary.items():
            lines.append(f"   {style('▼', CYAN)} {style(dictionary, BOLD + CYAN)}")
            for entry_index, entry in enumerate(entries, start=1):
                tags = _unique([*entry.term_tags, *entry.definition_tags])
                tag_text = " ".join(_tag_badge(tag) for tag in tags) if ansi_enabled() else f"[{' / '.join(tags)}]"
                tag_text = tag_text if tags else ""
                prefix = f"      {entry_index}. " if len(entries) > 1 else "      "
                if tag_text:
                    lines.append(prefix + tag_text)
                for definition_index, definition in enumerate(entry.definitions[:4], start=1):
                    marker = "・" if len(entry.definitions) == 1 else f"{definition_index}."
                    lines.append(f"      {style(marker, GREEN)} {_shorten(definition, 520)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_result_pages(results: list[LookupResult], lines_per_page: int = 18, width: int = 88) -> list[str]:
    return paginate_lookup_text(format_results(results), lines_per_page, width)


def paginate_lookup_text(text: str, lines_per_page: int = 18, width: int = 88) -> list[str]:
    lines_per_page = max(4, lines_per_page)
    width = max(24, width)
    blocks = [
        "\n".join(line for raw_line in block.splitlines() for line in _wrap_lookup_line(raw_line, width))
        for block in text.split("\n\n")
    ]
    pages: list[str] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            pages.append("\n".join(current).rstrip())
            current = []

    for block in blocks:
        block_lines = block.splitlines() or [""]
        if len(block_lines) > lines_per_page:
            flush()
            for start in range(0, len(block_lines), lines_per_page):
                pages.append("\n".join(block_lines[start : start + lines_per_page]).rstrip())
            continue

        separator = 1 if current else 0
        if current and len(current) + separator + len(block_lines) > lines_per_page:
            flush()
            separator = 0
        if separator:
            current.append("")
        current.extend(block_lines)

    flush()
    return pages or [text]


def _wrap_lookup_line(line: str, width: int) -> list[str]:
    visible = ANSI_RE.sub("", line)
    if len(visible) <= width:
        return [line]
    if visible != line:
        line = visible
    indent_length = len(line) - len(line.lstrip(" "))
    indent = line[:indent_length]
    content = line[indent_length:]
    wrapped = textwrap.wrap(
        content,
        width=max(12, width - indent_length),
        initial_indent=indent,
        subsequent_indent=indent + "  ",
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
        drop_whitespace=False,
    )
    return wrapped or [line]


def find_yomitan_sources(path: str | Path) -> list[Path]:
    source = Path(path).expanduser()
    if source.is_file() and source.suffix.lower() == ".zip":
        return [source]
    if not source.is_dir():
        return []
    candidates: list[Path] = []
    if (source / "index.json").exists():
        candidates.append(source)
    candidates.extend(source.rglob("*.zip"))
    candidates.extend(
        item.parent
        for item in source.rglob("index.json")
        if item.parent != source and (any(item.parent.glob("term_bank_*.json")) or any(item.parent.glob("term_meta_bank_*.json")))
    )
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in sorted(candidates, key=_source_sort_key):
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(candidate)
    return deduped


def _polite_stem_forms(stem: str, note: str) -> list[tuple[str, str]]:
    if not stem:
        return []
    results = [(stem + "る", note)]
    godan_map = {
        "い": "う",
        "き": "く",
        "ぎ": "ぐ",
        "し": "す",
        "ち": "つ",
        "に": "ぬ",
        "び": "ぶ",
        "み": "む",
        "り": "る",
    }
    replacement = godan_map.get(stem[-1])
    if replacement:
        results.append((stem[:-1] + replacement, note))
    if stem.endswith("し"):
        results.append((stem[:-1] + "する", note))
    return results


def _parse_term_bank_row(row: object, dictionary_name: str) -> dict[str, object] | None:
    if not isinstance(row, list) or len(row) < 6:
        return None
    term = str(row[0]).strip()
    reading = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
    if not term:
        return None
    definitions = _flatten_glossary(row[5])
    if not definitions:
        definitions = ["该词条没有可显示的文本释义。"]
    return {
        "term": term,
        "reading": reading,
        "definitions": definitions,
        "dictionary": dictionary_name,
        "definition_tags": str(row[2] or "") if len(row) > 2 else "",
        "rules": str(row[3] or "") if len(row) > 3 else "",
        "term_tags": str(row[7] or "") if len(row) > 7 else "",
    }


def _parse_pitch_bank_row(row: object, dictionary_name: str) -> dict[str, object] | None:
    parsed = _parse_term_bank_row(row, dictionary_name)
    if not parsed:
        return None
    return {
        "term": parsed["term"],
        "reading": parsed.get("reading", ""),
        "summary": _summarize_pitch_definitions([str(item) for item in parsed.get("definitions", [])]),
    }


def _parse_term_meta_bank_row(row: object) -> tuple[str | None, dict[str, object] | None]:
    if not isinstance(row, list) or len(row) < 3:
        return None, None
    term = str(row[0]).strip()
    kind = str(row[1]).strip()
    data = row[2]
    if not term:
        return None, None
    if kind == "freq":
        reading, value, display = _parse_frequency_data(data)
        return "frequency", {"term": term, "reading": reading, "value": value, "display": display}
    if kind == "pitch":
        reading, summary = _parse_pitch_data(data)
        return "pitch", {"term": term, "reading": reading, "summary": summary}
    return None, None


def _parse_frequency_data(data: object) -> tuple[str, str, str]:
    if isinstance(data, dict):
        reading = str(data.get("reading") or "")
        frequency = data.get("frequency")
        if isinstance(frequency, dict):
            value = str(frequency.get("value") or data.get("value") or "")
            display = str(frequency.get("displayValue") or data.get("displayValue") or value)
        else:
            value = str(data.get("value") or frequency or "")
            display = str(data.get("displayValue") or frequency or value)
        return reading, value, display
    return "", str(data), str(data)


def _parse_pitch_data(data: object) -> tuple[str, str]:
    if isinstance(data, dict):
        reading = str(data.get("reading") or "")
        pitches = data.get("pitches")
        if isinstance(pitches, list):
            positions = []
            for pitch in pitches:
                if isinstance(pitch, dict) and "position" in pitch:
                    positions.append(str(pitch["position"]))
            if positions:
                return reading, ",".join(positions)
        return reading, _shorten(json.dumps(data, ensure_ascii=False), 160)
    return "", _shorten(str(data), 160)


def _summarize_pitch_definitions(definitions: list[str]) -> str:
    text = "\n".join(definitions)
    matches = re.findall(r"［(\d+)］\s*([^\n；;]+)", text)
    if matches:
        return " / ".join(f"{position} {pronunciation.strip()}" for position, pronunciation in matches[:6])
    return _shorten(text, 160)


def _flatten_glossary(value: object) -> list[str]:
    results: list[str] = []
    if isinstance(value, str):
        if value.strip():
            results.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                text = _structured_text(item)
                if text:
                    results.append(text)
            else:
                results.extend(_flatten_glossary(item))
    elif isinstance(value, dict):
        text = _structured_text(value)
        if text:
            results.append(text)
    return results


def _structured_text(value: object) -> str:
    chunks: list[str] = []

    def walk(item: object) -> None:
        if isinstance(item, str):
            if item:
                chunks.append(item)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, dict):
            if "content" in item:
                walk(item["content"])
            elif "text" in item:
                walk(item["text"])

    walk(value)
    rendered = "".join(chunks)
    rendered = re.sub(r"\s+", " ", rendered)
    return rendered.strip()


def _format_aux_row(row: sqlite3.Row) -> str:
    dictionary = str(row["dictionary"])
    display = str(row["display"] or row["value"] or "").strip() if "value" in row.keys() else str(row["display"] or "").strip()
    reading = str(row["reading"] or "").strip()
    suffix = f" [{reading}]" if reading else ""
    return f"{dictionary}{suffix}: {display}" if display else f"{dictionary}{suffix}"


def _lookup_queries(text: str, scan_length: int) -> list[tuple[str, str]]:
    compact = re.sub(r"\s+", "", text.strip())
    if not compact:
        return []
    queries = [(compact, "exact")]
    max_length = min(len(compact), max(1, scan_length))
    for length in range(max_length, 0, -1):
        prefix = compact[:length]
        if prefix != compact:
            queries.append((prefix, f"从「{compact}」前方扫描"))
    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for query, note in queries:
        if query not in seen:
            seen.add(query)
            deduped.append((query, note))
    return deduped


def _group_lookup_results(results: list[LookupResult]) -> list[list[LookupResult]]:
    groups: list[list[LookupResult]] = []
    group_by_key: dict[tuple[str, str, str], list[LookupResult]] = {}
    for result in results:
        key = (result.term, result.reading, result.note)
        group = group_by_key.get(key)
        if group is None:
            group = []
            group_by_key[key] = group
            groups.append(group)
        group.append(result)
    return groups


def _split_tags(tags: str) -> list[str]:
    return [tag for tag in re.split(r"[\s,;|/]+", tags.strip()) if tag and not tag.isdigit()]


def _unique(items: Iterable[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            values.append(item)
    return values


def _aux_badge(text: str, kind: str = "aux") -> str:
    if ": " in text:
        dictionary, value = text.split(": ", 1)
        return _badge(_shorten(dictionary, 24), value, kind)
    return _badge(_shorten(text, 32), "", kind)


def _tag_badge(text: str) -> str:
    return _badge(text, "", "tag")


def _badge(label: str, value: str = "", kind: str = "aux") -> str:
    if not ansi_enabled():
        content = f"{label} {value}".strip()
        return f"[{content}]"
    palettes = {
        "frequency": ((87, 139, 214), (245, 248, 255)),
        "pitch": ((105, 197, 185), (246, 255, 252)),
        "tag": ((171, 126, 213), (255, 250, 255)),
        "aux": ((114, 156, 213), (247, 250, 255)),
    }
    label_bg, value_bg = palettes.get(kind, palettes["aux"])
    label_text = f"{rgb((255, 255, 255), label_bg)}{BOLD} {label} {RESET}"
    if not value:
        return label_text
    return f"{label_text}{rgb((25, 32, 42), value_bg)} {value} {RESET}"


def _shorten(text: str, limit: int = 360) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _natural_key(path: Path | str) -> list[object]:
    name = path.name if isinstance(path, Path) else str(path)
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def _zip_parent(name: str) -> str:
    parent = Path(name).parent.as_posix()
    return "" if parent == "." else parent


def _source_sort_key(path: Path) -> tuple[int, str]:
    order = {"term": 0, "pitch": 1, "frequency": 2}
    return (order[infer_dictionary_type(path, path.stem)], str(path).lower())
