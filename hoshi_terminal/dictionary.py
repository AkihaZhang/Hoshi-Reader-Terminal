from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable
import json
import re
import zipfile


BUILTIN_ENTRIES = [
    {
        "term": "星",
        "reading": "ほし",
        "definitions": ["星；夜空中发光的天体。"],
        "dictionary": "内置辞书",
    },
    {
        "term": "読む",
        "reading": "よむ",
        "definitions": ["読む；阅读，朗读，理解文字内容。"],
        "dictionary": "内置辞书",
    },
    {
        "term": "端末",
        "reading": "たんまつ",
        "definitions": ["终端；用于输入命令并显示输出的环境。"],
        "dictionary": "内置辞书",
    },
    {
        "term": "辞書",
        "reading": "じしょ",
        "definitions": ["辞书；按词条说明词义、读音或用法的资料。"],
        "dictionary": "内置辞书",
    },
]


@dataclass(frozen=True)
class LookupResult:
    term: str
    reading: str
    definitions: list[str]
    dictionary: str
    matched: str
    note: str = ""


class DictionaryManager:
    def __init__(self, data_file: Path) -> None:
        self.data_file = data_file
        self.entries = self._load_entries()

    def import_yomitan(self, path: str | Path) -> int:
        source = Path(path)
        if source.is_dir() and not (source / "index.json").exists():
            count = 0
            for candidate in find_yomitan_sources(source):
                if candidate.resolve() == source.resolve():
                    continue
                count += self.import_yomitan(candidate)
            return count

        imported: list[dict[str, object]] = []
        if source.is_dir():
            imported.extend(_read_yomitan_dir(source))
        elif source.suffix.lower() == ".zip":
            with TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(source) as archive:
                    archive.extractall(temp_dir)
                imported.extend(_read_yomitan_dir(Path(temp_dir)))
        else:
            raise ValueError("词典必须是 Yomitan zip 文件或目录")

        existing_keys = {(entry["term"], entry.get("reading", ""), entry.get("dictionary", "")) for entry in self.entries}
        count = 0
        for entry in imported:
            key = (entry["term"], entry.get("reading", ""), entry.get("dictionary", ""))
            if key in existing_keys:
                continue
            self.entries.append(entry)
            existing_keys.add(key)
            count += 1
        self._save_entries()
        return count

    def lookup(self, word: str, limit: int = 8) -> list[LookupResult]:
        needle = word.strip()
        if not needle:
            return []

        candidates = [(needle, "exact")]
        for base, note in deinflect(needle):
            if base != needle:
                candidates.append((base, note))

        results: list[LookupResult] = []
        seen: set[tuple[str, str, str]] = set()
        for candidate, note in candidates:
            for entry in self._iter_entries():
                if entry["term"] != candidate and entry.get("reading", "") != candidate:
                    continue
                key = (str(entry["term"]), str(entry.get("reading", "")), str(entry.get("dictionary", "")))
                if key in seen:
                    continue
                seen.add(key)
                results.append(
                    LookupResult(
                        term=str(entry["term"]),
                        reading=str(entry.get("reading", "")),
                        definitions=[str(item) for item in entry.get("definitions", [])],
                        dictionary=str(entry.get("dictionary", "未知词典")),
                        matched=candidate,
                        note="" if note == "exact" else note,
                    )
                )
                if len(results) >= limit:
                    return results
        return results

    def _iter_entries(self) -> Iterable[dict[str, object]]:
        yield from self.entries
        yield from BUILTIN_ENTRIES

    def _load_entries(self) -> list[dict[str, object]]:
        if not self.data_file.exists():
            return []
        with self.data_file.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, list):
            return []
        return [entry for entry in loaded if isinstance(entry, dict) and "term" in entry]

    def _save_entries(self) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        with self.data_file.open("w", encoding="utf-8") as handle:
            json.dump(self.entries, handle, ensure_ascii=False, indent=2)


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


def format_results(results: list[LookupResult]) -> str:
    if not results:
        return "没有命中。词典沉默地看着你。"
    blocks: list[str] = []
    for index, result in enumerate(results, start=1):
        heading = f"{index}. {result.term}"
        if result.reading:
            heading += f" [{result.reading}]"
        if result.note:
            heading += f"  ({result.note})"
        definitions = "\n".join(f"   - {_shorten(definition)}" for definition in result.definitions[:5])
        blocks.append(f"{heading}\n   @ {result.dictionary}\n{definitions}")
    return "\n\n".join(blocks)


def _shorten(text: str, limit: int = 360) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def find_yomitan_sources(path: str | Path) -> list[Path]:
    source = Path(path).expanduser()
    if source.is_file() and source.suffix.lower() == ".zip":
        return [source]
    if not source.is_dir():
        return []
    candidates: list[Path] = []
    if (source / "index.json").exists():
        candidates.append(source)
    candidates.extend(sorted(source.rglob("*.zip"), key=lambda item: str(item).lower()))
    candidates.extend(
        sorted(
            (
                item
                for item in source.rglob("index.json")
                if item.parent != source and any(item.parent.glob("term_bank_*.json"))
            ),
            key=lambda item: str(item.parent).lower(),
        )
    )
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path_candidate = candidate.parent if candidate.name == "index.json" else candidate
        resolved = path_candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(path_candidate)
    return deduped


def _read_yomitan_dir(path: Path) -> list[dict[str, object]]:
    index = _read_json(path / "index.json", default={})
    dictionary_name = str(index.get("title") or index.get("name") or path.name)
    entries: list[dict[str, object]] = []
    for bank_path in sorted(path.glob("term_bank_*.json"), key=_natural_key):
        bank = _read_json(bank_path, default=[])
        if not isinstance(bank, list):
            continue
        for row in bank:
            parsed = _parse_term_bank_row(row, dictionary_name)
            if parsed:
                entries.append(parsed)
    return entries


def _parse_term_bank_row(row: object, dictionary_name: str) -> dict[str, object] | None:
    if not isinstance(row, list) or len(row) < 6:
        return None
    term = str(row[0]).strip()
    reading = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
    if not term:
        return None
    glossary = row[5]
    definitions = _flatten_glossary(glossary)
    if not definitions:
        definitions = ["该词条没有可显示的文本释义。"]
    return {
        "term": term,
        "reading": reading,
        "definitions": definitions,
        "dictionary": dictionary_name,
    }


def _flatten_glossary(value: object) -> list[str]:
    results: list[str] = []
    if isinstance(value, str):
        if value.strip():
            results.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            results.extend(_flatten_glossary(item))
    elif isinstance(value, dict):
        if "content" in value:
            results.extend(_flatten_glossary(value["content"]))
        elif "text" in value:
            results.extend(_flatten_glossary(value["text"]))
        elif "tag" in value:
            rendered = " ".join(item.strip() for item in value.values() if isinstance(item, str) and item.strip())
            if rendered.strip():
                results.append(rendered.strip())
    return results


def _read_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.name)]
