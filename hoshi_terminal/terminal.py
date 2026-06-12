from __future__ import annotations

from contextlib import contextmanager
import os
import shutil
import sys
import textwrap
from typing import Iterator


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
ALT_SCREEN_ENTER = "\033[?1049h"
ALT_SCREEN_EXIT = "\033[?1049l"
CURSOR_HIDE = "\033[?25l"
CURSOR_SHOW = "\033[?25h"


def ansi_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty() or os.environ.get("FORCE_COLOR") == "1"


def style(text: str, code: str) -> str:
    if not ansi_enabled():
        return text
    return f"{code}{text}{RESET}"


def rgb(foreground: tuple[int, int, int] | None = None, background: tuple[int, int, int] | None = None) -> str:
    parts: list[str] = []
    if foreground is not None:
        parts.append(f"38;2;{foreground[0]};{foreground[1]};{foreground[2]}")
    if background is not None:
        parts.append(f"48;2;{background[0]};{background[1]};{background[2]}")
    return "\033[" + ";".join(parts) + "m" if parts else ""


def clear_screen() -> str:
    if not ansi_enabled():
        return "\n" * 3
    return "\033[3J\033[2J\033[H"


def draw_screen(frame: str) -> None:
    if not ansi_enabled():
        print(clear_screen(), end="")
        print(frame)
        return
    sys.stdout.write(f"\033[H{frame}\033[J")
    sys.stdout.flush()


def set_cursor_visible(visible: bool) -> None:
    if ansi_enabled():
        sys.stdout.write(CURSOR_SHOW if visible else CURSOR_HIDE)
        sys.stdout.flush()


@contextmanager
def reader_screen() -> Iterator[None]:
    active = ansi_enabled() and sys.stdin.isatty() and sys.stdout.isatty()
    if active:
        sys.stdout.write(ALT_SCREEN_ENTER + CURSOR_HIDE + "\033[H\033[2J")
        sys.stdout.flush()
    try:
        yield
    finally:
        if active:
            sys.stdout.write(CURSOR_SHOW + ALT_SCREEN_EXIT)
            sys.stdout.flush()


def terminal_size(default_columns: int = 88, default_rows: int = 28) -> tuple[int, int]:
    size = shutil.get_terminal_size((default_columns, default_rows))
    return size.columns, size.lines


def wrap_paragraphs(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").split("\n"):
        stripped = paragraph.strip()
        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        wrapped = textwrap.wrap(
            stripped,
            width=max(20, width),
            break_long_words=False,
            replace_whitespace=True,
        )
        lines.extend(wrapped or [""])
    return lines


def box(title: str, body: str, width: int | None = None) -> str:
    width = width or min(88, terminal_size()[0])
    content_width = max(24, width - 4)
    top = "╭" + "─" * (content_width + 2) + "╮"
    bottom = "╰" + "─" * (content_width + 2) + "╯"
    title_line = f"│ {title[:content_width].ljust(content_width)} │"
    body_lines = wrap_paragraphs(body, content_width)
    padded = [f"│ {line[:content_width].ljust(content_width)} │" for line in body_lines]
    return "\n".join([top, title_line, "├" + "─" * (content_width + 2) + "┤", *padded, bottom])


def ascii_box(title: str, body: str, width: int | None = None) -> str:
    width = width or min(88, terminal_size()[0])
    content_width = max(24, width - 4)
    top = "+" + "-" * (content_width + 2) + "+"
    bottom = "+" + "-" * (content_width + 2) + "+"
    title_line = f"| {title[:content_width].ljust(content_width)} |"
    body_lines = wrap_paragraphs(body, content_width)
    padded = [f"| {line[:content_width].ljust(content_width)} |" for line in body_lines]
    return "\n".join([top, title_line, "+" + "-" * (content_width + 2) + "+", *padded, bottom])


def banner() -> str:
    rendered_logo = "\n".join(logo_lines())
    title = style("    Hoshi Reader Terminal", CYAN)
    return f"{rendered_logo}\n{title}"


def logo_lines() -> list[str]:
    # Rasterized from the upstream Hoshi icon shape into terminal cells.
    # Dense ASCII reads more clearly than braille on light terminal themes.
    icon = [
        "         m@@m++++mNNm@@@@@@@@@@@@@@Ny,",
        "          m@@@@@@@@@NNmm+++ii@@@@@@@h",
        "           @@@@N      .:ii;.  ;@@@@@@,",
        "           i@@@@hdm@@@@@@@@@h d@@@@@:",
        "            @@@@@NNmm@@+i:, .@@@@@i",
        "            y@@@@     .:iNNmm@@@@+",
        "             @@@@@@@@@@@@@@@@@@@@i",
        "             ,N@@mmN@mm+;::,;NNi:",
        "          d@mhi    m@@@@@d:",
        "         .@@@@@@i  .@@@@@@:.:iNNNmi",
        "         m@@@@@dmNN@@@@@@@@@@@@@@@y",
        "        h@@@@@@@@@@@@@@@@@@@NNmm+;",
        "      .N@@@y  ,;ii;;N@@@@:",
        "     ;@@di          m@@@@+mNNddN:",
        "    :y:      ohdmN@@@@@@@@@@@@@@@@:",
        "             im@@@@@@@@@@NNm+i;,.",
        "                    @@@@@",
        "                    @@@@@:;i+mNNdmN@@@@@@Nh:",
        " :;ii++ommNNddmN@@@@@@@@@@@@@@@@@@@@@@@@@@@@N",
        " i@@@@@@@@@@@@@@@@@@@NNmmmddddNNNNddmN@@@@@@@",
    ]
    if ansi_enabled():
        colors = [
            (20, 162, 218),
            (43, 183, 224),
            (72, 202, 214),
            (92, 214, 190),
            (42, 176, 214),
            (71, 196, 224),
        ]
        return [f"{rgb(colors[index % len(colors)])}{line}{RESET}" for index, line in enumerate(icon)]
    return icon
