#!/usr/bin/env python
"""Verify a SQLite -> PostgreSQL migration by comparing row counts table-by-table.

A backup/restore is NOT considered verified just because a file was produced.
This tool restores confidence by checking that the recovered PostgreSQL data has
the same per-table row counts as the source SQLite database for the tables that
were migrated.

It reads the SQLite file directly and connects to PostgreSQL using DATABASE_URL
(the same variable the app uses). It prints a comparison and exits non-zero on any
mismatch. It never prints row contents — only table names and counts.

Usage (venv active, DATABASE_URL pointing at the migrated Postgres DB):

    python scripts/phase0_migrate/verify_parity.py --sqlite db.sqlite3
"""
import argparse
import os
import sqlite3
import sys

import dj_database_url
import psycopg

# Tables that are migrated as data (seed/system tables are recreated by migrations
# and are intentionally excluded from the parity check).
MIGRATED_TABLES = [
    "auth_user",
    "auth_group",
    "admin_console_admintask",
    "finance_account",
    "finance_category",
    "finance_transaction",
    "finance_receipt",
    "finance_recurringtransaction",
    "finance_taxalert",
    "finance_auditlog",
    "finance_csvimport",
    "products_product",
    "wlj_servicecost",
    "wlj_financialprojection",
    "wlj_codebasemetric",
    "wlj_document",
    "wlj_documentdownload",
]


def sqlite_counts(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    existing = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out = {}
    for t in MIGRATED_TABLES:
        out[t] = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] if t in existing else None
    con.close()
    return out


def pg_counts(database_url):
    cfg = dj_database_url.parse(database_url)
    conninfo = psycopg.conninfo.make_conninfo(
        host=cfg.get("HOST") or "localhost",
        port=cfg.get("PORT") or 5432,
        dbname=cfg["NAME"],
        user=cfg.get("USER") or None,
        password=cfg.get("PASSWORD") or None,
    )
    out = {}
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        for t in MIGRATED_TABLES:
            cur.execute(
                "SELECT to_regclass(%s)", (t,)
            )
            if cur.fetchone()[0] is None:
                out[t] = None
                continue
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            out[t] = cur.fetchone()[0]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default="db.sqlite3")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("ERROR: DATABASE_URL must be set to the migrated PostgreSQL database.")
    if not os.path.exists(args.sqlite):
        sys.exit(f"ERROR: SQLite file not found: {args.sqlite}")

    sq = sqlite_counts(args.sqlite)
    pg = pg_counts(database_url)

    print(f"{'table':38} {'sqlite':>8} {'postgres':>9}  status")
    print("-" * 70)
    mismatches = 0
    for t in MIGRATED_TABLES:
        s, p = sq[t], pg[t]
        if s is None and p is None:
            status = "absent both"
        elif s == p:
            status = "OK"
        else:
            status = "MISMATCH"
            mismatches += 1
        print(f"{t:38} {str(s):>8} {str(p):>9}  {status}")

    print("-" * 70)
    if mismatches:
        print(f"FAILED: {mismatches} table(s) do not match.")
        sys.exit(1)
    print("VERIFIED: all migrated tables match.")


if __name__ == "__main__":
    main()
