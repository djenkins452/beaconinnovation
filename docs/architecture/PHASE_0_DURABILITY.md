# Phase 0 — Durable Database & Receipt Storage

**Branch:** `phase-0-durable-db`
**Prepared:** 2026-10-31
**Status:** Code complete and **locally validated against PostgreSQL**. **Awaiting live production cutover** (deliberately not performed — see §6).
**Scope guardrail:** Durability + recovery only. **No** inventory, orders, customers, recipes, costing, storefront, schedulers, or dashboards were added.

> **Hard requirement applied:** PostgreSQL is mandatory in **every** environment — local dev, automated tests, CI, staging, and production. SQLite has been removed entirely; there is no SQLite configuration and no fallback.

---

## 1. Verified findings and remaining uncertainties

### Proven from the repository (verified)
- **Beacon's `default` DB was SQLite**, file `db.sqlite3` at `BASE_DIR`, with **no `DATABASE_URL` parsing** for `default` (old `settings.py` DATABASES block). `db.sqlite3` is **git-tracked** (added before `.gitignore`, which now lists it).
- The dependencies for Postgres already existed: `psycopg[binary]` and `dj-database-url` in `requirements.txt`; `dj_database_url` was already parsing `PLATFORM_DATABASE_URL` — but **only** for the separate aegis `platform` DB.
- **No deployment durability config is committed** — there is no `railway.json`, `railway.toml`, `nixpacks.toml`, `Dockerfile`, or volume declaration anywhere in the repo. The `Procfile` runs `migrate` then Gunicorn.
- **Receipts are stored on a local `FileField`** (`finance/models.py` `Receipt.file`, `upload_to='receipts/%Y/%m/'`) under `MEDIA_ROOT = BASE_DIR/media`, served through an **access-checked Django view** (`finance` `_check_receipt_access`), **not** a public URL. **Cloudinary is configured but entirely unwired.**
- **aegis isolation is real:** `aegis.core.routers.PlatformRouter` sends `aegis_*` apps to `platform` only, everything else to `default` only, and denies cross-DB relations.
- **Local `db.sqlite3` contains seed/reference data only:** 3 users, 3 seeded finance accounts, 15 seeded categories, 1 product (AIMS), WLJ demo rows (15 + 15 + 1). **Zero finance transactions and zero receipts** locally; the `media/` files are test CSVs, not receipts.

### Requires live hosting access — **UNVERIFIED** (no production access from this environment)
- **Whether production actually loses data on redeploy.** This depends on whether Railway has a **Volume mounted at the SQLite path**. If a volume is mounted, SQLite data persists across deploys and "data loss on every deploy" is **not** true. I could not inspect the Railway service, so this remains unverified — treat it as a serious *risk*, not a confirmed fact.
- **Whether production has real records** (transactions, receipts, users beyond seeds).
- **Where production receipts physically reside** and whether they survive redeploys (same volume question).
- **Existing backup/restore arrangements**, if any.
- **Production Python version:** `runtime.txt` pins `python-3.13.1`; the local venv and CI use `3.12`. Unverified which runs in prod.

> **Do not** claim production durability, data loss, or recovery as proven until it has been verified against the live Railway service. §6 lists exactly what you must check/do there.

---

## 2. Changes made and why

All on branch `phase-0-durable-db`. Nothing merged; nothing deployed.

