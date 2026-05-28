from __future__ import annotations

from dataclasses import dataclass
from urllib import request
from urllib.error import HTTPError, URLError
import json
import re


LATEST_RELEASE_API = "https://api.github.com/repos/AkihaZhang/Hoshi-Reader-Terminal/releases/latest"
INSTALL_SH_URL = "https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/latest/download/install.sh"
INSTALL_PS1_URL = "https://github.com/AkihaZhang/Hoshi-Reader-Terminal/releases/latest/download/install.ps1"


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    has_update: bool


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
    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        release_url=release_url,
        has_update=_version_key(latest_version) > _version_key(current_version),
    )


def format_update_info(info: UpdateInfo) -> str:
    if info.has_update:
        return "\n".join(
            [
                f"发现新版本：{info.latest_version}（当前 {info.current_version}）",
                f"Release: {info.release_url}",
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


def _version_key(version: str) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", version)]
    return tuple(parts or [0])
