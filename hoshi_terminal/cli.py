from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile

from . import __version__
from .anki import AnkiConnectError, add_note, settings_from_dict, version as ankiconnect_version
from .dictionary import (
    DICTIONARY_TYPES,
    TYPE_LABELS,
    DictionaryManager,
    find_yomitan_sources,
    format_result_pages,
    format_results,
    normalize_dictionary_type,
)
from .epub import extract_book
from .reader import Page, character_count, page_for_position, paginate, render_page, sentence_around
from .sasayaki import (
    SasayakiMatch,
    SasayakiMatchData,
    SasayakiPlayer,
    cue_at_time,
    find_cue_for_page,
    format_time,
    launch_audio,
    match_rate_text,
    match_sasayaki,
    next_cue,
    parse_srt,
    previous_cue,
)
from .storage import BookRecord, Library, summarize_text_progress
from .sync import sync_library
from .terminal import BOLD, CYAN, DIM, GREEN, MAGENTA, RED, YELLOW, banner, clear_screen, style, terminal_size
from .updates import check_for_updates, format_update_info, format_update_install_result, install_latest_update


BOOK_SUFFIXES = {".epub", ".txt", ".md", ".markdown", ".html", ".htm", ".xhtml"}
SKIP_SCAN_DIRS = {".git", ".venv", "__pycache__", "dist", "build"}
SKIP_SCAN_FILES = {"readme.md", "readme.zh-cn.md", "license", "install.zh-cn.txt"}


LANGUAGE_OPTIONS = [
    ("zh", "简体中文"),
    ("en", "English"),
    ("ja", "日本語"),
]