| File | Change | Why |
|---|---|---|
| `beaconinnovation/settings.py` | `default` DB now **requires** `DATABASE_URL` and refuses non-PostgreSQL URLs via `_require_postgres()`; raises `ImproperlyConfigured` with a clear message if missing. SQLite config removed. | Postgres mandatory everywhere; fail loudly, never silently pick SQLite. |
| `beaconinnovation/settings.py` | Loads a local `.env` via `python-dotenv` (real env vars win; no-op in prod). | Simple, reproducible local setup. |
| `beaconinnovation/settings.py` | `MEDIA_ROOT` is now `DJANGO_MEDIA_ROOT` (defaults to `BASE_DIR/media`). | Lets a persistent Volume back receipt storage without code change; preserves access controls + file references. |
| `beaconinnovation/settings.py` | `platform` DB parsing kept, now also guarded by `_require_postgres()`. **Router untouched.** | Preserve aegis isolation; do not merge databases. |
| `requirements.txt` | Added `python-dotenv>=1.0`. | Local `.env` support. |
| `docker-compose.yml` | PostgreSQL 16 service; provisions `beacon` + `beacon_platform` DBs. | One-command local Postgres. |
| `scripts/phase0_migrate/initdb/01-create-platform-db.sql` | Creates the separate `beacon_platform` DB on first `docker compose up`. | Keep the two DBs separate locally too. |
| `.env.example` | Documents `DATABASE_URL`, `PLATFORM_DATABASE_URL`, Django vars (no secrets). | Onboarding + matches compose defaults. |
| `.github/workflows/ci.yml` | CI runs `check` + migrations + full test suite **against a Postgres service**, with an isolated test DB. | Tests/CI on Postgres; never SQLite. |
| `scripts/phase0_migrate/export_legacy_sqlite.py` | Standalone one-time SQLite→fixture exporter (independent of the Postgres-only settings). | Migrate legacy data. |
| `scripts/phase0_migrate/verify_parity.py` | Compares per-table row counts (SQLite source vs Postgres target); exits non-zero on mismatch. | Prove a restore actually recovered the data. |
| `scripts/phase0_migrate/preflight_restore_check.py` | Read-only safety gate: refuses to green-light `flush` unless the target holds only freshly-seeded data; prints the target host/db. | Prevent flushing a populated or wrong database. |
| `.gitignore` | Ignore `backups/`. | Never commit data dumps. |
| `db.sqlite3` | **Untracked** via `git rm --cached` (local file kept). | Stop exposing a database (incl. password hashes) in the repo. |

**Explicitly NOT changed:** the `aegis` router/models/DB; the `STATICFILES_STOREAGE` typo (a static-files bug unrelated to durability — changing static storage during a DB cutover adds avoidable deploy risk; tracked separately). `db.sqlite3` is **untracked but not deleted** — the local file is retained as the pre-cutover recovery copy.

### Repository exposure review (item 5)

- **`db.sqlite3` was the only sensitive file tracked** in the repo. It contains user rows **including password hashes**, so it is now removed from tracking with `git rm --cached` (the working-copy file is kept as a recovery copy). It was already in `.gitignore`, so it will not be re-added.
- **Recovery copies live outside version control:** the raw `.bak` and the migration fixture are under `backups/`, which is gitignored (`git check-ignore` confirms). `.env` is gitignored and not tracked. No fixtures, dumps, or credentials are tracked.
- **Backups contain PII (password hashes, financial rows)** — keep them off the repo and ideally off the server (encrypted, offsite). Never `git add -f` them.
- **Historical exposure (reported separately, not acted on here, as instructed):** because `db.sqlite3` was committed previously, **old copies remain in Git history**. Untracking it now stops *future* exposure but does not remove it from past commits. If the committed history (local or on GitHub) is considered sensitive, that requires a separate, deliberate history-rewrite task (e.g. `git filter-repo`) and a credential rotation — **out of scope for this commit** and flagged for your decision. At minimum, rotate `DJANGO_SECRET_KEY` and any real user passwords that ever lived in the committed `db.sqlite3`.

---

## 3. Validation results (local, PostgreSQL 16)

Run on a local PostgreSQL 16 server with two throwaway databases (`beacon_p0`, `beacon_platform_p0`).

