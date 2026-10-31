#!/usr/bin/env python
"""Local PostgreSQL tests for the Phase 0 migration tooling.

Reproducible from a clean checkout: it generates a SYNTHETIC legacy SQLite database
(no dependency on db.sqlite3 or real data) containing representative users,
memberships, permissions, transactions, receipts, recurring transactions, and a
product membership, then exercises the tooling end to end.

Proves:
  A. preflight PASSES on a freshly created + migrated target.
  B. preflight BLOCKS when --expect-db does not match the live connection.
  C. preflight BLOCKS a populated target (unexpected user).
  D. preflight BLOCKS a MODIFIED seed account at the same row count.
  E. a faithful restore (with receipts + recurring, i.e. non-null UUID relations) VERIFIES.
  F. verify_parity DETECTS equal-count corruption of: a financial value, a receipt
     path, receipt ownership, a permission, and a relationship.

Everything runs against the LOCAL PostgreSQL server given by --pg-base (refused if
not localhost). It creates a uniquely named database via that server, never touches a
pre-existing database, and drops only the database it created. No hosted CI.

Usage (venv, from repo root):
    ./venv/bin/python scripts/phase0_migrate/test_phase0_tooling.py \
        --pg-base postgres://USER@localhost:5432
"""
import argparse
import os
import secrets
import subprocess
import sys
import tempfile
import urllib.parse

import psycopg

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
PRE = os.path.join(REPO, "scripts/phase0_migrate/preflight_restore_check.py")
VER = os.path.join(REPO, "scripts/phase0_migrate/verify_parity.py")
EXP = os.path.join(REPO, "scripts/phase0_migrate/export_legacy_sqlite.py")
MAKE = os.path.join(REPO, "scripts/phase0_migrate/make_synthetic_legacy_db.py")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "", None}

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail[:300]}" if detail and not ok else ""))


