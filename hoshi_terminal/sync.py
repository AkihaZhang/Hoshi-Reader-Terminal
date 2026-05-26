from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import math

from .reader import character_count
from .storage import BookRecord, DailyStatistic, Library


TTU_ROOT = "ttu-reader-data"
APPLE_REFERENCE_EPOCH_MS = 978_307_200_000


def sync_library(library: Library, direction: str = "auto") -> list[str]:
    mode = _normalize_direction(direction)
    sync_root = Path(library.settings["sync_path"]).expanduser() / TTU_ROOT
    sync_root.mkdir(parents=True, exist_ok=True)
    messages: list[str] = []
    for record in sorted(library.books, key=lambda item: item.title):
        try:
            messages.append(sync_book(library, record, sync_root, mode))
        except Exception as exc:
            messages.append(f"{record.title}: 同步失败: {exc}")
    if not messages:
        messages.append("书架为空，没有可同步进度。")
    return messages


def sync_book(library: Library, record: BookRecord, sync_root: Path, direction: str) -> str:
    book_dir = sync_root / sanitize_ttu_filename(record.title)
    book_dir.mkdir(parents=True, exist_ok=True)
    title, text = library.load_record_text(record)
    total = max(1, character_count(text))
    local_ts = iso_to_unix_ms(record.last_access)
    remote_file = latest_progress_file(book_dir)
    remote_ts = progress_timestamp(remote_file) if remote_file else None
    mode = direction
    if mode == "auto":
        if remote_ts is None:
            mode = "export"
        elif local_ts > remote_ts:
            mode = "export"
        elif remote_ts > local_ts:
            mode = "import"
        else:
            mode = "synced"

    if mode == "synced":
        import_statistics(library, record, book_dir)
        return f"{record.title}: 已同步"
    if mode == "import":
        if remote_file is None:
            return f"{record.title}: 没有远端进度"
        progress = read_progress(remote_file)
        position = int(progress.get("exploredCharCount", 0))
        timestamp = int(progress.get("lastBookmarkModified", progress_timestamp(remote_file) or local_ts))
        library.update_book_progress(record.id, min(max(0, position), total), timestamp)
        import_statistics(library, record, book_dir)
        return f"{record.title}: 已导入进度 {position}/{total}"
    if mode == "export":
        timestamp = max(local_ts, int(datetime.now().timestamp() * 1000))
        progress = {
            "dataId": int(read_progress(remote_file).get("dataId", 0)) if remote_file else 0,
            "exploredCharCount": min(max(0, record.position), total),
            "progress": min(1.0, max(0.0, record.position / total)),
            "lastBookmarkModified": timestamp,
        }
        write_progress(book_dir, progress)
        export_statistics(library, record, book_dir)
        library.update_book_progress(record.id, int(progress["exploredCharCount"]), timestamp)
        return f"{record.title}: 已导出进度 {progress['exploredCharCount']}/{total}"
    raise ValueError(f"未知同步模式: {direction}")


def sanitize_ttu_filename(title: str) -> str:
    result = title
    if result.endswith(" "):
        result = result[:-1] + "~ttu-spc~"
    if result.endswith("."):
        result = result[:-1] + "~ttu-dend~"
    result = result.replace("*", "~ttu-star~")
    unsafe = {'/', '?', '<', '>', '\\', ':', '*', '|', '%', '"'}
    return "".join(f"%{ord(char):02X}" if char in unsafe else char for char in result)


def latest_progress_file(book_dir: Path) -> Path | None:
    files = [path for path in book_dir.glob("progress_*.json") if path.is_file()]
    if not files:
        return None
    return max(files, key=lambda path: progress_timestamp(path) or 0)


def progress_timestamp(path: Path | None) -> int | None:
    if path is None:
        return None
    parts = path.name.split("_")
    if len(parts) > 3:
        try:
            return int(parts[3])
        except ValueError:
            pass
    try:
        return int(read_progress(path).get("lastBookmarkModified", 0))
    except Exception:
        return None


def read_progress(path: Path | None) -> dict[str, object]:
    if path is None or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return {}
    return data


def write_progress(book_dir: Path, progress: dict[str, object]) -> Path:
    for old in book_dir.glob("progress_*.json"):
        old.unlink()
    target = book_dir / f"progress_1_6_{progress['lastBookmarkModified']}_{progress['progress']}.json"
    with target.open("w", encoding="utf-8") as handle:
        json.dump(progress, handle, ensure_ascii=False, separators=(",", ":"))
    return target


def export_statistics(library: Library, record: BookRecord, book_dir: Path) -> Path | None:
    stats = library.statistics_for_title(record.title)
    if not stats:
        return None
    for old in book_dir.glob("statistics_*.json"):
        old.unlink()
    payload = [statistic_to_ttu(item) for item in stats]
    target = book_dir / statistics_filename(stats)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    return target


