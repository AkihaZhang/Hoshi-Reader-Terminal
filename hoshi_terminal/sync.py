from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path
import json
import math
import re
import tempfile
import time
import zipfile

from .drive import DriveCredentialStore, DriveFile, GoogleDeviceCodeAuthorizer, GoogleDriveClient
from .epub import extract_book
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


def google_drive_authorizer(library: Library) -> GoogleDeviceCodeAuthorizer:
    return GoogleDeviceCodeAuthorizer(DriveCredentialStore(library.root / "google_drive_auth.json"))


def sync_google_drive(
    library: Library,
    direction: str = "auto",
    *,
    sync_statistics: bool | None = None,
    statistics_mode: str | None = None,
    sync_audiobook: bool | None = None,
    upload_books: bool | None = None,
    client: GoogleDriveClient | None = None,
) -> list[str]:
    mode = _normalize_direction(direction)
    settings = library.settings
    include_stats = _setting_bool(settings.get("sync_statistics", "true")) if sync_statistics is None else sync_statistics
    stats_mode = statistics_mode or settings.get("sync_statistics_mode", "merge")
    if stats_mode not in {"merge", "replace"}:
        raise ValueError("统计同步模式只能是 merge/replace")
    include_audio = _setting_bool(settings.get("sync_audiobook", "true")) if sync_audiobook is None else sync_audiobook
    include_books = _setting_bool(settings.get("sync_upload_books", "true")) if upload_books is None else upload_books
    drive = client or GoogleDriveClient(google_drive_authorizer(library))
    root_folder_id = drive.find_root_folder()
    messages: list[str] = []
    for record in sorted(library.books, key=lambda item: item.title):
        try:
            messages.append(
                sync_google_drive_book(
                    library,
                    record,
                    drive,
                    root_folder_id,
                    mode,
                    sync_statistics=include_stats,
                    statistics_mode=stats_mode,
                    sync_audiobook=include_audio,
                    upload_book=include_books,
                )
            )
        except Exception as exc:
            messages.append(f"{record.title}: 同步失败: {exc}")
    if not messages:
        messages.append("书架为空，没有可同步内容。")
    return messages


def sync_google_drive_book(
    library: Library,
    record: BookRecord,
    drive: GoogleDriveClient,
    root_folder_id: str,
    direction: str,
    *,
    sync_statistics: bool,
    statistics_mode: str,
    sync_audiobook: bool,
    upload_book: bool,
    remote_folder_id: str | None = None,
) -> str:
    folder_id = remote_folder_id or drive.ensure_book_folder(record.title, root_folder_id)
    remote = drive.list_sync_files(folder_id)
    if upload_book and direction != "import" and remote.book_data is None:
        name, content = export_ttu_bookdata(record)
        drive.upload_file(folder_id, None, name, content, "application/zip")

    title, text = library.load_record_text(record)
    total = max(1, character_count(text))
    local_ts = record.progress_modified_at
    remote_ts = drive_file_timestamp(remote.progress, "progress_", 3)
    mode = direction
    if mode == "auto":
        if remote_ts is None and local_ts <= 0:
            mode = "synced"
        elif remote_ts is None:
            mode = "export"
        elif local_ts <= 0:
            mode = "import"
        elif local_ts > remote_ts:
            mode = "export"
        elif remote_ts > local_ts:
            mode = "import"
        else:
            mode = "synced"

    if mode == "synced":
        return f"{record.title}: 已同步"
    if mode == "import":
        if remote.progress is None:
            return f"{record.title}: Google Drive 中没有阅读进度"
        raw_progress = drive.download_json(remote.progress.id)
        progress = raw_progress if isinstance(raw_progress, dict) else {}
        position = min(max(0, int(progress.get("exploredCharCount", 0))), total)
        timestamp = int(progress.get("lastBookmarkModified", remote_ts or local_ts))
        library.update_book_progress(record.id, position, timestamp)
        if sync_statistics and remote.statistics is not None:
            raw_stats = drive.download_json(remote.statistics.id)
            imported = statistics_from_ttu(raw_stats, title)
            if statistics_mode == "replace":
                library.replace_statistics_for_title(title, imported)
            else:
                library.merge_statistics(imported)
        if sync_audiobook and remote.audio_book is not None:
            raw_audio = drive.download_json(remote.audio_book.id)
            if isinstance(raw_audio, dict):
                import_ttu_audiobook(library, record, raw_audio)
        return f"{record.title}: 已从 Google Drive 导入 {position}/{total}"
    if mode == "export":
        remote_progress: dict[str, object] = {}
        if remote.progress is not None:
            raw = drive.download_json(remote.progress.id)
            if isinstance(raw, dict):
                remote_progress = raw
        timestamp = local_ts or int(time.time() * 1000)
        progress = {
            "dataId": int(remote_progress.get("dataId", 0)),
            "exploredCharCount": min(max(0, record.position), total),
            "progress": min(1.0, max(0.0, record.position / total)),
            "lastBookmarkModified": timestamp,
        }
        drive.upload_json(
            folder_id,
            remote.progress.id if remote.progress else None,
            progress_filename(progress),
            progress,
        )
        if sync_statistics:
            local_stats = library.statistics_for_title(title)
            remote_stats: list[DailyStatistic] = []
            if remote.statistics is not None:
                remote_stats = statistics_from_ttu(drive.download_json(remote.statistics.id), title)
            stats = merge_statistics(remote_stats, local_stats, statistics_mode)
            if stats:
                drive.upload_json(
                    folder_id,
                    remote.statistics.id if remote.statistics else None,
                    statistics_filename(stats),
                    [statistic_to_ttu(item) for item in stats],
                )
        if sync_audiobook:
            audio = export_ttu_audiobook(library, record)
            if audio is not None:
                drive.upload_json(
                    folder_id,
                    remote.audio_book.id if remote.audio_book else None,
                    audiobook_filename(audio),
                    audio,
                )
        return f"{record.title}: 已上传到 Google Drive {progress['exploredCharCount']}/{total}"
    raise ValueError(f"未知同步模式: {direction}")


