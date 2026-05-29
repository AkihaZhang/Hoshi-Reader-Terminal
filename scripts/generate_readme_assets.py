from __future__ import annotations

from html import escape
from pathlib import Path
import os
import re
import subprocess
import tempfile
import textwrap


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "docs" / "images"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ASSET_BOOK = Path(os.environ.get("HOSHI_ASSET_BOOK", ROOT / "测试用" / "かがみの孤城 (辻村深月) (Z-Library).epub"))
ASSET_SRT = Path(os.environ.get("HOSHI_ASSET_SRT", ROOT / "测试用" / "かがみの孤城 [audiobook.jp 244083].srt"))
ASSET_AUDIO = Path(os.environ.get("HOSHI_ASSET_AUDIO", ROOT / "测试用" / "かがみの孤城 [audiobook.jp 244083].m4b"))


def main() -> int:
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for required in (ASSET_BOOK,):
        if not required.exists():
            raise FileNotFoundError(f"README asset source not found: {required}")
    with tempfile.TemporaryDirectory() as temp_dir:
        home = Path(temp_dir) / "home"
        sync = Path(temp_dir) / "sync"
        _run(["python3", "-m", "hoshi_terminal", "导入", str(ASSET_BOOK)], home=home)
        if ASSET_SRT.exists():
            command = ["python3", "-m", "hoshi_terminal", "sasayaki", "match", "1", str(ASSET_SRT)]
            if ASSET_AUDIO.exists():
                command += ["--audio", str(ASSET_AUDIO)]
            _run(command, home=home)
        _set_asset_progress(home)
        sasayaki_status = _run(["python3", "-m", "hoshi_terminal", "sasayaki", "status", "1"], home=home)
        sasayaki_status = sasayaki_status.replace(str(ASSET_SRT.resolve()), "测试用/かがみの孤城.srt")
        sasayaki_status = sasayaki_status.replace(str(ASSET_AUDIO.resolve()), "测试用/かがみの孤城.m4b")

        captures = {
            "01-menu.svg": _snippet(
                """
                from hoshi_terminal.terminal import banner
                print(banner())
                print("Hoshi Reader")
                print("1. 书库")
                print("2. 查词")
                print("3. 设置")
                print("0. 退出")
                print("请选择：")
                """,
                color=True,
            ),
            "02-reader.svg": _run(["python3", "-m", "hoshi_terminal", "阅读", "1", "--print", "--width", "72", "--lines", "15"], home=home),
            "03-dictionary.svg": _run(["python3", "-m", "hoshi_terminal", "查词", "秋"]),
            "04-sync.svg": _run(["python3", "-m", "hoshi_terminal", "同步", "export", "--path", str(sync)], home=home),
            "05-settings.svg": _snippet(
                """
                from hoshi_terminal.terminal import banner
                print(banner())
                print("设置")
                print("1. 辞典")
                print("2. Anki")
                print("3. 外观")
                print("4. 高级")
                print("5. 诊断")
                print("6. 关于")
                print("0. 返回主菜单")
                print()
                print("高级")
                print("1. 统计")
                print("2. 同步")
                print("3. AnkiConnect")
                print("4. 备份")
                print("5. Sasayaki 有声书")
                print("6. 检查更新")
                print("0. 返回")
                """,
                color=True,
            ),
            "06-sasayaki.svg": sasayaki_status,
        }

    for name, text in captures.items():
        (IMAGE_DIR / name).write_text(render_terminal_svg(text), encoding="utf-8")
    return 0


def _run(
    command: list[str],
    stdin: str | None = None,
    home: Path | None = None,
    color: bool = False,
) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    if color:
        env["FORCE_COLOR"] = "1"
    if home is not None:
        env["HOSHI_TERMINAL_HOME"] = str(home)
    result = subprocess.run(
        command,
        input=stdin,
        text=True,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return clean_terminal_output(result.stdout)


def _snippet(code: str, color: bool = False) -> str:
    return _run(["python3", "-c", textwrap.dedent(code)], color=color)


def _set_asset_progress(home: Path) -> None:
    script = textwrap.dedent(
        """
        from hoshi_terminal.storage import Library
        library = Library()
        record = library.books[0]
        library.update_book_progress(record.id, 120, 1700000000000)
        library.add_statistic(record.title, 120, 45)
        library._save_state()
        """
    )
    _run(["python3", "-c", script], home=home)


def clean_terminal_output(text: str) -> str:
    cleaned = ANSI_RE.sub("", text)
    cleaned = cleaned.replace("\x1b[3J", "").replace("\x1b[2J", "").replace("\x1b[H", "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in cleaned.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def render_terminal_svg(text: str) -> str:
    lines = _trim_lines(text)
    width = max(720, min(1040, max((visual_width(line) for line in lines), default=80) * 9 + 48))
    height = 54 + len(lines) * 19 + 30
    body_width = width - 48
    rows = []
    for index, line in enumerate(lines):
        y = 58 + index * 19
        fill = "#d8f5ff" if "Hoshi Reader Terminal" in line else "#e8eef2"
        if line.strip(" @") == "" and "@" in line:
            fill = "#8bdcff"
        if line.startswith("Hoshi Reader") or line in {"书库", "查词", "设置", "高级", "同步"}:
            fill = "#7ee6c4"
        if "已" in line or "词典" in line:
            fill = "#a8f3b2"
        if "请选择" in line or "hoshi>" in line:
            fill = "#79d7ff"
        rows.append(
            f'<text x="24" y="{y}" fill="{fill}" font-family="SFMono-Regular, Menlo, Consolas, monospace" '
            f'font-size="15" xml:space="preserve">{escape(line)}</text>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Hoshi Reader Terminal screenshot">
  <rect width="{width}" height="{height}" rx="8" fill="#111820"/>
  <rect x="0" y="0" width="{width}" height="34" rx="8" fill="#202a33"/>
  <circle cx="22" cy="17" r="6" fill="#ff5f57"/>
  <circle cx="42" cy="17" r="6" fill="#ffbd2e"/>
  <circle cx="62" cy="17" r="6" fill="#28c840"/>
  <text x="86" y="22" fill="#9fb4c0" font-family="SFMono-Regular, Menlo, Consolas, monospace" font-size="13">hoshi</text>
  <rect x="16" y="44" width="{body_width}" height="{height - 60}" rx="6" fill="#0b1016" stroke="#263542"/>
  {''.join(rows)}
</svg>
"""


def _trim_lines(text: str) -> list[str]:
    raw = text.splitlines()
    if not raw:
        return [""]
    if len(raw) > 34:
        raw = raw[:32] + ["..."]
    return [line[:110] for line in raw]


def visual_width(text: str) -> int:
    width = 0
    for char in text:
        width += 2 if ord(char) > 127 else 1
    return width


if __name__ == "__main__":
    raise SystemExit(main())
