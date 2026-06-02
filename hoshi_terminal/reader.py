from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .sasayaki import filter_sasayaki_text
from .terminal import BOLD, CYAN, DIM, GREEN, RESET, ansi_enabled, rgb, style, terminal_size, wrap_paragraphs


VERTICAL_NARROW_MAP = {
    "、": "､",
    "。": "｡",
    "，": ",",
    "．": ".",
    "：": ":",
    "；": ";",
    "！": "!",
    "？": "?",
    "「": "｢",
    "」": "｣",
    "『": "｢",
    "』": "｣",
    "（": "(",
    "）": ")",
    "［": "[",
    "］": "]",
    "【": "[",
    "】": "]",
    "・": "･",
    "…": "…",
}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
READER_MUTED = (116, 104, 88)
CURRENT_SENTENCE_BG = (188, 216, 225)
CURRENT_SENTENCE_INK = (18, 38, 45)


@dataclass(frozen=True)
class Page:
    index: int
    start_char: int
    end_char: int
    text: str


def character_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def paginate(text: str, width: int | None = None, lines_per_page: int | None = None) -> list[Page]:
    columns, rows = terminal_size()
    width = width or min(96, max(40, columns - 4))
    lines_per_page = lines_per_page or max(8, rows - 8)
    wrapped = wrap_paragraphs(text, width)
    pages: list[Page] = []
    current: list[str] = []
    start_char = 0
    cursor = 0

    for line in wrapped:
        if len(current) >= lines_per_page:
            page_text = "\n".join(current).strip()
            end_char = cursor
            pages.append(Page(len(pages), start_char, end_char, page_text))
            start_char = end_char
            current = []
        current.append(line)
        cursor += len(line)

    if current:
        page_text = "\n".join(current).strip()
        pages.append(Page(len(pages), start_char, max(cursor, start_char + len(page_text)), page_text))

    return pages or [Page(0, 0, 0, "这本书看起来只有气氛，没有文字。")]


def page_for_position(pages: list[Page], position: int) -> int:
    for index, page in enumerate(pages):
        is_last = index == len(pages) - 1
        if page.start_char <= position < page.end_char or (is_last and page.start_char <= position <= page.end_char):
            return page.index
    return 0


def render_page(
    title: str,
    page: Page,
    total_pages: int,
    vertical: bool = False,
    highlight: str | None = None,
    sasayaki_status: str | None = None,
) -> str:
    if vertical:
        return render_vertical_page(title, page, total_pages, highlight=highlight, sasayaki_status=sasayaki_status)

    header = style(title, BOLD) + style(f"  第 {page.index + 1}/{total_pages} 页", DIM)
    ruler = style("─" * min(96, max(24, len(header))), CYAN)
    page_text = highlight_sentence(page.text, highlight) if highlight else page.text
    content = page_text
    status = [style(f"Sasayaki: {sasayaki_status}", CYAN)] if sasayaki_status else []
    footer = "\n".join(
        [
            style("←/→ 翻页    ↑/↓ Sasayaki 上/下一句    Enter/Space 播放/暂停    t/c 目录    y 有声书    q 退出", DIM),
            style("/ 查词    a 制卡    f 搜索正文    h 划线/备注    l 划线列表    s 统计", DIM),
        ]
    )
    return "\n".join([header, ruler, content, *status, ruler, footer])


