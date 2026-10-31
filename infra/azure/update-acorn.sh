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
exec 9>"$STATE/update.lock"
flock -n 9 || { echo "Another update is already running."; exit 3; }

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

ai_test() {
  say "AI test question through the gateway..."
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

deploy() {  # build and start whatever is checked out now
  say "building..."
  $COMPOSE build 2>&1 | grep -E "^#[0-9]+ (ERROR|DONE)|error|Error" | tail -5
  [ "${PIPESTATUS[0]}" -eq 0 ] || return 1
  say "starting..."
  $COMPOSE up -d 2>&1 | grep -E "Error|error" | head -5
  [ "${PIPESTATUS[0]}" -eq 0 ] || return 1
  migrate && healthy
}

if [ "$MODE" = verify ]; then
  say "verify only (nothing changes). Running commit: $(head_commit)"
  migrate && healthy && ai_test && say "VERIFY OK" && exit 0
  say "VERIFY FAILED"; exit 1
fi

if [ "$MODE" = rollback ]; then
  [ -s "$STATE/last-good-commit" ] || { say "FAILED: no last-good commit is recorded"; exit 1; }
  target=$(cat "$STATE/last-good-commit")
  say "rolling back from $(head_commit) to $target"
  git reset --hard "$target" >/dev/null && deploy && ai_test && say "ROLLBACK OK ($target)" && exit 0
  say "ROLLBACK FAILED"; exit 1
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
if [ "$before" = "$target" ] && [ "$MODE" != force ]; then say "already up to date at $target"; exit 0; fi
[ "$before" != none ] && git rev-parse --verify -q "$before" >/dev/null && echo "$before" > "$STATE/previous-commit"
say "updating $before -> $target"
git log --oneline "$before..FETCH_HEAD" 2>/dev/null | head -20
git reset --hard FETCH_HEAD >/dev/null

if deploy && ai_test; then
  echo "$target" > "$STATE/last-good-commit"
  say "UPDATE OK ($target)"
  exit 0
fi

say "UPDATE FAILED at $target"
prev=$(cat "$STATE/previous-commit" 2>/dev/null || true)
if [ -n "$prev" ] && git rev-parse --verify -q "$prev" >/dev/null; then
  say "rolling back to $prev"
  git reset --hard "$prev" >/dev/null
  if deploy; then say "ROLLED BACK to $prev: A.C.O.R.N is running the old version again"; else say "ROLLBACK ALSO FAILED: look at $LOG"; fi
fi
exit 1
