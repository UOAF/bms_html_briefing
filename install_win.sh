#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
SPEC_FILE="$SCRIPT_DIR/html_brief_win.spec"
DIST_ROOT="$SCRIPT_DIR/dist"
APP_NAME="html_brief_win"
APP_DIR="$DIST_ROOT/$APP_NAME"
VERSION=""

while getopts ":v:" opt; do
  case "$opt" in
    v) VERSION="$OPTARG" ;;
    *) echo "Usage: $0 [-v VERSION]" >&2; exit 1 ;;
  esac
done

WINEPREFIX="/home/tolmak/.wine_python" wineconsole pyinstaller.exe html_brief_win.spec

if [[ ! -d "$APP_DIR" ]]; then
  echo "PyInstaller output not found at $APP_DIR" >&2
  exit 1
fi

copy_dir() {
  local src="$1"
  local dest="$2"
  if [[ -d "$src" ]]; then
    mkdir -p "$dest"
    cp -a "$src"/. "$dest"/
  fi
}

copy_file() {
  local src="$1"
  local dest="$2"
  if [[ -f "$src" ]]; then
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
  fi
}

copy_dir "$SCRIPT_DIR/assets" "$APP_DIR/assets"
copy_dir "$SCRIPT_DIR/templates" "$APP_DIR/templates"
copy_dir "$SCRIPT_DIR/web" "$APP_DIR/web"
copy_dir "$SCRIPT_DIR/dist/leaflet" "$APP_DIR/dist/leaflet"
# create kneeboards directory without copying existing files
mkdir -p "$APP_DIR/kneeboards"

copy_file "$SCRIPT_DIR/config.ini" "$APP_DIR/config.ini"
for ini in "$SCRIPT_DIR"/theaters*.ini; do
  copy_file "$ini" "$APP_DIR/$(basename "$ini")"
done

if [[ -n "$VERSION" ]]; then
  ARCHIVE_NAME="bms_html_briefing_${VERSION}_windows.tar.gz"
  echo "Creating archive $ARCHIVE_NAME..."
  tar -C "$DIST_ROOT" -czf "$DIST_ROOT/$ARCHIVE_NAME" "$(basename "$APP_DIR")"
fi

echo "Build finished. Executable and assets are in: $APP_DIR"
