#!/usr/bin/env python
"""Preflight safety gate to run BEFORE `manage.py flush` during a SQLite->Postgres
restore.

`flush` empties EVERY table. The restore only needs it to clear the reference rows
the data-seeding migrations create (finance Category/Account, with random uuid4
PKs), which would otherwise collide with the fixture's unique constraints. flush
must therefore run ONLY against a target that was just created and migrated and
holds nothing but that seed baseline.

This gate:
  * requires you to NAME the target (`--expect-db`) and refuses if the live
    connection is to a different database (explicit target identification);
  * inspects EVERY table flush would clear and permits ONLY the verified seed
    baseline — it validates the seed **contents** of finance Category and Account
    (names, types, balances, flags), not just their row counts, and requires every
    other application table to be empty; ANY deviation blocks;
  * reports whether another session is connected. NOTE: this is a point-in-time
    DETECTION only — it does NOT prevent a connection opening afterwards. The real
    guarantee is an **operational write freeze** (the app offline / not serving)
    maintained throughout flush + loaddata; this check cannot substitute for it.
  * connects with the full DATABASE_URL so libpq options such as sslmode are honored.

Read-only. Exit 0 = PASSED (safe to flush under the write freeze). Exit 1 = BLOCKED.

PASSED means the target matches the known post-migrate seed baseline, is the named
target, and has no other connection right now. It is NOT an absolute proof of
freshness, and it cannot guarantee quiescence after it returns — hold the write
freeze.

Usage:
    DATABASE_URL=postgres://... \
      python scripts/phase0_migrate/preflight_restore_check.py --expect-db beacon
"""
import argparse
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

import psycopg

# Seed tables validated by COUNT (contents are random/demo). A fresh `migrate` with no
# bootstrap and no DJANGO_SUPERUSER_PASSWORD produces exactly these.
EXPECTED_SEED_COUNTS = {
    "finance_category": 15,
    "finance_account": 3,
    "wlj_financialprojection": 15,
    "wlj_servicecost": 15,
    "wlj_codebasemetric": 1,
}

# Seed tables validated by CONTENT (so a modified seed with the same count is caught).
# Values mirror finance/migrations/0002 and 0003; these are non-sensitive repo seeds.
EXPECTED_SEED_CATEGORIES = {
    (n, "expense", "1") for n in [
        "Software & Subscriptions", "Equipment", "Professional Services",
        "Advertising & Marketing", "Office Supplies", "Education & Training",
        "Travel", "Meals & Entertainment", "Bank Fees & Interest", "Miscellaneous",
    ]
} | {
    (n, "income", "1") for n in [
        "Service Revenue", "Product Revenue", "Refunds", "Owner Contributions", "Other Income",
    ]
}
EXPECTED_SEED_ACCOUNTS = {
    ("Amex Business Checking", "checking", "American Express", "", "0", "1000.00"),
    ("Amex Blue Business Cash", "credit_card", "American Express", "", "0", "0.00"),
    ("Personal Amex", "credit_card", "American Express", "", "1", "0.00"),
}

# Django-managed tables that `migrate`/post_migrate populate; not application data.
SYSTEM_TABLES = {"django_migrations", "django_content_type", "auth_permission"}

# Every other public table (incl. auth_user — 0006 no longer seeds a superuser) must
# be EMPTY on a clean restore target.


