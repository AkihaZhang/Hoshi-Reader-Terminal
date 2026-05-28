from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .terminal import BOLD, CYAN, DIM, GREEN, style, terminal_size, wrap_paragraphs


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
    for page in pages:
        if page.start_char <= position <= page.end_char:
            return page.index
    return 0


def render_page(title: str, page: Page, total_pages: int, vertical: bool = False) -> str:
    header = style(title, BOLD) + style(f"  第 {page.index + 1}/{total_pages} 页", DIM)
    ruler = style("─" * min(96, max(24, len(header))), CYAN)
    content = render_vertical(page.text) if vertical else page.text
    footer = "\n".join(
        [
            style("←/→ 翻页    ↑/↓ Sasayaki 上/下一句    Enter/Space 播放/暂停    r 排版    y 详情    q 退出", DIM),
            style("输入 /読みました 查词    输入 a 読む 制卡    输入 h 备注内容 划线", DIM),
        ]
    )
    return "\n".join([header, ruler, content, ruler, footer])


def render_vertical(text: str, rows: int | None = None) -> str:
    plain = re.sub(r"\s+", "", text)
    if not plain:
        return ""
    _, terminal_rows = terminal_size()
    rows = rows or max(8, min(24, terminal_rows - 10))
    chunks = [plain[index : index + rows] for index in range(0, len(plain), rows)]
    chunks = chunks[:8]
    output: list[str] = []
    for row in range(rows):
        cells = []
        for chunk in reversed(chunks):
            cells.append(vertical_cell(chunk[row]) if row < len(chunk) else "  ")
        output.append(" ".join(cells).rstrip())
    warning = style("[竖排显示]", GREEN)
    return warning + "\n" + "\n".join(output).rstrip()


def vertical_cell(char: str) -> str:
    visible = VERTICAL_NARROW_MAP.get(char, char)
    width = terminal_cell_width(visible)
    if width <= 0:
        return "  "
    return visible + (" " * max(0, 2 - width))


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


def sentence_around(text: str, needle: str) -> str:
    index = text.find(needle)
    if index < 0:
        return text.strip().split("\n", 1)[0][:160]
    start = max(text.rfind("。", 0, index), text.rfind(".", 0, index), text.rfind("\n", 0, index))
    end_candidates = [candidate for candidate in [text.find("。", index), text.find(".", index), text.find("\n", index)] if candidate >= 0]
    end = min(end_candidates) + 1 if end_candidates else min(len(text), index + 160)
    return text[start + 1 : end].strip()
