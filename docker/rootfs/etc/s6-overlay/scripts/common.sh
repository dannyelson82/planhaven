#!/bin/sh
# Shared helpers for Planhaven startup scripts.
set -eu

PUID="${PUID:-99}"
PGID="${PGID:-100}"
case "$PUID$PGID" in
  *[!0-9]*|'') echo "planhaven: PUID and PGID must be numbers" >&2; exit 1 ;;
esac
if [ "$PUID" -eq 0 ] || [ "$PGID" -eq 0 ]; then
  echo "planhaven: refusing to run as root (PUID/PGID 0)" >&2; exit 1
fi

# Used by the scripts that source this file.
# shellcheck disable=SC2034
PGDATA=/config/pgdata
# shellcheck disable=SC2034
PG_SOCKET_DIR=/run/postgresql
# shellcheck disable=SC2034
PG_MAJOR_EXPECTED=18

# Run a command as the app user (PUID:PGID) with no other groups.
as_app() { exec s6-applyuidgid -u "$PUID" -g "$PGID" -G "$PGID" "$@"; }
# Run a command as the postgres user.
as_postgres() { s6-setuidgid postgres "$@"; }

# Set owner/mode of a directory without recursing (volumes may be large). Runs as root, so it
# refuses symlinks: otherwise a compromised app could redirect root's chown/chmod elsewhere.
own_dir() { # path uid gid mode
  if [ -L "$1" ]; then
    echo "planhaven: $1 is a symlink; refusing to start" >&2; exit 1
  fi
  mkdir -p "$1"
  [ -d "$1" ] || { echo "planhaven: $1 is not a directory; refusing to start" >&2; exit 1; }
  [ "$(stat -c %u:%g "$1")" = "$2:$3" ] || chown -h "$2:$3" "$1"
  [ "$(stat -c %a "$1")" = "${4#0}" ] || chmod "$4" "$1"
}
