#!/usr/bin/env python
"""Verify a SQLite -> PostgreSQL migration by comparing CONTENT and RELATIONSHIPS,
not just row counts.

For each important table it fetches a set of natural-key + value columns, normalizes
every value into a backend-independent canonical form (Decimals to fixed money
scale, dates to ISO, booleans to 0/1, UUIDs lower-cased, NULLs explicit), sorts the
rows, and compares a SHA-256 digest of each side. A digest mismatch is reported even
when the row counts are identical, so silent value corruption is caught.

It also checks relationship integrity on the PostgreSQL target (no orphaned foreign
keys), covering user/group membership and permissions, financial values, receipt
paths, and the finance relationships.

**No sensitive values are ever printed** — only table names, counts, and short
digests. (Password hashes and receipt paths are folded into the digests, never
displayed.)

Connections use the full DATABASE_URL so libpq options such as sslmode are honored.

Usage (venv active, DATABASE_URL = the migrated Postgres DB):
    python scripts/phase0_migrate/verify_parity.py --sqlite db.sqlite3
"""
import argparse
import hashlib
import os
import sqlite3
import sys
from decimal import Decimal, ROUND_HALF_UP

import psycopg

# --- content checks: label -> (sql, column kinds) ----------------------------
# The SQL is portable across SQLite and PostgreSQL. Joins resolve natural keys
# (usernames, group names, permission codenames, finance UUIDs) so comparisons are
# stable even though auth/permission integer ids differ between the two databases.
CONTENT_CHECKS = {
    "auth_user": (
        "SELECT username, is_active, is_staff, is_superuser, password FROM auth_user",
        ["str", "bool", "bool", "bool", "str"],
    ),
    "auth_group": (
        "SELECT name FROM auth_group",
        ["str"],
    ),
    "auth_user_groups": (
        "SELECT u.username, g.name FROM auth_user_groups ug "
        "JOIN auth_user u ON u.id = ug.user_id "
        "JOIN auth_group g ON g.id = ug.group_id",
        ["str", "str"],
    ),
    "auth_group_permissions": (
        "SELECT g.name, ct.app_label, p.codename FROM auth_group_permissions gp "
        "JOIN auth_group g ON g.id = gp.group_id "
        "JOIN auth_permission p ON p.id = gp.permission_id "
        "JOIN django_content_type ct ON ct.id = p.content_type_id",
        ["str", "str", "str"],
    ),
    "auth_user_user_permissions": (
        "SELECT u.username, ct.app_label, p.codename FROM auth_user_user_permissions up "
        "JOIN auth_user u ON u.id = up.user_id "
        "JOIN auth_permission p ON p.id = up.permission_id "
        "JOIN django_content_type ct ON ct.id = p.content_type_id",
        ["str", "str", "str"],
    ),
    "finance_account": (
        "SELECT a.name, a.account_type, a.opening_balance, a.is_personal, u.username "
        "FROM finance_account a LEFT JOIN auth_user u ON u.id = a.created_by_id",
        ["str", "str", "money", "bool", "str"],
    ),
    "finance_category": (
        "SELECT name, category_type, is_system FROM finance_category",
        ["str", "str", "bool"],
    ),
    "finance_transaction": (
        "SELECT t.transaction_date, t.transaction_type, t.amount, a.name, c.name, u.username "
        "FROM finance_transaction t "
        "JOIN finance_account a ON a.id = t.account_id "
        "LEFT JOIN finance_category c ON c.id = t.category_id "
        "LEFT JOIN auth_user u ON u.id = t.created_by_id",
        ["date", "str", "money", "str", "str", "str"],
    ),
    "finance_receipt": (
        "SELECT transaction_id, file, ocr_amount FROM finance_receipt",
        ["uuid", "str", "money"],
    ),
    "finance_recurringtransaction": (
        "SELECT amount, frequency, account_id, category_id FROM finance_recurringtransaction",
        ["money", "str", "uuid", "uuid"],
    ),
    "finance_taxalert": (
        "SELECT quarter, year, threshold_amount, actual_net_profit FROM finance_taxalert",
        ["int", "int", "money", "money"],
    ),
    "products_product": (
        "SELECT slug, bundle_id, current_version, current_build FROM products_product",
        ["str", "str", "str", "str"],
    ),
    "products_product_authorized_users": (
        "SELECT p.slug, u.username FROM products_product_authorized_users pau "
        "JOIN products_product p ON p.id = pau.product_id "
        "JOIN auth_user u ON u.id = pau.user_id",
        ["str", "str"],
    ),
}

# count-only tables (seed data recreated by migrations, or expected empty)
COUNT_ONLY = [
    "wlj_servicecost",
    "wlj_financialprojection",
    "wlj_codebasemetric",
    "wlj_document",
    "wlj_documentdownload",
    "admin_console_admintask",
    "finance_auditlog",
    "finance_csvimport",
]

