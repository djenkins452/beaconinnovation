#!/usr/bin/env python
"""Local PostgreSQL tests for the Phase 0 migration tooling.

Proves the safety properties we rely on:
  A. preflight PASSES on a freshly created + migrated target.
  B. preflight BLOCKS when --expect-db does not match the live connection.
  C. preflight BLOCKS when the target holds unexpected data (populated target).
  D. a full restore (export -> migrate -> flush -> loaddata) VERIFIES with verify_parity.
  E. verify_parity detects EQUAL-COUNT corruption (a changed value, same row count).

Runs entirely against a LOCAL PostgreSQL server (no hosted CI, no paid services).
It creates and drops its own throwaway database.

Run with the project's venv from the repo root, e.g.:
    DATABASE_URL unset; PATH includes pg bins
    ./venv/bin/python scripts/phase0_migrate/test_phase0_tooling.py \
        --pg-base postgres://USER@localhost:5432 --source-sqlite db.sqlite3
"""
import argparse
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
PREFLIGHT = os.path.join(REPO, "scripts/phase0_migrate/preflight_restore_check.py")
VERIFY = os.path.join(REPO, "scripts/phase0_migrate/verify_parity.py")
EXPORT = os.path.join(REPO, "scripts/phase0_migrate/export_legacy_sqlite.py")

results = []


def run(cmd, env=None, cwd=REPO):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True)


def check(name, condition, detail=""):
    results.append((name, condition))
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail and not condition else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg-base", required=True, help="postgres://USER[:PW]@HOST:PORT (no db)")
    ap.add_argument("--source-sqlite", default="db.sqlite3")
    args = ap.parse_args()

    db = f"beacon_tooltest_{os.getpid()}"
    base = args.pg_base.rstrip("/")
    url = f"{base}/{db}"
    src = os.path.join(REPO, args.source_sqlite)
    env = {"DATABASE_URL": url, "DJANGO_SECRET_KEY": "tooltest", "DJANGO_DEBUG": "False"}
    env.pop("PLATFORM_DATABASE_URL", None)

    fixture = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name

    try:
        subprocess.run(["dropdb", "--if-exists", db], check=False, capture_output=True)
        assert run(["createdb", db]).returncode == 0, "createdb failed"
        assert run([PY, "manage.py", "migrate", "--noinput"], env=env).returncode == 0, "migrate failed"

        # A. fresh migrated target -> PASS
        r = run([PY, PREFLIGHT, "--expect-db", db], env=env)
        check("A preflight PASSES on fresh migrated target", r.returncode == 0, r.stdout + r.stderr)

        # B. wrong --expect-db -> BLOCK
        r = run([PY, PREFLIGHT, "--expect-db", "not_the_target"], env=env)
        check("B preflight BLOCKS on wrong --expect-db", r.returncode == 1 and "BLOCKED" in r.stdout)

        # C. populated target -> BLOCK (add an unexpected user)
        run([PY, "manage.py", "shell", "-c",
             "from django.contrib.auth.models import User; User.objects.create_user('ghost','','x')"],
            env=env)
        r = run([PY, PREFLIGHT, "--expect-db", db], env=env)
        check("C preflight BLOCKS on populated target", r.returncode == 1 and "UNEXPECTED" in r.stdout)

        # D. full restore verifies
        assert run([PY, EXPORT, "--sqlite", src, "--out", fixture]).returncode == 0, "export failed"
        assert run([PY, "manage.py", "flush", "--no-input"], env=env).returncode == 0, "flush failed"
        assert run([PY, "manage.py", "loaddata", fixture], env=env).returncode == 0, "loaddata failed"
        r = run([PY, VERIFY, "--sqlite", src], env=env)
        check("D verify_parity VERIFIES a faithful restore", r.returncode == 0 and "VERIFIED" in r.stdout,
              r.stdout + r.stderr)

        # E. equal-count corruption detected
        subprocess.run(
            ["psql", url, "-c",
             "UPDATE finance_category SET name='__corrupted__' "
             "WHERE id=(SELECT id FROM finance_category ORDER BY name LIMIT 1)"],
            capture_output=True, text=True,
        )
        r = run([PY, VERIFY, "--sqlite", src], env=env)
        check("E verify_parity DETECTS equal-count corruption", r.returncode == 1 and "FAILED" in r.stdout,
              r.stdout[-400:])
    finally:
        subprocess.run(["dropdb", "--force", "--if-exists", db], check=False, capture_output=True)
        try:
            os.unlink(fixture)
        except OSError:
            pass

    passed = sum(1 for _, c in results if c)
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
