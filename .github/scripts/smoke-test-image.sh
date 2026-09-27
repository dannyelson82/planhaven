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

# Recommended runtime flags (SECURITY.md §7.13) and the required public-mode settings.
# shellcheck disable=SC2054  # commas are inside --tmpfs option values
hardening=(
  --read-only
  --tmpfs /run:rw,exec,nosuid,size=64m
  --tmpfs /tmp:rw,noexec,nosuid,size=64m
  --cap-drop=ALL
  --cap-add=CHOWN --cap-add=SETUID --cap-add=SETGID --cap-add=DAC_OVERRIDE
  --cap-add=FOWNER --cap-add=KILL
  --security-opt=no-new-privileges:true
)
config=(-e BASE_URL=https://planhaven.example.com -e TRUSTED_PROXIES=192.0.2.0/24)

expect_refusal() { # message docker-run-args...
  local message="$1"; shift
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" "${hardening[@]}" "$@" \
    -v "$work/config:/config" -v "$work/data:/data" "$image" >/dev/null
  for _ in $(seq 1 30); do
    [[ "$(docker inspect -f '{{.State.Running}}' "$name")" == "true" ]] || break
    sleep 1
  done
  [[ "$(docker inspect -f '{{.State.Running}}' "$name")" == "false" ]] \
    || fail "container kept running; expected refusal: $message"
  for _ in $(seq 1 10); do  # log output can lag the container exit
    docker logs "$name" 2>&1 | grep -qF "$message" && return 0
    sleep 1
  done
  fail "missing refusal message: $message"
}

# Insecure configuration must stop the container before anything is set up.
expect_refusal "configuration error: BASE_URL is required"
expect_refusal "BASE_URL must use https in public mode" \
  -e BASE_URL=http://planhaven.example.com -e TRUSTED_PROXIES=192.0.2.0/24
expect_refusal "TRUSTED_PROXIES is required in public mode" -e BASE_URL=https://planhaven.example.com
[[ -z "$(sudo ls -A "$work/config")" ]] || fail "refused configuration still wrote to /config"
echo "ok: refuses insecure configuration, before touching /config"
docker rm -f "$name" >/dev/null

docker run -d --name "$name" "${hardening[@]}" "${config[@]}" \
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
for h in content-security-policy strict-transport-security x-content-type-options \
         referrer-policy permissions-policy cross-origin-opener-policy x-request-id; do
  grep -qi "^$h:" <<<"$headers" || fail "missing header: $h"
done
echo "ok: /healthz, security headers, no Server header"

docker logs "$name" 2>&1 | grep '"logger": "planhaven.access"' | tail -1 | python3 -c \
  'import json,sys; e=json.loads(sys.stdin.read()); assert e["path"]=="/healthz" and e["status"]==200' \
  || fail "no structured access log line"
echo "ok: structured access log"

page="$(curl -fsS -D "$work/page-headers" "http://127.0.0.1:$port/projects")"
grep -q '<div id="root">' <<<"$page" || fail "web app not served"
grep -qi '^content-security-policy:' "$work/page-headers" || fail "web app without CSP"
asset="$(grep -oE '/static/[A-Za-z0-9_.-]+\.js' <<<"$page" | head -1)"
curl -fsS -D "$work/asset-headers" -o /dev/null "http://127.0.0.1:$port$asset" || fail "asset $asset not served"
grep -qi 'immutable' "$work/asset-headers" || fail "assets not cached as immutable"
echo "ok: web app and hashed assets served"

# First boot: a one-time setup token in the log, no default account. Use it to create the
# admin through the API, the way the web UI will.
token="$(docker logs "$name" 2>&1 | grep -oE 'phv_setup_[A-Za-z0-9_-]{40,}' | tail -1)"
[[ -n "$token" ]] || fail "no setup token printed at first boot"
curl -fsS "http://127.0.0.1:$port/api/v1/setup" | grep -q '"setup_required":true' \
  || fail "setup not reported as required"
bad_status="$(curl -sS -o /dev/null -w '%{http_code}' -H "Origin: https://planhaven.example.com" \
  -H 'Content-Type: application/json' \
  -d '{"setup_token":"phv_setup_wrong","email":"a@example.com","display_name":"A","password":"correct horse battery staple 42"}' \
  "http://127.0.0.1:$port/api/v1/setup")"
[[ "$bad_status" == "400" ]] || fail "wrong setup token not rejected ($bad_status)"
status="$(curl -sS -o /dev/null -w '%{http_code}' -H "Origin: https://planhaven.example.com" \
  -H 'Content-Type: application/json' \
  -d "{\"setup_token\":\"$token\",\"email\":\"admin@example.com\",\"display_name\":\"Admin\",\"password\":\"correct horse battery staple 42\"}" \
  "http://127.0.0.1:$port/api/v1/setup")"
