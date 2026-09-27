#!/usr/bin/env bash
# Start the image with the recommended hardening flags and check it behaves safely:
# ready on /readyz, no Server header, non-root processes, no TCP database port, secrets
# private and stable across restarts, clean shutdown. Usage: smoke-test-image.sh <image>
set -euo pipefail

image="$1"
name="planhaven-smoke-$$"
port=18080
work="$(mktemp -d)"
mkdir -p "$work/config" "$work/data"

cleanup() {
  status=$?
  if [[ $status -ne 0 ]]; then
    echo "::group::Container log"
    docker logs "$name" 2>&1 | tail -200 || true
    echo "::endgroup::"
  fi
  docker rm -f "$name" >/dev/null 2>&1 || true
  sudo rm -rf "$work"
  exit "$status"
}
trap cleanup EXIT

fail() { echo "::error::$*"; exit 1; }

# Recommended runtime flags (SECURITY.md §7.13).
docker run -d --name "$name" \
  --read-only \
  --tmpfs /run:rw,exec,nosuid,size=64m \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=ALL \
  --cap-add=CHOWN --cap-add=SETUID --cap-add=SETGID --cap-add=DAC_OVERRIDE \
  --cap-add=FOWNER --cap-add=KILL \
  --security-opt=no-new-privileges:true \
  -v "$work/config:/config" -v "$work/data:/data" \
  -p "127.0.0.1:$port:8080" \
  "$image" >/dev/null

wait_ready() {
  for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:$port/readyz" >/dev/null 2>&1; then return 0; fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "$name")" != "true" ]]; then
      fail "container exited during startup"
    fi
    sleep 1
  done
  fail "not ready after 120 seconds"
}

echo "Waiting for /readyz"
wait_ready
echo "ok: ready"

headers="$(curl -fsS -D - -o /dev/null "http://127.0.0.1:$port/healthz")"
curl -fsS "http://127.0.0.1:$port/healthz" | grep -q '"ok"' || fail "/healthz did not report ok"
if grep -qi '^server:' <<<"$headers"; then fail "Server header present"; fi
echo "ok: /healthz, no Server header"

echo "Processes:"
docker top "$name" -eo uid,user,args
uvicorn_uids="$(docker top "$name" -eo uid,args | awk '/uvicorn/ {print $1}' | sort -u)"
[[ "$uvicorn_uids" == "99" ]] || fail "app not running as UID 99 (got: $uvicorn_uids)"
pg_users="$(docker top "$name" -eo user,args | awk '/postgres -D/ {print $1}' | sort -u)"
pg_uid="$(docker exec "$name" id -u postgres)"
docker top "$name" -eo uid,args | awk -v u="$pg_uid" '/postgres -D/ && $1 != u {bad=1} END {exit bad}' \
  || fail "postgres not running as the postgres user ($pg_users)"
echo "ok: app runs as 99, PostgreSQL as postgres"

if docker exec "$name" python -c "import socket; socket.create_connection(('127.0.0.1', 5432), 2)" 2>/dev/null; then
  fail "PostgreSQL accepts TCP connections"
fi
echo "ok: no TCP database port"

check_mode() { # path expected-mode expected-owner
  actual="$(sudo stat -c '%a %u' "$1")"
  [[ "$actual" == "$2 $3" ]] || fail "$1 is '$actual', expected '$2 $3'"
}
check_mode "$work/config/secrets" 700 99
for f in master.key session.key vapid_private.pem vapid_public.txt; do
  check_mode "$work/config/secrets/$f" 600 99
done
check_mode "$work/config/pgdata" 700 "$pg_uid"
echo "ok: secrets and database files are private"

before="$(sudo sha256sum "$work/config/secrets/master.key")"
docker restart -t 30 "$name" >/dev/null
wait_ready
after="$(sudo sha256sum "$work/config/secrets/master.key")"
[[ "$before" == "$after" ]] || fail "master key changed on restart"
echo "ok: restart keeps secrets and database"

start=$SECONDS
docker stop -t 30 "$name" >/dev/null
elapsed=$((SECONDS - start))
[[ $elapsed -lt 25 ]] || fail "shutdown took ${elapsed}s (services not stopping cleanly)"
echo "ok: clean shutdown in ${elapsed}s"

echo "All smoke tests passed."