# relationship integrity checks on the TARGET (orphan count must be 0)
RELATIONSHIP_CHECKS = {
    "transaction.account -> account": (
        "SELECT count(*) FROM finance_transaction t "
        "LEFT JOIN finance_account a ON a.id = t.account_id WHERE a.id IS NULL"
    ),
    "transaction.category -> category": (
        "SELECT count(*) FROM finance_transaction t "
        "LEFT JOIN finance_category c ON c.id = t.category_id "
        "WHERE t.category_id IS NOT NULL AND c.id IS NULL"
    ),
    "receipt.transaction -> transaction": (
        "SELECT count(*) FROM finance_receipt r "
        "LEFT JOIN finance_transaction t ON t.id = r.transaction_id WHERE t.id IS NULL"
    ),
    "account.created_by -> user": (
        "SELECT count(*) FROM finance_account a "
        "LEFT JOIN auth_user u ON u.id = a.created_by_id "
        "WHERE a.created_by_id IS NOT NULL AND u.id IS NULL"
    ),
    "recurring.account -> account": (
        "SELECT count(*) FROM finance_recurringtransaction r "
        "LEFT JOIN finance_account a ON a.id = r.account_id WHERE a.id IS NULL"
    ),
    "authorized_users.user -> user": (
        "SELECT count(*) FROM products_product_authorized_users pau "
        "LEFT JOIN auth_user u ON u.id = pau.user_id WHERE u.id IS NULL"
    ),
}


def _norm(value, kind):
    if value is None:
        return "∅"
    if kind == "money":
        return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if kind == "bool":
        if isinstance(value, bool):
            return "1" if value else "0"
        return "1" if str(value).strip().lower() in ("1", "true", "t", "yes") else "0"
    if kind == "date":
        return str(value)[:10]
    if kind == "uuid":
        return str(value).strip().lower()
    if kind == "int":
        return str(int(value))
    return str(value)


def _digest(rows, kinds):
    normalized = [tuple(_norm(v, kinds[i]) for i, v in enumerate(row)) for row in rows]
    normalized.sort()
    h = hashlib.sha256()
    for row in normalized:
        h.update(repr(row).encode("utf-8"))
        h.update(b"\x1e")
    return len(normalized), h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default="db.sqlite3")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        sys.exit("ERROR: DATABASE_URL must be set to the migrated PostgreSQL database.")
    if not os.path.exists(args.sqlite):
        sys.exit(f"ERROR: SQLite file not found: {args.sqlite}")

    sq = sqlite3.connect(args.sqlite)
    pg = psycopg.connect(database_url)  # full URL -> honors sslmode etc.

    failures = 0

    print("Content verification (normalized, SHA-256; no values printed)")
    print(f"{'check':40} {'sqlite':>7} {'postgres':>9}  digest        status")
    print("-" * 78)
    for label, (sql, kinds) in CONTENT_CHECKS.items():
        try:
            sc = sq.execute(sql).fetchall()
            with pg.cursor() as cur:
                cur.execute(sql)
                pc = cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            print(f"{label:40} {'?':>7} {'?':>9}  ERROR         {type(exc).__name__}")
            failures += 1
            continue
        n_s, d_s = _digest(sc, kinds)
        n_p, d_p = _digest(pc, kinds)
        ok = d_s == d_p
        status = "MATCH" if ok else "MISMATCH"
        print(f"{label:40} {n_s:>7} {n_p:>9}  {d_p[:12]}  {status}")
        if not ok:
            failures += 1

    print("\nCount-only tables")
    print(f"{'table':40} {'sqlite':>7} {'postgres':>9}  status")
    print("-" * 70)
    for table in COUNT_ONLY:
        try:
            n_s = sq.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
        except sqlite3.OperationalError:
            n_s = None
        with pg.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (table,))
            n_p = None
            if cur.fetchone()[0] is not None:
                cur.execute(f'SELECT count(*) FROM "{table}"')
                n_p = cur.fetchone()[0]
        ok = n_s == n_p
        print(f"{table:40} {str(n_s):>7} {str(n_p):>9}  {'OK' if ok else 'MISMATCH'}")
        if not ok:
            failures += 1

    print("\nRelationship integrity on target (orphans must be 0)")
    print(f"{'relationship':44} {'orphans':>8}  status")
    print("-" * 64)
    for label, sql in RELATIONSHIP_CHECKS.items():
        try:
            with pg.cursor() as cur:
                cur.execute(sql)
                orphans = cur.fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            print(f"{label:44} {'?':>8}  ERROR {type(exc).__name__}")
            failures += 1
            continue
        ok = orphans == 0
        print(f"{label:44} {orphans:>8}  {'OK' if ok else 'ORPHANS'}")
        if not ok:
            failures += 1

    sq.close()
    pg.close()

    print("\n" + "-" * 78)
    if failures:
        print(f"FAILED: {failures} check(s) did not match. The restore is NOT verified.")
        sys.exit(1)
    print("VERIFIED: content, counts, and relationships match across both databases.")


if __name__ == "__main__":
    main()