def import_statistics(library: Library, record: BookRecord, book_dir: Path) -> None:
    files = [path for path in book_dir.glob("statistics_*.json") if path.is_file()]
    if not files:
        return
    source = max(files, key=lambda path: path.stat().st_mtime)
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, list):
        return
    stats: list[DailyStatistic] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if str(item.get("title", record.title)) != record.title:
            continue
        normalized = {
            "title": str(item.get("title", record.title)),
            "date_key": str(item.get("dateKey", item.get("date_key", ""))),
            "characters_read": int(item.get("charactersRead", item.get("characters_read", 0))),
            "reading_time": float(item.get("readingTime", item.get("reading_time", 0.0))),
            "min_reading_speed": int(item.get("minReadingSpeed", item.get("min_reading_speed", 0))),
            "alt_min_reading_speed": int(item.get("altMinReadingSpeed", item.get("alt_min_reading_speed", 0))),
            "last_reading_speed": int(item.get("lastReadingSpeed", item.get("last_reading_speed", 0))),
            "max_reading_speed": int(item.get("maxReadingSpeed", item.get("max_reading_speed", 0))),
            "last_statistic_modified": int(item.get("lastStatisticModified", item.get("last_statistic_modified", 0))),
        }
        if normalized["date_key"]:
            stats.append(DailyStatistic(**normalized))
    library.merge_statistics(stats)


def statistics_filename(stats: list[DailyStatistic]) -> str:
    reading_time = sum(item.reading_time for item in stats)
    characters_read = sum(item.characters_read for item in stats)
    min_reading_speed = _positive_min(item.min_reading_speed for item in stats)
    alt_min_reading_speed = _positive_min(item.alt_min_reading_speed for item in stats)
    max_reading_speed = max((item.max_reading_speed for item in stats), default=0)
    last_statistic_modified = max((item.last_statistic_modified for item in stats), default=0)
    valid_days = sum(1 for item in stats if item.reading_time > 0)
    weighted_sum = sum(int(item.reading_time) * item.characters_read for item in stats)
    average_reading_time = math.ceil(reading_time / valid_days) if valid_days else 0.0
    average_weighted_reading_time = math.ceil(weighted_sum / characters_read) if characters_read else 0.0
    average_characters_read = math.ceil(characters_read / valid_days) if valid_days else 0.0
    average_weighted_characters_read = math.ceil(weighted_sum / reading_time) if reading_time else 0.0
    last_reading_speed = math.ceil((3600 * characters_read) / reading_time) if reading_time else 0.0
    average_reading_speed = math.ceil((3600 * average_characters_read) / average_reading_time) if average_reading_time else 0.0
    average_weighted_reading_speed = (
        math.ceil((3600 * average_weighted_characters_read) / average_weighted_reading_time)
        if average_weighted_reading_time
        else 0.0
    )
    return (
        f"statistics_1_6_{last_statistic_modified}_{characters_read}_{reading_time}_"
        f"{min_reading_speed}_{alt_min_reading_speed}_{float(last_reading_speed)}_{max_reading_speed}_"
        f"{float(average_reading_time)}_{float(average_weighted_reading_time)}_{float(average_characters_read)}_"
        f"{float(average_weighted_characters_read)}_{float(average_reading_speed)}_{float(average_weighted_reading_speed)}_na.json"
    )


def statistic_to_ttu(item: DailyStatistic) -> dict[str, object]:
    return {
        "title": item.title,
        "dateKey": item.date_key,
        "charactersRead": item.characters_read,
        "readingTime": item.reading_time,
        "minReadingSpeed": item.min_reading_speed,
        "altMinReadingSpeed": item.alt_min_reading_speed,
        "lastReadingSpeed": item.last_reading_speed,
        "maxReadingSpeed": item.max_reading_speed,
        "lastStatisticModified": item.last_statistic_modified,
    }


def iso_to_unix_ms(value: str) -> int:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return 0
    return int(parsed.timestamp() * 1000)


def apple_reference_seconds_to_unix_ms(value: float) -> int:
    return int(value * 1000 + APPLE_REFERENCE_EPOCH_MS)


def unix_ms_to_apple_reference_seconds(value: int) -> float:
    return (value - APPLE_REFERENCE_EPOCH_MS) / 1000


def _positive_min(values: object) -> int:
    positive = [int(value) for value in values if int(value) > 0]
    return min(positive) if positive else 0


def _normalize_direction(direction: str) -> str:
    mapping = {
        "auto": "auto",
        "自动": "auto",
        "export": "export",
        "导出": "export",
        "import": "import",
        "导入": "import",
    }
    try:
        return mapping[direction]
    except KeyError as exc:
        raise ValueError("同步模式只能是 auto/export/import") from exc
