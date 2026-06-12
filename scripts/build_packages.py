from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import stat
import zipapp


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    pyz = DIST / "hoshi-terminal.pyz"
    _build_pyz(pyz)
    shutil.copy2(ROOT / "install.sh", DIST / "install.sh")
    shutil.copy2(ROOT / "install.ps1", DIST / "install.ps1")
    _chmod_executable(DIST / "install.sh")
    _write_checksums([pyz, DIST / "install.sh", DIST / "install.ps1"])

    print("打包完成：")
    for artifact in sorted(DIST.iterdir()):
        print(f"  {artifact}")
    return 0


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


def _write_checksums(paths: list[Path]) -> None:
    lines = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    (DIST / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="ascii")


def _chmod_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    raise SystemExit(main())