def sync_book(library: Library, record: BookRecord, sync_root: Path, direction: str) -> str:
    book_dir = sync_root / sanitize_ttu_filename(record.title)
    book_dir.mkdir(parents=True, exist_ok=True)
    title, text = library.load_record_text(record)
    total = max(1, character_count(text))
    local_ts = record.progress_modified_at
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


def desanitize_ttu_filename(name: str) -> str:
    result = name.replace("~ttu-star~", "*")
    if result.endswith("~ttu-spc~"):
        result = result.removesuffix("~ttu-spc~") + " "
    if result.endswith("~ttu-dend~"):
        result = result.removesuffix("~ttu-dend~") + "."
    return re.sub(
        r"%([0-9A-Fa-f]{2})",
        lambda match: chr(int(match.group(1), 16)),
        result,
    )


def list_google_drive_books(
    library: Library,
    client: GoogleDriveClient | None = None,
) -> tuple[GoogleDriveClient, list[DriveFile]]:
    drive = client or GoogleDriveClient(google_drive_authorizer(library))
    root_folder_id = drive.find_root_folder()
    return drive, sorted(
        drive.list_books(root_folder_id),
        key=lambda item: desanitize_ttu_filename(item.name).casefold(),
    )


def import_google_drive_book(
    library: Library,
    folder: DriveFile,
    client: GoogleDriveClient,
) -> BookRecord:
    files = client.list_sync_files(folder.id)
    if files.book_data is None:
        raise ValueError("这本远端书没有 bookdata 文件。")
    archive = client.download_bytes(files.book_data.id)
    title, epub = ttu_bookdata_to_epub(archive)
    record = next((book for book in library.books if book.title == title), None)
    if record is None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "ttu-import.epub"
            source.write_bytes(epub)
            record = library.import_book(source, title=title)
    settings = library.settings
    sync_google_drive_book(
        library,
        record,
        client,
        client.find_root_folder(),
        "import",
        sync_statistics=_setting_bool(settings.get("sync_statistics", "true")),
        statistics_mode=settings.get("sync_statistics_mode", "merge"),
        sync_audiobook=_setting_bool(settings.get("sync_audiobook", "true")),
        upload_book=False,
        remote_folder_id=folder.id,
    )
    return record


