# A.C.O.R.N: how to work in this repo

(A draft; this repository has no CLAUDE.md today. CORE's rules in the other repository's CLAUDE.md also apply to anything shared.)

## Names and style
- Say **A.C.O.R.N**. US spelling: organization, not organisation. New CORE files are named `acorn-*`.
- A.C.O.R.N holds no vendor credentials. It queues requests for CORE (`vendor_actions`, vendor `core`) and shows what CORE reports back.

## Checks before saying done
- API (`services/api`): `python -m ruff check app tests` and `python -m ruff format --check app tests`; `OTEL_SDK_DISABLED=true python -m pytest <the tests you touched>`.
- Web (`apps/web`): `npx tsc --noEmit -p .` and `npx vitest run <the folder you touched>`; run the whole `npx vitest run` before a push (the API path test reads every URL the web calls against `docs/openapi.yaml`).
- Postgres tests need a disposable database: `source` the `pgenv.sh` recipe (sets `AISOC_TEST_PG_URL` and `AISOC_TEST_PG_APP_URL`). SQLite stand-ins cannot show row-level security. Tests that delete tenants under `session_replication_role = replica` leave orphan rows (the cascade is skipped): use a new id per test and clean up orphans, or the index-plan tests drift.
- Prove a new test fails when the code is reverted. Known unrelated failures here: passkey tests (webauthn missing locally), and a test or two that fail under load but pass alone.

## Migrations
- A new file `services/api/migrations/NNN_name.sql`, idempotent, with a row in `migrations/README.md`. Run locally with `AISOC_MIGRATIONS_REQUIRED=1 python -m app.scripts.run_migrations`. They apply on the next deploy.
- Row-level security: every tenant table gets the standard policy (copy migration 177 or 180). A new `vendor_actions.action` value needs the check widened in a migration and added to `ClaimedAction` in `inbox_core_feed.py` (a test compares them).

## Routes that need listing
- A new route CORE calls with the feed token is added to: `tests/test_core_feed_contract.py` (MODELS, with a fixture synced from CORE), `tests/test_anonymous_access_sweep.py` and `tests/test_unauthenticated_and_login_only_routes.py`.
- After any route change: regenerate the capability docs and `docs/openapi.yaml` (see CORE's `docs/DEPLOY.md`).

## The in-app guide
- Every user-visible feature gets a bullet in BOTH `docs/USER_GUIDE.md` and `apps/web/src/content/user-guide.ts`. No backticks in it: the string is a template literal and a backtick breaks the production build.

## Shipping
- Commit and push in two separate calls. Deploy with the script in CORE's `docs/DEPLOY.md`; it rolls itself back when the build or health check fails.
- Don't edit shell text with backslashes or apostrophes through a heredoc: use the Edit or Write tool.

## The roadmap (Settings, Upcoming improvements)
- docs/ROADMAP_ITEMS.json mirrors everything pending. Keep it current as work goes on: add an item when one is agreed, move its status (new, not_started, in_progress, completed), set needs (claude, signoff, hal) and a note saying what it waits for. Never write a priority: that is Hal's.
- Bring the live page up to date AFTER a deploy (the VM gets the file only through a deploy; the file is too long to send through `az`): run on the VM `cd /srv/acorn/AiSOC && docker exec -i aisoc-api python -m app.scripts.roadmap_sync --tenant-name Default < docs/ROADMAP_ITEMS.json` with `az vm run-command` (Default is the tenant the people sign in to).
