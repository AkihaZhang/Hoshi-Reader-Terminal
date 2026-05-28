#!/bin/sh
set -eu

REPO="AkihaZhang/Hoshi-Reader-Terminal"
API_URL="https://api.github.com/repos/$REPO/releases/latest"
DOWNLOAD_BASE="https://github.com/$REPO/releases/download"

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少命令: $1"
    exit 1
  fi
}

need curl
need tar

if ! command -v python3 >/dev/null 2>&1; then
  echo "Hoshi Reader Terminal 需要 Python 3.10+。"
  echo "请先安装 Python 3.10+，然后重新运行本脚本。"
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Hoshi Reader Terminal 需要 Python 3.10+。")
PY

case "$(uname -s)" in
  Darwin) platform="macos" ;;
  Linux) platform="linux" ;;
  *)
    echo "当前 install.sh 只支持 macOS / Linux。Windows 请使用 install.ps1。"
    exit 1
    ;;
esac

tag="${HOSHI_VERSION:-}"
if [ -z "$tag" ]; then
  tag="$(curl -fsSL "$API_URL" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
fi
if [ -z "$tag" ]; then
  echo "无法获取最新版本。"
  exit 1
fi
case "$tag" in
  v*) version="${tag#v}" ;;
  *) version="$tag"; tag="v$tag" ;;
esac

asset="Hoshi-Reader-Terminal-$version-$platform.tar.gz"
url="$DOWNLOAD_BASE/$tag/$asset"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT INT TERM

echo "下载 $asset"
curl -fL "$url" -o "$tmp_dir/$asset"
tar -xzf "$tmp_dir/$asset" -C "$tmp_dir"
"$tmp_dir/Hoshi-Reader-Terminal-$version-$platform/install.sh"

echo
echo "安装完成。新开一个终端后运行: hoshi"
echo "检查更新: hoshi 检查更新"
