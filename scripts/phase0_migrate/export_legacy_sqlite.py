#!/usr/bin/env python
"""One-time exporter: read a legacy SQLite database and emit a Django fixture
(JSON) that can be loaded into PostgreSQL with `manage.py loaddata`.

This is a MIGRATION TOOL, not part of Beacon's runtime. It is intentionally
independent of ``beaconinnovation.settings`` (which now requires PostgreSQL and
has no SQLite configuration). It stands up a throwaway Django configuration that
points ONLY at the given SQLite file, long enough to serialize the data.

It exports only the apps that live in Beacon's ``default`` database. It never
touches the aegis ``platform`` database.

Usage (from the repo root, with the project's venv active):

    python scripts/phase0_migrate/export_legacy_sqlite.py \
        --sqlite db.sqlite3 \
        --out backups/phase0/legacy_default_fixture.json

Then, with PostgreSQL configured and migrated:

    python manage.py loaddata backups/phase0/legacy_default_fixture.json
    python scripts/phase0_migrate/verify_parity.py --sqlite db.sqlite3
"""
import argparse
import os
import sys

# Ensure the repo root is importable so the Beacon apps resolve regardless of cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django
from django.conf import settings

# Apps whose data lives in Beacon's default DB and is worth preserving.
# (contenttypes / auth.permission / sessions / admin.logentry are recreated by
# migrations or are disposable, so they are excluded from the export below.)
DEFAULT_DB_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "admin_console",
    "finance",
    "products",
    "wlj",
]

EXPORT_TARGETS = ["auth.User", "auth.Group", "admin_console", "finance", "products", "wlj"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default="db.sqlite3", help="Path to the legacy SQLite file")
    parser.add_argument(
        "--out",
        default="backups/phase0/legacy_default_fixture.json",
        help="Output fixture path",
    )
    args = parser.parse_args()

    if not os.path.exists(args.sqlite):
        sys.exit(f"ERROR: SQLite file not found: {args.sqlite}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    settings.configure(
        DEBUG=False,
        INSTALLED_APPS=DEFAULT_DB_APPS,
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": args.sqlite,
            }
        },
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        USE_TZ=True,
        TIME_ZONE="UTC",
    )
    django.setup()

    from django.core.management import call_command

    with open(args.out, "w") as fh:
        call_command(
            "dumpdata",
            *EXPORT_TARGETS,
            natural_primary=True,
            natural_foreign=True,
            indent=2,
            stdout=fh,
        )

    # Report what was captured.
    import json

    with open(args.out) as fh:
        data = json.load(fh)
    from collections import Counter

    counts = Counter(o["model"] for o in data)
    print(f"Exported {len(data)} objects from {args.sqlite} -> {args.out}")
    for model, n in sorted(counts.items()):
        print(f"  {n:>6}  {model}")


if __name__ == "__main__":
    main()
