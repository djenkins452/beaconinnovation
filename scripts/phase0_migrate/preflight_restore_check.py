#!/usr/bin/env python
"""Preflight safety check to run BEFORE `manage.py flush` during a SQLite->Postgres
restore.

`flush` is destructive: it empties every table. The restore procedure only needs
it to clear the reference rows that the data-seeding migrations create with random
uuid4 primary keys (finance Category/Account), which would otherwise collide with
the fixture's unique constraints. flush must therefore run ONLY against a FRESHLY
CREATED, not-yet-populated target database.

This script refuses to green-light a flush if the target `DATABASE_URL` database
contains ANY real (non-seed) data, and it prints the exact host/database so the
operator can confirm they are not pointed at the wrong (e.g. production) database.
It is read-only; it never modifies anything.

Exit code 0 = SAFE to flush. Exit code 1 = NOT safe (abort).

Usage:
    DATABASE_URL=postgres://... python scripts/phase0_migrate/preflight_restore_check.py
"""
import os
import sys

import dj_database_url
import psycopg

# Tables that must be EMPTY on a freshly-migrated target. Any rows here mean the
# database already holds real data and must NOT be flushed.
REAL_DATA_TABLES = [
    "finance_transaction",
    "finance_receipt",
    "finance_recurringtransaction",
    "finance_taxalert",
    "finance_csvimport",
    "finance_auditlog",
    "admin_console_admintask",
    "wlj_document",
    "wlj_documentdownload",
    "django_admin_log",
]


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("ERROR: DATABASE_URL must be set to the target PostgreSQL database.")

    cfg = dj_database_url.parse(database_url)
    if "postgresql" not in cfg.get("ENGINE", ""):
        sys.exit("ERROR: target is not PostgreSQL; refusing.")

    host = cfg.get("HOST") or "localhost"
    dbname = cfg["NAME"]
    print(f"Target database: {dbname} @ {host}:{cfg.get('PORT') or 5432}")
    print("Confirm this is the FRESH restore target, not production, before flushing.\n")

    conninfo = psycopg.conninfo.make_conninfo(
        host=host,
        port=cfg.get("PORT") or 5432,
        dbname=dbname,
        user=cfg.get("USER") or None,
        password=cfg.get("PASSWORD") or None,
    )

    populated = []
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        for table in REAL_DATA_TABLES:
            cur.execute("SELECT to_regclass(%s)", (table,))
            if cur.fetchone()[0] is None:
                # Table missing -> schema not migrated yet; not a fresh-migrated target.
                print(f"  {table:32} (missing — run `migrate` first)")
                populated.append(table)
                continue
            cur.execute(f'SELECT COUNT(*) FROM "{table}"')
            n = cur.fetchone()[0]
            flag = "" if n == 0 else "  <-- NON-EMPTY"
            print(f"  {table:32} {n:>8}{flag}")
            if n:
                populated.append(table)

    print()
    if populated:
        print("NOT SAFE: target contains real data (or is not migrated). Do NOT flush.")
        print("Create a fresh empty database and migrate it first, or restore elsewhere.")
        sys.exit(1)
    print("SAFE: target holds only freshly-seeded reference data. flush may proceed.")


if __name__ == "__main__":
    main()
