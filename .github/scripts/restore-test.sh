#!/usr/bin/env bash
# Backup and restore round trip (ARCHITECTURE.md §16): back up a container that has data,
# restore the backup into a brand-new container, and check the data is there.
# Usage: restore-test.sh <image> <source-container> <expected-project-title>
set -euo pipefail
image="$1"
source="$2"
expected="$3"
target="planhaven-restore-$$"
work="$(mktemp -d)"
trap 'docker rm -f "$target" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT

docker exec "$source" /etc/s6-overlay/scripts/backup-now
dump="$(docker exec "$source" sh -c 'ls /config/backups/planhaven-*.dump' | tail -1)"
docker cp "$source:$dump" "$work/"

docker run -d --name "$target" -p 127.0.0.1:18082:8080 \
  --read-only --tmpfs /run:rw,exec,nosuid,size=64m --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=ALL --cap-add=CHOWN --cap-add=SETUID --cap-add=SETGID \
  --cap-add=DAC_OVERRIDE --cap-add=FOWNER --cap-add=KILL \
  --security-opt=no-new-privileges:true \
  -e PUBLIC_MODE=false -e BASE_URL=http://localhost:18082 "$image" >/dev/null
for _ in $(seq 1 120); do
  curl -fsS http://localhost:18082/readyz >/dev/null 2>&1 && break
  sleep 1
done

docker cp "$work/$(basename "$dump")" "$target:$dump"
docker exec "$target" chown postgres:postgres "$dump"
docker exec "$target" /etc/s6-overlay/scripts/restore-db "$dump"

for _ in $(seq 1 60); do
  curl -fsS http://localhost:18082/readyz >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://localhost:18082/readyz >/dev/null || { echo "::error::not ready after restore"; exit 1; }
titles="$(docker exec "$target" s6-setuidgid postgres psql -h /run/postgresql -U postgres \
  -d planhaven -tAc 'SELECT title FROM projects')"
grep -qxF "$expected" <<<"$titles" || { echo "::error::restored data missing: got '$titles'"; exit 1; }
setup="$(curl -fsS http://localhost:18082/api/v1/setup)"
grep -q '"setup_required":false' <<<"$setup" || { echo "::error::restored instance wants setup"; exit 1; }
echo "ok: backup restored into a fresh container; data and accounts present"