[[ "$status" == "201" ]] || fail "setup with the printed token failed ($status)"
curl -fsS "http://127.0.0.1:$port/api/v1/setup" | grep -q '"setup_required":false' \
  || fail "setup still required after completing it"
if docker logs "$name" 2>&1 | grep '"logger"' | grep -q 'phv_setup_'; then
  fail "setup token appears in structured logs"
fi
echo "ok: first-boot setup token creates the admin once"

echo "Processes:"
docker top "$name" -eo pid,uid,user,args
uvicorn_uids="$(docker top "$name" -eo pid,uid,args | awk '/uvicorn/ {print $2}' | sort -u)"
[[ "$uvicorn_uids" == "99" ]] || fail "app not running as UID 99 (got: $uvicorn_uids)"
pg_users="$(docker top "$name" -eo pid,user,args | awk '/postgres -D/ {print $2}' | sort -u)"
pg_uid="$(docker exec "$name" id -u postgres)"
docker top "$name" -eo pid,uid,args | awk -v u="$pg_uid" '/postgres -D/ && $2 != u {bad=1} END {exit bad}' \
  || fail "postgres not running as the postgres user ($pg_users)"
worker_uids="$(docker top "$name" -eo pid,uid,args | awk '/app.workers/ {print $2}' | sort -u)"
[[ "$worker_uids" == "99" ]] || fail "worker not running as UID 99 (got: $worker_uids)"
docker top "$name" -eo pid,uid,args | awk -v u="$pg_uid" '/backup-scheduler/ && $2 != u {bad=1} END {exit bad}' \
  || fail "backup scheduler not running as the postgres user"
echo "ok: app and worker run as 99, PostgreSQL and backups as postgres"

if docker exec "$name" python -c "import socket; socket.create_connection(('127.0.0.1', 5432), 2)" 2>/dev/null; then
  fail "PostgreSQL accepts TCP connections"
fi
echo "ok: no TCP database port"

if docker exec "$name" sh -c 'ls /etc/ssl/private/*.key' >/dev/null 2>&1; then
  fail "a private key file ships in the image (/etc/ssl/private)"
fi
if docker exec "$name" python -c "import pip" 2>/dev/null; then fail "pip present at runtime"; fi
echo "ok: no bundled private keys, no pip"

check_mode() { # path expected-mode expected-owner
  actual="$(sudo stat -c '%a %u' "$1")"
  [[ "$actual" == "$2 $3" ]] || fail "$1 is '$actual', expected '$2 $3'"
}
check_mode "$work/config" 711 0
check_mode "$work/config/secrets" 700 99
for f in master.key session.key vapid_private.pem vapid_public.txt; do
  check_mode "$work/config/secrets/$f" 600 99
done
check_mode "$work/config/pgdata" 700 "$pg_uid"
echo "ok: secrets and database files are private"

docker exec "$name" /etc/s6-overlay/scripts/backup-now | grep -q 'backup written' || fail "backup failed"
backup="$(sudo sh -c "ls $work/config/backups/planhaven-*.dump" | head -1)"
[[ -n "$backup" ]] || fail "no backup file"
check_mode "$work/config/backups" 700 "$pg_uid"
check_mode "$backup" 600 "$pg_uid"
echo "ok: backup written and private to the database user"

before="$(sudo sha256sum "$work/config/secrets/master.key")"
banners_before="$(docker logs "$name" 2>&1 | grep -c 'Planhaven setup: no admin account' || true)"
docker restart -t 30 "$name" >/dev/null
wait_ready
after="$(sudo sha256sum "$work/config/secrets/master.key")"
banners_after="$(docker logs "$name" 2>&1 | grep -c 'Planhaven setup: no admin account' || true)"
[[ "$banners_after" == "$banners_before" ]] || fail "setup token printed again after an admin exists"
[[ "$before" == "$after" ]] || fail "master key changed on restart"
echo "ok: restart keeps secrets and database"

start=$SECONDS
docker stop -t 30 "$name" >/dev/null
elapsed=$((SECONDS - start))
[[ $elapsed -lt 25 ]] || fail "shutdown took ${elapsed}s (services not stopping cleanly)"
echo "ok: clean shutdown in ${elapsed}s"

# A symlinked volume directory must stop startup, not be followed by root.
sudo rm -rf "$work/config/logs"
sudo ln -s /etc "$work/config/logs"
expect_refusal "is a symlink; refusing to start" "${config[@]}"
echo "ok: refuses symlinked volume directories"

echo "All smoke tests passed."