- **Guardrail — missing config:** `manage.py check` with no `DATABASE_URL` → fails with a clear `ImproperlyConfigured` ("DATABASE_URL is not set… SQLite is no longer supported"). ✅
- **Guardrail — no silent SQLite, every alias:** a `sqlite:///…` URL is rejected for **both** `DATABASE_URL` and `PLATFORM_DATABASE_URL` (the error names the offending variable). The `_require_postgres()` guard runs on every configured alias. Because all environments (local dev, automated tests, CI, staging, production) import the same `settings.py`, the Postgres-only rule applies uniformly to all of them — there is no environment-specific SQLite path. aegis isolation is unchanged (router untouched). ✅
- **Migrations:** `migrate` (default) and `migrate --database=platform` both succeed on Postgres. ✅
- **aegis isolation (verified both directions):** platform DB contains **only** `aegis_*` tables (15) + `django_migrations`; default DB contains finance/wlj/products/auth/etc. and **no** `aegis_*` tables. (Note: migration *records* appear in both `django_migrations` tables — standard Django multi-DB behavior — but no schema or data leaks across; `allow_migrate` gated all table creation and the data-seeding `RunPython`.) ✅
- **Data migration + restore + parity:** `migrate → flush → loaddata(fixture) → sqlsequencereset` restored all data; `verify_parity.py` reported **VERIFIED — all 17 migrated tables match** the SQLite source. ✅
- **Receipt upload/retrieval:** exercised by the finance receipt/OCR test suites (`test_receipts.py`, `test_ocr.py`) against Postgres + the local `FileField`, including the access-checked retrieval path. ✅
- **Backup restored into a fresh, isolated DB:** created an empty `beacon_restore_test`, ran migrate → flush → loaddata → sqlsequencereset, and `verify_parity.py` reported **VERIFIED**. Spot-check confirmed 3 users recovered with **password hashes intact**, 3 accounts, 15 categories. (Run with no `PLATFORM_DATABASE_URL`, also proving the default DB works standalone while `/platform/` stays fail-closed.) ✅
- **Full test suite on PostgreSQL:** **574 tests, 573 passing, 1 known failure.** The one failure is `products…BootstrapCommandTests.test_publishes_committed_aims_build`. **Evidence it is pre-existing and backend-independent:**
  1. It was reproduced on the **baseline** — with all Phase 0 changes stashed and the original SQLite settings active, the test fails identically: `AssertionError: False is not true` at `products/tests.py:365` (`self.assertTrue(aims.is_available)`).
  2. `git diff HEAD -- products/` is **empty** — no products code or test was touched; the test is byte-identical to the branch point.
  3. The assertion is about **file availability** (`is_available` = the committed `AIMSField.ipa` being published by `bootstrap_portal`), which has no dependency on the database backend. It matches the project's own prior record of this test as a known pre-existing failure.
  The test was **not** weakened, skipped, or modified. It is reported honestly as a known failure.
- **One Postgres-surfaced test bug fixed (not hidden):** `finance…test_export_income_statement_includes_owners_draw` created a `Category` with an invalid 11-char `category_type` ('owners_draw') that only SQLite tolerated (SQLite ignores `varchar` length and `choices`); PostgreSQL correctly rejects it. The test now uses an uncategorized owner's draw (`category=None`), which matches the model's design (`Transaction.clean` does not require a category for draws). The model and production code were correct and **unchanged**. ✅

> **Local vs hosting:** these results prove the **code and migration procedure** on PostgreSQL. They do **not** prove anything about the live Railway service (see §1 uncertainties and §6 steps).

---

## 4. Backup, restore, migration, and rollback

### 4.1 Backup (do this FIRST, before any change)
On the source (local, or the **current pre-Phase-0 production deploy** where settings still use SQLite):
```bash
# Raw file snapshot
cp db.sqlite3 "backups/phase0/db.sqlite3.$(date +%Y%m%d-%H%M%S).bak"
# Portable fixture (natural keys; excludes recreated/system tables)
python manage.py dumpdata --natural-primary --natural-foreign --indent 2 \
  auth.User auth.Group admin_console finance products wlj \
  -o backups/phase0/legacy_default_fixture.json
```
If you can only obtain a copy of the production `db.sqlite3` file (not a running old deploy), use the standalone exporter instead:
```bash
python scripts/phase0_migrate/export_legacy_sqlite.py \
  --sqlite /path/to/prod_db.sqlite3 \
  --out backups/phase0/legacy_default_fixture.json
```

