#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/pyinstaller_venv"
SPEC_FILE="$SCRIPT_DIR/openchart_cli.spec"
DIST_ROOT="$SCRIPT_DIR/pyinstaller_dist"
APP_NAME="openchart_cli"
APP_DIR="$DIST_ROOT/$APP_NAME"
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

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Virtualenv not found at $VENV_DIR" >&2
  exit 1
fi

cd "$SCRIPT_DIR"
source "$VENV_DIR/bin/activate"
python -m PyInstaller --noconfirm --distpath "$APP_DIR" \
  --workpath "$SCRIPT_DIR/build_cli/linux" "$SPEC_FILE"

if [[ ! -f "$APP_DIR/openchart_cli" ]]; then
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
  ARCHIVE_NAME="bms_openchart_cli_${VERSION}_linux.tar.gz"
  echo "Creating archive $ARCHIVE_NAME..."
  tar -C "$DIST_ROOT" -czf "$DIST_ROOT/$ARCHIVE_NAME" "$APP_NAME"
fi

echo "Build: $APP_DIR"
