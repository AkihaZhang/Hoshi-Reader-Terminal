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

tag="${HOSHI_VERSION:-}"
if [ -z "$tag" ]; then
  tag="$(curl -fsSL "$API_URL" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
fi
if [ -z "$tag" ]; then
  echo "无法获取最新版本。"
  exit 1
fi
case "$tag" in v*) ;; *) tag="v$tag" ;; esac

asset="hoshi-terminal.pyz"
url="$DOWNLOAD_BASE/$tag/$asset"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT INT TERM

echo "下载 $asset"
curl -fL "$url" -o "$tmp_dir/$asset"
app_dir="$HOME/.local/share/hoshi-reader-terminal/app"
bin_dir="$HOME/.local/bin"
mkdir -p "$app_dir" "$bin_dir"
cp "$tmp_dir/$asset" "$app_dir/$asset"
cat > "$bin_dir/hoshi" <<'EOF'
#!/bin/sh
exec python3 "$HOME/.local/share/hoshi-reader-terminal/app/hoshi-terminal.pyz" "$@"
EOF
cp "$bin_dir/hoshi" "$bin_dir/hoshi-terminal"
chmod +x "$app_dir/$asset" "$bin_dir/hoshi" "$bin_dir/hoshi-terminal"

echo
echo "安装完成: $bin_dir/hoshi"
echo "如果当前终端找不到 hoshi，请把 $bin_dir 加入 PATH 或新开一个终端。"
echo "检查更新: hoshi 检查更新"