### 4.2 Migration sequence (into PostgreSQL) — validated locally

**The restore ALWAYS targets a freshly created, empty database — never an existing or populated one.**

```bash
# 1. Create a NEW, empty target database (do not reuse an existing/populated one)
createdb beacon                 # or provision a fresh DB in the hosting platform

# 2. Point at the fresh target
export DATABASE_URL=postgres://USER:PASS@HOST:PORT/beacon      # add ?sslmode=require if public
export PLATFORM_DATABASE_URL=postgres://USER:PASS@HOST:PORT/beacon_platform   # only if platform in use

# 3. Create schema. NOTE: the data-seeding migrations ALSO insert reference rows
#    (finance Category/Account) with RANDOM uuid4 primary keys.
python manage.py migrate --noinput
python manage.py migrate --database=platform --noinput          # only if platform in use

# 4. SAFETY GATE — must print "SAFE" before the destructive flush in step 5.
#    Prints the target host/db and refuses if it holds ANY real data or is not a
#    freshly-migrated database. Abort if it does not print SAFE.
python scripts/phase0_migrate/preflight_restore_check.py

# 5. Clear ONLY the freshly-seeded reference rows so the fixture is authoritative.
#    Run ONLY after step 4 printed SAFE.
python manage.py flush --no-input

# 6. Load the legacy data
python manage.py loaddata backups/phase0/legacy_default_fixture.json

# 7. Reset integer-PK sequences so new inserts don't collide
for app in products wlj auth admin admin_console; do python manage.py sqlsequencereset $app; done | psql "$DATABASE_URL"

# 8. VERIFY the restore (not just that a file exists)
python scripts/phase0_migrate/verify_parity.py --sqlite /path/to/source_db.sqlite3
```

**Why `flush` is needed (and why it is safe here).** The seed migrations `finance/migrations/0002_seed_default_categories` and `0003_seed_default_accounts` call `create()` without explicit PKs, so every run generates **new random `uuid4` PKs**. Loading the fixture (whose rows carry the *source* UUIDs) onto those freshly-seeded rows would violate the `unique(name, category_type)` constraint. `flush` removes the just-seeded rows (keeping the schema; `contenttypes`/`permissions` are recreated by its `post_migrate`). Because step 1 creates an **empty** database and step 4 **refuses to proceed if any real data is present**, `flush` can only ever clear seed data — never real records, never the wrong database.

**No destructive step runs automatically.** `flush` exists only in this operator-run runbook. The `Procfile` runs `migrate` plus idempotent seed/bootstrap commands at deploy — it contains **no** `flush`, `reset`, drop, or truncate. Never add a destructive command to startup or deploy.

**Keys/constraints:** finance + admin_console use **UUID** PKs (no sequence issues). `products`/`wlj`/`auth` use integer PKs — step 7 resets their sequences. FKs are preserved via natural keys (`--natural-foreign`); `contenttypes`/`permissions` are recreated by `migrate`/`flush` and intentionally excluded from the fixture.

### 4.3 Restore verification into an isolated environment
`verify_parity.py` is the gate: it reads the source SQLite directly and the target Postgres via `DATABASE_URL`, compares per-table counts, and **exits non-zero on any mismatch**. A backup is only "verified" once this passes against a freshly-restored database.

### 4.4 Rollback — depends on whether PostgreSQL has accepted production writes

Decide this explicitly before acting; the two cases are different.

**Case A — BEFORE the new PostgreSQL has accepted any production writes**
(cutover not started, or it failed during migration, or the app has not yet served write traffic):
- Safe to revert. Don't merge/deploy Phase 0 (or redeploy the prior commit). The retained SQLite is still authoritative and nothing has diverged.
- Keep the Postgres DB for diagnosis; no data is lost either way.