def run(cmd, env):
    return subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg-base", required=True, help="postgres://USER[:PW]@HOST:PORT (no database)")
    args = ap.parse_args()
    base = args.pg_base.rstrip("/")

    host = urllib.parse.urlsplit(base).hostname
    if host not in LOCAL_HOSTS:
        sys.exit(f"ERROR: refusing non-local PostgreSQL host '{host}'. This harness is local-only.")

    db = f"beacon_tooltest_{os.getpid()}_{secrets.token_hex(4)}"
    url = f"{base}/{db}"
    admin_url = f"{base}/postgres"

    # Clean, isolated subprocess env: only this test DB; no inherited platform/superuser config.
    # PLATFORM_DATABASE_URL and DJANGO_SUPERUSER_PASSWORD are set to EMPTY strings (not
    # merely unset) so python-dotenv's load_dotenv(override=False) in settings.py cannot
    # repopulate them from a local .env — an empty value is still "present".
    env = dict(os.environ)
    env.update({
        "DATABASE_URL": url,
        "DJANGO_SECRET_KEY": "tooltest",
        "DJANGO_DEBUG": "False",
        "PLATFORM_DATABASE_URL": "",
        "DJANGO_SUPERUSER_PASSWORD": "",
    })

    synthetic = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False).name
    os.unlink(synthetic)  # generator writes it fresh
    fixture = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name

    created = False
    try:
        # Build the synthetic legacy source.
        r = run([PY, MAKE, "--out", synthetic], env)
        assert r.returncode == 0, f"synthetic build failed: {r.stdout}{r.stderr}"

        # Create the test DB on the SUPPLIED server; never touch a pre-existing DB.
        with psycopg.connect(admin_url, autocommit=True) as ac, ac.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
            if cur.fetchone():
                sys.exit(f"ERROR: database {db} already exists; aborting to avoid touching it.")
            cur.execute(f'CREATE DATABASE "{db}"')
            created = True

        assert run([PY, "manage.py", "migrate", "--noinput"], env).returncode == 0, "migrate failed"

        # A/B/C/D — preflight
        r = run([PY, PRE, "--expect-db", db], env)
        check("A preflight PASSES on fresh migrated target", r.returncode == 0, r.stdout + r.stderr)
        r = run([PY, PRE, "--expect-db", "not_the_target"], env)
        check("B preflight BLOCKS on wrong --expect-db", r.returncode == 1 and "BLOCKED" in r.stdout)

        def q(sql, params=None):
            with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
                cur.execute(sql, params or ())
                return cur.fetchall() if cur.description else None

        q("INSERT INTO auth_user (password,is_superuser,username,first_name,last_name,email,"
          "is_staff,is_active,date_joined) VALUES ('x',false,'ghost','','','',false,true,now())")
        r = run([PY, PRE, "--expect-db", db], env)
        check("C preflight BLOCKS a populated target", r.returncode == 1 and "UNEXPECTED DATA" in r.stdout)
        q("DELETE FROM auth_user WHERE username='ghost'")

        bal = q("SELECT opening_balance FROM finance_account WHERE name='Personal Amex'")[0][0]
        q("UPDATE finance_account SET opening_balance=opening_balance+1 WHERE name='Personal Amex'")
        r = run([PY, PRE, "--expect-db", db], env)
        check("D preflight BLOCKS a MODIFIED seed account (same count)",
              r.returncode == 1 and "account" in r.stdout.lower(), r.stdout)
        q("UPDATE finance_account SET opening_balance=%s WHERE name='Personal Amex'", (bal,))

        # E — faithful restore
        assert run([PY, EXP, "--sqlite", synthetic, "--out", fixture], env).returncode == 0, "export failed"
        assert run([PY, "manage.py", "flush", "--no-input"], env).returncode == 0, "flush failed"
        assert run([PY, "manage.py", "loaddata", fixture], env).returncode == 0, "loaddata failed"
        r = run([PY, VER, "--sqlite", synthetic], env)
        check("E verify_parity VERIFIES a faithful restore (receipts + recurring UUIDs)",
              r.returncode == 0 and "VERIFIED" in r.stdout, r.stdout + r.stderr)

        # F — equal-count corruption battery; each must FAIL, then revert
        def corrupt_case(name, mutate_sql, mutate_params, revert_sql, revert_params):
            q(mutate_sql, mutate_params)
            rr = run([PY, VER, "--sqlite", synthetic], env)
            check(f"F {name}", rr.returncode == 1 and "FAILED" in rr.stdout, rr.stdout[-300:])
            q(revert_sql, revert_params)

        amt = q("SELECT amount FROM finance_transaction WHERE reference_number='INV-1001'")[0][0]
        corrupt_case("detects changed financial value",
                     "UPDATE finance_transaction SET amount=amount+5 WHERE reference_number='INV-1001'", (),
                     "UPDATE finance_transaction SET amount=%s WHERE reference_number='INV-1001'", (amt,))

        fp = q("SELECT file FROM finance_receipt LIMIT 1")[0][0]
        corrupt_case("detects changed receipt path",
                     "UPDATE finance_receipt SET file='receipts/2026/01/HACKED.pdf'", (),
                     "UPDATE finance_receipt SET file=%s", (fp,))

        owner = q("SELECT uploaded_by_id FROM finance_receipt LIMIT 1")[0][0]
        other = q("SELECT id FROM auth_user WHERE id<>%s LIMIT 1", (owner,))[0][0]
        corrupt_case("detects changed receipt ownership",
                     "UPDATE finance_receipt SET uploaded_by_id=%s", (other,),
                     "UPDATE finance_receipt SET uploaded_by_id=%s", (owner,))

        gp = q("SELECT group_id, permission_id FROM auth_group_permissions LIMIT 1")[0]
        corrupt_case("detects removed permission",
                     "DELETE FROM auth_group_permissions WHERE group_id=%s AND permission_id=%s", (gp[0], gp[1]),
                     "INSERT INTO auth_group_permissions (group_id,permission_id) VALUES (%s,%s)", (gp[0], gp[1]))

        acct = q("SELECT account_id FROM finance_transaction WHERE reference_number='INV-1001'")[0][0]
        alt = q("SELECT id FROM finance_account WHERE id<>%s LIMIT 1", (acct,))[0][0]
        corrupt_case("detects changed relationship (transaction.account)",
                     "UPDATE finance_transaction SET account_id=%s WHERE reference_number='INV-1001'", (alt,),
                     "UPDATE finance_transaction SET account_id=%s WHERE reference_number='INV-1001'", (acct,))

        r = run([PY, VER, "--sqlite", synthetic], env)
        check("F final re-verify is clean after reverts", r.returncode == 0 and "VERIFIED" in r.stdout)
    finally:
        if created:
            with psycopg.connect(admin_url, autocommit=True) as ac, ac.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        for f in (synthetic, fixture):
            try:
                os.unlink(f)
            except OSError:
                pass

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) and results else 1)


if __name__ == "__main__":
    main()