def _bool(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    return "1" if str(v).strip().lower() in ("1", "true", "t", "yes") else "0"


def _money(v):
    return str(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-db", required=True,
                        help="The database you intend to restore into (must match the live connection).")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("ERROR: DATABASE_URL must be set to the target PostgreSQL database.")
    try:
        conn = psycopg.connect(database_url)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"ERROR: could not connect to the target database: {exc}")

    blocks = []
    with conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        dbname = cur.fetchone()[0]
        print(f"Target database: {dbname} @ {conn.info.host or '(local)'}:{conn.info.port}")

        # 1) Explicit target identification.
        if dbname != args.expect_db:
            print(f"\nBLOCKED: connected to '{dbname}' but --expect-db is '{args.expect_db}'.")
            sys.exit(1)

        # 2) Point-in-time connection detection (NOT a write-freeze guarantee).
        cur.execute("SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()")
        others = cur.fetchone()[0]
        print(f"Other active connections right now: {others} "
              "(detection only — hold an operational write freeze through the restore)")
        if others:
            blocks.append(f"{others} other connection(s) open now — ensure the app is offline, then retry.")

        # 3) Every table flush would clear.
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        tables = [r[0] for r in cur.fetchall()]
        if not tables:
            blocks.append("no tables found — run `migrate` on this target first.")

        print("\nSeed tables — COUNT:")
        for table in sorted(EXPECTED_SEED_COUNTS):
            if table not in tables:
                print(f"  {table:34} MISSING")
                blocks.append(f"seed table '{table}' missing — target not migrated.")
                continue
            cur.execute(f'SELECT count(*) FROM "{table}"')
            n = cur.fetchone()[0]
            want = EXPECTED_SEED_COUNTS[table]
            print(f"  {table:34} {n:>8}  (want {want})  {'OK' if n == want else 'UNEXPECTED'}")
            if n != want:
                blocks.append(f"'{table}' has {n} rows, expected {want}.")

        # 4) Seed CONTENT validation (catches a modified seed at the same row count).
        print("\nSeed tables — CONTENT:")
        if "finance_category" in tables:
            cur.execute("SELECT name, category_type, is_system FROM finance_category")
            actual = {(r[0], r[1], _bool(r[2])) for r in cur.fetchall()}
            cat_ok = actual == EXPECTED_SEED_CATEGORIES
            print(f"  finance_category content {'OK' if cat_ok else 'UNEXPECTED'}")
            if not cat_ok:
                for extra in sorted(actual - EXPECTED_SEED_CATEGORIES):
                    blocks.append(f"unexpected/modified category: {extra}")
                for missing in sorted(EXPECTED_SEED_CATEGORIES - actual):
                    blocks.append(f"missing expected category: {missing}")
        if "finance_account" in tables:
            cur.execute("SELECT name, account_type, institution, last_four, is_personal, opening_balance "
                        "FROM finance_account")
            actual = {(r[0], r[1], r[2], r[3], _bool(r[4]), _money(r[5])) for r in cur.fetchall()}
            acc_ok = actual == EXPECTED_SEED_ACCOUNTS
            print(f"  finance_account  content {'OK' if acc_ok else 'UNEXPECTED'}")
            if not acc_ok:
                for extra in sorted(actual - EXPECTED_SEED_ACCOUNTS):
                    blocks.append(f"unexpected/modified account: {extra}")
                for missing in sorted(EXPECTED_SEED_ACCOUNTS - actual):
                    blocks.append(f"missing expected account: {missing}")

        # 5) Every other non-system table must be empty.
        print("\nAll other tables — must be EMPTY:")
        for table in tables:
            if table in EXPECTED_SEED_COUNTS or table in SYSTEM_TABLES:
                continue
            cur.execute(f'SELECT count(*) FROM "{table}"')
            n = cur.fetchone()[0]
            if n:
                print(f"  {table:34} {n:>8}  UNEXPECTED DATA")
                blocks.append(f"'{table}' contains {n} unexpected row(s) that flush would delete.")

    print()
    if blocks:
        print("BLOCKED — do NOT flush this database:")
        for b in blocks:
            print(f"  - {b}")
        print("\nRestore only into a freshly created + migrated database, with the app offline. "
              "See docs/architecture/PHASE_0_DURABILITY.md.")
        sys.exit(1)

    print(f"PASSED: '{dbname}' is the named target, matches the seed baseline (counts + "
          "category/account contents), and has no other connection right now.\n"
          "This is not an absolute proof of freshness and cannot guarantee quiescence after "
          "it returns — hold the operational write freeze through flush + loaddata.")


if __name__ == "__main__":
    main()