**Case B — AFTER the new PostgreSQL has accepted production writes**
(the app has served real users on Postgres):
- ⚠️ **Redeploying old code against the retained SQLite is NOT a valid rollback.** Every record written on Postgres since cutover would be silently lost. Do not do this.
- Instead:
  1. **Stop writes first.** Put the app into maintenance/read-only (scale the web service to zero, or serve a maintenance page) so no further records are created while you decide. This preserves the current Postgres state.
  2. **Capture the current Postgres state** with `pg_dump` before changing anything.
  3. **Prefer forward recovery.** Postgres now holds the authoritative data — fix the fault and roll *forward* (redeploy a corrected build on Postgres) rather than back.
  4. If you truly must leave Postgres, first migrate the **current** Postgres data (not the stale SQLite) to the destination, verify it, then cut over. Never discard the post-cutover writes.
- The pre-cutover `db.sqlite3`, `.bak`, and fixture are a recovery copy of the state **at cutover time only** — they do **not** contain any post-cutover writes.

**Routine backups once live:** schedule `pg_dump` and keep copies off the server; restore with `pg_restore`. This supersedes the one-time SQLite fixture, which exists only for the initial migration. Do not delete the pre-cutover SQLite recovery copy until Postgres has run clean in production for an agreed bake-in period.

---

### 4.5 Receipt files — backup, migration, and access (PENDING production verification)

Receipts are sensitive financial documents stored on a private `FileField` (`finance` `Receipt.file`, `upload_to='receipts/%Y/%m/'`) and served **only** through the access-checked view (`finance._check_receipt_access`: superuser, or the transaction's creator / the receipt's uploader; denied → 404). They are not in `STATICFILES_DIRS` or `/downloads/`. **Durability of the receipt *files* in production is UNVERIFIED** — it depends on whether a persistent Volume is mounted (§1).

**Make files durable + copy existing files (operator, production):**
1. Provision a persistent Volume; set `DJANGO_MEDIA_ROOT` to its mount path (e.g. `/data/media`).
2. Copy existing files in, preserving the relative layout so `FileField` paths still resolve:
   `rsync -a <old_media>/ /data/media/`   (receipts land at `/data/media/receipts/YYYY/MM/...`).
3. **Verify the copy** (counts + checksums):
   ```bash
   find <old_media> -type f | wc -l ; find /data/media -type f | wc -l            # counts match
   ( cd <old_media>  && find . -type f -exec shasum {} + | sort ) > /tmp/old.sha
   ( cd /data/media  && find . -type f -exec shasum {} + | sort ) > /tmp/new.sha
   diff /tmp/old.sha /tmp/new.sha && echo "files match"
   ```
4. **Verify DB references resolve** (every `Receipt.file` points to a present file):
   ```bash
   python manage.py shell -c "import os;from finance.models import Receipt;print('missing:',[str(r.id) for r in Receipt.objects.all() if not (r.file and os.path.exists(r.file.path))])"
   # expect: missing: []
   ```

**Access control is preserved** — only the storage *path* changes; the serving view and its permission check are untouched. Cloudinary is deliberately **not** used (its delivery URLs are unsuitable for private financial records).

**Back up BOTH halves together and restore together:**
- DB records: `pg_dump` (routine) / the fixture (one-time migration). Receipt rows carry the relative file path.
- Files: `tar czf receipts-$(date +%F).tgz -C "$DJANGO_MEDIA_ROOT" .` (or a Volume snapshot), stored off the server.
- Snapshot DB **and** files in the same maintenance window — a row without its file (or vice-versa) is a broken receipt.
- Restore = restore the DB (`pg_restore`/`loaddata`) **and** extract files back under `DJANGO_MEDIA_ROOT`, then re-run step 4's "references resolve" check.

---

## 5. Production configuration steps **you** must perform

These require Railway access I do not have. None of this has been done.

