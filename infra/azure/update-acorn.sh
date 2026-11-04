#!/usr/bin/env bash
# Updates A.C.O.R.N on the Azure Linux VM from GitHub: pull, rebuild, restart, migrate, check, and roll back if the check fails.
#
#   sudo bash /srv/acorn/AiSOC/infra/azure/update-acorn.sh                 update to the latest main
#   sudo bash /srv/acorn/AiSOC/infra/azure/update-acorn.sh --verify-only   change nothing: run the migrations (a no-op when current), the health check and an AI test question
#   sudo bash /srv/acorn/AiSOC/infra/azure/update-acorn.sh --rollback      go back to the last commit that passed the check
#   sudo bash /srv/acorn/AiSOC/infra/azure/update-acorn.sh --force         rebuild and restart even if nothing changed
#
# It is what CORE's rebuild button runs (through Azure Run Command), so everything it prints is what the person sees. The full log is /srv/acorn/update.log.
# Settings that survive an update because git does not hold them: /srv/acorn/AiSOC/.env, /srv/acorn/config/litellm.yaml, /root/.ssh/acorn_deploy (the read-only deploy key).
# Database migrations are NOT rolled back by a rollback: they are written to be applied once and to leave older code working.
set -uo pipefail

REPO=/srv/acorn/AiSOC
REMOTE=git@github.com:halion9000/acorn.git
BRANCH=main
KEY=/root/.ssh/acorn_deploy
STATE=/srv/acorn
LOG=$STATE/update.log
COMPOSE="docker compose -f docker-compose.yml -f infra/azure/docker-compose.azure.yml"
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

MODE=update
for arg in "$@"; do
  case "$arg" in
    --verify-only) MODE=verify ;;
    --rollback) MODE=rollback ;;
    --force) MODE=force ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

exec > >(tee -a "$LOG") 2>&1

# The last line of every run is machine-readable: CORE reads the verdict from it instead of from the wording above it.
# status is one of: ok, up_to_date, verify_ok, rollback_ok, rolled_back, failed, verify_failed, rollback_failed, busy.
STATUS=failed
emit_result() { echo "RESULT {\"status\":\"$STATUS\",\"commit\":\"$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo none)\"}"; }
trap emit_result EXIT

exec 9>"$STATE/update.lock"
flock -n 9 || { echo "Another update is already running."; STATUS=busy; exit 3; }

say() { echo "[$(date -u +%H:%M:%S)] $*"; }
cd "$REPO" || { say "FAILED: $REPO does not exist"; exit 1; }

head_commit() { git rev-parse --short HEAD 2>/dev/null || echo none; }

migrate() {
  say "migrations..."
  out=$(docker exec aisoc-api python -m app.scripts.run_migrations 2>&1); rc=$?
  echo "$out" | tail -4 | cut -c1-200
  [ $rc -eq 0 ]
}

healthy() {
  say "waiting for the API and every container to be healthy..."
  for i in $(seq 1 60); do
    code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://10.20.1.4:8000/health || true)
    bad=$(docker ps --filter health=unhealthy --filter status=restarting --format '{{.Names}}' | tr '\n' ' ')
    starting=$(docker ps --filter health=starting --format '{{.Names}}' | tr '\n' ' ')
    if [ "$code" = "200" ] && [ -z "$bad" ] && [ -z "$starting" ]; then say "healthy: API answers 200, $(docker ps -q | wc -l) containers up"; return 0; fi
    sleep 5
  done
  say "NOT healthy: API HTTP ${code:-none}; unhealthy or restarting: ${bad:-none}; still starting: ${starting:-none}"
  return 1
}

# One slow answer from the AI link (it runs through the CORE VM's Claude session, which can be busy) must not undo a good update: three tries, a pause between.
ai_test() {
  say "AI test question through the gateway..."
  for attempt in 1 2 3; do
    ai_try && return 0
    [ "$attempt" -lt 3 ] && { say "AI test attempt $attempt did not answer; trying again in 20 s"; sleep 20; }
  done
  return 1
}

ai_try() {
  docker exec -i aisoc-api python - <<'PY'
import json, os, time, urllib.request
req = urllib.request.Request(
    "http://litellm:4000/v1/chat/completions",
    data=json.dumps({"model": "aisoc-copilot", "messages": [{"role": "user", "content": "Reply with exactly the single word: pong"}], "max_tokens": 20}).encode(),
    headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY", "")},
)
t = time.time()
try:
    r = json.load(urllib.request.urlopen(req, timeout=90))
    print("AI answered in %.1fs: %s" % (time.time() - t, r["choices"][0]["message"]["content"][:40].replace("\n", " ")))
except Exception as e:
    print("AI test FAILED:", type(e).__name__, str(e)[:120])
    raise SystemExit(1)
PY
}

