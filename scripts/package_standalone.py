from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hoshi_terminal import __version__

DIST = ROOT / "dist"
APP_NAME = "Hoshi-Reader-Terminal"


WINDOWS_RUN = """@echo off
chcp 65001 >nul
set SCRIPT_DIR=%~dp0
"%SCRIPT_DIR%hoshi.exe" %*
"""


WINDOWS_INSTALL = """@echo off
chcp 65001 >nul
set SCRIPT_DIR=%~dp0
set TARGET=%LOCALAPPDATA%\\HoshiReaderTerminal\\bin
if not exist "%TARGET%" mkdir "%TARGET%"
copy /Y "%SCRIPT_DIR%hoshi.exe" "%TARGET%\\hoshi.exe" >nul
(
  echo @echo off
  echo "%%LOCALAPPDATA%%\\HoshiReaderTerminal\\bin\\hoshi.exe" %%*
) > "%TARGET%\\hoshi.cmd"
echo Installed to %TARGET%
echo Add this folder to PATH if you want to run hoshi anywhere.
pause
"""


POSIX_RUN = """#!/bin/sh
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$SCRIPT_DIR/hoshi" "$@"
"""


POSIX_INSTALL = """#!/bin/sh
set -eu
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
cp "$(dirname "$0")/hoshi" "$BIN_DIR/hoshi"
cp "$(dirname "$0")/hoshi" "$BIN_DIR/hoshi-terminal"
chmod +x "$BIN_DIR/hoshi" "$BIN_DIR/hoshi-terminal"
echo "已安装到 $BIN_DIR/hoshi"
echo "如果命令不可用，请把 $BIN_DIR 加入 PATH。"
"""


INSTALL_TEXT = """Hoshi Reader Terminal 独立安装包

这个包已经包含运行时，不需要另装 Python。

快速运行：
- Windows: 双击 hoshi.cmd，或在 PowerShell/CMD 里运行 .\\hoshi.cmd
- macOS/Linux: ./hoshi

安装到用户目录：
- Windows: 双击 install.bat，然后把提示目录加入 PATH
- macOS/Linux: ./install.sh，然后运行 hoshi
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("platform", choices=["windows", "macos", "linux"])
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--deb", action="store_true", help="Linux only: also build a .deb package")
    args = parser.parse_args()

    executable = args.executable.resolve()
    if not executable.exists():
        raise FileNotFoundError(executable)

    DIST.mkdir(exist_ok=True)
    package = build_package(args.platform, executable, args.version)
    print(package)
    if args.deb:
        print(build_deb(executable, args.version))
    return 0


def build_package(platform_name: str, executable: Path, version: str) -> Path:
    package_base = f"{APP_NAME}-{version}-{platform_name}-standalone"
    folder = DIST / package_base
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    _common_payload(folder)

    if platform_name == "windows":
        shutil.copy2(executable, folder / "hoshi.exe")
        _write_text(folder / "run.bat", WINDOWS_RUN)
        _write_text(folder / "hoshi.cmd", WINDOWS_RUN)
        _write_text(folder / "install.bat", WINDOWS_INSTALL)
        target = DIST / f"{package_base}.zip"
        if target.exists():
            target.unlink()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob("*")):
                archive.write(path, path.relative_to(DIST))
        return target

    shutil.copy2(executable, folder / "hoshi")
    _chmod_executable(folder / "hoshi")
    _write_text(folder / "run.sh", POSIX_RUN)
    _write_text(folder / "install.sh", POSIX_INSTALL)
    _chmod_executable(folder / "run.sh")
    _chmod_executable(folder / "install.sh")
    target = DIST / f"{package_base}.tar.gz"
    if target.exists():
        target.unlink()
    with tarfile.open(target, "w:gz") as archive:
        archive.add(folder, arcname=folder.name)
    return target


def build_deb(executable: Path, version: str) -> Path:
    deb_root = DIST / f"hoshi-reader-terminal_{version}_amd64"
    if deb_root.exists():
        shutil.rmtree(deb_root)
    bin_dir = deb_root / "usr" / "bin"
    doc_dir = deb_root / "usr" / "share" / "doc" / "hoshi-reader-terminal"
    control_dir = deb_root / "DEBIAN"
    bin_dir.mkdir(parents=True)
    doc_dir.mkdir(parents=True)
    control_dir.mkdir(parents=True)
    shutil.copy2(executable, bin_dir / "hoshi")
    _chmod_executable(bin_dir / "hoshi")
    shutil.copy2(ROOT / "README.md", doc_dir / "README.md")
    shutil.copy2(ROOT / "LICENSE", doc_dir / "copyright")
    _write_text(
        control_dir / "control",
        f"""Package: hoshi-reader-terminal
Version: {version}
Section: text
Priority: optional
Architecture: amd64
Maintainer: Hoshi Reader Terminal contributors
Description: Terminal reader inspired by Hoshi Reader
 A terminal interface for reading, dictionary lookup, card creation, and progress sync.
""",
    )
    target = DIST / f"hoshi-reader-terminal_{version}_amd64.deb"
    if target.exists():
        target.unlink()
    subprocess.run(["dpkg-deb", "--build", str(deb_root), str(target)], check=True)
    return target


def _common_payload(folder: Path) -> None:
    shutil.copy2(ROOT / "README.md", folder / "README.md")
    shutil.copy2(ROOT / "README.zh-CN.md", folder / "README.zh-CN.md")
    shutil.copy2(ROOT / "LICENSE", folder / "LICENSE")
    shutil.copytree(ROOT / "examples", folder / "examples")
    _write_text(folder / "INSTALL.zh-CN.txt", INSTALL_TEXT)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")


def _chmod_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    raise SystemExit(main())
