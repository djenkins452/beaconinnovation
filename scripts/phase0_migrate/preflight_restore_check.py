#!/usr/bin/env python
"""Preflight safety gate to run BEFORE `manage.py flush` during a SQLite->Postgres
restore.

`flush` empties EVERY table. The restore only needs it to clear the reference rows
that the data-seeding migrations create with random uuid4 primary keys (finance
Category/Account), which would otherwise collide with the fixture's unique
constraints. flush must therefore run ONLY against a target that was just created
and migrated and holds nothing but that seed baseline.

This gate inspects **every** table flush would clear and permits ONLY the
explicitly verified seed/system data. ANY unexpected row (extra users, groups,
products, transactions, receipts, admin tasks, …) blocks the restore. It also:
  * requires the operator to name the target database (`--expect-db`) and refuses
    if the live connection is to a different database (explicit target id);
  * refuses if any OTHER session is connected to the target, so a live app cannot
    write between this check and the destructive flush (run the whole restore in a
    single maintenance window — see the runbook);
  * connects with the FULL DATABASE_URL so libpq options such as sslmode are
    honored.

It is read-only. Exit 0 = PASSED (safe to flush). Exit 1 = BLOCKED (abort).

This verifies the target matches the known post-migrate seed baseline, is the
named target, and is quiescent **now**. It is NOT an absolute proof of freshness;
keeping the application in maintenance through flush+loaddata is what closes the
write window.

Usage:
    DATABASE_URL=postgres://... \
      python scripts/phase0_migrate/preflight_restore_check.py --expect-db beacon
"""
import argparse
import os
import sys

import psycopg

# Tables that MUST contain exactly the migration-seeded reference rows produced by a
# fresh `migrate` (no bootstrap management commands). More or fewer rows => not a
# clean target. NOTE: finance/migrations/0006_create_superuser creates ONE superuser
# unconditionally (a known hardcoded-password seed); the restore's flush removes it
# and loaddata restores the real users, so auth_user must be exactly 1 here.
EXPECTED_SEED_COUNTS = {
    "auth_user": 1,
    "finance_category": 15,
    "finance_account": 3,
    "wlj_financialprojection": 15,
    "wlj_servicecost": 15,
    "wlj_codebasemetric": 1,
}

# Django-managed tables that `migrate`/post_migrate populate; not application data.
# Allowed to be non-empty; their exact counts depend on installed apps.
SYSTEM_TABLES = {
    "django_migrations",
    "django_content_type",
    "auth_permission",
}

# Every other public table must be EMPTY (0 rows) on a clean restore target.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect-db",
        required=True,
        help="The database name you intend to restore into (must match the live connection).",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("ERROR: DATABASE_URL must be set to the target PostgreSQL database.")

    # Connect with the FULL URL so sslmode and other libpq options are honored.
    try:
        conn = psycopg.connect(database_url)
    except Exception as exc:  # noqa: BLE001 - surface the connection failure plainly
        sys.exit(f"ERROR: could not connect to the target database: {exc}")

    blocks = []
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database()")
            dbname = cur.fetchone()[0]
            host = conn.info.host or "(local)"
            port = conn.info.port
            print(f"Target database: {dbname} @ {host}:{port}")

            # 1) Explicit target identification.
            if dbname != args.expect_db:
                print(
                    f"\nBLOCKED: connected to '{dbname}' but --expect-db is "
                    f"'{args.expect_db}'. Refusing to touch a database you did not name."
                )
                sys.exit(1)

            # 2) No other sessions (a live app could write before/after flush).
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
            others = cur.fetchone()[0]
            print(f"Other active connections to this database: {others}")
            if others:
                blocks.append(
                    f"{others} other connection(s) are open — the app may still be live. "
                    "Put it in maintenance (no writes) for the whole restore, then retry."
                )

            # 3) Inspect EVERY table flush would clear.
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            tables = [r[0] for r in cur.fetchall()]
            if not tables:
                blocks.append("no tables found — run `migrate` on this target first.")

            print("\nTable inspection (every table flush would clear):")
            # Seed tables must be present with the exact expected counts.
            for table in sorted(EXPECTED_SEED_COUNTS):
                if table not in tables:
                    print(f"  {table:34} MISSING")
                    blocks.append(f"seed table '{table}' is missing — target not migrated.")
                    continue
                cur.execute(f'SELECT count(*) FROM "{table}"')
                n = cur.fetchone()[0]
                want = EXPECTED_SEED_COUNTS[table]
                ok = n == want
                print(f"  {table:34} {n:>8}  (expected seed {want})  {'OK' if ok else 'UNEXPECTED'}")
                if not ok:
                    blocks.append(
                        f"'{table}' has {n} rows, expected exactly {want} seed rows."
                    )

            # Every other non-system table must be empty.
            for table in tables:
                if table in EXPECTED_SEED_COUNTS or table in SYSTEM_TABLES:
                    continue
                cur.execute(f'SELECT count(*) FROM "{table}"')
                n = cur.fetchone()[0]
                flag = "OK (empty)" if n == 0 else "UNEXPECTED DATA"
                print(f"  {table:34} {n:>8}  {flag}")
                if n:
                    blocks.append(f"'{table}' contains {n} unexpected row(s) that flush would delete.")

    print()
    if blocks:
        print("BLOCKED — do NOT flush this database:")
        for b in blocks:
            print(f"  - {b}")
        print(
            "\nRestore only into a freshly created + migrated database, with the app "
            "in maintenance. See docs/architecture/PHASE_0_DURABILITY.md."
        )
        sys.exit(1)

    print(
        f"PASSED: '{dbname}' matches the expected post-migrate seed baseline, is the "
        "named target, and has no other active connections.\n"
        "This confirms the target matches the known seed baseline and is quiescent now; "
        "it is not an absolute proof of freshness. Keep the app in maintenance through "
        "flush + loaddata so no writes land in between."
    )


if __name__ == "__main__":
    main()
