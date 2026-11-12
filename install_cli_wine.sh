#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_ROOT="$SCRIPT_DIR/pyinstaller_dist"
APP_NAME="openchart_cli_win"
APP_DIR="$DIST_ROOT/$APP_NAME"
# set the Wine prefix here
WINEPFX=""
VERSION=""

while getopts ":v:" opt; do
  case "$opt" in
    v) VERSION="$OPTARG" ;;
    *) echo "Usage: $0 [-v VERSION]" >&2; exit 1 ;;
  esac
done
shift "$((OPTIND - 1))"
if [[ $# -ne 0 ]]; then
  echo "Usage: $0 [-v VERSION]" >&2
  exit 1
fi

cd "$SCRIPT_DIR"
# Relative paths are resolved by Windows Python inside the repository directory.
WINEPREFIX="$WINEPFX" wine pyinstaller.exe --noconfirm \
  --distpath "pyinstaller_dist/$APP_NAME" \
  --workpath "build_cli/windows" openchart_cli.spec

if [[ ! -f "$APP_DIR/openchart_cli.exe" ]]; then
  echo "PyInstaller output not found at $APP_DIR" >&2
  exit 1
fi

cp "$SCRIPT_DIR/README_cli.md" "$APP_DIR/README.md"

# Runtime assets are bundled by the one-file spec; retain the release notices.
while IFS= read -r -d '' rel_path; do
  mkdir -p "$APP_DIR/$(dirname "$rel_path")"
  cp "$SCRIPT_DIR/$rel_path" "$APP_DIR/$rel_path"
done < <(git -C "$SCRIPT_DIR" ls-files -z -- LICENSE licenses)

if [[ -n "$VERSION" ]]; then
  ARCHIVE_NAME="bms_openchart_cli_${VERSION}_windows.tar.gz"
  echo "Creating archive $ARCHIVE_NAME..."
  tar -C "$DIST_ROOT" -czf "$DIST_ROOT/$ARCHIVE_NAME" "$APP_NAME"
fi

echo "Build: $APP_DIR"
