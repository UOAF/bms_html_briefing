#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

WINEPFX="" ## SET YOUR WINE PREFIX HERE
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/pyinstaller_venv"
SPEC_FILE="$SCRIPT_DIR/html_brief_win.spec"
DIST_ROOT="$SCRIPT_DIR/pyinstaller_dist"
APP_NAME="html_brief_win"
APP_DIR="$DIST_ROOT/$APP_NAME"
VERSION=""

while getopts ":v:" opt; do
  case "$opt" in
    v) VERSION="$OPTARG" ;;
    *) echo "Usage: $0 [-v VERSION]" >&2; exit 1 ;;
  esac
done

cd "$SCRIPT_DIR"
WINEPREFIX="$WINEPFX" wineconsole pyinstaller.exe --distpath pyinstaller_dist "$SPEC_FILE"

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

copy_git_tracked_dir() {
  local src_rel="$1"
  local dest="$2"
  if [[ ! -d "$SCRIPT_DIR/$src_rel" ]]; then
    return
  fi
  mkdir -p "$dest"
  while IFS= read -r -d '' rel_path; do
    local rel_to_src="${rel_path#"$src_rel/"}"
    local src_file="$SCRIPT_DIR/$rel_path"
    local dst_file="$dest/$rel_to_src"
    mkdir -p "$(dirname "$dst_file")"
    cp -a "$src_file" "$dst_file"
  done < <(git -C "$SCRIPT_DIR" ls-files -z -- "$src_rel")
}

copy_file() {
  local src="$1"
  local dest="$2"
  if [[ -f "$src" ]]; then
    mkdir -p "$(dirname "$dest")"
    cp "$src" "$dest"
  fi
}

copy_git_tracked_dir "assets" "$APP_DIR/assets"
copy_git_tracked_dir "templates" "$APP_DIR/templates"
copy_git_tracked_dir "web" "$APP_DIR/web"
copy_git_tracked_dir "licenses" "$APP_DIR/licenses"
copy_git_tracked_dir "dist/leaflet" "$APP_DIR/dist/leaflet"
# create kneeboards directory without copying existing files
mkdir -p "$APP_DIR/kneeboards"

copy_file "$SCRIPT_DIR/config.ini" "$APP_DIR/config.ini"
copy_file "$SCRIPT_DIR/LICENSE" "$APP_DIR/LICENSE"
while IFS= read -r -d '' ini_rel; do
  copy_file "$SCRIPT_DIR/$ini_rel" "$APP_DIR/$(basename "$ini_rel")"
done < <(git -C "$SCRIPT_DIR" ls-files -z -- 'theaters*.ini')

if [[ -n "$VERSION" ]]; then
  ARCHIVE_NAME="bms_html_briefing_${VERSION}_windows.tar.gz"
  echo "Creating archive $ARCHIVE_NAME..."
  tar -C "$DIST_ROOT" -czf "$DIST_ROOT/$ARCHIVE_NAME" "$(basename "$APP_DIR")"
fi

echo "Build finished. Executable and assets are in: $APP_DIR"