def ttu_bookdata_to_epub(archive_bytes: bytes) -> tuple[str, bytes]:
    try:
        source = zipfile.ZipFile(BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("TTU bookdata 不是有效 ZIP。") from exc
    with source:
        try:
            static_data = json.loads(source.read("staticdata.json").decode("utf-8"))
        except KeyError as exc:
            raise ValueError("TTU bookdata 缺少 staticdata.json。") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("TTU staticdata.json 无效。") from exc
        if not isinstance(static_data, dict):
            raise ValueError("TTU staticdata.json 格式错误。")
        title = str(static_data.get("title", "")).strip()
        element_html = str(static_data.get("elementHtml", "")).strip()
        if not title or not element_html:
            raise ValueError("TTU bookdata 缺少标题或正文。")
        stylesheet = str(static_data.get("styleSheet", ""))
        element_html = re.sub(
            r"data:image/gif;ttu:([^;]+);",
            lambda match: f"images/{match.group(1)}",
            element_html,
        )
        image_entries: list[tuple[str, bytes, str]] = []
        for name in source.namelist():
            if not name.startswith("blobs/") or name.endswith("/"):
                continue
            relative = name.removeprefix("blobs/")
            if not _safe_zip_relative_path(relative):
                continue
            media_type = _image_media_type(relative)
            if media_type is None:
                continue
            image_entries.append((relative, source.read(name), media_type))

    output = BytesIO()
    with zipfile.ZipFile(output, "w") as epub:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        epub.writestr(mimetype, "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        epub.writestr(
            "OEBPS/content.xhtml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" lang="ja"><head>'
            f"<title>{escape(title)}</title>"
            '<link rel="stylesheet" type="text/css" href="style.css"/>'
            f"</head><body>{element_html}</body></html>",
        )
        epub.writestr("OEBPS/style.css", stylesheet)
        epub.writestr(
            "OEBPS/nav.xhtml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
            f"<title>{escape(title)}</title></head><body><nav epub:type=\"toc\"><ol>"
            f'<li><a href="content.xhtml">{escape(title)}</a></li>'
            "</ol></nav></body></html>",
        )
        image_manifest: list[str] = []
        for index, (relative, content, media_type) in enumerate(image_entries):
            epub.writestr(f"OEBPS/images/{relative}", content)
            image_manifest.append(
                f'<item id="image-{index}" href="images/{escape(relative)}" media-type="{media_type}"/>'
            )
        epub.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="book-id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="book-id">hoshi-ttu-import</dc:identifier>'
            f"<dc:title>{escape(title)}</dc:title><dc:language>ja</dc:language></metadata><manifest>"
            '<item id="content" href="content.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="style" href="style.css" media-type="text/css"/>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            + "".join(image_manifest)
            + '</manifest><spine><itemref idref="content"/></spine></package>',
        )
    return title, output.getvalue()


def _safe_zip_relative_path(value: str) -> bool:
    path = Path(value.replace("\\", "/"))
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _image_media_type(name: str) -> str | None:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }.get(Path(name).suffix.lower())


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


def progress_filename(progress: dict[str, object]) -> str:
    return f"progress_1_6_{progress['lastBookmarkModified']}_{progress['progress']}.json"


def audiobook_filename(audio: dict[str, object]) -> str:
    return f"audioBook_1_6_{audio['lastAudioBookModified']}_{audio['playbackPosition']}.json"


def drive_file_timestamp(file: DriveFile | None, prefix: str, index: int) -> int | None:
    if file is None or not file.name.startswith(prefix):
        return None
    try:
        return int(file.name.split("_")[index])
    except (IndexError, ValueError):
        return None


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


