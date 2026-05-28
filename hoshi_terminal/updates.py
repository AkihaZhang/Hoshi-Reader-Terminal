from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError
import os
import json
import platform
import re
import shutil
import sys
import tarfile
import tempfile
import zipfile


LATEST_RELEASE_API = "https://api.github.com/repos/AkihaZhang/Hoshi-Reader-Terminal/releases/latest"
INSTALL_SH_URL = "https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/latest/download/install.sh"
INSTALL_PS1_URL = "https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/latest/download/install.ps1"


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    has_update: bool
    assets: list[ReleaseAsset] = field(default_factory=list)


@dataclass(frozen=True)
class UpdateInstallResult:
    info: UpdateInfo
    target: Path
    asset_name: str
    backup: Path | None
    installed: bool


def check_for_updates(current_version: str, timeout: float = 5.0) -> UpdateInfo:
    req = request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Hoshi-Reader-Terminal",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"检查更新失败：{exc}") from exc

    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise RuntimeError("检查更新失败：GitHub Release 没有返回版本号")
    latest_version = tag[1:] if tag.startswith("v") else tag
    release_url = str(payload.get("html_url") or f"https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/tag/{tag}")
    assets = [
        ReleaseAsset(name=str(item.get("name", "")), download_url=str(item.get("browser_download_url", "")))
        for item in payload.get("assets", [])
        if isinstance(item, dict) and item.get("name") and item.get("browser_download_url")
    ]
    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        release_url=release_url,
        has_update=_version_key(latest_version) > _version_key(current_version),
        assets=assets,
    )


def format_update_info(info: UpdateInfo) -> str:
    if info.has_update:
        return "\n".join(
            [
                f"发现新版本：{info.latest_version}（当前 {info.current_version}）",
                f"Release: {info.release_url}",
                "运行 `hoshi 更新` 可直接更新当前便携安装。",
                "macOS / Linux 一键安装:",
                f"curl -fsSL {INSTALL_SH_URL} | sh",
                "Windows PowerShell 一键安装:",
                f"irm {INSTALL_PS1_URL} | iex",
            ]
        )
    if _version_key(info.current_version) > _version_key(info.latest_version):
        return "\n".join(
            [
                f"当前版本：{info.current_version}",
                f"已发布最新版本：{info.latest_version}",
                f"Release: {info.release_url}",
            ]
        )
    return "\n".join(
        [
            f"已经是最新版本：{info.current_version}",
            f"Release: {info.release_url}",
        ]
    )


def install_latest_update(
    current_version: str,
    target: str | Path | None = None,
    timeout: float = 30.0,
    info: UpdateInfo | None = None,
) -> UpdateInstallResult:
    info = info or check_for_updates(current_version, timeout=timeout)
    target_path = resolve_update_target(target)
    if not info.has_update:
        return UpdateInstallResult(info=info, target=target_path, asset_name="", backup=None, installed=False)

    asset = release_asset_for_platform(info)
    with tempfile.TemporaryDirectory(prefix="hoshi-update-") as temp_dir:
        temp_root = Path(temp_dir)
        package = temp_root / asset.name
        _download(asset.download_url, package, timeout=timeout)
        extracted_pyz = extract_pyz_from_package(package, temp_root / "extract")
        backup = target_path.with_suffix(target_path.suffix + ".bak")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            shutil.copy2(target_path, backup)
        temp_target = target_path.with_suffix(target_path.suffix + ".new")
        shutil.copy2(extracted_pyz, temp_target)
        try:
            os.replace(temp_target, target_path)
        except OSError as exc:
            if backup.exists():
                shutil.copy2(backup, target_path)
            raise RuntimeError(f"替换程序失败：{exc}") from exc
        _chmod_executable(target_path)
    return UpdateInstallResult(info=info, target=target_path, asset_name=asset.name, backup=backup, installed=True)


def resolve_update_target(target: str | Path | None = None) -> Path:
    if target is not None:
        return Path(target).expanduser().resolve()
    candidate = Path(sys.argv[0]).expanduser()
    if candidate.name == "hoshi-terminal.pyz" or candidate.suffix == ".pyz":
        return candidate.resolve()
    raise RuntimeError(
        "当前不是便携 pyz 安装，无法原地更新。请使用一键安装脚本，或用 `hoshi 更新 --target /path/to/hoshi-terminal.pyz`。"
    )


def release_asset_for_platform(info: UpdateInfo) -> ReleaseAsset:
    platform_name = package_platform()
    expected = f"Hoshi-Reader-Terminal-{info.latest_version}-{platform_name}"
    suffix = ".zip" if platform_name == "windows" else ".tar.gz"
    expected += suffix
    for asset in info.assets:
        if asset.name == expected:
            return asset
    raise RuntimeError(f"Release 中没有当前系统安装包：{expected}")


def package_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    if system == "Linux":
        return "linux"
    raise RuntimeError(f"暂不支持自动更新当前系统：{system}")


def extract_pyz_from_package(package: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    if package.suffix == ".zip":
        with zipfile.ZipFile(package) as archive:
            for member in archive.namelist():
                _ensure_inside(destination, destination / member)
            archive.extractall(destination)
    elif package.name.endswith(".tar.gz"):
        with tarfile.open(package, "r:gz") as archive:
            for member in archive.getmembers():
                _ensure_inside(destination, destination / member.name)
            archive.extractall(destination)
    else:
        raise RuntimeError(f"不支持的安装包格式：{package.name}")
    matches = list(destination.rglob("hoshi-terminal.pyz"))
    if not matches:
        raise RuntimeError("安装包里没有 hoshi-terminal.pyz")
    return matches[0]


def format_update_install_result(result: UpdateInstallResult) -> str:
    if not result.installed:
        return format_update_info(result.info)
    lines = [
        f"已更新到 {result.info.latest_version}",
        f"安装目标: {result.target}",
        f"安装包: {result.asset_name}",
    ]
    if result.backup:
        lines.append(f"备份: {result.backup}")
    lines.append("重新运行 `hoshi --version` 可确认版本。")
    return "\n".join(lines)


def _download(url: str, target: Path, timeout: float) -> None:
    req = request.Request(url, headers={"User-Agent": "Hoshi-Reader-Terminal"})
    try:
        with request.urlopen(req, timeout=timeout) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"下载更新失败：{exc}") from exc


def _chmod_executable(path: Path) -> None:
    if os.name != "nt":
        path.chmod(path.stat().st_mode | 0o755)


def _ensure_inside(root: Path, target: Path) -> None:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if root_resolved != target_resolved and root_resolved not in target_resolved.parents:
        raise RuntimeError(f"安装包路径不安全：{target}")


def _version_key(version: str) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", version)]
    return tuple(parts or [0])