UI_TEXT = {
    "main_title": {"zh": "Hoshi Reader", "en": "Hoshi Reader", "ja": "Hoshi Reader"},
    "books": {"zh": "书库", "en": "Books", "ja": "本棚"},
    "dictionary": {"zh": "查词", "en": "Dictionary", "ja": "辞書"},
    "settings": {"zh": "设置", "en": "Settings", "ja": "設定"},
    "exit": {"zh": "退出", "en": "Exit", "ja": "終了"},
    "exited": {"zh": "已退出。", "en": "Exited.", "ja": "終了しました。"},
    "choose": {"zh": "请选择：", "en": "Select: ", "ja": "選択: "},
    "back": {"zh": "返回", "en": "Back", "ja": "戻る"},
    "main_back": {"zh": "返回主菜单", "en": "Back to Main Menu", "ja": "メインメニューへ戻る"},
    "shelf": {"zh": "书架", "en": "Shelf", "ja": "本棚"},
    "import_epub": {"zh": "导入 EPUB", "en": "Import EPUB", "ja": "EPUB をインポート"},
    "read": {"zh": "阅读", "en": "Read", "ja": "読む"},
    "book_settings": {"zh": "书库设置", "en": "Book Settings", "ja": "本棚設定"},
    "search": {"zh": "搜索", "en": "Search", "ja": "検索"},
    "import_dictionary": {"zh": "导入辞典", "en": "Import Dictionary", "ja": "辞書をインポート"},
    "dictionary_list": {"zh": "辞典列表", "en": "Dictionary List", "ja": "辞書一覧"},
    "dictionary_settings": {"zh": "辞典设置", "en": "Dictionary Settings", "ja": "辞書設定"},
    "anki": {"zh": "Anki", "en": "Anki", "ja": "Anki"},
    "appearance": {"zh": "外观", "en": "Appearance", "ja": "表示"},
    "advanced": {"zh": "高级", "en": "Advanced", "ja": "詳細"},
    "doctor": {"zh": "诊断", "en": "Diagnostics", "ja": "診断"},
    "about": {"zh": "关于", "en": "About", "ja": "情報"},
    "statistics": {"zh": "统计", "en": "Statistics", "ja": "統計"},
    "sync": {"zh": "同步", "en": "Sync", "ja": "同期"},
    "sasayaki": {"zh": "Sasayaki 有声书", "en": "Sasayaki Audiobook", "ja": "Sasayaki オーディオブック"},
    "backup": {"zh": "备份", "en": "Backup", "ja": "バックアップ"},
    "check_update": {"zh": "检查更新", "en": "Check Updates", "ja": "アップデート確認"},
    "writing_direction": {"zh": "文字方向", "en": "Writing Direction", "ja": "文字方向"},
    "language": {"zh": "界面语言", "en": "Interface Language", "ja": "表示言語"},
    "current": {"zh": "当前", "en": "Current", "ja": "現在"},
    "horizontal": {"zh": "横排", "en": "Horizontal", "ja": "横書き"},
    "vertical": {"zh": "竖排", "en": "Vertical", "ja": "縦書き"},
    "saved": {"zh": "已保存", "en": "Saved", "ja": "保存しました"},
    "invalid_language": {"zh": "语言选项无效。", "en": "Invalid language option.", "ja": "言語オプションが無効です。"},
    "pause": {"zh": "按 Enter 返回", "en": "Press Enter to return", "ja": "Enter で戻る"},
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


DEMO_TEXT = """
星読み端末版へようこそ。

これは端末で EPUB やテキストを読むための小さなアプリです。横書きと簡易的な縦書き表示に対応しています。

辞書を引くこともできます。活用形から基本形を推定して検索することがあります。

今日の目標は読むことです。読んだ文字数と時間は統計に保存されます。
""".strip()


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

    demo = subparsers.add_parser("demo", aliases=["演示"], help="打开内置演示书")
    demo.add_argument("--print", action="store_true", dest="print_only", help="打印第一页后退出")
    demo.add_argument("--vertical", action="store_true", help="用终端竖排显示")
    demo.set_defaults(func=cmd_demo)

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
    mine.set_defaults(func=cmd_mine)

    stats = subparsers.add_parser("stats", aliases=["统计"], help="显示阅读统计")
    stats.set_defaults(func=cmd_stats)

    sync = subparsers.add_parser("sync", aliases=["同步"], help="同步阅读进度")
    sync.add_argument("direction", nargs="?", default="auto", choices=["auto", "export", "import", "自动", "导出", "导入"])
    sync.add_argument("--path", metavar="目录", help="临时指定同步目录并保存")
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


def cmd_demo(args: argparse.Namespace) -> int:
    print(banner())
    pages = paginate(DEMO_TEXT, width=args.width if hasattr(args, "width") else None)
    if args.print_only or not sys.stdin.isatty():
        print(render_page("Hoshi Reader Terminal 演示", pages[0], len(pages), vertical=args.vertical))
        return 0
    return interactive_loop("Hoshi Reader Terminal 演示", DEMO_TEXT, pages, None, args.vertical)


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
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    library = Library()
    record: BookRecord | None = None
    title: str
    text: str

    target_path = Path(args.target).expanduser() if args.target else None
    if target_path and target_path.exists():
        extracted = extract_book(target_path)
        title = extracted.title
        text = extracted.text
    else:
        record = _find_book_for_input(library, args.target)
        if record is None:
            raise ValueError("找不到这本书。可以先运行 `shelf` / `书架`，或直接传文件路径。")
        title, text = library.load_record_text(record)

    pages = paginate(text, width=args.width, lines_per_page=args.lines)
    start_page = page_for_position(pages, record.position if record else 0)
    if args.print_only or not sys.stdin.isatty():
        print(render_page(title, pages[start_page], len(pages), vertical=args.vertical))
        return 0
    return interactive_loop(title, text, pages, record, args.vertical, start_page=start_page)


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
    print(mine_word(args.word, sentence=args.sentence, note=args.note))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    library = Library()
    stats = sorted(library.statistics, key=lambda item: (item.date_key, item.title), reverse=True)
    if not stats:
        print("还没有统计。")
        return 0
    print(style("阅读统计", BOLD))
    for item in stats:
        minutes = item.reading_time / 60
        print(
            f"{item.date_key}  {item.title}  "
            f"{item.characters_read} 字符  {minutes:.1f} 分钟  {item.last_reading_speed} 字符/分钟"
        )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    library = Library()
    if args.path:
        library.set_setting("sync_path", args.path)
    for message in sync_library(library, args.direction):
        print(message)
    return 0


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
    print(f"同步目录: {library.settings['sync_path']}")
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
    audio = Path(audio_path).expanduser().resolve() if audio_path else None
    if audio is not None and not audio.exists():
        raise FileNotFoundError(audio)

    extracted = extract_book(Path(record.stored_path))
    cues = parse_srt(srt)
    result = match_sasayaki(extracted, cues, search_window=max(0, search_window))
    existing = library.sasayaki_for(record) or {}
    playback = existing.get("playback", {}) if isinstance(existing.get("playback"), dict) else {}
    data = {
        "srt_path": str(srt),
        "audio_path": str(audio) if audio else str(existing.get("audio_path", "")),
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
    if audio:
        print(style("音频", DIM), audio)
    return 0


def _sasayaki_set_audio(library: Library, record: BookRecord, audio_path: str | Path) -> int:
    audio = Path(audio_path).expanduser().resolve()
    if not audio.exists():
        raise FileNotFoundError(audio)
    data = library.sasayaki_for(record) or {"playback": {"lastPosition": 0.0, "delay": 0.0, "rate": 1.0}}
    data["audio_path"] = str(audio)
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
    results = DictionaryManager(library.dictionary_file).lookup(word)
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
                current_results = DictionaryManager(library.dictionary_file).lookup(next_word)
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
) -> None:
    current = _reader_sasayaki_current(library, record, page, prefer_playback=direction != "current")
    if current is None:
        _flash_message("这本书还没有 Sasayaki 匹配。")
        return
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


def _reader_sasayaki_toggle(
    library: Library,
    record: BookRecord | None,
    page: Page,
    player: SasayakiPlayer,
) -> None:
    if player.is_playing():
        player.toggle_pause()
        _flash_message("Sasayaki 已暂停" if player.paused else "Sasayaki 继续播放")
        return
    _reader_sasayaki_play(library, record, page, player)


def _flash_message(message: str, seconds: float = 0.45) -> None:
    print(style(message, YELLOW))
    time.sleep(seconds)


def interactive_loop(
    title: str,
    text: str,
    pages: list[Page],
    record: BookRecord | None,
    vertical: bool = False,
    start_page: int = 0,
) -> int:
    library = Library()
    page_index = start_page
    session_started = time.monotonic()
    session_start_char = pages[start_page].start_char if pages else 0
    sasayaki_player = SasayakiPlayer()

    try:
        while True:
            page = pages[page_index]
            print(clear_screen(), end="")
            print(render_page(title, page, len(pages), vertical=vertical))
            command = _read_reader_command(style("hoshi> ", CYAN)).strip()
            if command == "right":
                page_index = min(len(pages) - 1, page_index + 1)
            elif command == "left":
                page_index = max(0, page_index - 1)
            elif command == "down":
                _reader_sasayaki_play(library, record, page, sasayaki_player, direction="next")
            elif command == "up":
                _reader_sasayaki_play(library, record, page, sasayaki_player, direction="previous")
            elif command in {"", "space"}:
                _reader_sasayaki_toggle(library, record, page, sasayaki_player)
            elif command in {"q", "quit", "exit"}:
                break
            elif command in {"r", "v"}:
                vertical = not vertical
            elif command == "y":
                _reader_sasayaki_panel(library, record, page, sasayaki_player)
            elif command.startswith("/"):
                word = command[1:].strip()
                if word:
                    _show_lookup(word, library)
            elif command.startswith("a "):
                word = command[2:].strip()
                sentence = sentence_around(page.text, word)
                card_path = library.mine_card(word, sentence=sentence)
                print(style("已制卡", MAGENTA), f"{word} -> {card_path}")
                _read_input(style("按 Enter 继续", DIM))
            elif command.startswith("h"):
                note = command[1:].strip()
                if record is None:
                    print("直接阅读文件时没有书架记录，无法保存划线。")
                else:
                    library.add_highlight(record, page.text, note)
                    print(style("已划线当前页", GREEN))
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
            else:
                print("未知命令。")
                _read_input(style("按 Enter 继续", DIM))
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
        print(f"1. {_ui('shelf', library)}")
        print(f"2. {_ui('import_epub', library)}")
        print(f"3. {_ui('read', library)}")
        print(f"4. {_ui('book_settings', library)}")
        print(f"0. {_ui('back', library)}")
        choice = _read_input(style(_ui("choose", library), CYAN)).strip()
        if choice == "1":
            cmd_shelf(argparse.Namespace())
            _pause()
        elif choice == "2":
            _menu_import_book()
        elif choice == "3":
            _menu_shelf_read()
        elif choice == "4":
            _bookshelf_settings()
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


def _menu_demo() -> None:
    pages = paginate(DEMO_TEXT)
    vertical = Library().settings["reader_vertical"] == "true"
    interactive_loop("Hoshi Reader Terminal 演示", DEMO_TEXT, pages, None, vertical)
    _pause("已回到主菜单。按 Enter 继续")


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
        try:
            imported, skipped = library.import_books(targets)
        except Exception as exc:
            print(style(f"批量导入失败：{exc}", RED))
        else:
            print(style("批量导入完成", GREEN), f"新增 {len(imported)} 本，跳过 {len(skipped)} 本")
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
    _print_book_choices(books)
    query = _read_input("输入序号或标题片段开始阅读（留空打开最近一本）：").strip() or None
    record = _find_book_for_input(library, query)
    if record is None:
        print("找不到这本书。")
        _pause()
        return
    try:
        title, text = library.load_record_text(record)
    except Exception as exc:
        print(style(f"打开失败：{exc}", RED))
        _pause()
        return
    pages = paginate(text)
    start_page = page_for_position(pages, record.position)
    vertical = library.settings["reader_vertical"] == "true"
    interactive_loop(title, text, pages, record, vertical, start_page=start_page)
    _pause("已返回。按 Enter 继续")


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
        print("1. 设置词典目录")
        print("2. 扫描并导入词典目录")
        print("3. 查看词典与优先级")
        print("4. 调整词典优先级")
        print("5. 启用 / 停用词典")
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
    print(style("书库设置", BOLD))
    print(f"小说目录: {book_dir}")
    print(f"目录内可导入文件: {len(files)}")
    print("1. 设置小说目录")
    print("2. 扫描并导入小说目录")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    if choice == "1":
        _menu_set_path("book_path", "小说目录")
    elif choice == "2":
        _settings_import_books()


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
    stats = sorted(library.statistics, key=lambda item: (item.date_key, item.title), reverse=True)
    print(style("阅读统计", BOLD))
    if not stats:
        print("还没有统计。")
    else:
        for item in stats:
            minutes = item.reading_time / 60
            print(
                f"{item.date_key}  {item.title}  "
                f"{item.characters_read} 字符  {minutes:.1f} 分钟  {item.last_reading_speed} 字符/分钟"
            )
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
    try:
        imported, skipped = library.import_books(files)
    except Exception as exc:
        print(style(f"导入失败：{exc}", RED))
    else:
        print(style("导入完成", GREEN), f"新增 {len(imported)} 本，跳过 {len(skipped)} 本")
    _pause()


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
    print()
    print("1. 修改 URL")
    print("2. 修改模式")
    print("3. 修改牌组")
    print("4. 修改模板")
    print("5. 修改字段")
    print("6. 测试连接")
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


def _settings_appearance() -> None:
    library = Library()
    current = library.settings["reader_vertical"] == "true"
    language = library.settings.get("language", "zh")
    print(style(_ui("appearance", library), BOLD))
    print(f"1. {_ui('writing_direction', library)}")
    print(f"2. {_ui('language', library)}")
    print(f"{_ui('current', library)}: {_ui('vertical' if current else 'horizontal', library)}")
    print(f"{_ui('language', library)}: {_language_name(language)}")
    choice = _read_input(style(_ui("choose", library), CYAN)).strip()
    if choice == "1":
        library.set_setting("reader_vertical", "false" if current else "true")
        new_direction = _ui("horizontal" if current else "vertical", library)
        print(style(_ui("saved", library), GREEN), f"{_ui('writing_direction', library)}: {new_direction}")
    elif choice == "2":
        _settings_language()
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
    print(style("同步", BOLD))
    print(f"同步目录: {library.settings['sync_path']}")
    print("1. 自动同步阅读进度")
    print("2. 导出到同步目录")
    print("3. 从同步目录导入")
    print("4. 设置同步目录")
    print("0. 返回")
    choice = _read_input(style("请选择：", CYAN)).strip()
    if choice == "1":
        for message in sync_library(library, "auto"):
            print(message)
        _pause()
    elif choice == "2":
        for message in sync_library(library, "export"):
            print(message)
        _pause()
    elif choice == "3":
        for message in sync_library(library, "import"):
            print(message)
        _pause()
    elif choice == "4":
        _menu_set_path("sync_path", "同步目录")


def _advanced_backup() -> None:
    library = Library()
    try:
        archive = create_backup(library)
    except Exception as exc:
        print(style(f"备份失败：{exc}", RED))
    else:
        print(style("备份完成", GREEN), archive)
    _pause()


def _advanced_check_update() -> None:
    try:
        cmd_update(argparse.Namespace(check=False, yes=False, target=None))
    except RuntimeError as exc:
        print(style(str(exc), YELLOW))
    _pause()


def create_backup(library: Library) -> Path:
    backup_dir = library.root.parent / f"{library.root.name}-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    archive = backup_dir / f"hoshi-terminal-backup-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    root = library.root.resolve()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as backup:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.startswith("hoshi-terminal-backup-") and path.suffix == ".zip":
                continue
            backup.write(path, path.resolve().relative_to(root))
    return archive


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


def mine_word(word: str, sentence: str = "", note: str = "") -> str:
    library = Library()
    settings = library.settings
    anki = settings_from_dict(settings)
    outputs: list[str] = []
    csv_path = None
    if anki.mode in {"csv", "both"}:
        csv_path = library.mine_card(word, sentence=sentence, note=note)
        outputs.append(f"CSV: {csv_path}")
    if anki.mode in {"ankiconnect", "both"}:
        try:
            note_id = add_note(anki, word, sentence=sentence, note=note)
        except AnkiConnectError as exc:
            if anki.mode == "ankiconnect":
                outputs.append(f"AnkiConnect 失败: {exc}")
            else:
                outputs.append(f"AnkiConnect 未添加，已保留 CSV: {exc}")
        else:
            outputs.append(f"AnkiConnect: 已添加 note {note_id}")
    if not outputs:
        csv_path = library.mine_card(word, sentence=sentence, note=note)
        outputs.append(f"CSV: {csv_path}")
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


def _sorted_books(library: Library) -> list[BookRecord]:
    return sorted(library.books, key=lambda item: item.last_access, reverse=True)


def _print_book_choices(books: list[BookRecord]) -> None:
    for index, book in enumerate(books, start=1):
        progress = summarize_text_progress(book.position, _safe_text_for_progress(book))
        print(f"{index:>2}. {progress}  {book.title}  {style(book.kind, DIM)}")


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


def _read_reader_command(prompt: str = "") -> str:
    if not sys.stdin.isatty():
        return _read_input(prompt)
    print(prompt, end="", flush=True)
    key = _read_single_key()
    command = _normalize_reader_key(key)
    if command in {"right", "down", "left", "up", "space", ""}:
        print()
        return command
    if command in {"r", "v", "y", "s", "q"}:
        print(command)
        return command
    if command == "/":
        return "/" + _read_input("/")
    if command == "a":
        return "a " + _read_input("a ")
    if command == "h":
        return "h " + _read_input("h ")
    if command == "g":
        return "g " + _read_input("g ")
    print(command)
    return command


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


def _read_single_key() -> str:
    if os.name == "nt":
        import msvcrt

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
        data = os.read(fd, 1)
        if data == b"\x1b":
            for _ in range(5):
                if not select.select([fd], [], [], 0.1)[0]:
                    break
                data += os.read(fd, 1)
        return data.decode(errors="ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _parse_page_number(raw: str, total_pages: int) -> int | None:
    try:
        page = int(raw.strip()) - 1
    except ValueError:
        return None
    return min(total_pages - 1, max(0, page))


def _safe_text_for_progress(book: BookRecord) -> str:
    try:
        return extract_book(Path(book.stored_path)).text
    except Exception:
        return "?"