1. **Provision managed PostgreSQL** for Beacon on Railway. Set `DATABASE_URL` on the Beacon service (use `?sslmode=require` if connecting over the public network).
2. **Set `DJANGO_SECRET_KEY`** (strong, unique) and `DJANGO_DEBUG=False`.
3. **Receipt durability:** mount a **persistent Volume** and set `DJANGO_MEDIA_ROOT` to its mount path (e.g. `/data/media`). Copy existing receipt files in and **verify them** — see **§4.5** for the rsync + checksum procedure, the "references resolve" check, and joint DB+file backup/restore. Keep receipts private — served only through the access-checked view, never `/static/` or a CDN. (Receipt-file durability in prod is currently **unverified**.)
4. **(Optional) platform DB:** only set `PLATFORM_DATABASE_URL` when the aegis platform DB is provisioned. Leaving it unset keeps `/platform/` failing closed, Beacon unaffected.
5. **Capture production data first** (§4.1) from the current deploy **before** deploying this branch.
6. **Deploy, run the migration (§4.2), and verify parity (§4.3)** against production data.
7. Confirm `runtime.txt` (3.13.1) vs the actually-deployed Python; align if needed.

> ⚠️ Because `DATABASE_URL` is now mandatory, **merging this branch without `DATABASE_URL` set in production will make the app fail to boot** (by design). Set the env vars **before** deploying.

---

## 6. Is Phase 0 complete?

**Partially — code complete and locally validated; the live cutover is intentionally not done.**

- ✅ Done: Postgres-only settings with fail-loud guards; `.env`/compose/CI; receipt-storage path made volume-ready; backup tooling; a **verified** SQLite→Postgres migration + parity procedure; full test run on Postgres; aegis isolation preserved.
- ⏳ Awaiting your review + action: the §5 production steps (provision Postgres + Volume, set env vars, capture prod data, cut over, verify). Per your instruction I **stopped before any live cutover or destructive action**.
- 🔒 Nothing merged, nothing deployed, no data deleted. `db.sqlite3` is untracked (`git rm --cached`) but retained locally as the pre-cutover recovery copy. Committed on `phase-0-durable-db` only (not pushed).

---

## 7. Future integration rule (documented, not implemented)

**Inventory movements describe physical quantities; finance entries describe money. They are linked deliberately, never automatically.**
- Receiving stock or consuming materials **must not** create a finance expense. The money is recorded **once**, as a `finance.Transaction`, when the purchase is paid (cash basis).
- A future `Purchase`/`PurchaseLine` bridge will reference that single `Transaction` and emit inventory **receipt movements** separately. Opening inventory is entered as movements with **no** expense.
- This document does not implement any accounting policy; it only records the rule so Phase 1 honors it.

---

## 8. Proposed Phase 1 scope (for approval — not started)

Narrowly: **purchases, materials/spools, opening inventory, and print consumption.** Everything else stays out.

- **Models:** Supplier (light), Purchase/PurchaseLine (bridging one `finance.Transaction`; use-split business/personal/shared), Material, FilamentSpool (per-spool: mfr, material, color, nominal/tare weight, estimated vs measured remaining g, cost, location, status), StockItem (hardware/consumables/packaging), Location, Equipment, and the append-only **InventoryMovement** ledger (purchase_receipt, opening_balance, consumption, waste, adjustment).
- **Flows:** enter opening inventory (no expense); record a purchase (one expense + inventory receipt, no double-count); log consumption; log a print (successful units, failures, waste g — failed prints consume material but create no sellable stock); weigh-in reconciliation.
- **Out of scope for Phase 1:** products/recipes catalog, orders/customers/quotes/proofs, costing engine, storefront, OCR auto-link, QR, scheduling, dashboards.
- **Acceptance:** on-hand == Σ(movements); available == on-hand − reservations; a purchase creates exactly one expense; opening inventory creates none; movements are immutable (corrections are new movements).

---

*Phase 0 ends here, awaiting your review of §5–§6 before any production cutover.*
