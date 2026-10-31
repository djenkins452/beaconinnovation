#!/usr/bin/env python
"""Build a SYNTHETIC legacy SQLite database with representative data, for testing the
Phase 0 migration tooling reproducibly from a clean checkout (no dependency on the
untracked db.sqlite3 or any real user data).

It stands up a throwaway Django config pointed only at the given SQLite file, runs
`migrate` (real schema + seeds), and creates representative records across the
relationships the tooling must preserve:
  * users (regular + superuser), a group with membership, a group permission, and a
    direct user permission;
  * finance transactions (income + expense) with owners and references;
  * a recurring transaction (non-null account/category UUID relationships);
  * a receipt (non-null transaction UUID relationship, file path, uploader/ownership);
  * a product with an authorized user (membership).

Usage:
    python scripts/phase0_migrate/make_synthetic_legacy_db.py --out /tmp/legacy.sqlite3
"""
import argparse
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import django
from django.conf import settings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Path to the SQLite file to create")
    args = ap.parse_args()

    if os.path.exists(args.out):
        os.unlink(args.out)

    settings.configure(
        DEBUG=False,
        INSTALLED_APPS=[
            "django.contrib.contenttypes",
            "django.contrib.auth",
            "django.contrib.admin",
            "django.contrib.sessions",
            "admin_console",
            "finance",
            "products",
            "wlj",
        ],
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": args.out}},
        DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        USE_TZ=True,
        TIME_ZONE="UTC",
        PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"],
    )
    django.setup()

    from django.core.management import call_command
    call_command("migrate", verbosity=0, skip_checks=True)

    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group, Permission
    from finance.models import Account, Category, Transaction, Receipt, RecurringTransaction
    from products.models import Product

    User = get_user_model()

    alice = User.objects.create_user("alice", "alice@example.com", "alice-pass-123", is_staff=True)
    bob = User.objects.create_user("bob", "bob@example.com", "bob-pass-123")
    User.objects.create_superuser("root", "root@example.com", "root-pass-123")

    editors = Group.objects.create(name="editors")
    alice.groups.add(editors)
    editors.permissions.add(Permission.objects.get(codename="add_transaction",
                                                   content_type__app_label="finance"))
    bob.user_permissions.add(Permission.objects.get(codename="view_account",
                                                    content_type__app_label="finance"))

    checking = Account.objects.get(name="Amex Business Checking")
    equipment = Category.objects.get(name="Equipment", category_type="expense")
    revenue = Category.objects.get(name="Service Revenue", category_type="income")

    expense = Transaction.objects.create(
        account=checking, transaction_type="expense", category=equipment,
        amount=Decimal("249.99"), transaction_date=date(2026, 1, 15),
        description="3D printer part", vendor="Bambu Lab", reference_number="INV-1001",
        created_by=alice,
    )
    Transaction.objects.create(
        account=checking, transaction_type="income", category=revenue,
        amount=Decimal("500.00"), transaction_date=date(2026, 1, 20),
        description="Service income", vendor="Client A", created_by=bob,
    )
    RecurringTransaction.objects.create(
        account=checking, category=equipment, amount=Decimal("12.00"),
        description="Monthly subscription", vendor="SaaS", frequency="monthly",
        day_of_month=1, start_date=date(2026, 1, 1), next_due=date(2026, 2, 1),
        created_by=alice,
    )
    Receipt.objects.create(
        transaction=expense, file="receipts/2026/01/part.pdf",
        original_filename="part.pdf", file_type="pdf", file_size=2048,
        ocr_amount=Decimal("249.99"), uploaded_by=bob,
    )

    product = Product.objects.create(
        name="Widget", slug="widget", description="A widget", current_version="1.0",
        current_build="100", download_enabled=True,
    )
    product.authorized_users.add(alice)

    print(f"Synthetic legacy SQLite written: {args.out}")


if __name__ == "__main__":
    main()