# The intake service needs its own database connection (the owner account, in the postgres:// form with sslmode). Made from the migration URL the first time, kept in .env after that.
ensure_ingest_dsn() {
  local envfile=$REPO/.env url
  grep -q '^AZURE_INGEST_DSN=' "$envfile" && return 0
  url=$(grep '^AZURE_MIGRATION_DATABASE_URL=' "$envfile" | head -1 | cut -d= -f2-)
  url=${url#\"}; url=${url%\"}
  [ -n "$url" ] || { say "FAILED: AZURE_MIGRATION_DATABASE_URL is not in $envfile, so the intake service has no database to use"; return 1; }
  url=${url/postgresql+asyncpg:/postgres:}; url=${url/postgres+asyncpg:/postgres:}
  url=${url/ssl=require/sslmode=require}
  [ -n "$(tail -c1 "$envfile")" ] && echo >> "$envfile"   # a last line with no newline would swallow the new one
  echo "AZURE_INGEST_DSN=$url" >> "$envfile"
  say "added AZURE_INGEST_DSN to .env (derived from the migration URL)"
}

# A "?ssl=require" on AZURE_DATABASE_URL works for the API (SQLAlchemy) but makes every service that opens a raw asyncpg connection (fusion, which saves every alert; the agents' memory and
# guardrails; cost tracking) fail with "parameter ssl cannot be changed now". Encryption is required through PGSSLMODE in the compose file instead, so the address carries no ssl setting.
ensure_plain_database_url() {
  local envfile=$REPO/.env
  grep -qE '^AZURE_DATABASE_URL=.*[?&]ssl=' "$envfile" || return 0
  sed -i -E '/^AZURE_DATABASE_URL=/ { s/\?ssl=[a-z-]+&/?/; s/[?&]ssl=[a-z-]+$//; }' "$envfile"
  say "removed ?ssl= from AZURE_DATABASE_URL in .env (PGSSLMODE=require carries it now)"
}

# Optional services that are not started with the rest (the compose file's "extras" profile): honeytokens (planted tripwire links and files that alert when touched) and purple-team (attack
# simulation to test detections). Which ones run is the ACORN_EXTRAS setting in .env, a space-separated list; when it is not there, honeytokens runs and purple-team does not. An empty
# ACORN_EXTRAS= turns them all off. A failure to start one is said but never fails the update: the rest of the platform does not depend on them.
start_extras() {
  local extras
  if grep -qE '^ACORN_EXTRAS=' "$REPO/.env" 2>/dev/null; then
    extras=$(grep -E '^ACORN_EXTRAS=' "$REPO/.env" | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
  else
    extras="honeytokens"
  fi
  [ -n "$extras" ] || return 0
  case "$extras" in *[!a-z\ -]*) say "ACORN_EXTRAS has something other than service names: left alone"; return 0 ;; esac
  say "starting extras: $extras..."
  $COMPOSE --profile extras build $extras 2>&1 | grep -E "^#[0-9]+ ERROR|error|Error" | tail -3
  $COMPOSE --profile extras up -d $extras 2>&1 | grep -E "Error|error" | head -3
  return 0
}

# The Cloudflare tunnel token for the public honeytoken address. CORE's "Cloudflare canary" card sends it to the API, which keeps it in $CTL/cloudflared.token (see services/api/app/services/canary_tunnel.py);
# this puts it into .env, makes sure cloudflared is in ACORN_EXTRAS and sets the public address if none is set yet (https://canary.goliveoak.com; change ACORN_CANARY_URL in .env to use another). The file is only
# ever read here, and only a value made of base64 characters is written, so nothing can add or change another line of .env. Never fails an update: the tunnel is not needed by the rest of the platform.
CTL=${ACORN_UPDATE_CTL:-/srv/acorn/update-ctl}
canary_token() { [ -s "$CTL/cloudflared.token" ] && tr -d '
 ' < "$CTL/cloudflared.token"; return 0; }
canary_pending() {  # true when a token is waiting that .env does not hold yet
  local want have
  want=$(canary_token); [ -n "$want" ] || return 1
  case "$want" in *[!A-Za-z0-9+/_=-]*) return 1 ;; esac
  have=$(grep -E '^CLOUDFLARED_TUNNEL_TOKEN=' "$REPO/.env" 2>/dev/null | tail -1 | cut -d= -f2-)
  [ "$want" != "$have" ]
}
apply_canary_tunnel() {
  canary_pending || return 0
  local want envfile=$REPO/.env extras
  want=$(canary_token)
  say "applying the Cloudflare tunnel token from CORE..."
  touch "$envfile"
  { grep -vE '^CLOUDFLARED_TUNNEL_TOKEN=' "$envfile"; echo "CLOUDFLARED_TUNNEL_TOKEN=$want"; } > "$envfile.new" && cat "$envfile.new" > "$envfile"; rm -f "$envfile.new"
  grep -qE '^ACORN_CANARY_URL=.+' "$envfile" || echo "ACORN_CANARY_URL=https://canary.goliveoak.com" >> "$envfile"
  if grep -qE '^ACORN_EXTRAS=' "$envfile"; then
    extras=$(grep -E '^ACORN_EXTRAS=' "$envfile" | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
    case " $extras " in *" cloudflared "*) ;; *) { grep -vE '^ACORN_EXTRAS=' "$envfile"; echo "ACORN_EXTRAS=\"$extras cloudflared\""; } > "$envfile.new" && cat "$envfile.new" > "$envfile"; rm -f "$envfile.new" ;; esac
  else
    echo 'ACORN_EXTRAS="honeytokens cloudflared"' >> "$envfile"
  fi
  # the tunnel container, and the honeytokens service (which reads ACORN_CANARY_URL), start again with the new values
  $COMPOSE --profile extras up -d --force-recreate cloudflared honeytokens 2>&1 | grep -E "Error|error" | head -3
  return 0
}

