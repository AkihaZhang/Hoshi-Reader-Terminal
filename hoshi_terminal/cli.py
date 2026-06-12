from __future__ import annotations

import argparse
from bisect import bisect_right
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import zipfile

from . import __version__
from .anki import (
    AnkiConnectError,
    MiningPayload,
    add_note,
    csv_fields,
    fetch_decks,
    fetch_note_types,
    lapis_default_mappings_for_fields,
    lapis_note_type_matches,
    select_deck_after_fetch,
    select_note_type_after_fetch,
    settings_from_dict,
    version as ankiconnect_version,
)
from .audio import (
    AudioSource,
    LocalAudioRepository,
    audio_sources_from_settings,
    default_audio_sources_json,
    resolve_word_audio,
)
from .dictionary import (
    DICTIONARY_TYPES,
    TYPE_LABELS,
    DictionaryManager,
    find_yomitan_sources,
    format_result_pages,
    format_results,
    normalize_dictionary_type,
)
from .epub import ExtractedBook, extract_book
from .reader import Page, character_count, page_for_position, paginate, render_page, sentence_around
from .sasayaki import (
    SasayakiMatch,
    SasayakiMatchData,
    SasayakiPlayer,
    cue_at_or_before_time,
    cue_at_time,
    export_cue_audio,
    find_cue_for_page,
    filter_sasayaki_text,
    filter_sasayaki_text_with_positions,
    format_time,
    is_audio_url,
    launch_audio,
    match_rate_text,
    match_sasayaki,
    next_cue,
    parse_srt,
    previous_cue,
)
from .storage import BookRecord, DailyStatistic, Library, summarize_text_progress
from .drive import (
    DeviceCodePrompt,
    DriveAuthError,
    DriveAuthorizationRequired,
    DriveFile,
    GoogleDriveClient,
)
from .sync import (
    TTU_ROOT,
    google_drive_authorizer,
    import_google_drive_book,
    list_google_drive_books,
    sync_book,
    sync_google_drive,
    sync_google_drive_book,
    sync_library,
)
from .terminal import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    MAGENTA,
    RED,
    YELLOW,
    banner,
    clear_screen,
    draw_screen,
    reader_screen,
    set_cursor_visible,
    style,
    terminal_size,
)
from .updates import check_for_updates, format_update_info, format_update_install_result, install_latest_update


BOOK_SUFFIXES = {".epub", ".txt", ".md", ".markdown", ".html", ".htm", ".xhtml"}
SKIP_SCAN_DIRS = {".git", ".venv", "__pycache__", "dist", "build"}
SKIP_SCAN_FILES = {"readme.md", "readme.zh-cn.md", "license", "install.zh-cn.txt"}


LANGUAGE_OPTIONS = [
    ("zh", "简体中文"),
    ("en", "English"),
]

HIGHLIGHT_COLORS = {
    "yellow": ("黄色", YELLOW),
    "blue": ("蓝色", CYAN),
    "green": ("绿色", GREEN),
    "red": ("红色", RED),
    "purple": ("紫色", MAGENTA),
}


UI_TEXT = {
    "main_title": {"zh": "Hoshi Reader", "en": "Hoshi Reader"},
    "books": {"zh": "书库", "en": "Books"},
    "dictionary": {"zh": "查词", "en": "Dictionary"},
    "settings": {"zh": "设置", "en": "Settings"},
    "exit": {"zh": "退出", "en": "Exit"},
    "exited": {"zh": "已退出。", "en": "Exited."},
    "choose": {"zh": "请选择：", "en": "Select: "},
    "back": {"zh": "返回", "en": "Back"},
    "main_back": {"zh": "返回主菜单", "en": "Back to Main Menu"},
    "shelf": {"zh": "书架", "en": "Shelf"},
    "shelf_read": {"zh": "书架 / 阅读", "en": "Shelf / Read"},
    "import_epub": {"zh": "导入文件", "en": "Import File"},
    "import_folder": {"zh": "导入文件夹", "en": "Import Folder"},
    "read": {"zh": "阅读", "en": "Read"},
    "manage_books": {"zh": "管理书籍", "en": "Manage Books"},
    "book_settings": {"zh": "书库设置", "en": "Book Settings"},
    "search": {"zh": "搜索", "en": "Search"},
    "import_dictionary": {"zh": "导入辞典", "en": "Import Dictionary"},
    "dictionary_list": {"zh": "辞典列表", "en": "Dictionary List"},
    "dictionary_settings": {"zh": "辞典设置", "en": "Dictionary Settings"},
    "anki": {"zh": "Anki", "en": "Anki"},
    "appearance": {"zh": "外观", "en": "Appearance"},
    "advanced": {"zh": "高级", "en": "Advanced"},
    "doctor": {"zh": "诊断", "en": "Diagnostics"},
    "about": {"zh": "关于", "en": "About"},
    "statistics": {"zh": "统计", "en": "Statistics"},
    "sync": {"zh": "同步", "en": "Sync"},
    "sasayaki": {"zh": "Sasayaki 有声书", "en": "Sasayaki Audiobook"},
    "backup": {"zh": "备份", "en": "Backup"},
    "check_update": {"zh": "检查更新", "en": "Check Updates"},
    "writing_direction": {"zh": "文字方向", "en": "Writing Direction"},
    "language": {"zh": "界面语言", "en": "Interface Language"},
    "current": {"zh": "当前", "en": "Current"},
    "horizontal": {"zh": "横排", "en": "Horizontal"},
    "vertical": {"zh": "竖排", "en": "Vertical"},
    "saved": {"zh": "已保存", "en": "Saved"},
    "invalid_language": {"zh": "语言选项无效。", "en": "Invalid language option."},
    "pause": {"zh": "按 Enter 返回", "en": "Press Enter to return"},
}


ARGPARSE_TRANSLATIONS = {
    "usage: ": "用法：",
    "positional arguments": "位置参数",
    "options": "选项",
    "optional arguments": "可选参数",
    "show this help message and exit": "显示帮助信息并退出",
    "the following arguments are required: %s": "缺少必需参数：%s",
    "invalid choice: %(value)r (choose from %(choices)s)": "无效选择：%(value)r（可选：%(choices)s）",
}


