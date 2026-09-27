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

PGDATA=/config/pgdata
PG_SOCKET_DIR=/run/postgresql
PG_MAJOR_EXPECTED=18

# Run a command as the app user (PUID:PGID) with no other groups.
as_app() { exec s6-applyuidgid -u "$PUID" -g "$PGID" -G "$PGID" "$@"; }
# Run a command as the postgres user.
as_postgres() { s6-setuidgid postgres "$@"; }

# Set owner/mode of a directory without recursing (volumes may be large).
own_dir() { # path uid gid mode
  mkdir -p "$1"
  [ "$(stat -c %u:%g "$1")" = "$2:$3" ] || chown "$2:$3" "$1"
  chmod "$4" "$1"
}