deploy() {  # build and start whatever is checked out now
  # The version being started, handed to the API container (compose reads it as ACORN_COMMIT) so the health page can say what is running.
  ACORN_COMMIT=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)
  export ACORN_COMMIT
  ensure_ingest_dsn || return 1
  ensure_plain_database_url
  # Every build leaves layers behind in containerd's store on the VM's main disk (about 3 GB a build). Keep 10 GB of cache for speed, drop the rest, and stop with a clear
  # message rather than a half-written image if the disk is still nearly full (on 2026-10-31 it filled up and an update failed mid-build).
  docker builder prune -f --keep-storage 10GB >/dev/null 2>&1 || true
  free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
  if [ "${free_gb:-0}" -lt 6 ]; then say "NOT ENOUGH DISK: only ${free_gb:-0} GB free on the main disk (need 6): free some space, then update again"; return 1; fi
  say "building..."
  $COMPOSE build 2>&1 | grep -E "^#[0-9]+ (ERROR|DONE)|error|Error" | tail -5
  [ "${PIPESTATUS[0]}" -eq 0 ] || return 1
  say "starting..."
  $COMPOSE up -d 2>&1 | grep -E "Error|error" | head -5
  [ "${PIPESTATUS[0]}" -eq 0 ] || return 1
  # The proxy reads its file once when it starts, and a changed file does not recreate it: tell it to read the file again. A file it cannot accept is refused and the old one stays in force.
  $COMPOSE exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>&1 | tail -2 || true
  apply_canary_tunnel
  start_extras
  migrate && healthy
}

if [ "$MODE" = verify ]; then
  say "verify only (nothing changes). Running commit: $(head_commit)"
  migrate && healthy && ai_test && say "VERIFY OK" && { STATUS=verify_ok; exit 0; }
  say "VERIFY FAILED"; STATUS=verify_failed; exit 1
fi

if [ "$MODE" = rollback ]; then
  [ -s "$STATE/last-good-commit" ] || { say "FAILED: no last-good commit is recorded"; exit 1; }
  target=$(cat "$STATE/last-good-commit")
  say "rolling back from $(head_commit) to $target"
  git reset --hard "$target" >/dev/null && deploy && ai_test && say "ROLLBACK OK ($target)" && { STATUS=rollback_ok; exit 0; }
  say "ROLLBACK FAILED"; STATUS=rollback_failed; exit 1
fi

[ -f "$KEY" ] || { say "FAILED: the deploy key $KEY is missing"; exit 1; }
if [ ! -d .git ]; then
  say "first update: turning the unpacked archive into a git checkout"
  git init -q && git remote add origin "$REMOTE" || true
fi
git remote set-url origin "$REMOTE"
before=$(head_commit)
say "fetching $BRANCH..."
git fetch -q origin "$BRANCH" || { say "FAILED: could not fetch from GitHub (is the deploy key added to the repository?)"; exit 1; }
target=$(git rev-parse --short FETCH_HEAD)
if [ "$before" = "$target" ] && [ "$MODE" != force ]; then
  # Nothing new to build, but a tunnel token sent from CORE since the last run still needs putting to use.
  if canary_pending; then (cd "$REPO" && apply_canary_tunnel); fi
  say "already up to date at $target"; STATUS=up_to_date; exit 0
fi
[ "$before" != none ] && git rev-parse --verify -q "$before" >/dev/null && echo "$before" > "$STATE/previous-commit"
say "updating $before -> $target"
git log --oneline "$before..FETCH_HEAD" 2>/dev/null | head -20
git reset --hard FETCH_HEAD >/dev/null

if deploy && ai_test; then
  echo "$target" > "$STATE/last-good-commit"
  say "UPDATE OK ($target)"
  STATUS=ok
  exit 0
fi

say "UPDATE FAILED at $target"
prev=$(cat "$STATE/previous-commit" 2>/dev/null || true)
if [ -n "$prev" ] && git rev-parse --verify -q "$prev" >/dev/null; then
  say "rolling back to $prev"
  git reset --hard "$prev" >/dev/null
  if deploy; then say "ROLLED BACK to $prev: A.C.O.R.N is running the old version again"; STATUS=rolled_back; else say "ROLLBACK ALSO FAILED: look at $LOG"; STATUS=rollback_failed; fi
fi
exit 1