def render_vertical_page(
    title: str,
    page: Page,
    total_pages: int,
    highlight: str | None = None,
    sasayaki_status: str | None = None,
) -> str:
    columns, terminal_rows = terminal_size(default_columns=120, default_rows=36)
    width = max(64, columns)
    content_rows = max(10, terminal_rows - 7)
    max_columns = max(4, min(28, (width - 8) // 5))
    percent = (page.index + 1) / max(1, total_pages) * 100.0
    progress = f"{title}  {page.index + 1}/{total_pages}  {percent:.2f}%"
    lines = [
        _layout_line(progress, width, align="right", fg=READER_MUTED, bold=True),
        _layout_line("", width),
    ]
    body = render_vertical(page.text, rows=content_rows, highlight=highlight, paper=True, max_columns=max_columns).splitlines()
    body_width = max((_visible_width(line) for line in body), default=0)
    for line in body:
        left = max(2, (width - body_width) // 2)
        right = max(0, width - left - _visible_width(line))
        lines.append(" " * left + line + " " * right)
    while len(lines) < max(4, terminal_rows - 3):
        lines.append(_layout_line("", width))
    if sasayaki_status:
        lines.append(_layout_line(f"Sasayaki  {sasayaki_status}", width, align="center", fg=READER_MUTED))
    else:
        lines.append(_layout_line("", width))
    lines.append(
        _layout_line(
            "←/→ 翻页    ↑/↓ 上/下一句    Enter/Space 播放/暂停    t/c 目录    / 查词    a 制卡    f 搜索    l 划线    q 退出",
            width,
            align="center",
            fg=READER_MUTED,
        )
    )
    return "\n".join(lines[:terminal_rows])


def highlight_sentence(text: str, highlight: str | None) -> str:
    ranges = _highlight_ranges(text, highlight)
    if not ranges:
        return text
    start, end = ranges[0]
    return text[:start] + style(text[start:end], BOLD + CYAN) + text[end:]


def _highlight_ranges(text: str, highlight: str | None) -> list[tuple[int, int]]:
    if not highlight:
        return []
    if highlight in text:
        start = text.find(highlight)
        return [(start, start + len(highlight))]
    filtered_text, positions = _filtered_with_positions(text)
    filtered_highlight = filter_sasayaki_text(highlight)
    if not filtered_text or not filtered_highlight:
        return []
    index = filtered_text.find(filtered_highlight)
    if index < 0:
        return []
    start = positions[index]
    end = positions[index + len(filtered_highlight) - 1] + 1
    return [(start, end)]


def _filtered_with_positions(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        filtered = filter_sasayaki_text(char)
        for item in filtered:
            chars.append(item)
            positions.append(index)
    return "".join(chars), positions


def render_vertical(
    text: str,
    rows: int | None = None,
    highlight: str | None = None,
    paper: bool = False,
    max_columns: int | None = None,
) -> str:
    _, terminal_rows = terminal_size()
    rows = rows or max(8, min(24, terminal_rows - 10))
    chunks = _vertical_columns(text, rows, highlight)
    if not chunks:
        return ""
    chunks = chunks[: max_columns or 8]
    output: list[str] = []
    for row in range(rows):
        cells = []
        for chunk in reversed(chunks):
            if row < len(chunk):
                char, is_highlighted = chunk[row]
                cells.append(vertical_cell(char, highlighted=is_highlighted, paper=paper))
            else:
                cells.append("  ")
        output.append(" ".join(cells).rstrip())
    if paper:
        return "\n".join(output).rstrip()
    warning = style("[竖排显示]", GREEN)
    return warning + "\n" + "\n".join(output).rstrip()


def _vertical_columns(text: str, rows: int, highlight: str | None) -> list[list[tuple[str, bool]]]:
    ranges = _highlight_ranges(text, highlight)
    columns: list[list[tuple[str, bool]]] = []
    offset = 0
    previous_was_blank = False
    for line in text.splitlines() or [text]:
        items = _vertical_items(line, ranges, offset)
        if items:
            columns.extend(items[index : index + rows] for index in range(0, len(items), rows))
            previous_was_blank = False
        elif columns and not previous_was_blank:
            columns.append([])
            previous_was_blank = True
        offset += len(line) + 1
    while columns and not columns[-1]:
        columns.pop()
    return columns


def _vertical_items(
    text: str,
    ranges: list[tuple[int, int]],
    offset: int = 0,
) -> list[tuple[str, bool]]:
    items: list[tuple[str, bool]] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        absolute_index = offset + index
        highlighted = any(start <= absolute_index < end for start, end in ranges)
        items.append((char, highlighted))
    return items


def vertical_cell(char: str, highlighted: bool = False, paper: bool = False) -> str:
    visible = VERTICAL_NARROW_MAP.get(char, char)
    width = terminal_cell_width(visible)
    if width <= 0:
        cell = "  "
    else:
        cell = visible + (" " * max(0, 2 - width))
    if paper:
        if highlighted:
            return _ansi_span(cell, fg=CURRENT_SENTENCE_INK, bg=CURRENT_SENTENCE_BG, bold=True)
        return cell
    if highlighted:
        return style(cell, BOLD + CYAN)
    return cell


def terminal_cell_width(char: str) -> int:
    if not char:
        return 0
    width = 0
    for codepoint in char:
        category = unicodedata.category(codepoint)
        if category.startswith("M") or category == "Cf":
            continue
        width += 2 if unicodedata.east_asian_width(codepoint) in {"W", "F"} else 1
    return width


def _ansi_span(
    text: str,
    fg: tuple[int, int, int] | None = None,
    bg: tuple[int, int, int] | None = None,
    bold: bool = False,
) -> str:
    if not ansi_enabled():
        return text
    code = rgb(fg, bg)
    if not code and not bold:
        return text
    return f"{BOLD if bold else ''}{code}{text}{RESET}"


def _layout_line(
    content: str,
    width: int,
    align: str = "left",
    fg: tuple[int, int, int] | None = None,
    bold: bool = False,
) -> str:
    visible = _visible_width(content)
    if visible > width:
        content = _truncate_visible(content, width)
        visible = _visible_width(content)
    remaining = max(0, width - visible)
    if align == "center":
        left = remaining // 2
        right = remaining - left
    elif align == "right":
        left = remaining
        right = 0
    else:
        left = 0
        right = remaining
    return _ansi_span(" " * left + content + " " * right, fg=fg, bold=bold)


def _visible_width(text: str) -> int:
    plain = ANSI_RE.sub("", text)
    return sum(terminal_cell_width(char) for char in plain)


def _truncate_visible(text: str, width: int) -> str:
    output: list[str] = []
    used = 0
    plain = ANSI_RE.sub("", text)
    for char in plain:
        char_width = terminal_cell_width(char)
        if used + char_width > width:
            break
        output.append(char)
        used += char_width
    return "".join(output)


def sentence_around(text: str, needle: str) -> str:
    index = text.find(needle)
    if index < 0:
        return text.strip().split("\n", 1)[0][:160]
    start = max(text.rfind("。", 0, index), text.rfind(".", 0, index), text.rfind("\n", 0, index))
    end_candidates = [candidate for candidate in [text.find("。", index), text.find(".", index), text.find("\n", index)] if candidate >= 0]
    end = min(end_candidates) + 1 if end_candidates else min(len(text), index + 160)
    return text[start + 1 : end].strip()
