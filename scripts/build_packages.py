from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import stat
import tarfile
import zipapp
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP_NAME = "Hoshi-Reader-Terminal"
VERSION = "0.1.4"
PACKAGE_BASE = f"{APP_NAME}-{VERSION}"


WINDOWS_RUN = """@echo off
chcp 65001 >nul
set SCRIPT_DIR=%~dp0
py -3 "%SCRIPT_DIR%hoshi-terminal.pyz" %*
if errorlevel 9009 (
  python "%SCRIPT_DIR%hoshi-terminal.pyz" %*
)
"""

WINDOWS_HOSHI = """@echo off
chcp 65001 >nul
set SCRIPT_DIR=%~dp0
py -3 "%SCRIPT_DIR%hoshi-terminal.pyz" %*
if errorlevel 9009 (
  python "%SCRIPT_DIR%hoshi-terminal.pyz" %*
)
"""


WINDOWS_INSTALL = """@echo off
chcp 65001 >nul
set SCRIPT_DIR=%~dp0
set TARGET=%LOCALAPPDATA%\\HoshiReaderTerminal\\bin
if not exist "%TARGET%" mkdir "%TARGET%"
copy /Y "%SCRIPT_DIR%hoshi-terminal.pyz" "%TARGET%\\hoshi-terminal.pyz" >nul
(
  echo @echo off
  echo py -3 "%%LOCALAPPDATA%%\\HoshiReaderTerminal\\bin\\hoshi-terminal.pyz" %%*
  echo if errorlevel 9009 python "%%LOCALAPPDATA%%\\HoshiReaderTerminal\\bin\\hoshi-terminal.pyz" %%*
) > "%TARGET%\\hoshi-terminal.cmd"
(
  echo @echo off
  echo py -3 "%%LOCALAPPDATA%%\\HoshiReaderTerminal\\bin\\hoshi-terminal.pyz" %%*
  echo if errorlevel 9009 python "%%LOCALAPPDATA%%\\HoshiReaderTerminal\\bin\\hoshi-terminal.pyz" %%*
) > "%TARGET%\\hoshi.cmd"
echo Installed to %TARGET%
echo Add this folder to PATH if you want to run hoshi anywhere.
pause
"""


POSIX_RUN = """#!/bin/sh
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/hoshi-terminal.pyz" "$@"
"""


POSIX_INSTALL = """#!/bin/sh
set -eu
APP_DIR="$HOME/.local/share/hoshi-reader-terminal/app"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$APP_DIR" "$BIN_DIR"
cp "$(dirname "$0")/hoshi-terminal.pyz" "$APP_DIR/hoshi-terminal.pyz"
cat > "$BIN_DIR/hoshi" <<'EOF'
#!/bin/sh
exec python3 "$HOME/.local/share/hoshi-reader-terminal/app/hoshi-terminal.pyz" "$@"
EOF
cp "$BIN_DIR/hoshi" "$BIN_DIR/hoshi-terminal"
chmod +x "$BIN_DIR/hoshi" "$BIN_DIR/hoshi-terminal"
echo "已安装到 $BIN_DIR/hoshi"
echo "如果命令不可用，请把 $BIN_DIR 加入 PATH。"
"""


POSIX_HOSHI = """#!/bin/sh
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/hoshi-terminal.pyz" "$@"
"""


README_TXT = """Hoshi Reader Terminal 便携包

要求：Python 3.10 或更高版本。

快速运行：
- Windows: 双击 hoshi.cmd，或在 PowerShell/CMD 里运行 .\\hoshi.cmd
- macOS/Linux: ./hoshi

安装到用户目录：
- Windows: 双击 install.bat，然后把提示目录加入 PATH
- macOS/Linux: ./install.sh，然后运行 hoshi

常用菜单：
hoshi

常用命令：
hoshi 演示
hoshi 导入 examples/demo_book.txt
hoshi 书架
hoshi 阅读 demo
hoshi 导入词典 examples/mini-yomitan
hoshi 查词 読みました
hoshi 同步 export
"""


def main() -> int:
    DIST.mkdir(exist_ok=True)
    _clean_old_artifacts()
    pyz = DIST / "hoshi-terminal.pyz"
    _build_pyz(pyz)
    _package_windows(pyz)
    _package_posix(pyz, "macos")
    _package_posix(pyz, "linux")
    _copy_install_scripts()
    print("打包完成：")
    for artifact in sorted(DIST.glob(f"{PACKAGE_BASE}-*")):
        if artifact.is_file():
            print(f"  {artifact}")
    for artifact in (DIST / "install.sh", DIST / "install.ps1"):
        print(f"  {artifact}")
    return 0


def _clean_old_artifacts() -> None:
    for path in DIST.glob(f"{APP_NAME}-*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    old_pyz = DIST / "hoshi-terminal.pyz"
    if old_pyz.exists():
        old_pyz.unlink()
    for path in DIST.glob("hoshi-reader-terminal_*.deb"):
        path.unlink()
    for path in (DIST / "install.sh", DIST / "install.ps1"):
        if path.exists():
            path.unlink()


def _build_pyz(target: Path) -> None:
    with TemporaryDirectory() as temp_dir:
        staging = Path(temp_dir) / "app"
        shutil.copytree(ROOT / "hoshi_terminal", staging / "hoshi_terminal")
        zipapp.create_archive(
            staging,
            target=target,
            interpreter="/usr/bin/env python3",
            main="hoshi_terminal.cli:main",
            compressed=True,
        )
    _chmod_executable(target)


def _package_windows(pyz: Path) -> None:
    folder = DIST / f"{PACKAGE_BASE}-windows"
    _common_payload(folder, pyz)
    _write_text(folder / "run.bat", WINDOWS_RUN)
    _write_text(folder / "hoshi.cmd", WINDOWS_HOSHI)
    _write_text(folder / "install.bat", WINDOWS_INSTALL)
    target = DIST / f"{PACKAGE_BASE}-windows.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            archive.write(path, path.relative_to(DIST))


def _package_posix(pyz: Path, platform_name: str) -> None:
    folder = DIST / f"{PACKAGE_BASE}-{platform_name}"
    _common_payload(folder, pyz)
    _write_text(folder / "run.sh", POSIX_RUN)
    _write_text(folder / "hoshi", POSIX_HOSHI)
    _write_text(folder / "install.sh", POSIX_INSTALL)
    _chmod_executable(folder / "run.sh")
    _chmod_executable(folder / "hoshi")
    _chmod_executable(folder / "install.sh")
    _chmod_executable(folder / "hoshi-terminal.pyz")
    target = DIST / f"{PACKAGE_BASE}-{platform_name}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(folder, arcname=folder.name)


def _common_payload(folder: Path, pyz: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    shutil.copy2(pyz, folder / "hoshi-terminal.pyz")
    shutil.copy2(ROOT / "README.md", folder / "README.md")
    shutil.copy2(ROOT / "README.zh-CN.md", folder / "README.zh-CN.md")
    shutil.copy2(ROOT / "LICENSE", folder / "LICENSE")
    shutil.copytree(ROOT / "examples", folder / "examples")
    _write_text(folder / "INSTALL.zh-CN.txt", README_TXT)


def _copy_install_scripts() -> None:
    shutil.copy2(ROOT / "install.sh", DIST / "install.sh")
    shutil.copy2(ROOT / "install.ps1", DIST / "install.ps1")
    _chmod_executable(DIST / "install.sh")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _chmod_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    raise SystemExit(main())
