# Shared pre-build version check for the application installers.

build_version_tuple() {
  local version="$1"
  if [[ "$version" =~ ^v?([0-9]+)\.([0-9]+)(\.([0-9]+))?$ ]]; then
    local major="${BASH_REMATCH[1]}"
    local minor="${BASH_REMATCH[2]}"
    local patch="${BASH_REMATCH[4]:-0}"
    printf '%d.%d.%d\n' "$((10#$major))" "$((10#$minor))" "$((10#$patch))"
  else
    return 1
  fi
}

confirm_build_version() {
  local requested_version="$1"
  local source_file="$2"
  [[ -n "$requested_version" ]] || return 0

  local app_version requested_tuple app_tuple reply
  app_version="$(sed -nE "s/^APP_VERSION[[:space:]]*=[[:space:]]*['\"]([^'\"]+)['\"].*/\1/p" "$source_file")"
  if requested_tuple="$(build_version_tuple "$requested_version")" &&
     app_tuple="$(build_version_tuple "$app_version")" &&
     [[ "$requested_tuple" == "$app_tuple" ]]; then
    return 0
  fi

  printf 'The provided version %s differs from the version %s in the app. Proceed? [y/N] ' \
    "$requested_version" "$app_version" >&2
  IFS= read -r reply || return 1
  case "$reply" in
    [yY]|[yY][eE][sS]) return 0 ;;
    *) return 1 ;;
  esac
}