class GracefulExit(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if not argv:
            return menu_loop()
        parser = build_parser()
        args = parser.parse_args(argv)
        return int(args.func(args) or 0)
    except GracefulExit:
        return 0
    except KeyboardInterrupt:
        print("\n已退出。")
        return 130
    except Exception as exc:
        print(style(f"错误：{exc}", RED), file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    argparse._ = lambda message: ARGPARSE_TRANSLATIONS.get(message, message)
    parser = argparse.ArgumentParser(
        prog="hoshi-terminal",
        description="Hoshi Reader 终端版。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}", help="显示版本号并退出")
    subparsers = parser.add_subparsers(dest="command", required=True)

    menu = subparsers.add_parser("menu", aliases=["菜单"], help="打开中文主菜单")
    menu.set_defaults(func=cmd_menu)

    import_cmd = subparsers.add_parser("import", aliases=["导入"], help="导入书籍到书架")
    import_cmd.add_argument("path", metavar="路径")
    import_cmd.add_argument("--title", metavar="标题", help="手动指定书名")
    import_cmd.set_defaults(func=cmd_import)

    shelf = subparsers.add_parser("shelf", aliases=["书架"], help="查看已导入书籍")
    shelf.set_defaults(func=cmd_shelf)

    read = subparsers.add_parser("read", aliases=["阅读"], help="阅读书籍 id、标题片段或文件路径")
    read.add_argument("target", nargs="?", metavar="目标")
    read.add_argument("--print", action="store_true", dest="print_only", help="打印当前页后退出")
    read.add_argument("--vertical", action="store_true", help="启动时使用终端竖排显示")
    read.add_argument("--width", type=int, help="非交互输出的页面宽度")
    read.add_argument("--lines", type=int, help="非交互输出的页面行数")
    read.set_defaults(func=cmd_read)

    lookup = subparsers.add_parser("lookup", aliases=["查词"], help="查词")
    lookup.add_argument("word", metavar="词")
    lookup.set_defaults(func=cmd_lookup)

    dict_import = subparsers.add_parser("dict-import", aliases=["导入词典"], help="导入 Yomitan 词典 zip 或目录")
    dict_import.add_argument("path", metavar="路径")
    dict_import.set_defaults(func=cmd_dict_import)

    dict_list = subparsers.add_parser("dict-list", aliases=["词典列表"], help="查看已导入词典")
    dict_list.add_argument("type", nargs="?", metavar="类型", help="term / frequency / pitch")
    dict_list.set_defaults(func=cmd_dict_list)

    dict_order = subparsers.add_parser("dict-order", aliases=["词典排序"], help="调整词典优先级")
    dict_order.add_argument("type", metavar="类型", help="term / frequency / pitch")
    dict_order.add_argument("from_index", type=int, metavar="原序号")
    dict_order.add_argument("to_index", type=int, metavar="新序号")
    dict_order.set_defaults(func=cmd_dict_order)

    dict_toggle = subparsers.add_parser("dict-toggle", aliases=["词典开关"], help="启用或停用词典")
    dict_toggle.add_argument("type", metavar="类型", help="term / frequency / pitch")
    dict_toggle.add_argument("index", type=int, metavar="序号")
    dict_toggle.add_argument("state", nargs="?", choices=["on", "off", "启用", "停用"], metavar="状态")
    dict_toggle.set_defaults(func=cmd_dict_toggle)

    mine = subparsers.add_parser("card", aliases=["制卡", "mine"], help="制卡：写入 CSV 或发送到 AnkiConnect")
    mine.add_argument("word", metavar="词")
    mine.add_argument("--sentence", default="", help="例句")
    mine.add_argument("--note", default="", help="备注")
    mine.add_argument("--reading", default="", help="读音")
    mine.add_argument("--sentence-audio", default="", help="句子音频文件")
    mine.add_argument("--no-audio", action="store_true", help="制卡时不抓取词语音频")
    mine.set_defaults(func=cmd_mine)

    stats = subparsers.add_parser("stats", aliases=["统计"], help="显示阅读统计")
    stats.set_defaults(func=cmd_stats)

    sync = subparsers.add_parser("sync", aliases=["同步"], help="通过 Google Drive 同步 TTU 阅读数据")
    sync.add_argument(
        "direction",
        nargs="?",
        default="auto",
        metavar="操作",
        help="auto/export/import/connect/status/disconnect/books/get/local",
    )
    sync.add_argument("--path", metavar="目录", help="本地兼容后端目录")
    sync.add_argument("--local", action="store_true", help="使用本地目录兼容后端")
    sync.add_argument("--client-id", help="Google OAuth Client ID")
    sync.add_argument("--client-secret", help="Google OAuth Client Secret")
    sync.add_argument("--no-browser", action="store_true", help="授权时不自动打开浏览器")
    sync.add_argument("--book", help="远端书籍序号或标题片段")
    sync.set_defaults(func=cmd_sync)

    sasayaki = subparsers.add_parser("sasayaki", aliases=["有声书", "低语"], help="Sasayaki 有声书匹配和播放")
    sasayaki.add_argument("action", nargs="?", default="status", metavar="操作", help="status/list/match/audio/play")
    sasayaki.add_argument("target", nargs="?", metavar="书", help="书架序号、id 或标题片段")
    sasayaki.add_argument("path", nargs="?", metavar="路径", help="match 时为 SRT；audio 时为音频文件")
    sasayaki.add_argument("--audio", metavar="音频文件", help="匹配时顺便保存音频文件")
    sasayaki.add_argument("--window", type=int, default=200, metavar="N", help="匹配搜索窗口，默认 200")
    sasayaki.add_argument("--cue", type=int, metavar="N", help="播放/显示第 N 条匹配台词")
    sasayaki.add_argument("--rate", type=float, metavar="倍速", help="播放倍速")
    sasayaki.add_argument("--delay", type=float, metavar="秒", help="播放延迟，正数表示更晚开始")
    sasayaki.add_argument("--line", action="store_true", help="只播放这一条台词的时间范围")
    sasayaki.set_defaults(func=cmd_sasayaki)

    settings = subparsers.add_parser("settings", aliases=["设置"], help="打开设置")
    settings.set_defaults(func=cmd_settings)

    doctor = subparsers.add_parser("doctor", aliases=["诊断"], help="检查运行环境")
    doctor.set_defaults(func=cmd_doctor)

    update = subparsers.add_parser("update", aliases=["检查更新", "更新"], help="检查或安装新版本")
    update.add_argument("--check", action="store_true", help="只检查，不安装")
    update.add_argument("-y", "--yes", action="store_true", help="发现更新时直接安装")
    update.add_argument("--target", metavar="PYZ", help="指定要替换的 hoshi-terminal.pyz")
    update.set_defaults(func=cmd_update)

    return parser


def cmd_menu(args: argparse.Namespace) -> int:
    return menu_loop()


def cmd_settings(args: argparse.Namespace) -> int:
    return settings_loop()


def cmd_import(args: argparse.Namespace) -> int:
    library = Library()
    record = library.import_book(args.path, title=args.title)
    print(style("已导入", GREEN), f"{record.title} [{record.id}]")
    print(style("保存位置", DIM), record.stored_path)
    return 0


def cmd_shelf(args: argparse.Namespace) -> int:
    library = Library()
    books = _sorted_books(library)
    if not books:
        print("书架是空的。")
        return 0
    print(style("Hoshi 终端书架", BOLD))
    _print_book_choices(books)
    if sys.stdin.isatty():
        query = _read_input("输入序号或标题片段开始阅读（留空只查看书架）：").strip() or None
        if query is not None:
            record = _find_book_for_input(library, query)
            if record is None:
                print("找不到这本书。")
                return 1
            _open_book_record(library, record)
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    library = Library()
    record: BookRecord | None = None
    title: str
    text: str
    chapter_marks: list[tuple[str, int]] = []

    target_path = Path(args.target).expanduser() if args.target else None
    if target_path and target_path.exists():
        extracted = extract_book(target_path)
        title = extracted.title
        text = extracted.text
        chapter_marks = _chapter_marks_from_extracted(extracted)
    else:
        record = _find_book_for_input(library, args.target)
        if record is None:
            raise ValueError("找不到这本书。可以先运行 `shelf` / `书架`，或直接传文件路径。")
        extracted = extract_book(Path(record.stored_path))
        title = record.title or extracted.title
        text = extracted.text
        chapter_marks = _chapter_marks_from_extracted(extracted)

    pages = paginate(
        text,
        width=args.width or _optional_int_setting(library, "reader_width"),
        lines_per_page=args.lines or _optional_int_setting(library, "reader_lines"),
    )
    start_page = page_for_position(pages, record.position if record else 0)
    if args.print_only or not sys.stdin.isatty():
        print(render_page(title, pages[start_page], len(pages), vertical=args.vertical))
        return 0
    return interactive_loop(
        title,
        text,
        pages,
        record,
        args.vertical,
        start_page=start_page,
        chapter_marks=chapter_marks,
        reader_width=args.width or _optional_int_setting(library, "reader_width"),
        reader_lines=args.lines or _optional_int_setting(library, "reader_lines"),
    )


def cmd_lookup(args: argparse.Namespace) -> int:
    library = Library()
    _show_lookup(args.word, library)
    return 0


def cmd_dict_import(args: argparse.Namespace) -> int:
    manager = DictionaryManager(Library().dictionary_file)
    count = manager.import_yomitan(args.path)
    print(style("词典已导入", GREEN), f"新增 {count} 条")
    return 0


def cmd_dict_list(args: argparse.Namespace) -> int:
    manager = DictionaryManager(Library().dictionary_file)
    dict_type = normalize_dictionary_type(args.type) if args.type else None
    _print_dictionary_table(manager, dict_type)
    return 0


def cmd_dict_order(args: argparse.Namespace) -> int:
    manager = DictionaryManager(Library().dictionary_file)
    dict_type = normalize_dictionary_type(args.type)
    manager.move_dictionary(dict_type, args.from_index - 1, args.to_index - 1)
    print(style("已调整词典优先级", GREEN), f"{TYPE_LABELS[dict_type]}: {args.from_index} -> {args.to_index}")
    return 0


def cmd_dict_toggle(args: argparse.Namespace) -> int:
    manager = DictionaryManager(Library().dictionary_file)
    dict_type = normalize_dictionary_type(args.type)
    dictionaries = manager.dictionaries(dict_type)
    if args.index < 1 or args.index > len(dictionaries):
        raise ValueError("词典序号无效")
    dictionary = dictionaries[args.index - 1]
    enabled = not dictionary.enabled if args.state is None else args.state in {"on", "启用"}
    manager.set_enabled(dictionary.id, enabled)
    print(style("已保存", GREEN), f"{dictionary.title}: {'启用' if enabled else '停用'}")
    return 0


def cmd_mine(args: argparse.Namespace) -> int:
    print(
        mine_word(
            args.word,
            sentence=args.sentence,
            note=args.note,
            reading=args.reading,
            sentence_audio_path=args.sentence_audio,
            include_word_audio=not args.no_audio,
        )
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    library = Library()
    print(_statistics_report(library.statistics))
    return 0


def _statistics_report(stats: list[DailyStatistic], today_key: str | None = None) -> str:
    today_key = today_key or time.strftime("%Y-%m-%d")
    ordered = sorted(stats, key=lambda item: (item.date_key, item.title), reverse=True)
    lines = [style("阅读统计", BOLD)]
    if not ordered:
        lines.append("还没有统计。")
        return "\n".join(lines)

    today = [item for item in ordered if item.date_key == today_key]
    lines.append(_statistics_summary_block("今日", today))
    lines.append(_statistics_summary_block("累计", ordered))
    lines.append(style("书籍", BOLD))
    for index, (title, items) in enumerate(_statistics_by_book(ordered)[:10], start=1):
        characters = sum(item.characters_read for item in items)
        seconds = sum(item.reading_time for item in items)
        days = len({item.date_key for item in items})
        last = max(items, key=lambda item: item.date_key)
        max_speed = max((item.max_reading_speed for item in items), default=0)
        lines.append(
            f"{index:>2}. {title}  {characters} 字符  {_minutes_text(seconds)}  "
            f"{_reading_speed(characters, seconds)} 字符/分钟  {days} 天  最近 {last.date_key}  最高 {max_speed}"
        )
    lines.append(style("最近记录", BOLD))
    for item in ordered[:14]:
        lines.append(
            f"{item.date_key}  {item.title}  {item.characters_read} 字符  "
            f"{_minutes_text(item.reading_time)}  {item.last_reading_speed} 字符/分钟"
        )
    return "\n".join(lines)


def _statistics_summary_block(label: str, stats: list[DailyStatistic]) -> str:
    characters = sum(item.characters_read for item in stats)
    seconds = sum(item.reading_time for item in stats)
    books = len({item.title for item in stats})
    days = len({item.date_key for item in stats})
    return (
        f"{style(label, BOLD)}\n"
        f"字符: {characters}    时间: {_minutes_text(seconds)}    "
        f"速度: {_reading_speed(characters, seconds)} 字符/分钟    书籍: {books}    天数: {days}"
    )


def _statistics_by_book(stats: list[DailyStatistic]) -> list[tuple[str, list[DailyStatistic]]]:
    grouped: dict[str, list[DailyStatistic]] = {}
    for item in stats:
        grouped.setdefault(item.title, []).append(item)
    return sorted(grouped.items(), key=lambda pair: sum(item.characters_read for item in pair[1]), reverse=True)


def _minutes_text(seconds: float) -> str:
    return f"{seconds / 60:.1f} 分钟"


def _reading_speed(characters: int, seconds: float) -> int:
    if characters <= 0:
        return 0
    return int(characters / max(seconds / 60.0, 1 / 60))


def cmd_sync(args: argparse.Namespace) -> int:
    library = Library()
    action = _normalize_sync_action(args.direction)
    if args.path:
        library.set_setting("sync_path", args.path)
        library.set_setting("sync_provider", "local")
    if action == "connect":
        _connect_google_drive(
            library,
            client_id=args.client_id,
            client_secret=args.client_secret,
            open_browser=not args.no_browser,
        )
        return 0
    authorizer = google_drive_authorizer(library)
    if action == "status":
        print(_google_drive_status_text(authorizer.status()))
        return 0
    if action == "disconnect":
        authorizer.disconnect()
        print("已在本机断开 Google Drive。Google 账号中的授权和远端文件没有删除。")
        return 0
    if action in {"books", "get"}:
        drive, books = list_google_drive_books(library)
        if not books:
            print("Google Drive 的 ttu-reader-data 中没有书籍。")
            return 0
        if action == "books":
            _print_remote_books(books)
            return 0
        query = args.book
        if not query and sys.stdin.isatty():
            _print_remote_books(books)
            query = _read_input("输入远端书籍序号或标题片段：").strip()
        folder = _find_remote_book(books, query)
        if folder is None:
            raise ValueError("找不到这本远端书。")
        record = import_google_drive_book(library, folder, drive)
        print(style("已导入", GREEN), record.title)
        return 0
    use_local = args.local or action == "local" or library.settings.get("sync_provider") == "local"
    direction = "auto" if action == "local" else action
    runner = sync_library if use_local else sync_google_drive
    for message in runner(library, direction):
        print(message)
    return 0


def _normalize_sync_action(value: str) -> str:
    aliases = {
        "auto": "auto",
        "自动": "auto",
        "export": "export",
        "导出": "export",
        "import": "import",
        "导入": "import",
        "connect": "connect",
        "连接": "connect",
        "status": "status",
        "状态": "status",
        "disconnect": "disconnect",
        "断开": "disconnect",
        "books": "books",
        "书籍": "books",
        "get": "get",
        "获取": "get",
        "local": "local",
        "本地": "local",
    }
    action = aliases.get(str(value).strip().lower())
    if action is None:
        raise ValueError("同步操作只能是 auto/export/import/connect/status/disconnect/books/get/local")
    return action


def _connect_google_drive(
    library: Library,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    open_browser: bool = True,
) -> None:
    authorizer = google_drive_authorizer(library)
    stored = authorizer.store.load()
    client_id = (client_id or str(stored.get("client_id", ""))).strip()
    client_secret = (client_secret or str(stored.get("client_secret", ""))).strip()
    if not client_id and sys.stdin.isatty():
        client_id = _read_input("Google OAuth Client ID：").strip()
    if not client_secret and sys.stdin.isatty():
        client_secret = _read_input("Google OAuth Client Secret：").strip()
    authorizer.configure(client_id, client_secret)

    def show_prompt(prompt: DeviceCodePrompt) -> None:
        print(f"打开: {prompt.verification_url}")
        print(style(f"授权码: {prompt.user_code}", BOLD + CYAN))
        print("完成 Google 授权后保持本程序运行。")

    authorizer.authorize(on_prompt=show_prompt, open_browser=open_browser)
    library.set_setting("sync_provider", "google_drive")
    print(style("Google Drive 已连接。", GREEN))


def _google_drive_status_text(status: str) -> str:
    return {
        "connected": "Google Drive: 已连接",
        "not_connected": "Google Drive: 已配置 OAuth 客户端，尚未授权",
        "missing_configuration": "Google Drive: 尚未配置 OAuth 客户端",
    }.get(status, f"Google Drive: {status}")


def cmd_sasayaki(args: argparse.Namespace) -> int:
    library = Library()
    try:
        action = _normalize_sasayaki_action(args.action)
    except ValueError:
        if args.target is not None:
            raise
        args.target = args.action
        action = "status"
    record = _find_book_for_input(library, args.target)
    if record is None:
        raise ValueError("找不到这本书。Sasayaki 需要先把书导入书架。")

    if action == "match":
        if not args.path:
            raise ValueError("匹配需要 SRT 路径：hoshi sasayaki match 书 SRT --audio 音频")
        return _sasayaki_match(library, record, args.path, audio_path=args.audio, search_window=args.window)
    if action == "audio":
        audio_path = args.path or args.audio
        if not audio_path:
            raise ValueError("请提供音频文件路径。")
        return _sasayaki_set_audio(library, record, audio_path)
    if action == "list":
        return _sasayaki_list(library, record, cue_index=args.cue)
    if action == "play":
        return _sasayaki_play(library, record, cue_index=args.cue, rate=args.rate, delay=args.delay, line_only=args.line)
    return _sasayaki_status(library, record)


def cmd_doctor(args: argparse.Namespace) -> int:
    columns, rows = terminal_size()
    library = Library()
    print(banner())
    print(style("运行环境", BOLD))
    print(f"Python: {sys.version.split()[0]}")
    print(f"数据目录: {library.root}")
    print(f"终端尺寸: {columns}x{rows}")
    print(f"书籍数量: {len(library.books)}")
    print(_google_drive_status_text(google_drive_authorizer(library).status()))
    print(f"本地同步兼容目录: {library.settings['sync_path']}")
    print(f"词典文件: {library.dictionary_file}")
    print(style("诊断结果", YELLOW), "正常")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    info = check_for_updates(__version__)
    if args.check or not info.has_update:
        print(format_update_info(info))
        return 0
    print(format_update_info(info))
    if not args.yes and sys.stdin.isatty():
        confirm = _read_input(style("现在更新？[y/N] ", CYAN)).strip().lower()
        if confirm not in {"y", "yes", "是"}:
            print("已取消更新。")
            return 0
    result = install_latest_update(__version__, target=args.target, info=info)
    print(format_update_install_result(result))
    return 0


def check_update_message() -> str:
    info = check_for_updates(__version__)
    return format_update_info(info)


SASAYAKI_ACTIONS = {
    "status": "status",
    "状态": "status",
    "info": "status",
    "list": "list",
    "列表": "list",
    "cue": "list",
    "台词": "list",
    "match": "match",
    "匹配": "match",
    "audio": "audio",
    "音频": "audio",
    "play": "play",
    "播放": "play",
}


def _normalize_sasayaki_action(raw: str | None) -> str:
    key = (raw or "status").strip().lower()
    action = SASAYAKI_ACTIONS.get(key)
    if not action:
        raise ValueError("Sasayaki 操作应为 status/list/match/audio/play。")
    return action


def _sasayaki_match(
    library: Library,
    record: BookRecord,
    srt_path: str | Path,
    audio_path: str | Path | None = None,
    search_window: int = 200,
) -> int:
    srt = Path(srt_path).expanduser().resolve()
    if not srt.exists():
        raise FileNotFoundError(srt)
    audio = str(audio_path) if audio_path and is_audio_url(str(audio_path)) else None
    audio_file = Path(audio_path).expanduser().resolve() if audio_path and audio is None else None
    if audio_file is not None and not audio_file.exists():
        raise FileNotFoundError(audio_file)

    extracted = extract_book(Path(record.stored_path))
    cues = parse_srt(srt)
    result = match_sasayaki(extracted, cues, search_window=max(0, search_window))
    existing = library.sasayaki_for(record) or {}
    playback = existing.get("playback", {}) if isinstance(existing.get("playback"), dict) else {}
    data = {
        "srt_path": str(srt),
        "audio_path": audio or (str(audio_file) if audio_file else str(existing.get("audio_path", ""))),
        "search_window": max(0, search_window),
        "match": result.to_dict(),
        "playback": {
            "lastPosition": float(playback.get("lastPosition", 0.0)),
            "delay": float(playback.get("delay", 0.0)),
            "rate": float(playback.get("rate", 1.0)),
        },
    }
    library.set_sasayaki(record, data)
    print(style("Sasayaki 匹配完成", GREEN), f"{record.title}: {match_rate_text(result)}")
    if audio or audio_file:
        print(style("音频", DIM), audio or audio_file)
    return 0


def _sasayaki_set_audio(library: Library, record: BookRecord, audio_path: str | Path) -> int:
    if is_audio_url(str(audio_path)):
        audio = str(audio_path)
    else:
        audio_file = Path(audio_path).expanduser().resolve()
        if not audio_file.exists():
            raise FileNotFoundError(audio_file)
        audio = str(audio_file)
    data = library.sasayaki_for(record) or {"playback": {"lastPosition": 0.0, "delay": 0.0, "rate": 1.0}}
    data["audio_path"] = audio
    library.set_sasayaki(record, data)
    print(style("Sasayaki 音频已保存", GREEN), audio)
    return 0


def _sasayaki_status(library: Library, record: BookRecord) -> int:
    print(style("Sasayaki", BOLD), record.title)
    data = library.sasayaki_for(record)
    if not data:
        print("还没有匹配。用 `hoshi sasayaki match 书 SRT --audio 音频`。")
        return 0
    match = _sasayaki_match_data(data)
    playback = _sasayaki_playback(data)
    print(f"SRT: {data.get('srt_path', '') or '未设置'}")
    print(f"音频: {data.get('audio_path', '') or '未设置'}")
    if match:
        print(f"匹配率: {match_rate_text(match)}")
        current = cue_at_time(match, float(playback.get("lastPosition", 0.0))) or (match.matches[0] if match.matches else None)
        if current:
            print("当前台词:")
            _print_sasayaki_cue(current, 1 + match.matches.index(current))
    else:
        print("匹配数据: 未生成")
    print(f"延迟: {float(playback.get('delay', 0.0)):.2f}s")
    print(f"倍速: {float(playback.get('rate', 1.0)):.2f}x")
    return 0


def _sasayaki_list(library: Library, record: BookRecord, cue_index: int | None = None) -> int:
    data = library.sasayaki_for(record)
    match = _sasayaki_match_data(data)
    if not match:
        print("还没有 Sasayaki 匹配数据。")
        return 0
    print(style(f"Sasayaki 台词  {record.title}  {match_rate_text(match)}", BOLD))
    if cue_index is not None:
        cue = _sasayaki_cue_by_index(match, cue_index)
        if cue is None:
            raise ValueError("台词序号超出范围。")
        _print_sasayaki_cue(cue, cue_index)
        return 0
    for index, cue in enumerate(match.matches[:30], start=1):
        _print_sasayaki_cue(cue, index)
    if len(match.matches) > 30:
        print(style(f"... 还有 {len(match.matches) - 30} 条。用 --cue N 查看指定台词。", DIM))
    return 0


def _sasayaki_play(
    library: Library,
    record: BookRecord,
    cue_index: int | None = None,
    rate: float | None = None,
    delay: float | None = None,
    line_only: bool = False,
    player_session: SasayakiPlayer | None = None,
    quiet: bool = False,
) -> int:
    data = library.sasayaki_for(record)
    match = _sasayaki_match_data(data)
    if not data or not match:
        raise ValueError("还没有 Sasayaki 匹配数据。")
    audio_path = str(data.get("audio_path", ""))
    if not audio_path:
        raise ValueError("还没有设置音频文件。")
    playback = _sasayaki_playback(data)
    if rate is not None:
        playback["rate"] = max(0.1, float(rate))
    if delay is not None:
        playback["delay"] = float(delay)
    cue = _sasayaki_cue_by_index(match, cue_index) if cue_index is not None else None
    if cue is None:
        cue = cue_at_time(match, float(playback.get("lastPosition", 0.0))) or (match.matches[0] if match.matches else None)
    if cue is None:
        raise ValueError("没有可播放的匹配台词。")

    start_time = max(0.0, cue.start_time + float(playback.get("delay", 0.0)))
    duration = max(0.1, cue.end_time - cue.start_time) if line_only else None
    if player_session is None:
        command, player = launch_audio(audio_path, start_time=start_time, rate=float(playback.get("rate", 1.0)), duration=duration)
    else:
        command, player = player_session.play(audio_path, start_time=start_time, rate=float(playback.get("rate", 1.0)), duration=duration)
    playback["lastPosition"] = cue.start_time
    data["playback"] = playback
    library.set_sasayaki(record, data)
    if not quiet:
        label = "Sasayaki 播放本句" if line_only else "Sasayaki 从此句播放"
        print(style(label, GREEN), f"{format_time(cue.start_time)}  {cue.text}")
        if player in {"open", "start", "xdg-open"}:
            print(style("提示", YELLOW), "系统默认播放器可能不会跳到指定时间；安装 mpv 或 ffplay 可按台词起点播放。")
        print(style("播放器", DIM), player, " ".join(command))
    return 0


def _sasayaki_match_data(data: dict[str, object] | None) -> SasayakiMatchData | None:
    if not data:
        return None
    raw_match = data.get("match")
    if not isinstance(raw_match, dict):
        return None
    return SasayakiMatchData.from_dict(raw_match)


def _sasayaki_playback(data: dict[str, object]) -> dict[str, object]:
    playback = data.get("playback")
    if not isinstance(playback, dict):
        playback = {}
    playback.setdefault("lastPosition", 0.0)
    playback.setdefault("delay", 0.0)
    playback.setdefault("rate", 1.0)
    return playback


def _sasayaki_cue_by_index(match: SasayakiMatchData, cue_index: int | None) -> SasayakiMatch | None:
    if cue_index is None:
        return None
    if cue_index < 1 or cue_index > len(match.matches):
        return None
    return match.matches[cue_index - 1]


def _print_sasayaki_cue(cue: SasayakiMatch, index: int) -> None:
    print(
        f"{index:>4}. {format_time(cue.start_time)} -> {format_time(cue.end_time)}  "
        f"ch{cue.chapter_index + 1}:{cue.start}  {cue.text}"
    )


def _show_lookup(word: str, library: Library | None = None) -> None:
    library = library or Library()
    results = DictionaryManager(library.dictionary_file).lookup(
        word,
        limit=_bounded_int_setting(library, "dictionary_max_results", default=16, minimum=1, maximum=50),
        scan_length=_bounded_int_setting(library, "dictionary_scan_length", default=16, minimum=1, maximum=64),
    )
    if not sys.stdin.isatty():
        print(format_results(results))
        return
    _lookup_pager(word, results, library)


def _lookup_pager(word: str, results: object, library: Library) -> None:
    current_word = word
    page_index = 0
    current_results = results
    while True:
        columns, rows = terminal_size()
        pages = format_result_pages(current_results, lines_per_page=max(8, rows - 7), width=max(40, columns - 2))
        page_index = max(0, min(page_index, len(pages) - 1))
        print(clear_screen(), end="")
        print(style(f"查词 {current_word}  第 {page_index + 1}/{len(pages)} 页", BOLD))
        print(style("─" * min(96, max(24, len(current_word) + 18)), CYAN))
        print(pages[page_index])
        print(style("─" * min(96, max(24, len(current_word) + 18)), CYAN))
        print(style("→/↓ 下一页    ←/↑ 上一页    /词 递归查词    a 词 制卡    q 返回", DIM))
        command = _read_reader_command(style("dict> ", CYAN)).strip()
        if command in {"right", "down"}:
            page_index = min(len(pages) - 1, page_index + 1)
        elif command in {"left", "up"}:
            page_index = max(0, page_index - 1)
        elif command in {"q", "quit", "exit"}:
            return
        elif command.startswith("/"):
            next_word = command[1:].strip()
            if next_word:
                current_word = next_word
                current_results = DictionaryManager(library.dictionary_file).lookup(
                    next_word,
                    limit=_bounded_int_setting(library, "dictionary_max_results", default=16, minimum=1, maximum=50),
                    scan_length=_bounded_int_setting(library, "dictionary_scan_length", default=16, minimum=1, maximum=64),
                )
                page_index = 0
        elif command.startswith("a "):
            card_word = command[2:].strip()
            if card_word:
                print(mine_word(card_word))
                _read_input(style("按 Enter 继续", DIM))


def _reader_sasayaki_panel(
    library: Library,
    record: BookRecord | None,
    page: Page,
    player: SasayakiPlayer,
) -> None:
    if record is None:
        print("直接阅读文件时没有书架记录，无法使用 Sasayaki。")
        _read_input(style("按 Enter 继续", DIM))
        return
    data = library.sasayaki_for(record)
    match = _sasayaki_match_data(data)
    if not data or not match:
        print("这本书还没有 Sasayaki 匹配。先在 设置 -> 高级 -> Sasayaki 有声书 里匹配 SRT。")
        _read_input(style("按 Enter 继续", DIM))
        return
    playback = _sasayaki_playback(data)
    cue = (
        find_cue_for_page(match, page.text)
        or cue_at_time(match, float(playback.get("lastPosition", 0.0)))
        or (match.matches[0] if match.matches else None)
    )
    if cue is None:
        print("当前页面没有匹配到 Sasayaki 台词。")
        _read_input(style("按 Enter 继续", DIM))
        return

    while True:
        print(clear_screen(), end="")
        print(style("Sasayaki", BOLD), f"{match_rate_text(match)}")
        cue_index = match.matches.index(cue) + 1
        _print_sasayaki_cue(cue, cue_index)
        print("1. 播放这一句")
        print("2. 从这一句继续")
        print("3. 停止播放")
        print("4. 上一句")
        print("5. 下一句")
        print("0. 返回阅读")
        choice = _read_input(style("请选择：", CYAN)).strip()
        if choice == "1":
            try:
                _sasayaki_play(library, record, cue_index=cue_index, line_only=True, player_session=player)
            except Exception as exc:
                print(style(f"播放失败：{exc}", YELLOW))
            _read_input(style("按 Enter 继续", DIM))
        elif choice == "2":
            try:
                _sasayaki_play(library, record, cue_index=cue_index, player_session=player)
            except Exception as exc:
                print(style(f"播放失败：{exc}", YELLOW))
            _read_input(style("按 Enter 继续", DIM))
        elif choice == "3":
            player.stop()
            print(style("已停止", GREEN))
            _pause()
        elif choice == "4":
            cue = previous_cue(match, cue.start_time) or cue
        elif choice == "5":
            cue = next_cue(match, cue.start_time) or cue
        elif choice in {"0", "q", "Q", "返回"}:
            return
        else:
            print("没有这个 Sasayaki 选项。")


def _reader_sasayaki_current(
    library: Library,
    record: BookRecord | None,
    page: Page,
    prefer_playback: bool = False,
    player: SasayakiPlayer | None = None,
) -> tuple[dict[str, object], SasayakiMatchData, SasayakiMatch, int] | None:
    if record is None:
        return None
    data = library.sasayaki_for(record)
    match = _sasayaki_match_data(data)
    if not data or not match or not match.matches:
        return None
    playback = _sasayaki_playback(data)
    page_cue = find_cue_for_page(match, page.text)
    last_position = float(playback.get("lastPosition", 0.0))
    live_position = player.current_time() if player is not None else None
    if prefer_playback and live_position is not None:
        delay = float(playback.get("delay", 0.0))
        anchor = max(0.0, live_position - delay)
        live_cue = cue_at_time(match, anchor) or cue_at_or_before_time(match, anchor)
        if live_cue is not None:
            return data, match, live_cue, match.matches.index(live_cue) + 1
    position_cue = cue_at_time(match, last_position) if last_position > 0 else None
    if prefer_playback and position_cue is not None:
        cue = position_cue
    else:
        cue = page_cue or position_cue or match.matches[0]
    return data, match, cue, match.matches.index(cue) + 1


def _reader_sasayaki_play(
    library: Library,
    record: BookRecord | None,
    page: Page,
    player: SasayakiPlayer,
    direction: str = "current",
) -> SasayakiMatch | None:
    current = _reader_sasayaki_current(
        library,
        record,
        page,
        prefer_playback=direction != "current",
        player=player,
    )
    if current is None:
        _flash_message("这本书还没有 Sasayaki 匹配。")
        return None
    _, match, cue, _ = current
    if direction == "next":
        cue = next_cue(match, cue.start_time) or cue
    elif direction == "previous":
        cue = previous_cue(match, cue.start_time) or cue
    cue_index = match.matches.index(cue) + 1
    try:
        _sasayaki_play(library, record, cue_index=cue_index, player_session=player, quiet=True)
    except Exception as exc:
        _flash_message(f"Sasayaki 播放失败：{exc}", seconds=0.9)
        return None
    return cue


def _reader_sasayaki_toggle(
    library: Library,
    record: BookRecord | None,
    page: Page,
    player: SasayakiPlayer,
) -> SasayakiMatch | None:
    if player.is_playing():
        player.toggle_pause()
        _flash_message("Sasayaki 已暂停" if player.paused else "Sasayaki 继续播放")
        return None
    return _reader_sasayaki_play(library, record, page, player)


def _reader_sasayaki_tick(
    library: Library,
    record: BookRecord | None,
    player: SasayakiPlayer,
    current_cue: SasayakiMatch | None,
) -> SasayakiMatch | None:
    if record is None or not player.is_playing() or player.paused:
        return None
    data = library.sasayaki_for(record)
    match = _sasayaki_match_data(data)
    if not data or not match:
        return None
    position = player.current_time()
    if position is None:
        return None
    playback = _sasayaki_playback(data)
    cue_time = max(0.0, position - float(playback.get("delay", 0.0)))
    cue = cue_at_time(match, cue_time) or cue_at_or_before_time(match, cue_time)
    if cue is None or cue.id == (current_cue.id if current_cue else None):
        return None
    playback["lastPosition"] = cue.start_time
    data["playback"] = playback
    library.set_sasayaki(record, data)
    return cue


def _reader_sasayaki_seek(
    library: Library,
    record: BookRecord | None,
    player: SasayakiPlayer,
    delta_seconds: float,
) -> SasayakiMatch | None:
    if record is None:
        _flash_message("直接阅读文件时没有书架记录，无法使用 Sasayaki。")
        return None
    if not player.is_playing():
        _flash_message("Sasayaki 未在播放。")
        return None
    current = player.current_time()
    if current is None:
        _flash_message("无法读取当前播放位置。")
        return None
    target = max(0.0, current + delta_seconds)
    if not player.seek(target):
        _flash_message("当前播放器不支持终端内跳转；建议安装 mpv 或 ffplay。")
        return None
    data = library.sasayaki_for(record)
    match = _sasayaki_match_data(data)
    if not data or not match:
        return None
    playback = _sasayaki_playback(data)
    cue_time = max(0.0, target - float(playback.get("delay", 0.0)))
    cue = cue_at_time(match, cue_time) or cue_at_or_before_time(match, cue_time)
    playback["lastPosition"] = cue.start_time if cue is not None else cue_time
    data["playback"] = playback
    library.set_sasayaki(record, data)
    _flash_message(f"Sasayaki 跳转到 {format_time(cue_time)}", seconds=0.25)
    return cue


def _reader_sentence_audio(
    library: Library,
    record: BookRecord | None,
    page: Page,
    sentence: str,
    current_cue: SasayakiMatch | None,
) -> Path | None:
    if record is None:
        return None
    data = library.sasayaki_for(record)
    match = _sasayaki_match_data(data)
    if not data or not match:
        return None
    audio_path = str(data.get("audio_path", ""))
    if not audio_path:
        return None
    playback = _sasayaki_playback(data)
    cue = current_cue or find_cue_for_page(match, page.text) or cue_at_time(match, float(playback.get("lastPosition", 0.0)))
    if cue is None:
        return None
    return export_cue_audio(
        audio_path,
        data=match,
        cue=cue,
        sentence=sentence,
        output_dir=library.root / "anki-media" / "sasayaki",
        delay=float(playback.get("delay", 0.0)),
    )


def _sasayaki_chapter_offsets(record: BookRecord | None) -> list[int]:
    if record is None:
        return []
    try:
        chapters = extract_book(Path(record.stored_path)).chapters
    except Exception:
        return []
    offsets: list[int] = []
    cursor = 0
    for chapter in chapters:
        offsets.append(cursor)
        cursor += len(chapter.text) + 2
    return offsets


def _page_index_for_cue(
    pages: list[Page],
    cue: SasayakiMatch,
    chapter_offsets: list[int],
    current_index: int,
) -> int:
    cue_text = filter_sasayaki_text(cue.text)
    if cue_text and cue_text in filter_sasayaki_text(pages[current_index].text):
        return current_index
    if cue_text:
        for index, page in enumerate(pages):
            if cue_text in filter_sasayaki_text(page.text):
                return index
    if cue.chapter_index < len(chapter_offsets):
        position = chapter_offsets[cue.chapter_index] + cue.start
        for page in pages:
            if page.start_char <= position <= page.end_char:
                return page.index
    return current_index


def _reader_sasayaki_status_text(cue: SasayakiMatch | None, match: SasayakiMatchData | None = None) -> str | None:
    if cue is None:
        return None
    prefix = ""
    if match is not None and cue in match.matches:
        prefix = f"{match.matches.index(cue) + 1}/{len(match.matches)} "
    return f"{prefix}{format_time(cue.start_time)}  {cue.text}"


def _reader_toc_panel(
    title: str,
    pages: list[Page],
    current_index: int,
    chapter_marks: list[tuple[str, int]],
    initial_command: str | None = None,
) -> int:
    if not chapter_marks:
        print(clear_screen(), end="")
        print(style("目录", BOLD), title)
        print("这本书没有可用章节信息。")
        _pause()
        return current_index

    columns, rows = terminal_size()
    page_size = max(8, rows - 8)
    current_char = pages[current_index].start_char if pages else 0
    active_mark = _chapter_mark_index_for_position(chapter_marks, current_char)
    list_page = active_mark // page_size
    total_list_pages = max(1, (len(chapter_marks) + page_size - 1) // page_size)
    pending_command = initial_command.strip() if initial_command else None

    while True:
        print(clear_screen(), end="")
        total_chars = pages[-1].end_char if pages else 0
        list_page = max(0, min(total_list_pages - 1, list_page))
        start = list_page * page_size
        end = min(len(chapter_marks), start + page_size)
        print(style("目录", BOLD), title)
        print(f"当前位置: 第 {current_index + 1}/{len(pages)} 页  字符 {current_char}/{total_chars}")
        print(f"目录页: {list_page + 1}/{total_list_pages}")
        print(style("─" * min(columns, 96), CYAN))
        for index in range(start, end):
            label, position = chapter_marks[index]
            page_number = page_for_position(pages, position) + 1
            marker = ">" if index == active_mark else " "
            print(f"{marker} {index + 1:>3}. p{page_number:<4} {position:>7}  {label}")
        print(style("─" * min(columns, 96), CYAN))
        print(style("←/p 上一页目录    →/n 下一页目录    输入序号跳转    g 页码    j 字符位置    q 返回", DIM))
        if pending_command is not None:
            raw = pending_command
            pending_command = None
        else:
            raw = _read_toc_command(style("目录> ", CYAN)).strip()
        if raw in {"", "q", "Q", "back", "返回"}:
            return current_index
        if raw in {"right", "down", "n", "N"}:
            list_page = min(total_list_pages - 1, list_page + 1)
            continue
        if raw in {"left", "up", "p", "P"}:
            list_page = max(0, list_page - 1)
            continue
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(chapter_marks):
                return page_for_position(pages, chapter_marks[index - 1][1])
        if raw.startswith("g "):
            page_number = _parse_page_number(raw[2:], len(pages))
            if page_number is not None:
                return page_number
        if raw.startswith("j "):
            try:
                target = int(raw[2:].strip())
            except ValueError:
                target = -1
            if target >= 0:
                return page_for_position(pages, target)
        print("目录输入无效。")
        _pause()


def _chapter_mark_index_for_position(chapter_marks: list[tuple[str, int]], current_char: int) -> int:
    active = 0
    for index, (_, position) in enumerate(chapter_marks):
        if position > current_char:
            break
        active = index
    return active


def _reader_search_panel(
    title: str,
    text: str,
    pages: list[Page],
    current_index: int,
    initial_query: str | None = None,
) -> int:
    query = (initial_query or "").strip()
    if not query:
        query = _read_input("搜索正文：").strip()
    if not query:
        return current_index

    list_page = 0
    while True:
        matches = _find_text_matches(text, query)
        columns, rows = terminal_size()
        page_size = max(8, rows - 8)
        print(clear_screen(), end="")
        print(style("正文搜索", BOLD), title)
        print(f"关键词: {query}")
        if not matches:
            print(style("没有命中。", DIM))
            print(style("/ 新关键词    q 返回", DIM))
            raw = _read_search_command(style("搜索> ", CYAN)).strip()
            if raw.startswith("/"):
                next_query = raw[1:].strip()
                if next_query:
                    query = next_query
                    list_page = 0
                    continue
            return current_index

        active = _nearest_match_index(matches, pages[current_index].start_char)
        total_list_pages = max(1, (len(matches) + page_size - 1) // page_size)
        list_page = max(0, min(total_list_pages - 1, list_page))
        start = list_page * page_size
        end = min(len(matches), start + page_size)
        print(f"命中: {len(matches)}    结果页: {list_page + 1}/{total_list_pages}")
        print(style("─" * min(columns, 96), CYAN))
        for index in range(start, end):
            position = matches[index]
            marker = ">" if index == active else " "
            page_number = page_for_position(pages, position) + 1
            snippet = _snippet_around(text, position, len(query))
            print(f"{marker} {index + 1:>3}. p{page_number:<4} {snippet}")
        print(style("─" * min(columns, 96), CYAN))
        print(style("←/p 上一页结果    →/n 下一页结果    输入序号跳转    / 新关键词    q 返回", DIM))
        raw = _read_search_command(style("搜索> ", CYAN)).strip()
        if raw in {"", "q", "Q", "back", "返回"}:
            return current_index
        if raw in {"right", "down", "n", "N"}:
            list_page = min(total_list_pages - 1, list_page + 1)
            continue
        if raw in {"left", "up", "p", "P"}:
            list_page = max(0, list_page - 1)
            continue
        if raw.startswith("/"):
            next_query = raw[1:].strip()
            if next_query:
                query = next_query
                list_page = 0
            continue
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(matches):
                return page_for_position(pages, matches[index - 1])
        print("搜索输入无效。")
        _pause()


def _reader_highlights_panel(
    library: Library,
    record: BookRecord | None,
    text: str,
    pages: list[Page],
    current_index: int,
) -> int:
    if record is None:
        print("直接阅读文件时没有书架记录，无法保存或查看划线。")
        _pause()
        return current_index
    highlights = library.highlights_for(record)
    if not highlights:
        print("这本书还没有划线。阅读时按 h 可以保存当前页和备注。")
        _pause()
        return current_index

    list_page = 0
    while True:
        columns, rows = terminal_size()
        page_size = max(8, rows - 8)
        total_list_pages = max(1, (len(highlights) + page_size - 1) // page_size)
        list_page = max(0, min(total_list_pages - 1, list_page))
        start = list_page * page_size
        end = min(len(highlights), start + page_size)
        print(clear_screen(), end="")
        print(style("划线 / 备注", BOLD), record.title)
        print(f"结果页: {list_page + 1}/{total_list_pages}")
        print(style("─" * min(columns, 96), CYAN))
        for index in range(start, end):
            item = highlights[index]
            position = _highlight_position(item, text)
            page_number = page_for_position(pages, position) + 1
            color = str(item.get("color", "yellow"))
            color_label, color_code = HIGHLIGHT_COLORS.get(color, HIGHLIGHT_COLORS["yellow"])
            color_text = style(color_label, color_code)
            note = str(item.get("note", "")).strip()
            note_text = f"  {style(note, YELLOW)}" if note else ""
            snippet = _snippet_around(text, position, 0, fallback=str(item.get("text", "")))
            print(f"{index + 1:>3}. p{page_number:<4} {color_text}  {snippet}{note_text}")
        print(style("─" * min(columns, 96), CYAN))
        print(style("←/p 上一页    →/n 下一页    输入序号跳转    q 返回", DIM))
        raw = _read_toc_command(style("划线> ", CYAN)).strip()
        if raw in {"", "q", "Q", "back", "返回"}:
            return current_index
        if raw in {"right", "down", "n", "N"}:
            list_page = min(total_list_pages - 1, list_page + 1)
            continue
        if raw in {"left", "up", "p", "P"}:
            list_page = max(0, list_page - 1)
            continue
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(highlights):
                return page_for_position(pages, _highlight_position(highlights[index - 1], text))
        print("划线输入无效。")
        _pause()


def _find_text_matches(text: str, query: str, limit: int = 500) -> list[int]:
    needle = query.strip()
    if not needle:
        return []
    haystack = text.lower()
    target = needle.lower()
    matches: list[int] = []
    cursor = 0
    while len(matches) < limit:
        index = haystack.find(target, cursor)
        if index < 0:
            break
        matches.append(index)
        cursor = index + max(1, len(target))
    return matches


def _nearest_match_index(matches: list[int], position: int) -> int:
    if not matches:
        return 0
    for index, match in enumerate(matches):
        if match >= position:
            return index
    return len(matches) - 1


def _highlight_position(item: dict[str, object], text: str) -> int:
    raw_position = item.get("position", 0)
    try:
        position = int(raw_position)
    except (TypeError, ValueError):
        position = 0
    if position > 0:
        return position
    snippet = str(item.get("text", "")).strip()
    if snippet:
        found = text.find(snippet[:80])
        if found >= 0:
            return found
    return 0


def _parse_highlight_command(raw: str) -> tuple[str, str]:
    text = raw.strip()
    if not text:
        return "yellow", ""
    first, _, rest = text.partition(" ")
    aliases = {
        "1": "yellow",
        "黄": "yellow",
        "黄色": "yellow",
        "yellow": "yellow",
        "2": "blue",
        "蓝": "blue",
        "蓝色": "blue",
        "blue": "blue",
        "3": "green",
        "绿": "green",
        "绿色": "green",
        "green": "green",
        "4": "red",
        "红": "red",
        "红色": "red",
        "red": "red",
        "5": "purple",
        "紫": "purple",
        "紫色": "purple",
        "purple": "purple",
    }
    color = aliases.get(first.lower())
    if color is None:
        return "yellow", text
    return color, rest.strip()


def _snippet_around(text: str, position: int, length: int, radius: int = 34, fallback: str = "") -> str:
    if text and 0 <= position < len(text):
        start = max(0, position - radius)
        end = min(len(text), position + max(length, 1) + radius)
        snippet = text[start:end].replace("\n", " ").strip()
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(text) else ""
        return prefix + snippet + suffix
    fallback = fallback.replace("\n", " ").strip()
    return fallback[:80] + ("…" if len(fallback) > 80 else "")


def _flash_message(message: str, seconds: float = 0.45) -> None:
    print(style(message, YELLOW))
    time.sleep(seconds)


class _ReaderSasayakiSession:
    def __init__(self, library: Library, record: BookRecord | None) -> None:
        self.library = library
        self.record = record
        self.data = library.sasayaki_for(record) if record is not None else None
        self.match = _sasayaki_match_data(self.data)
        self.playback = _sasayaki_playback(self.data) if self.data is not None else {}
        self.audio_path = str(self.data.get("audio_path", "")) if self.data is not None else ""
        self.matches = self.match.matches if self.match is not None else []
        self.index_by_id = {cue.id: index for index, cue in enumerate(self.matches)}
        self.time_starts = [cue.start_time for cue in self.matches]
        self.ranges = self._build_ranges()
        ordered_ranges = sorted(
            (start, end, self.matches[index])
            for index, value in enumerate(self.ranges)
            if value is not None
            for start, end in [value]
        )
        self.range_starts = [item[0] for item in ordered_ranges]
        self.ordered_ranges = ordered_ranges

    def _build_ranges(self) -> list[tuple[int, int] | None]:
        if self.record is None or not self.matches:
            return [None] * len(self.matches)
        try:
            chapters = extract_book(Path(self.record.stored_path)).chapters
        except Exception:
            return [None] * len(self.matches)
        chapter_maps: list[tuple[int, list[int]]] = []
        absolute_offset = 0
        for chapter in chapters:
            _, positions = filter_sasayaki_text_with_positions(chapter.text)
            chapter_maps.append((absolute_offset, positions))
            absolute_offset += len(chapter.text) + 2
        ranges: list[tuple[int, int] | None] = []
        for cue in self.matches:
            if cue.chapter_index >= len(chapter_maps):
                ranges.append(None)
                continue
            offset, positions = chapter_maps[cue.chapter_index]
            start_index = cue.start
            end_index = cue.start + max(1, cue.length) - 1
            if start_index < 0 or start_index >= len(positions):
                ranges.append(None)
                continue
            end_index = min(end_index, len(positions) - 1)
            ranges.append((offset + positions[start_index], offset + positions[end_index] + 1))
        return ranges

    def range_for(self, cue: SasayakiMatch | None) -> tuple[int, int] | None:
        if cue is None:
            return None
        index = self.index_by_id.get(cue.id)
        return self.ranges[index] if index is not None else None

    def cue_for_page(self, page: Page) -> SasayakiMatch | None:
        if self.ordered_ranges:
            index = max(0, bisect_right(self.range_starts, page.start_char) - 1)
            while index < len(self.ordered_ranges):
                start, end, cue = self.ordered_ranges[index]
                if start >= page.end_char:
                    break
                if end > page.start_char:
                    return cue
                index += 1
        if self.match is not None:
            return find_cue_for_page(self.match, page.text)
        return None

    def cue_at(self, seconds: float) -> SasayakiMatch | None:
        index = bisect_right(self.time_starts, seconds + 0.01) - 1
        return self.matches[index] if index >= 0 else None

    def current(self, page: Page, player: SasayakiPlayer, prefer_playback: bool = False) -> SasayakiMatch | None:
        if not self.matches:
            return None
        if prefer_playback:
            live = player.estimated_time()
            if live is not None:
                cue = self.cue_at(max(0.0, live - float(self.playback.get("delay", 0.0))))
                if cue is not None:
                    return cue
            last = float(self.playback.get("lastPosition", 0.0))
            if last > 0:
                cue = self.cue_at(last)
                if cue is not None:
                    return cue
        return self.cue_for_page(page) or self.cue_at(float(self.playback.get("lastPosition", 0.0))) or self.matches[0]

    def play(
        self,
        page: Page,
        player: SasayakiPlayer,
        current_cue: SasayakiMatch | None,
        direction: str = "current",
    ) -> SasayakiMatch | None:
        if not self.audio_path or not self.matches:
            return None
        cue = current_cue or self.current(page, player, prefer_playback=direction != "current")
        if cue is None:
            return None
        index = self.index_by_id.get(cue.id, 0)
        if direction == "next":
            index = min(len(self.matches) - 1, index + 1)
        elif direction == "previous":
            index = max(0, index - 1)
        cue = self.matches[index]
        target = max(0.0, cue.start_time + float(self.playback.get("delay", 0.0)))
        same_audio = str(player.audio_path or "") == self.audio_path
        if not (player.is_playing() and same_audio and player.seek(target)):
            player.play(self.audio_path, start_time=target, rate=float(self.playback.get("rate", 1.0)))
        self.playback["lastPosition"] = cue.start_time
        if self.data is not None:
            self.data["playback"] = self.playback
        return cue

    def toggle(
        self,
        page: Page,
        player: SasayakiPlayer,
        current_cue: SasayakiMatch | None,
    ) -> SasayakiMatch | None:
        if player.is_playing():
            player.toggle_pause()
            return current_cue
        return self.play(page, player, current_cue)

    def tick(self, player: SasayakiPlayer, current_cue: SasayakiMatch | None) -> SasayakiMatch | None:
        if not player.is_playing() or player.paused:
            return None
        position = player.estimated_time()
        if position is None:
            return None
        cue = self.cue_at(max(0.0, position - float(self.playback.get("delay", 0.0))))
        if cue is None or cue.id == (current_cue.id if current_cue else None):
            return None
        self.playback["lastPosition"] = cue.start_time
        if self.data is not None:
            self.data["playback"] = self.playback
        return cue

    def seek(self, player: SasayakiPlayer, delta_seconds: float) -> SasayakiMatch | None:
        current = player.current_time()
        if current is None:
            return None
        target = max(0.0, current + delta_seconds)
        if not player.seek(target):
            return None
        cue_time = max(0.0, target - float(self.playback.get("delay", 0.0)))
        cue = self.cue_at(cue_time)
        self.playback["lastPosition"] = cue.start_time if cue is not None else cue_time
        if self.data is not None:
            self.data["playback"] = self.playback
        return cue

    def page_index_for_cue(self, pages: list[Page], cue: SasayakiMatch, current_index: int) -> int:
        cue_range = self.range_for(cue)
        if cue_range is not None:
            return page_for_position(pages, cue_range[0])
        return _page_index_for_cue(pages, cue, _sasayaki_chapter_offsets(self.record), current_index)

    def status_text(self, cue: SasayakiMatch | None) -> str | None:
        if cue is None:
            return None
        index = self.index_by_id.get(cue.id)
        prefix = f"{index + 1}/{len(self.matches)} " if index is not None else ""
        return f"{prefix}{format_time(cue.start_time)}  {cue.text}"


def interactive_loop(
    title: str,
    text: str,
    pages: list[Page],
    record: BookRecord | None,
    vertical: bool = False,
    start_page: int = 0,
    chapter_marks: list[tuple[str, int]] | None = None,
    reader_width: int | None = None,
    reader_lines: int | None = None,
) -> int:
    library = Library()
    page_index = start_page
    session_started = time.monotonic()
    session_start_char = pages[start_page].start_char if pages else 0
    sasayaki_player = SasayakiPlayer()
    sasayaki = _ReaderSasayakiSession(library, record)
    current_cue: SasayakiMatch | None = None
    needs_render = True
    last_size = terminal_size()

    with reader_screen():
        try:
            while True:
                current_size = terminal_size()
                if current_size != last_size:
                    anchor_range = sasayaki.range_for(current_cue)
                    anchor = anchor_range[0] if anchor_range is not None else pages[page_index].start_char
                    pages = paginate(text, width=reader_width, lines_per_page=reader_lines)
                    page_index = page_for_position(pages, anchor)
                    last_size = current_size
                    needs_render = True

                page = pages[page_index]
                if needs_render:
                    display_cue = current_cue or sasayaki.cue_for_page(page)
                    draw_screen(
                        render_page(
                            title,
                            page,
                            len(pages),
                            vertical=vertical,
                            highlight=display_cue.text if display_cue else None,
                            highlight_range=sasayaki.range_for(display_cue),
                            sasayaki_status=sasayaki.status_text(display_cue),
                        )
                    )
                    needs_render = False
                command = _read_reader_command("", timeout=0.1, echo=False)
                tick_cue = sasayaki.tick(sasayaki_player, current_cue)
                if tick_cue is not None:
                    current_cue = tick_cue
                    page_index = sasayaki.page_index_for_cue(pages, tick_cue, page_index)
                    needs_render = True
                    if command is None:
                        continue
                    page = pages[page_index]
                if command is None:
                    continue
                command = command.strip()
                if command == "right":
                    page_index = min(len(pages) - 1, page_index + 1)
                    if not sasayaki_player.is_playing():
                        current_cue = None
                elif command == "left":
                    page_index = max(0, page_index - 1)
                    if not sasayaki_player.is_playing():
                        current_cue = None
                elif command == "down":
                    cue = sasayaki.play(page, sasayaki_player, current_cue, direction="next")
                    if cue is not None:
                        current_cue = cue
                        page_index = sasayaki.page_index_for_cue(pages, cue, page_index)
                elif command == "up":
                    cue = sasayaki.play(page, sasayaki_player, current_cue, direction="previous")
                    if cue is not None:
                        current_cue = cue
                        page_index = sasayaki.page_index_for_cue(pages, cue, page_index)
                elif command in {"", "space"}:
                    cue = sasayaki.toggle(page, sasayaki_player, current_cue)
                    if cue is not None:
                        current_cue = cue
                        page_index = sasayaki.page_index_for_cue(pages, cue, page_index)
                elif command in {"[", "]", "{", "}"}:
                    step = _sasayaki_seek_step(library)
                    delta = -step if command == "[" else step if command == "]" else -30 if command == "{" else 30
                    cue = sasayaki.seek(sasayaki_player, float(delta))
                    if cue is not None:
                        current_cue = cue
                        page_index = sasayaki.page_index_for_cue(pages, cue, page_index)
                elif command.startswith("j "):
                    delta = _parse_relative_seconds(command[2:])
                    if delta is not None:
                        cue = sasayaki.seek(sasayaki_player, delta)
                        if cue is not None:
                            current_cue = cue
                            page_index = sasayaki.page_index_for_cue(pages, cue, page_index)
                elif command in {"q", "quit", "exit"}:
                    break
                elif command in {"r", "v"}:
                    vertical = not vertical
                elif command == "y":
                    _reader_sasayaki_panel(library, record, page, sasayaki_player)
                elif _is_toc_command(command):
                    page_index = _reader_toc_panel(
                        title,
                        pages,
                        page_index,
                        chapter_marks or [],
                        initial_command=_toc_initial_command(command),
                    )
                    if not sasayaki_player.is_playing():
                        current_cue = None
                elif command.startswith("f "):
                    query = command[2:].strip()
                    page_index = _reader_search_panel(title, text, pages, page_index, initial_query=query)
                    if not sasayaki_player.is_playing():
                        current_cue = None
                elif command == "l":
                    page_index = _reader_highlights_panel(library, record, text, pages, page_index)
                    if not sasayaki_player.is_playing():
                        current_cue = None
                elif command.startswith("/"):
                    word = command[1:].strip()
                    if word:
                        _show_lookup(word, library)
                elif command.startswith("a "):
                    word = command[2:].strip()
                    sentence = sentence_around(page.text, word)
                    sentence_audio = _reader_sentence_audio(library, record, page, sentence, current_cue)
                    print(
                        mine_word(
                            word,
                            sentence=sentence,
                            sentence_audio_path=str(sentence_audio or ""),
                            document_title=record.title if record else title,
                        )
                    )
                    _read_input(style("按 Enter 继续", DIM))
                elif command.startswith("h"):
                    color, note = _parse_highlight_command(command[1:].strip())
                    if record is None:
                        print("直接阅读文件时没有书架记录，无法保存划线。")
                    else:
                        library.add_highlight(record, page.text, note, position=page.start_char, color=color)
                        color_label, color_code = HIGHLIGHT_COLORS[color]
                        print(style("已划线当前页", GREEN), style(color_label, color_code))
                    _read_input(style("按 Enter 继续", DIM))
                elif command == "s":
                    chars = max(0, page.end_char - session_start_char)
                    seconds = max(0.1, time.monotonic() - session_started)
                    print(f"本次阅读：{chars} 字符，{seconds / 60:.1f} 分钟，{int(chars / (seconds / 60))} 字符/分钟")
                    _read_input(style("按 Enter 继续", DIM))
                elif command.startswith("g "):
                    page_number = _parse_page_number(command[2:], len(pages))
                    if page_number is not None:
                        page_index = page_number
                        if not sasayaki_player.is_playing():
                            current_cue = None
                needs_render = True
        finally:
            sasayaki_player.stop()

    if record is not None:
        end_char = pages[page_index].start_char
        characters_delta = max(0, end_char - session_start_char)
        seconds = max(0.0, time.monotonic() - session_started)
        library.touch_progress(record, end_char, characters_delta, seconds)
    print(style("已保存阅读进度。", GREEN))
    return 0


def menu_loop() -> int:
    while True:
        library = Library()
        print(clear_screen(), end="")
        print(banner())
        print(style(_ui("main_title", library), BOLD))
        print(f"1. {_ui('books', library)}")
        print(f"2. {_ui('dictionary', library)}")
        print(f"3. {_ui('settings', library)}")
        print(f"0. {_ui('exit', library)}")
        choice = _read_input(style(_ui("choose", library), CYAN)).strip()

        if choice == "1":
            books_menu()
        elif choice == "2":
            dictionary_menu()
        elif choice == "3":
            settings_loop()
        elif choice in {"0", "q", "Q", "退出", "exit"}:
            print(style(_ui("exited", library), GREEN))
            return 0
        else:
            print("没有这个选项。")
            _pause()


def books_menu() -> int:
    while True:
        library = Library()
        print(clear_screen(), end="")
        print(banner())
        print(style(_ui("books", library), BOLD))
        print(f"1. {_ui('shelf_read', library)}")
        print(f"2. {_ui('import_epub', library)}")
        print(f"3. {_ui('import_folder', library)}")
        print(f"4. {_ui('manage_books', library)}")
        print("5. 管理书架")
        print(f"6. {_ui('book_settings', library)}")
        print("7. 批量操作")
        print(f"0. {_ui('back', library)}")
        choice = _read_input(style(_ui("choose", library), CYAN)).strip()
        if choice == "1":
            _menu_shelf_read()
        elif choice == "2":
            _menu_import_book()
        elif choice == "3":
            _settings_import_books()
        elif choice == "4":
            _book_management_menu()
        elif choice == "5":
            _shelf_management_menu()
        elif choice == "6":
            _bookshelf_settings()
        elif choice == "7":
            _bulk_book_management_menu()
        elif choice in {"0", "q", "Q", "返回", "back"}:
            return 0
        else:
            print("没有这个书库选项。")
            _pause()


def dictionary_menu() -> int:
    while True:
        library = Library()
        print(clear_screen(), end="")
        print(banner())
        print(style(_ui("dictionary", library), BOLD))
        print(f"1. {_ui('search', library)}")
        print(f"2. {_ui('import_dictionary', library)}")
        print(f"3. {_ui('dictionary_list', library)}")
        print(f"4. {_ui('dictionary_settings', library)}")
        print(f"0. {_ui('back', library)}")
        choice = _read_input(style(_ui("choose", library), CYAN)).strip()
        if choice == "1":
            word = _read_input("请输入要查的词：").strip()
            if word:
                _show_lookup(word, library)
        elif choice == "2":
            _dictionary_import_prompt()
        elif choice == "3":
            _dictionary_list()
        elif choice == "4":
            _dictionary_settings()
        elif choice in {"0", "q", "Q", "返回", "back"}:
            return 0
        else:
            print("没有这个查词选项。")
            _pause()


def _menu_import_book() -> None:
    library = Library()
    book_dir = Path(library.settings["book_path"]).expanduser()
    files = find_book_files(book_dir)
    print(style("书籍目录", BOLD), book_dir)
    if files:
        print("可导入文件：")
        for index, file_path in enumerate(files[:30], start=1):
            print(f"{index:>2}. {file_path.relative_to(book_dir) if file_path.is_relative_to(book_dir) else file_path}")
        if len(files) > 30:
            print(f"... 还有 {len(files) - 30} 个文件未显示")
    else:
        print("没有扫描到 epub/txt/md/html 文件。可以在设置里改小说目录。")
    raw = _read_input("输入序号、路径，或 a 全部导入（留空返回）：").strip().strip('"')
    if not raw:
        return
    if raw.lower() == "a":
        targets = files
        if not targets:
            _pause()
            return
        imported, skipped, failed = library.import_books_detailed(targets)
        _print_book_import_summary(imported, skipped, failed)
        _pause()
        return
    if raw.isdigit() and files:
        index = int(raw)
        if index < 1 or index > len(files):
            print("序号超出范围。")
            _pause()
            return
        path = str(files[index - 1])
    else:
        path = raw
    title = _read_input("自定义标题（可留空）：").strip() or None
    try:
        record = library.import_book(path, title=title)
    except Exception as exc:
        print(style(f"导入失败：{exc}", RED))
    else:
        print(style("已导入", GREEN), f"{record.title} [{record.id}]")
    _pause()


def _menu_shelf_read() -> None:
    library = Library()
    books = _sorted_books(library)
    if not books:
        print("书架是空的。先用 2 导入一本书。")
        _pause()
        return
    print(style("Hoshi 终端书架", BOLD))
    _print_shelf_sections(library)
    query = _read_input("输入序号或标题片段开始阅读（留空打开最近一本）：").strip() or None
    record = _find_book_for_input(library, query)
    if record is None:
        print("找不到这本书。")
        _pause()
        return
    _open_book_record(library, record)
    _pause("已返回。按 Enter 继续")


def _book_management_menu() -> None:
    while True:
        library = Library()
        books = _sorted_books(library)
        if not books:
            print("书架是空的。")
            _pause()
            return
        print(style("管理书籍", BOLD))
        _print_book_choices(books)
        query = _read_input("输入书籍序号、标题片段或 id（留空返回）：").strip()
        if not query:
            return
        record = _find_book_for_input(library, query)
        if record is None:
            print("找不到这本书。")
            _pause()
            continue
        _book_action_menu(record)


def _book_action_menu(record: BookRecord) -> None:
    while True:
        library = Library()
        current = _find_book_for_input(library, record.id)
        if current is None:
            print("这本书已经不在书架里。")
            _pause()
            return
        record = current
        print(style(record.title, BOLD))
        print(f"id: {record.id}")
        print(f"文件: {record.stored_path}")
        print(f"进度: {summarize_text_progress(record.position, _safe_text_for_progress(record))}")
        print("1. 重命名")
        print("2. 删除")
        print("3. 标记已读")
        print("4. 同步本书进度")
        print("5. 匹配 Sasayaki 有声书")
        print("6. 移动到书架")
        print("0. 返回")
        choice = _read_input(style("请选择：", CYAN)).strip()
        if choice == "1":
            title = _read_input("新标题：").strip()
            if library.rename_book(record.id, title):
                print(style("已重命名", GREEN), title)
            else:
                print(style("重命名失败。", RED))
            _pause()
        elif choice == "2":
            confirm = _read_input(f"确认删除《{record.title}》？输入 y 删除：").strip().lower()
            if confirm == "y":
                if library.delete_book(record.id):
                    print(style("已删除", GREEN), record.title)
                    _pause()
                    return
                print(style("删除失败。", RED))
                _pause()
        elif choice == "3":
            if library.mark_book_read(record.id):
                print(style("已标记为已读", GREEN), record.title)
            else:
                print(style("标记失败。", RED))
            _pause()
        elif choice == "4":
            try:
                print(_sync_one_book(library, record))
            except Exception as exc:
                print(style(f"同步失败：{exc}", RED))
            _pause()
        elif choice == "5":
            srt = _read_input("SRT 路径（留空返回）：").strip().strip('"')
            if not srt:
                continue
            audio = _read_input("音频路径或 URL（可留空）：").strip().strip('"') or None
            window = _read_input("搜索窗口（默认 200）：").strip()
            try:
                _sasayaki_match(
                    library,
                    record,
                    srt,
                    audio_path=audio,
                    search_window=int(window) if window else 200,
                )
            except Exception as exc:
                print(style(f"Sasayaki 匹配失败：{exc}", RED))
            _pause()
        elif choice == "6":
            _move_book_to_shelf_prompt(library, record)
        elif choice in {"0", "q", "Q", "返回"}:
            return
        else:
            print("没有这个书籍操作。")
            _pause()


def _bulk_book_management_menu() -> None:
    library = Library()
    books = _sorted_books(library)
    if not books:
        print("书架是空的。")
        _pause()
        return
    print(style("批量操作", BOLD))
    _print_book_choices(books)
    raw = _read_input("输入书籍序号，支持空格/逗号/范围（例如 1 3-5，留空返回）：").strip()
    selected = _parse_book_selection(raw, books)
    if not selected:
        return
    print(f"已选择 {len(selected)} 本：")
    for record in selected:
        print(f"- {record.title}")
    print("1. 移动到书架")
    print("2. 标记已读")
    print("3. 删除")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    if choice == "1":
        target = _select_shelf_target(library)
        if target == "__cancel__":
            return
        for record in selected:
            library.move_book_to_shelf(record.id, target)
        print(style("已移动", GREEN), f"{len(selected)} 本 -> {target or '未归类'}")
        _pause()
    elif choice == "2":
        count = sum(1 for record in selected if library.mark_book_read(record.id))
        print(style("已标记为已读", GREEN), f"{count} 本")
        _pause()
    elif choice == "3":
        confirm = _read_input(f"确认删除 {len(selected)} 本？输入 y 删除：").strip().lower()
        if confirm == "y":
            count = sum(1 for record in selected if library.delete_book(record.id))
            print(style("已删除", GREEN), f"{count} 本")
            _pause()


def _open_book_record(library: Library, record: BookRecord) -> None:
    try:
        extracted = extract_book(Path(record.stored_path))
    except Exception as exc:
        print(style(f"打开失败：{exc}", RED))
        return
    title = record.title or extracted.title
    text = extracted.text
    pages = paginate(
        text,
        width=_optional_int_setting(library, "reader_width"),
        lines_per_page=_optional_int_setting(library, "reader_lines"),
    )
    start_page = page_for_position(pages, record.position)
    vertical = library.settings["reader_vertical"] == "true"
    interactive_loop(
        title,
        text,
        pages,
        record,
        vertical,
        start_page=start_page,
        chapter_marks=_chapter_marks_from_extracted(extracted),
    )


def _menu_lookup() -> None:
    library = Library()
    dictionary = DictionaryManager(library.dictionary_file)
    default_path = library.settings["dictionary_path"]
    print(style("词典目录", BOLD), default_path)
    print(f"已导入词条：{dictionary.entry_count()}")
    import_path = _read_input("导入词典路径；输入 d 导入当前词典目录；留空跳过：").strip().strip('"')
    if import_path.lower() == "d":
        import_path = default_path
    if import_path:
        try:
            count = dictionary.import_yomitan(import_path)
        except Exception as exc:
            print(style(f"词典导入失败：{exc}", RED))
        else:
            print(style("词典已导入", GREEN), f"新增 {count} 条")
    word = _read_input("请输入要查的词：").strip()
    if word:
        _show_lookup(word, library)
    else:
        _pause()


def _dictionary_import_prompt() -> None:
    library = Library()
    default_path = library.settings["dictionary_path"]
    print(style("词典目录", BOLD), default_path)
    import_path = _read_input("导入词典路径；输入 d 导入当前词典目录；留空返回：").strip().strip('"')
    if import_path.lower() == "d":
        import_path = default_path
    if not import_path:
        return
    try:
        count = DictionaryManager(library.dictionary_file).import_yomitan(import_path)
    except Exception as exc:
        print(style(f"词典导入失败：{exc}", RED))
    else:
        print(style("词典已导入", GREEN), f"新增 {count} 条")
    _pause()


def _dictionary_list() -> None:
    library = Library()
    manager = DictionaryManager(library.dictionary_file)
    print(style("辞典", BOLD))
    print(f"词典目录: {library.settings['dictionary_path']}")
    print(f"已导入词条: {manager.entry_count()}")
    _print_dictionary_table(manager)
    sources = find_yomitan_sources(library.settings["dictionary_path"])
    print(f"目录内可导入词典源: {len(sources)}")
    for index, source in enumerate(sources[:20], start=1):
        print(f"{index:>2}. {source.name}")
    if len(sources) > 20:
        print(f"... 还有 {len(sources) - 20} 个")
    _pause()


def _dictionary_settings() -> None:
    while True:
        library = Library()
        print(style("辞典设置", BOLD))
        print(f"词典目录: {library.settings['dictionary_path']}")
        print(
            "查词参数: "
            f"最大结果 {library.settings.get('dictionary_max_results', '16')} / "
            f"扫描长度 {library.settings.get('dictionary_scan_length', '16')}"
        )
        print("1. 设置词典目录")
        print("2. 扫描并导入词典目录")
        print("3. 查看词典与优先级")
        print("4. 调整词典优先级")
        print("5. 启用 / 停用词典")
        print("6. 查词参数")
        print("0. 返回")
        choice = _read_input(style("请选择：", CYAN)).strip()
        if choice == "1":
            _menu_set_path("dictionary_path", "词典目录")
        elif choice == "2":
            _settings_import_dictionaries()
        elif choice == "3":
            _dictionary_list()
        elif choice == "4":
            _dictionary_priority_menu()
        elif choice == "5":
            _dictionary_toggle_menu()
        elif choice == "6":
            _dictionary_behavior_settings()
        elif choice in {"0", "q", "Q", "返回"}:
            return
        else:
            print("没有这个辞典设置项。")
            _pause()


def _dictionary_priority_menu() -> None:
    manager = DictionaryManager(Library().dictionary_file)
    dict_type = _choose_dictionary_type()
    if not dict_type:
        return
    dictionaries = manager.dictionaries(dict_type)
    if not dictionaries:
        print("这个分类还没有导入词典。")
        _pause()
        return
    _print_dictionary_table(manager, dict_type)
    raw = _read_input("输入 原序号 新序号（例如 3 1，留空返回）：").strip()
    if not raw:
        return
    parts = raw.split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        print("格式应为两个数字。")
        _pause()
        return
    try:
        manager.move_dictionary(dict_type, int(parts[0]) - 1, int(parts[1]) - 1)
    except ValueError as exc:
        print(style(str(exc), RED))
    else:
        print(style("已调整词典优先级", GREEN))
    _pause()


def _dictionary_toggle_menu() -> None:
    manager = DictionaryManager(Library().dictionary_file)
    dict_type = _choose_dictionary_type()
    if not dict_type:
        return
    dictionaries = manager.dictionaries(dict_type)
    if not dictionaries:
        print("这个分类还没有导入词典。")
        _pause()
        return
    _print_dictionary_table(manager, dict_type)
    raw = _read_input("输入序号切换启用状态（留空返回）：").strip()
    if not raw:
        return
    if not raw.isdigit() or int(raw) < 1 or int(raw) > len(dictionaries):
        print("词典序号无效。")
        _pause()
        return
    dictionary = dictionaries[int(raw) - 1]
    manager.set_enabled(dictionary.id, not dictionary.enabled)
    print(style("已保存", GREEN), f"{dictionary.title}: {'停用' if dictionary.enabled else '启用'}")
    _pause()


def _dictionary_behavior_settings() -> None:
    library = Library()
    print(style("查词参数", BOLD))
    print(f"1. 最大结果数: {library.settings.get('dictionary_max_results', '16')}  (1-50)")
    print(f"2. 扫描长度: {library.settings.get('dictionary_scan_length', '16')}  (1-64)")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    if choice == "1":
        _menu_set_numeric_setting("dictionary_max_results", "最大结果数", 1, 50)
    elif choice == "2":
        _menu_set_numeric_setting("dictionary_scan_length", "扫描长度", 1, 64)


def _choose_dictionary_type() -> str | None:
    print("1. Term / 释义")
    print("2. Frequency / 频率")
    print("3. Pitch / 音高")
    raw = _read_input(style("选择分类：", CYAN)).strip()
    if not raw:
        return None
    try:
        return normalize_dictionary_type(raw)
    except ValueError as exc:
        print(style(str(exc), RED))
        _pause()
        return None


def _print_dictionary_table(manager: DictionaryManager, dict_type: str | None = None) -> None:
    types = [dict_type] if dict_type else list(DICTIONARY_TYPES)
    for current_type in types:
        dictionaries = manager.dictionaries(current_type)
        print(style(TYPE_LABELS[current_type], BOLD))
        if not dictionaries:
            print("  未导入")
            continue
        for index, dictionary in enumerate(dictionaries, start=1):
            state = "开" if dictionary.enabled else "关"
            revision = f"  {style(dictionary.revision, DIM)}" if dictionary.revision else ""
            print(f"{index:>2}. [{state}] {dictionary.title}  {dictionary.entry_count} 条{revision}")


def _bookshelf_settings() -> None:
    library = Library()
    book_dir = Path(library.settings["book_path"]).expanduser()
    files = find_book_files(book_dir)
    sort_label = "标题" if library.settings.get("bookshelf_sort") == "title" else "最近阅读"
    print(style("书库设置", BOLD))
    print(f"小说目录: {book_dir}")
    print(f"目录内可导入文件: {len(files)}")
    print(f"排序: {sort_label}")
    print(f"正在阅读分组: {'开' if library.settings.get('bookshelf_show_reading') == 'true' else '关'}")
    print("1. 设置小说目录")
    print("2. 扫描并导入小说目录")
    print("3. 切换排序")
    print("4. 切换正在阅读分组")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    if choice == "1":
        _menu_set_path("book_path", "小说目录")
    elif choice == "2":
        _settings_import_books()
    elif choice == "3":
        current = library.settings.get("bookshelf_sort")
        library.set_setting("bookshelf_sort", "title" if current != "title" else "recent")
        print(style("已保存", GREEN), "排序：" + ("标题" if current != "title" else "最近阅读"))
        _pause()
    elif choice == "4":
        current = library.settings.get("bookshelf_show_reading") == "true"
        library.set_setting("bookshelf_show_reading", "false" if current else "true")
        print(style("已保存", GREEN), "正在阅读分组：" + ("关" if current else "开"))
        _pause()


def _menu_mine() -> None:
    word = _read_input("请输入要制卡的词：").strip()
    if not word:
        return
    sentence = _read_input("例句（可留空）：").strip()
    note = _read_input("备注（可留空）：").strip()
    print(mine_word(word, sentence=sentence, note=note))
    _pause()


def _menu_stats_doctor() -> None:
    library = Library()
    print(_statistics_report(library.statistics))
    columns, rows = terminal_size()
    print()
    print(style("诊断", BOLD))
    print(f"Python: {sys.version.split()[0]}")
    print(f"数据目录: {library.root}")
    print(f"终端尺寸: {columns}x{rows}")
    print(f"词典文件: {library.dictionary_file}")
    print(style("诊断结果", YELLOW), "正常")
    _pause()


def settings_loop() -> int:
    while True:
        library = Library()
        print(clear_screen(), end="")
        print(banner())
        print(style(_ui("settings", library), BOLD))
        print(f"1. {_ui('dictionary_settings', library)}")
        print(f"2. {_ui('anki', library)}")
        print(f"3. {_ui('appearance', library)}")
        print(f"4. {_ui('advanced', library)}")
        print(f"5. {_ui('doctor', library)}")
        print(f"6. {_ui('about', library)}")
        print(f"0. {_ui('main_back', library)}")
        choice = _read_input(style(_ui("choose", library), CYAN)).strip()
        if choice == "1":
            _dictionary_settings()
        elif choice == "2":
            _settings_anki()
        elif choice == "3":
            _settings_appearance()
        elif choice == "4":
            advanced_menu()
        elif choice == "5":
            cmd_doctor(argparse.Namespace())
            _pause()
        elif choice == "6":
            _settings_about()
        elif choice in {"0", "q", "Q", "返回", "back"}:
            return 0
        else:
            print("没有这个设置项。")
            _pause()


def _menu_set_path(key: str, label: str) -> None:
    library = Library()
    current = library.settings[key]
    raw = _read_input(f"请输入新的{label}（当前：{current}）：").strip().strip('"')
    if not raw:
        return
    path = Path(raw).expanduser()
    if not path.exists():
        print(style("路径不存在，已保存但暂时无法使用。", YELLOW))
    library.set_setting(key, path)
    print(style("已保存", GREEN), f"{label}: {path}")
    _pause()


def _settings_import_books() -> None:
    library = Library()
    book_dir = Path(library.settings["book_path"]).expanduser()
    files = find_book_files(book_dir)
    if not files:
        print(f"没有在 {book_dir} 找到可导入小说。")
        _pause()
        return
    print(f"找到 {len(files)} 个可导入文件。")
    confirm = _read_input("输入 y 全部导入：").strip().lower()
    if confirm != "y":
        return
    imported, skipped, failed = library.import_books_detailed(files)
    _print_book_import_summary(imported, skipped, failed)
    _pause()


def _print_book_import_summary(
    imported: list[BookRecord],
    skipped: list[Path],
    failed: list[tuple[Path, str]],
) -> None:
    print(style("批量导入完成", GREEN), f"新增 {len(imported)} 本，跳过 {len(skipped)} 本，失败 {len(failed)} 本")
    if failed:
        print(style("失败项", RED))
        for path, message in failed[:10]:
            print(f"- {path}: {message}")
        if len(failed) > 10:
            print(f"... 还有 {len(failed) - 10} 个失败项")


def _settings_import_dictionaries() -> None:
    library = Library()
    dictionary_dir = Path(library.settings["dictionary_path"]).expanduser()
    sources = find_yomitan_sources(dictionary_dir)
    if not sources:
        print(f"没有在 {dictionary_dir} 找到 Yomitan 词典 zip 或目录。")
        _pause()
        return
    print(f"找到 {len(sources)} 个词典源。")
    for index, source in enumerate(sources[:25], start=1):
        print(f"{index:>2}. {source.relative_to(dictionary_dir) if source.is_relative_to(dictionary_dir) else source}")
    if len(sources) > 25:
        print(f"... 还有 {len(sources) - 25} 个词典源未显示")
    confirm = _read_input("输入 y 全部导入（大词典可能需要一会）：").strip().lower()
    if confirm != "y":
        return
    manager = DictionaryManager(library.dictionary_file)
    total = 0
    for source in sources:
        try:
            count = manager.import_yomitan(source)
        except Exception as exc:
            print(style(f"跳过 {source.name}: {exc}", YELLOW))
            continue
        total += count
        print(f"{source.name}: 新增 {count} 条")
    print(style("词典导入完成", GREEN), f"总新增 {total} 条")
    _pause()


def _settings_anki() -> None:
    while True:
        library = Library()
        settings = library.settings
        print(clear_screen(), end="")
        print(banner())
        print(style("Anki", BOLD))
        print(f"制卡模式: {settings['anki_mode']}")
        print(f"牌组: {settings['anki_deck']}")
        print(f"模板: {settings['anki_model']}")
        print("1. 制卡一个词")
        print("2. AnkiConnect")
        print("3. 修改牌组")
        print("4. 修改模板")
        print("5. 修改字段")
        print("6. 词语音频")
        print("0. 返回")
        choice = _read_input(style("请选择：", CYAN)).strip()
        if choice == "1":
            _menu_mine()
        elif choice == "2":
            _settings_ankiconnect()
        elif choice == "3":
            _menu_set_raw_setting("anki_deck", "牌组")
        elif choice == "4":
            _menu_set_raw_setting("anki_model", "模板")
        elif choice == "5":
            _menu_set_raw_setting("anki_front_field", "正面字段")
            _menu_set_raw_setting("anki_back_field", "背面字段")
        elif choice == "6":
            _settings_audio()
        elif choice in {"0", "q", "Q", "返回"}:
            return
        else:
            print("没有这个 Anki 选项。")
            _pause()


def _settings_ankiconnect() -> None:
    library = Library()
    settings = library.settings
    print(style("AnkiConnect 设置", BOLD))
    print(f"URL: {settings['ankiconnect_url']}")
    print(f"模式: {settings['anki_mode']}  (csv / ankiconnect / both)")
    print(f"牌组: {settings['anki_deck']}")
    print(f"模板: {settings['anki_model']}")
    print(f"正面字段: {settings['anki_front_field']}")
    print(f"背面字段: {settings['anki_back_field']}")
    print(f"标签: {settings['anki_tag']}")
    print(f"允许重复: {'是' if settings.get('anki_allow_duplicates') == 'true' else '否'}")
    print(f"重复范围: {_anki_duplicate_scope_label(settings.get('anki_duplicate_scope', 'collection'))}")
    print(f"跨模板检查: {'开' if settings.get('anki_check_all_models') == 'true' else '关'}")
    print(f"添加后同步: {'开' if settings.get('anki_force_sync') == 'true' else '关'}")
    print()
    print("1. 修改 URL")
    print("2. 修改模式")
    print("3. 修改牌组")
    print("4. 修改模板")
    print("5. 修改字段")
    print("6. 测试连接")
    print("7. 从 AnkiConnect 拉取牌组和模板")
    print("8. 修改重复检查范围")
    print("9. 启用/停用跨模板重复检查")
    print("10. 启用/停用允许重复")
    print("11. 启用/停用添加后同步")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    if choice == "1":
        _menu_set_raw_setting("ankiconnect_url", "AnkiConnect URL")
    elif choice == "2":
        raw = _read_input("模式 csv / ankiconnect / both：").strip().lower()
        if raw in {"csv", "ankiconnect", "both"}:
            library.set_setting("anki_mode", raw)
            print(style("已保存", GREEN), raw)
        else:
            print("模式无效。")
        _pause()
    elif choice == "3":
        _menu_set_raw_setting("anki_deck", "牌组")
    elif choice == "4":
        _menu_set_raw_setting("anki_model", "模板")
    elif choice == "5":
        _menu_set_raw_setting("anki_front_field", "正面字段")
        _menu_set_raw_setting("anki_back_field", "背面字段")
    elif choice == "6":
        anki = settings_from_dict(settings)
        try:
            connected_version = ankiconnect_version(anki.url)
        except AnkiConnectError as exc:
            print(style(f"连接失败：{exc}", YELLOW))
        else:
            print(style("连接成功", GREEN), f"AnkiConnect v{connected_version}")
        _pause()
    elif choice == "7":
        _settings_fetch_ankiconnect_config(library, settings)
    elif choice == "8":
        _settings_anki_duplicate_scope(library)
    elif choice == "9":
        current = settings.get("anki_check_all_models") == "true"
        library.set_setting("anki_check_all_models", "false" if current else "true")
        print(style("已保存", GREEN), "跨模板重复检查：" + ("关" if current else "开"))
        _pause()
    elif choice == "10":
        current = settings.get("anki_allow_duplicates") == "true"
        library.set_setting("anki_allow_duplicates", "false" if current else "true")
        print(style("已保存", GREEN), "允许重复：" + ("否" if current else "是"))
        _pause()
    elif choice == "11":
        current = settings.get("anki_force_sync") == "true"
        library.set_setting("anki_force_sync", "false" if current else "true")
        print(style("已保存", GREEN), "添加后同步：" + ("关" if current else "开"))
        _pause()


def _settings_fetch_ankiconnect_config(library: Library, settings: dict[str, str]) -> None:
    anki = settings_from_dict(settings)
    try:
        decks = fetch_decks(anki.url)
        note_types = fetch_note_types(anki.url)
    except AnkiConnectError as exc:
        print(style(f"拉取失败：{exc}", YELLOW))
        _pause()
        return
    deck = select_deck_after_fetch(decks, anki.deck)
    note_type = select_note_type_after_fetch(note_types, anki.model)
    if deck:
        library.set_setting("anki_deck", deck)
    if note_type is not None:
        library.set_setting("anki_model", note_type.name)
        if lapis_note_type_matches(note_type):
            mappings = lapis_default_mappings_for_fields(note_type.fields)
            if mappings:
                library.set_setting("anki_field_mappings", json.dumps(mappings, ensure_ascii=False))
    print(style("已拉取", GREEN), f"{len(decks)} 个牌组，{len(note_types)} 个模板")
    if deck:
        print("牌组:", deck)
    if note_type is not None:
        print("模板:", note_type.name, f"({len(note_type.fields)} 字段)")
    _pause()


def _settings_anki_duplicate_scope(library: Library) -> None:
    print(style("重复检查范围", BOLD))
    print("1. collection  全部收藏")
    print("2. deck        当前牌组")
    print("3. deckroot    当前根牌组及子牌组")
    raw = _read_input(style("请选择：", CYAN)).strip().lower()
    scopes = {"1": "collection", "2": "deck", "3": "deckroot", "collection": "collection", "deck": "deck", "deckroot": "deckroot"}
    scope = scopes.get(raw)
    if scope is None:
        print("范围无效。")
    else:
        library.set_setting("anki_duplicate_scope", scope)
        print(style("已保存", GREEN), _anki_duplicate_scope_label(scope))
    _pause()


def _anki_duplicate_scope_label(scope: str) -> str:
    return {
        "collection": "全部收藏",
        "deck": "当前牌组",
        "deckroot": "根牌组及子牌组",
    }.get(scope, "全部收藏")


def _settings_audio() -> None:
    while True:
        library = Library()
        settings = library.settings
        sources = audio_sources_from_settings(settings)
        print(clear_screen(), end="")
        print(style("词语音频", BOLD))
        print(f"本地音频: {'开' if settings.get('audio_enable_local') == 'true' else '关'}")
        print(f"本地数据库: {settings.get('audio_local_db_path', '')}")
        print(f"本地源配置: {settings.get('audio_local_source_config_path', '')}")
        print("音频源:")
        for index, source in enumerate(sources, start=1):
            state = "开" if source.enabled else "关"
            print(f"{index}. [{state}] {source.name}  {source.url}")
        print()
        print("1. 启用/停用本地音频")
        print("2. 设置本地 android.db")
        print("3. 调整本地音频源优先级")
        print("4. 设置本地源配置 android_sources.json")
        print("5. 添加在线音频源")
        print("6. 启用/停用在线源")
        print("7. 恢复 Android 默认在线源")
        print("0. 返回")
        choice = _read_input(style("请选择：", CYAN)).strip()
        if choice == "1":
            library.set_setting("audio_enable_local", "false" if settings.get("audio_enable_local") == "true" else "true")
        elif choice == "2":
            _menu_set_path("audio_local_db_path", "本地音频数据库")
        elif choice == "3":
            _settings_local_audio_sources()
        elif choice == "4":
            _menu_set_path("audio_local_source_config_path", "本地音频源配置")
        elif choice == "5":
            name = _read_input("名称：").strip()
            url = _read_input("URL 模板（支持 {term} 和 {reading}）：").strip()
            if name and url:
                next_sources = [source.to_dict() for source in sources]
                next_sources.append(AudioSource(name=name, url=url, enabled=True).to_dict())
                library.set_setting("audio_sources", json.dumps(next_sources, ensure_ascii=False))
        elif choice == "6":
            raw = _read_input("输入源序号：").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(sources):
                index = int(raw) - 1
                next_sources = []
                for source_index, source in enumerate(sources):
                    enabled = not source.enabled if source_index == index else source.enabled
                    next_sources.append(AudioSource(source.name, source.url, enabled, source.is_default).to_dict())
                library.set_setting("audio_sources", json.dumps(next_sources, ensure_ascii=False))
        elif choice == "7":
            library.set_setting("audio_sources", default_audio_sources_json())
        elif choice in {"0", "q", "Q", "返回"}:
            return


def _settings_local_audio_sources() -> None:
    while True:
        library = Library()
        settings = library.settings
        repo = LocalAudioRepository(
            settings.get("audio_local_db_path", ""),
            source_config_file=settings.get("audio_local_source_config_path", ""),
        )
        sources = repo.ensure_source_order()
        print(clear_screen(), end="")
        print(style("本地音频源优先级", BOLD))
        print(f"数据库: {repo.db_file}")
        print(f"配置: {repo.source_config_file}")
        if not sources:
            print(style("没有从 android.db 读到可用音频源。", YELLOW))
            print("0. 返回")
            if _read_input(style("请选择：", CYAN)).strip() in {"0", "q", "Q", "返回", ""}:
                return
            continue
        for index, source in enumerate(sources, start=1):
            print(f"{index}. {source}")
        print()
        print("输入两个数字调整顺序，例如 `3 1` 表示把第 3 个移到第 1 个。")
        print("r. 按 android.db 重建默认顺序")
        print("0. 返回")
        raw = _read_input(style("请选择：", CYAN)).strip()
        if raw in {"0", "q", "Q", "返回"}:
            return
        if raw.lower() == "r":
            repo.ensure_source_order(reset=True)
            continue
        parts = raw.replace(",", " ").split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            continue
        from_index, to_index = (int(parts[0]) - 1, int(parts[1]) - 1)
        if not (0 <= from_index < len(sources) and 0 <= to_index < len(sources)):
            continue
        next_sources = list(sources)
        moved = next_sources.pop(from_index)
        next_sources.insert(to_index, moved)
        repo.update_source_order(next_sources)


def _settings_appearance() -> None:
    library = Library()
    current = library.settings["reader_vertical"] == "true"
    language = library.settings.get("language", "zh")
    print(style(_ui("appearance", library), BOLD))
    print(f"1. {_ui('writing_direction', library)}")
    print(f"2. {_ui('language', library)}")
    print(f"3. 阅读页宽: {library.settings.get('reader_width', '0')}  (0 为自动)")
    print(f"4. 阅读页行数: {library.settings.get('reader_lines', '0')}  (0 为自动)")
    print("5. 重置阅读分页")
    print(f"{_ui('current', library)}: {_ui('vertical' if current else 'horizontal', library)}")
    print(f"{_ui('language', library)}: {_language_name(language)}")
    choice = _read_input(style(_ui("choose", library), CYAN)).strip()
    if choice == "1":
        library.set_setting("reader_vertical", "false" if current else "true")
        new_direction = _ui("horizontal" if current else "vertical", library)
        print(style(_ui("saved", library), GREEN), f"{_ui('writing_direction', library)}: {new_direction}")
    elif choice == "2":
        _settings_language()
        return
    elif choice == "3":
        _menu_set_numeric_setting("reader_width", "阅读页宽", 0, 240)
        return
    elif choice == "4":
        _menu_set_numeric_setting("reader_lines", "阅读页行数", 0, 120)
        return
    elif choice == "5":
        library.set_setting("reader_width", "0")
        library.set_setting("reader_lines", "0")
        print(style(_ui("saved", library), GREEN), "阅读分页：自动")
    _pause()


def _settings_language() -> None:
    library = Library()
    print(style(_ui("language", library), BOLD))
    for index, (_, label) in enumerate(LANGUAGE_OPTIONS, start=1):
        print(f"{index}. {label}")
    raw = _read_input(style(_ui("choose", library), CYAN)).strip()
    if not raw:
        return
    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= len(LANGUAGE_OPTIONS):
            code, label = LANGUAGE_OPTIONS[index - 1]
            library.set_setting("language", code)
            print(style(_ui("saved", library), GREEN), f"{_ui('language', library)}: {label}")
            return
    codes = {code: label for code, label in LANGUAGE_OPTIONS}
    if raw in codes:
        library.set_setting("language", raw)
        print(style(_ui("saved", library), GREEN), f"{_ui('language', library)}: {codes[raw]}")
    else:
        print(_ui("invalid_language", library))


def advanced_menu() -> int:
    while True:
        library = Library()
        print(clear_screen(), end="")
        print(banner())
        print(style(_ui("advanced", library), BOLD))
        print(f"1. {_ui('statistics', library)}")
        print(f"2. {_ui('sync', library)}")
        print("3. AnkiConnect")
        print(f"4. {_ui('backup', library)}")
        print(f"5. {_ui('sasayaki', library)}")
        print(f"6. {_ui('check_update', library)}")
        print(f"0. {_ui('back', library)}")
        choice = _read_input(style(_ui("choose", library), CYAN)).strip()
        if choice == "1":
            _menu_stats_doctor()
        elif choice == "2":
            _advanced_sync()
        elif choice == "3":
            _settings_ankiconnect()
        elif choice == "4":
            _advanced_backup()
        elif choice == "5":
            _advanced_sasayaki()
        elif choice == "6":
            _advanced_check_update()
        elif choice in {"0", "q", "Q", "返回", "back"}:
            return 0
        else:
            print("没有这个高级选项。")
            _pause()


def _advanced_sasayaki() -> None:
    library = Library()
    books = _sorted_books(library)
    if not books:
        print("书架是空的。先导入一本 EPUB 或文本。")
        _pause()
        return
    print(style("Sasayaki 有声书", BOLD))
    _print_book_choices(books)
    raw = _read_input("输入书籍序号或标题片段（留空最近一本）：").strip() or None
    record = _find_book_for_input(library, raw)
    if record is None:
        print("找不到这本书。")
        _pause()
        return
    while True:
        print(clear_screen(), end="")
        print(style("Sasayaki 有声书", BOLD), record.title)
        _sasayaki_status(library, record)
        print()
        print("1. 匹配 SRT")
        print("2. 设置音频文件")
        print("3. 查看台词")
        print("4. 播放台词")
        print("5. 设置延迟")
        print("6. 设置倍速")
        print(f"7. 设置音频跳转步长（当前 {_sasayaki_seek_step(library)} 秒）")
        print("0. 返回")
        choice = _read_input(style("请选择：", CYAN)).strip()
        if choice == "1":
            srt = _read_input("SRT 路径：").strip().strip('"')
            if srt:
                audio = _read_input("音频路径（可留空）：").strip().strip('"') or None
                window = _read_input("搜索窗口（默认 200）：").strip()
                try:
                    _sasayaki_match(library, record, srt, audio_path=audio, search_window=int(window) if window else 200)
                except Exception as exc:
                    print(style(f"匹配失败：{exc}", RED))
                _pause()
        elif choice == "2":
            audio = _read_input("音频路径：").strip().strip('"')
            if audio:
                try:
                    _sasayaki_set_audio(library, record, audio)
                except Exception as exc:
                    print(style(f"保存失败：{exc}", RED))
                _pause()
        elif choice == "3":
            _sasayaki_list(library, record)
            _pause()
        elif choice == "4":
            raw_cue = _read_input("台词序号（留空当前/第一句）：").strip()
            try:
                _sasayaki_play(library, record, cue_index=int(raw_cue) if raw_cue else None)
            except Exception as exc:
                print(style(f"播放失败：{exc}", RED))
            _pause()
        elif choice == "5":
            raw_delay = _read_input("延迟秒数（可为负数）：").strip()
            if raw_delay:
                try:
                    _sasayaki_playback_setting(library, record, "delay", float(raw_delay))
                except Exception as exc:
                    print(style(f"保存失败：{exc}", RED))
                _pause()
        elif choice == "6":
            raw_rate = _read_input("倍速（例如 1.25）：").strip()
            if raw_rate:
                try:
                    _sasayaki_playback_setting(library, record, "rate", max(0.1, float(raw_rate)))
                except Exception as exc:
                    print(style(f"保存失败：{exc}", RED))
                _pause()
        elif choice == "7":
            raw_step = _read_input("跳转步长（5/10/15/30）：").strip()
            if raw_step in {"5", "10", "15", "30"}:
                library.set_setting("sasayaki_seek_step", raw_step)
                print(style("已保存", GREEN), f"音频跳转步长: {raw_step} 秒")
            else:
                print("只能输入 5、10、15、30。")
            _pause()
        elif choice in {"0", "q", "Q", "返回"}:
            return
        else:
            print("没有这个 Sasayaki 选项。")
            _pause()


def _sasayaki_playback_setting(library: Library, record: BookRecord, key: str, value: float) -> None:
    data = library.sasayaki_for(record) or {}
    playback = _sasayaki_playback(data)
    playback[key] = value
    data["playback"] = playback
    library.set_sasayaki(record, data)
    print(style("已保存", GREEN), f"{key}: {value}")


def _advanced_sync() -> None:
    library = Library()
    settings = library.settings
    authorizer = google_drive_authorizer(library)
    print(style("同步", BOLD))
    print(_google_drive_status_text(authorizer.status()))
    print(
        "同步内容: "
        f"统计 {_on_off(settings.get('sync_statistics'))} / "
        f"有声书 {_on_off(settings.get('sync_audiobook'))} / "
        f"书籍数据 {_on_off(settings.get('sync_upload_books'))}"
    )
    print("1. 连接 / 重新连接 Google Drive")
    print("2. 自动判断并同步")
    print("3. 上传到 Google Drive")
    print("4. 从 Google Drive 下载")
    print("5. 从 Google Drive 导入书籍")
    print("6. 同步选项")
    print("7. 断开 Google Drive")
    print("8. 本地目录兼容后端")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    if choice == "1":
        try:
            _connect_google_drive(library)
        except Exception as exc:
            print(style(f"连接失败：{exc}", RED))
        _pause()
    elif choice == "2":
        _run_google_drive_sync_menu(library, "auto")
        _pause()
    elif choice == "3":
        _run_google_drive_sync_menu(library, "export")
        _pause()
    elif choice == "4":
        _run_google_drive_sync_menu(library, "import")
        _pause()
    elif choice == "5":
        _remote_book_import_menu(library)
    elif choice == "6":
        _sync_options_menu()
    elif choice == "7":
        authorizer.disconnect()
        print("已在本机断开。远端 ttu-reader-data 未删除。")
        _pause()
    elif choice == "8":
        _local_sync_menu()


def _remote_book_import_menu(library: Library) -> None:
    try:
        drive, books = list_google_drive_books(library)
        if not books:
            print("Google Drive 的 ttu-reader-data 中没有书籍。")
            _pause()
            return
        _print_remote_books(books)
        query = _read_input("输入远端书籍序号或标题片段（留空返回）：").strip()
        if not query:
            return
        folder = _find_remote_book(books, query)
        if folder is None:
            print(style("找不到这本远端书。", RED))
        else:
            record = import_google_drive_book(library, folder, drive)
            print(style("已导入", GREEN), record.title)
    except Exception as exc:
        print(style(f"导入失败：{exc}", RED))
    _pause()


def _print_remote_books(books: list[DriveFile]) -> None:
    from .sync import desanitize_ttu_filename

    print(style("Google Drive 书籍", BOLD))
    for index, folder in enumerate(books, start=1):
        print(f"{index}. {desanitize_ttu_filename(folder.name)}")


def _find_remote_book(books: list[DriveFile], query: str | None) -> DriveFile | None:
    from .sync import desanitize_ttu_filename

    if not query:
        return None
    cleaned = query.strip()
    if cleaned.isdigit():
        index = int(cleaned) - 1
        return books[index] if 0 <= index < len(books) else None
    lowered = cleaned.casefold()
    exact = [
        folder
        for folder in books
        if desanitize_ttu_filename(folder.name).casefold() == lowered
    ]
    if exact:
        return exact[0]
    return next(
        (
            folder
            for folder in books
            if lowered in desanitize_ttu_filename(folder.name).casefold()
        ),
        None,
    )


def _run_google_drive_sync_menu(library: Library, direction: str) -> None:
    try:
        for message in sync_google_drive(library, direction):
            print(message)
    except (DriveAuthError, DriveAuthorizationRequired) as exc:
        print(style(f"Google Drive 未连接：{exc}", RED))
    except Exception as exc:
        print(style(f"同步失败：{exc}", RED))


def _sync_options_menu() -> None:
    library = Library()
    settings = library.settings
    print(style("同步选项", BOLD))
    print(f"1. 阅读统计: {_on_off(settings.get('sync_statistics'))}")
    print(f"2. 统计冲突: {'合并' if settings.get('sync_statistics_mode') == 'merge' else '以同步来源替换'}")
    print(f"3. Sasayaki 进度: {_on_off(settings.get('sync_audiobook'))}")
    print(f"4. 首次同步上传书籍数据: {_on_off(settings.get('sync_upload_books'))}")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    if choice == "1":
        _toggle_setting(library, "sync_statistics")
    elif choice == "2":
        next_mode = "replace" if settings.get("sync_statistics_mode") == "merge" else "merge"
        library.set_setting("sync_statistics_mode", next_mode)
        print(style("已保存", GREEN), "合并" if next_mode == "merge" else "替换")
    elif choice == "3":
        _toggle_setting(library, "sync_audiobook")
    elif choice == "4":
        _toggle_setting(library, "sync_upload_books")
    if choice != "0":
        _pause()


def _local_sync_menu() -> None:
    library = Library()
    print(style("本地目录兼容后端", BOLD))
    print("该模式只读写本地 ttu-reader-data，不连接 Google Drive。")
    print(f"目录: {library.settings['sync_path']}")
    print("1. 自动")
    print("2. 导出")
    print("3. 导入")
    print("4. 设置目录")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    if choice in {"1", "2", "3"}:
        direction = {"1": "auto", "2": "export", "3": "import"}[choice]
        for message in sync_library(library, direction):
            print(message)
        _pause()
    elif choice == "4":
        _menu_set_path("sync_path", "本地同步目录")


def _sync_one_book(library: Library, record: BookRecord) -> str:
    if library.settings.get("sync_provider") == "local":
        sync_root = Path(library.settings["sync_path"]).expanduser() / TTU_ROOT
        sync_root.mkdir(parents=True, exist_ok=True)
        return sync_book(library, record, sync_root, "auto")
    drive = GoogleDriveClient(google_drive_authorizer(library))
    root_folder_id = drive.find_root_folder()
    settings = library.settings
    return sync_google_drive_book(
        library,
        record,
        drive,
        root_folder_id,
        "auto",
        sync_statistics=_is_true(settings.get("sync_statistics")),
        statistics_mode=settings.get("sync_statistics_mode", "merge"),
        sync_audiobook=_is_true(settings.get("sync_audiobook")),
        upload_book=_is_true(settings.get("sync_upload_books")),
    )


def _is_true(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "是", "开启"}


def _on_off(value: object) -> str:
    return "开启" if _is_true(value) else "关闭"


def _toggle_setting(library: Library, key: str) -> None:
    enabled = not _is_true(library.settings.get(key))
    library.set_setting(key, "true" if enabled else "false")
    print(style("已保存", GREEN), _on_off(enabled))


def _advanced_backup() -> None:
    library = Library()
    print(style("备份 / 恢复", BOLD))
    print("1. 备份全部")
    print("2. 只备份书籍")
    print("3. 只备份词典")
    print("4. 恢复全部")
    print("5. 只恢复书籍")
    print("6. 只恢复词典")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    try:
        if choice == "1":
            archive = create_backup(library, "all")
            print(style("备份完成", GREEN), archive)
        elif choice == "2":
            archive = create_backup(library, "books")
            print(style("书籍备份完成", GREEN), archive)
        elif choice == "3":
            archive = create_backup(library, "dictionaries")
            print(style("词典备份完成", GREEN), archive)
        elif choice in {"4", "5", "6"}:
            path = _read_input("备份 zip 路径：").strip().strip('"')
            if path:
                category = {"4": "all", "5": "books", "6": "dictionaries"}[choice]
                restore_backup(library, path, category)
                print(style("恢复完成", GREEN), category)
    except Exception as exc:
        print(style(f"备份/恢复失败：{exc}", RED))
    _pause()


def _advanced_check_update() -> None:
    try:
        cmd_update(argparse.Namespace(check=False, yes=False, target=None))
    except RuntimeError as exc:
        print(style(str(exc), YELLOW))
    _pause()


def create_backup(library: Library, category: str = "all") -> Path:
    category = _normalize_backup_category(category)
    backup_dir = library.root.parent / f"{library.root.name}-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive = backup_dir / f"hoshi-terminal-{category}-backup-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    root = library.root.resolve()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as backup:
        for path in _backup_paths(library, category):
            if not path.is_file():
                continue
            if path.name.startswith("hoshi-terminal-backup-") and path.suffix == ".zip":
                continue
            backup.write(path, path.resolve().relative_to(root))
    return archive


def restore_backup(library: Library, archive_path: str | Path, category: str = "all") -> None:
    category = _normalize_backup_category(category)
    archive = Path(archive_path).expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    root = library.root.resolve()
    with tempfile.TemporaryDirectory() as temp_dir:
        extract_root = Path(temp_dir) / "restore"
        extract_root.mkdir()
        with zipfile.ZipFile(archive) as backup:
            for member in backup.infolist():
                target = (extract_root / member.filename).resolve()
                if not str(target).startswith(str(extract_root.resolve())):
                    raise ValueError("备份包内路径不安全。")
            backup.extractall(extract_root)
        if category == "all":
            auth_file = root / "google_drive_auth.json"
            auth_data = auth_file.read_bytes() if auth_file.is_file() else None
            _replace_directory_contents(root, extract_root)
            if auth_data is not None:
                auth_file.write_bytes(auth_data)
                if os.name != "nt":
                    auth_file.chmod(0o600)
        elif category == "books":
            source_books = extract_root / "books"
            if source_books.exists():
                _replace_directory_contents(library.books_dir, source_books)
            source_state = extract_root / "library.json"
            if source_state.exists():
                _merge_book_state(library.state_file, source_state)
        elif category == "dictionaries":
            for name in ("dictionaries.json", "dictionaries.sqlite3"):
                source = extract_root / name
                if source.exists():
                    shutil.copy2(source, root / name)


def _backup_paths(library: Library, category: str) -> list[Path]:
    root = library.root.resolve()
    if category == "all":
        return sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.name != "google_drive_auth.json"
        )
    if category == "books":
        paths = [library.state_file]
        if library.books_dir.exists():
            paths.extend(path for path in sorted(library.books_dir.rglob("*")) if path.is_file())
        return [path for path in paths if path.exists()]
    if category == "dictionaries":
        return [path for path in (library.dictionary_file, library.dictionary_file.with_suffix(".sqlite3")) if path.exists()]
    raise ValueError("未知备份类型。")


def _normalize_backup_category(category: str) -> str:
    aliases = {
        "all": "all",
        "全部": "all",
        "books": "books",
        "book": "books",
        "书籍": "books",
        "dictionaries": "dictionaries",
        "dictionary": "dictionaries",
        "dict": "dictionaries",
        "词典": "dictionaries",
        "辞典": "dictionaries",
    }
    normalized = aliases.get(category.strip().lower())
    if normalized is None:
        raise ValueError("备份类型必须是 all / books / dictionaries")
    return normalized


def _replace_directory_contents(target: Path, source: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in target.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def _merge_book_state(current_file: Path, backup_file: Path) -> None:
    current = json.loads(current_file.read_text(encoding="utf-8")) if current_file.exists() else {}
    backup = json.loads(backup_file.read_text(encoding="utf-8"))
    for key in ("books", "statistics", "highlights", "shelves"):
        if key in backup:
            current[key] = backup[key]
    if "sasayaki" in backup:
        current["sasayaki"] = backup["sasayaki"]
    current_file.parent.mkdir(parents=True, exist_ok=True)
    current_file.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def _settings_about() -> None:
    print(style("关于", BOLD))
    print(f"Hoshi Reader Terminal {__version__}")
    print("菜单结构参考 Hoshi Reader iOS / Android。")
    _pause()


def _menu_set_raw_setting(key: str, label: str) -> None:
    library = Library()
    current = library.settings[key]
    raw = _read_input(f"请输入新的{label}（当前：{current}）：").strip()
    if not raw:
        return
    library.set_setting(key, raw)
    print(style("已保存", GREEN), f"{label}: {raw}")
    _pause()


def _menu_set_numeric_setting(key: str, label: str, minimum: int, maximum: int) -> None:
    library = Library()
    current = library.settings.get(key, "")
    raw = _read_input(f"请输入新的{label}（当前：{current}，范围 {minimum}-{maximum}）：").strip()
    if not raw:
        return
    try:
        value = int(raw)
    except ValueError:
        print("请输入数字。")
        _pause()
        return
    if value < minimum or value > maximum:
        print(f"范围应为 {minimum}-{maximum}。")
        _pause()
        return
    library.set_setting(key, str(value))
    print(style("已保存", GREEN), f"{label}: {value}")
    _pause()


def mine_word(
    word: str,
    sentence: str = "",
    note: str = "",
    reading: str = "",
    sentence_audio_path: str = "",
    document_title: str = "",
    include_word_audio: bool = True,
) -> str:
    library = Library()
    settings = library.settings
    anki = settings_from_dict(settings)
    word_audio = resolve_word_audio(word, reading, settings, library.root) if include_word_audio else None
    payload = MiningPayload(
        expression=word,
        sentence=sentence,
        note=note,
        reading=reading,
        matched=word,
        glossary_first=note,
        glossary=note,
        selection_text=word,
        document_title=document_title,
        word_audio=word_audio,
        sentence_audio_path=sentence_audio_path,
    )
    fields = csv_fields(payload)
    outputs: list[str] = []
    csv_path = None
    if anki.mode in {"csv", "both"}:
        csv_path = library.mine_card(word, sentence=sentence, note=note, fields=fields)
        outputs.append(f"CSV: {csv_path}")
    if anki.mode in {"ankiconnect", "both"}:
        try:
            note_id = add_note(
                anki,
                word,
                sentence=sentence,
                note=note,
                reading=reading,
                glossary=note,
                glossary_first=note,
                word_audio=word_audio,
                sentence_audio_path=sentence_audio_path,
                document_title=document_title,
                matched=word,
            )
        except AnkiConnectError as exc:
            if anki.mode == "ankiconnect":
                outputs.append(f"AnkiConnect 失败: {exc}")
            else:
                outputs.append(f"AnkiConnect 未添加，已保留 CSV: {exc}")
        else:
            outputs.append(f"AnkiConnect: 已添加 note {note_id}")
    if not outputs:
        csv_path = library.mine_card(word, sentence=sentence, note=note, fields=fields)
        outputs.append(f"CSV: {csv_path}")
    if word_audio is not None:
        outputs.append(f"词语音频: {word_audio.source}")
    if sentence_audio_path:
        outputs.append("句子音频: Sasayaki")
    return style("已制卡", MAGENTA) + " " + f"{word} -> " + " | ".join(outputs)


def find_book_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_SCAN_DIRS for part in path.parts):
            continue
        if path.name.lower() in SKIP_SCAN_FILES:
            continue
        if path.suffix.lower() in BOOK_SUFFIXES:
            files.append(path)
    return sorted(files, key=lambda item: str(item).lower())


def _chapter_marks_from_extracted(book: ExtractedBook) -> list[tuple[str, int]]:
    marks: list[tuple[str, int]] = []
    cursor = 0
    for index, chapter in enumerate(book.chapters, start=1):
        text = chapter.text.strip()
        if not text:
            continue
        label = chapter.title.strip() or f"Chapter {index}"
        marks.append((label, cursor))
        cursor += len(text) + 2
    if len(marks) <= 1:
        return []
    return marks


def _sorted_books(library: Library) -> list[BookRecord]:
    if library.settings.get("bookshelf_sort") == "title":
        return sorted(library.books, key=lambda item: item.title.lower())
    return sorted(library.books, key=lambda item: item.last_access, reverse=True)


def _print_book_choices(books: list[BookRecord]) -> None:
    for index, book in enumerate(books, start=1):
        progress = summarize_text_progress(book.position, _safe_text_for_progress(book))
        print(f"{index:>2}. {progress}  {book.title}  {style(book.kind, DIM)}")


def _print_shelf_sections(library: Library) -> None:
    books = _sorted_books(library)
    by_id = {book.id: book for book in books}
    printed: set[str] = set()
    index_by_id = {book.id: index for index, book in enumerate(books, start=1)}

    if library.settings.get("bookshelf_show_reading") == "true":
        reading = [
            book
            for book in books
            if 0 < book.position < character_count(_safe_text_for_progress(book))
        ]
        if reading:
            print(style("正在阅读", BOLD))
            _print_indexed_books(reading, index_by_id, library)
            print()

    for shelf in library.shelves:
        shelf_books = [by_id[book_id] for book_id in shelf.get("book_ids", []) if book_id in by_id]
        if not shelf_books:
            continue
        print(style(str(shelf.get("name")), BOLD))
        _print_indexed_books(shelf_books, index_by_id, library)
        printed.update(book.id for book in shelf_books)
        print()

    unshelved = [book for book in books if book.id not in printed]
    if unshelved:
        label = "未归类" if library.shelves else "全部"
        print(style(label, BOLD))
        _print_indexed_books(unshelved, index_by_id, library)


def _print_indexed_books(books: list[BookRecord], index_by_id: dict[str, int], library: Library) -> None:
    for book in books:
        progress = summarize_text_progress(book.position, _safe_text_for_progress(book))
        shelf = library.shelf_for(book.id)
        shelf_text = f"  {style(shelf, DIM)}" if shelf else ""
        print(f"{index_by_id[book.id]:>2}. {progress}  {book.title}  {style(book.kind, DIM)}{shelf_text}")


def _shelf_management_menu() -> None:
    while True:
        library = Library()
        print(clear_screen(), end="")
        print(style("管理书架", BOLD))
        _print_shelves(library)
        print("1. 新建书架")
        print("2. 删除书架")
        print("3. 调整书架顺序")
        print("4. 移动书籍到书架")
        print("5. 切换正在阅读分组")
        print("0. 返回")
        choice = _read_input(style("请选择：", CYAN)).strip()
        if choice == "1":
            name = _read_input("书架名：").strip()
            if library.create_shelf(name):
                print(style("已新建", GREEN), name)
            else:
                print("书架名为空或已存在。")
            _pause()
        elif choice == "2":
            raw = _read_input("输入书架序号或名称：").strip()
            name = _shelf_name_for_input(library, raw)
            if name and library.delete_shelf(name):
                print(style("已删除", GREEN), name)
            else:
                print("找不到这个书架。")
            _pause()
        elif choice == "3":
            raw = _read_input("输入 原序号 新序号（例如 3 1）：").strip()
            parts = raw.split()
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                ok = library.move_shelf(int(parts[0]) - 1, int(parts[1]) - 1)
                print(style("已调整", GREEN) if ok else "书架序号无效。")
            else:
                print("格式应为两个数字。")
            _pause()
        elif choice == "4":
            books = _sorted_books(library)
            if not books:
                print("书架是空的。")
                _pause()
                continue
            _print_book_choices(books)
            raw_book = _read_input("输入书籍序号、标题片段或 id：").strip()
            record = _find_book_for_input(library, raw_book)
            if record is None:
                print("找不到这本书。")
                _pause()
                continue
            _move_book_to_shelf_prompt(library, record)
        elif choice == "5":
            current = library.settings.get("bookshelf_show_reading") == "true"
            library.set_setting("bookshelf_show_reading", "false" if current else "true")
            print(style("已保存", GREEN), "正在阅读分组：" + ("关" if current else "开"))
            _pause()
        elif choice in {"0", "q", "Q", "返回"}:
            return
        else:
            print("没有这个书架选项。")
            _pause()


def _print_shelves(library: Library) -> None:
    shelves = library.shelves
    if not shelves:
        print("还没有自定义书架。")
        return
    print("现有书架：")
    for index, shelf in enumerate(shelves, start=1):
        count = len(shelf.get("book_ids", []))
        print(f"{index}. {shelf.get('name')}  {count} 本")


def _shelf_name_for_input(library: Library, raw: str) -> str | None:
    if not raw:
        return None
    shelves = library.shelves
    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= len(shelves):
            return str(shelves[index - 1].get("name"))
    for shelf in shelves:
        if str(shelf.get("name")) == raw:
            return raw
    return None


def _move_book_to_shelf_prompt(library: Library, record: BookRecord) -> None:
    print(style("移动到书架", BOLD), record.title)
    target = _select_shelf_target(library)
    if target == "__cancel__":
        return
    if library.move_book_to_shelf(record.id, target):
        print(style("已移动", GREEN), target or "未归类")
    else:
        print("移动失败。")
    _pause()


def _select_shelf_target(library: Library) -> str | None:
    shelves = library.shelves
    print("0. 未归类")
    for index, shelf in enumerate(shelves, start=1):
        print(f"{index}. {shelf.get('name')}")
    raw = _read_input("输入书架序号；或输入新书架名：").strip()
    if not raw:
        return "__cancel__"
    if raw == "0":
        return None
    if raw.isdigit() and 1 <= int(raw) <= len(shelves):
        return str(shelves[int(raw) - 1].get("name"))
    return raw


def _parse_book_selection(raw: str, books: list[BookRecord]) -> list[BookRecord]:
    selected: list[BookRecord] = []
    seen: set[str] = set()
    tokens = raw.replace(",", " ").split()
    for token in tokens:
        numbers: list[int] = []
        if "-" in token:
            start_raw, _, end_raw = token.partition("-")
            if start_raw.isdigit() and end_raw.isdigit():
                start, end = int(start_raw), int(end_raw)
                if start > end:
                    start, end = end, start
                numbers = list(range(start, end + 1))
        elif token.isdigit():
            numbers = [int(token)]
        for number in numbers:
            if 1 <= number <= len(books):
                record = books[number - 1]
                if record.id not in seen:
                    selected.append(record)
                    seen.add(record.id)
    return selected


def _find_book_for_input(library: Library, query: str | None) -> BookRecord | None:
    books = _sorted_books(library)
    if not books:
        return None
    if query is None:
        return books[0]
    raw = query.strip()
    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= len(books):
            return books[index - 1]
    return library.find_book(raw)


def _ui(key: str, library: Library | None = None) -> str:
    language = (library or Library()).settings.get("language", "zh")
    values = UI_TEXT.get(key, {})
    return values.get(language, values.get("zh", key))


def _optional_int_setting(library: Library, key: str) -> int | None:
    try:
        value = int(str(library.settings.get(key, "0")).strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _bounded_int_setting(library: Library, key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(library.settings.get(key, default)).strip())
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


def _sasayaki_seek_step(library: Library) -> int:
    raw_step = _bounded_int_setting(library, "sasayaki_seek_step", default=5, minimum=5, maximum=30)
    return raw_step if raw_step in {5, 10, 15, 30} else 5


def _parse_relative_seconds(raw: str) -> float | None:
    value = raw.strip()
    if not value:
        return None
    if value[0] not in {"+", "-"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _language_name(code: str) -> str:
    for option, label in LANGUAGE_OPTIONS:
        if option == code:
            return label
    return LANGUAGE_OPTIONS[0][1]


def _pause(prompt: str | None = None) -> None:
    if prompt is None:
        prompt = _ui("pause", Library())
    _read_input(style(prompt, DIM))


def _read_input(prompt: str = "") -> str:
    try:
        return input(prompt)
    except EOFError as exc:
        raise GracefulExit from exc


def _read_reader_command(prompt: str = "", timeout: float | None = None, echo: bool = True) -> str | None:
    if not sys.stdin.isatty():
        return _read_input(prompt)
    if echo:
        print(prompt, end="", flush=True)
    key = _read_single_key(timeout=timeout)
    if key is None:
        if echo and prompt:
            print("\r\033[K", end="", flush=True)
        return None
    command = _normalize_reader_key(key)
    if command in {"right", "down", "left", "up", "space", ""}:
        if echo:
            print()
        return command
    if command in {"r", "v", "y", "c", "t", "l", "s", "q", "[", "]", "{", "}"}:
        if echo:
            print(command)
        return command
    if command == "/":
        return "/" + _read_reader_line("/")
    if command == "a":
        return "a " + _read_reader_line("a ")
    if command == "f":
        return "f " + _read_reader_line("f ")
    if command == "h":
        return "h " + _read_reader_line("h ")
    if command == "g":
        return "g " + _read_reader_line("g ")
    if command == "j":
        return "j " + _read_reader_line("j ")
    if echo:
        print(command)
    return command


def _read_reader_line(prompt: str) -> str:
    set_cursor_visible(True)
    try:
        return _read_input(prompt)
    finally:
        set_cursor_visible(False)


def _read_toc_command(prompt: str = "") -> str:
    if not sys.stdin.isatty():
        return _read_input(prompt)
    print(prompt, end="", flush=True)
    key = _read_single_key()
    command = _normalize_reader_key(key)
    if command in {"right", "down", "left", "up", ""}:
        print()
        return command
    if command.isdigit():
        return command + _read_input(command)
    if command in {"g", "j"}:
        return command + " " + _read_input(command + " ")
    print(command)
    return command


def _read_search_command(prompt: str = "") -> str:
    if not sys.stdin.isatty():
        return _read_input(prompt)
    print(prompt, end="", flush=True)
    key = _read_single_key()
    command = _normalize_reader_key(key)
    if command in {"right", "down", "left", "up", ""}:
        print()
        return command
    if command.isdigit():
        return command + _read_input(command)
    if command == "/":
        return "/" + _read_input("/")
    print(command)
    return command


def _is_toc_command(command: str) -> bool:
    return command in {"c", "t"} or command.startswith("t ") or command.startswith("c ") or (
        len(command) > 1 and command[0] in {"t", "c"} and command[1:].strip().isdigit()
    )


def _toc_initial_command(command: str) -> str | None:
    if command in {"c", "t"}:
        return None
    return command[1:].strip()


def _normalize_reader_key(key: str) -> str:
    arrows = {
        "\x1b[C": "right",
        "\x1b[B": "down",
        "\x1b[D": "left",
        "\x1b[A": "up",
        "\xe0M": "right",
        "\xe0P": "down",
        "\xe0K": "left",
        "\xe0H": "up",
        "\x00M": "right",
        "\x00P": "down",
        "\x00K": "left",
        "\x00H": "up",
    }
    if key in arrows:
        return arrows[key]
    if key in {"\r", "\n"}:
        return ""
    if key == " ":
        return "space"
    return key


def _read_single_key(timeout: float | None = None) -> str | None:
    if os.name == "nt":
        import msvcrt
        if timeout is not None:
            deadline = time.monotonic() + timeout
            while not msvcrt.kbhit():
                if time.monotonic() >= deadline:
                    return None
                time.sleep(0.03)

        first = msvcrt.getwch()
        if first in {"\x00", "\xe0"}:
            return first + msvcrt.getwch()
        return first

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        if timeout is not None and not select.select([fd], [], [], timeout)[0]:
            return None
        data = os.read(fd, 1)
        if data == b"\x1b":
            for _ in range(7):
                if not select.select([fd], [], [], 0.03)[0]:
                    break
                next_byte = os.read(fd, 1)
                data += next_byte
                if len(data) == 2 and next_byte not in {b"[", b"O"}:
                    break
                if len(data) >= 3 and 0x40 <= next_byte[0] <= 0x7E:
                    break
        return data.decode(errors="ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _parse_page_number(raw: str, total_pages: int) -> int | None:
    value = raw.strip()
    if value.endswith("%"):
        try:
            percent = float(value[:-1].strip())
        except ValueError:
            return None
        percent = min(100.0, max(0.0, percent))
        return min(total_pages - 1, max(0, round((total_pages - 1) * percent / 100)))
    try:
        page = int(value) - 1
    except ValueError:
        return None
    return min(total_pages - 1, max(0, page))


def _safe_text_for_progress(book: BookRecord) -> str:
    try:
        return extract_book(Path(book.stored_path)).text
    except Exception:
        return "?"
