"""
Seed default accounts for Beacon Innovations.

Creates:
- Amex Business Checking ($1,000 opening balance)
- Amex Blue Business Cash ($0 opening balance)
- Personal Amex ($0 opening balance, is_personal=True)
"""
from datetime import date
from decimal import Decimal

from django.db import migrations


def create_default_accounts(apps, schema_editor):
    """Create the default accounts."""
    Account = apps.get_model('finance', 'Account')

    accounts = [
        {
            'name': 'Amex Business Checking',
            'account_type': 'checking',
            'institution': 'American Express',
            'last_four': '',
            'is_personal': False,
            'is_active': True,
            'opening_balance': Decimal('1000.00'),
            'opening_balance_date': date.today(),
            'notes': 'Primary operating account for revenue deposits and payments.',
        },
        {
            'name': 'Amex Blue Business Cash',
            'account_type': 'credit_card',
            'institution': 'American Express',
            'last_four': '',
            'is_personal': False,
            'is_active': True,
            'opening_balance': Decimal('0.00'),
            'opening_balance_date': date.today(),
            'notes': 'Primary expense card. Earns 2% cash back on eligible purchases.',
        },
        {
            'name': 'Personal Amex',
            'account_type': 'credit_card',
            'institution': 'American Express',
            'last_four': '',
            'is_personal': True,
            'is_active': True,
            'opening_balance': Decimal('0.00'),
            'opening_balance_date': date.today(),
            'notes': 'Backup personal card used for business expenses when necessary.',
        },
    ]

    for account_data in accounts:
        Account.objects.get_or_create(
            name=account_data['name'],
            defaults=account_data
        )

    print(f"Created {len(accounts)} default accounts.")


def remove_default_accounts(apps, schema_editor):
    """Remove the default accounts."""
    Account = apps.get_model('finance', 'Account')
    Account.objects.filter(name__in=[
        'Amex Business Checking',
        'Amex Blue Business Cash',
        'Personal Amex',
    ]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0002_seed_default_categories'),
    ]

    operations = [
        migrations.RunPython(create_default_accounts, remove_default_accounts),
    ]