def statistics_from_ttu(raw: object, title: str) -> list[DailyStatistic]:
    if not isinstance(raw, list):
        return []
    stats: list[DailyStatistic] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        item_title = str(item.get("title", title))
        if item_title != title:
            continue
        date_key = str(item.get("dateKey", item.get("date_key", "")))
        if not date_key:
            continue
        stats.append(
            DailyStatistic(
                title=item_title,
                date_key=date_key,
                characters_read=int(item.get("charactersRead", item.get("characters_read", 0))),
                reading_time=float(item.get("readingTime", item.get("reading_time", 0.0))),
                min_reading_speed=int(item.get("minReadingSpeed", item.get("min_reading_speed", 0))),
                alt_min_reading_speed=int(item.get("altMinReadingSpeed", item.get("alt_min_reading_speed", 0))),
                last_reading_speed=int(item.get("lastReadingSpeed", item.get("last_reading_speed", 0))),
                max_reading_speed=int(item.get("maxReadingSpeed", item.get("max_reading_speed", 0))),
                last_statistic_modified=int(
                    item.get("lastStatisticModified", item.get("last_statistic_modified", 0))
                ),
            )
        )
    return stats


def merge_statistics(
    existing: list[DailyStatistic],
    incoming: list[DailyStatistic],
    mode: str,
) -> list[DailyStatistic]:
    if mode == "replace":
        return incoming
    by_date: dict[str, DailyStatistic] = {item.date_key: item for item in existing}
    for item in incoming:
        current = by_date.get(item.date_key)
        if current is None or item.last_statistic_modified > current.last_statistic_modified:
            by_date[item.date_key] = item
    return list(by_date.values())


def export_ttu_audiobook(library: Library, record: BookRecord) -> dict[str, object] | None:
    data = library.sasayaki_for(record)
    if not isinstance(data, dict):
        return None
    playback = data.get("playback")
    if not isinstance(playback, dict):
        return None
    position = float(playback.get("lastPosition", 0.0))
    return {
        "title": record.title,
        "playbackPosition": max(0.0, position),
        "lastAudioBookModified": int(time.time() * 1000),
    }


def import_ttu_audiobook(library: Library, record: BookRecord, raw: dict[str, object]) -> None:
    data = library.sasayaki_for(record) or {}
    playback = data.get("playback")
    if not isinstance(playback, dict):
        playback = {"delay": 0.0, "rate": 1.0}
    playback["lastPosition"] = max(0.0, float(raw.get("playbackPosition", 0.0)))
    data["playback"] = playback
    library.set_sasayaki(record, data)


def export_ttu_bookdata(record: BookRecord) -> tuple[str, bytes]:
    extracted = extract_book(Path(record.stored_path))
    now_ms = int(time.time() * 1000)
    last_access_ms = iso_to_unix_ms(record.last_access)
    sections: list[dict[str, object]] = []
    element_parts: list[str] = []
    character_offset = 0
    for index, chapter in enumerate(extracted.chapters, start=1):
        reference = f"ttu-chapter-{index}"
        chapter_characters = character_count(chapter.text)
        paragraphs = [
            f"<p>{escape(line)}</p>"
            for line in chapter.text.splitlines()
            if line.strip()
        ]
        body = "".join(paragraphs) or "<p></p>"
        element_parts.append(
            f'<div id="{reference}"><div class="ttu-book-html-wrapper">'
            f'<div class="ttu-book-body-wrapper">{body}</div></div></div>'
        )
        sections.append(
            {
                "reference": reference,
                "charactersWeight": max(1, chapter_characters),
                "label": chapter.title or f"Chapter {index}",
                "startCharacter": character_offset,
                "characters": chapter_characters,
                "parentChapter": None,
            }
        )
        character_offset += chapter_characters
    static_data = {
        "title": record.title or extracted.title,
        "styleSheet": "",
        "elementHtml": "".join(element_parts),
        "sections": sections,
    }
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "staticdata.json",
            json.dumps(static_data, ensure_ascii=False, separators=(",", ":")),
        )
    name = f"bookdata_1_6_{max(1, character_offset)}_{now_ms}_{last_access_ms}.zip"
    return name, output.getvalue()


def statistics_filename(stats: list[DailyStatistic]) -> str:
    reading_time = sum(item.reading_time for item in stats)
    characters_read = sum(item.characters_read for item in stats)
    min_reading_speed = _positive_min(item.min_reading_speed for item in stats)
    alt_min_reading_speed = _positive_min(item.alt_min_reading_speed for item in stats)
    max_reading_speed = max((item.last_reading_speed for item in stats), default=0)
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


def _setting_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "是", "开启"}
