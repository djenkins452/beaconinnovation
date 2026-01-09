from decimal import Decimal
from datetime import date, timedelta
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from finance.models import Account, Category, Transaction, RecurringTransaction


class GenerateRecurringCommandTest(TestCase):
    """Tests for the generate_recurring management command."""

    def setUp(self):
        self.account = Account.objects.create(
            name='Test Checking',
            account_type='checking',
            institution='Test Bank'
        )
        self.category, _ = Category.objects.get_or_create(
            name='Subscriptions',
            category_type='expense'
        )

    def test_generate_monthly_recurring(self):
        """Test generating a monthly recurring transaction."""
        # Create a recurring template due today
        today = date.today()
        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('9.99'),
            description='Monthly Subscription',
            vendor='Netflix',
            frequency='monthly',
            day_of_month=today.day,
            start_date=today - timedelta(days=30),
            next_due=today
        )

        # Run the command
        out = StringIO()
        call_command('generate_recurring', stdout=out)

        # Verify transaction was created
        self.assertEqual(Transaction.objects.count(), 1)
        transaction = Transaction.objects.first()
        self.assertEqual(transaction.vendor, 'Netflix')
        self.assertEqual(transaction.amount, Decimal('9.99'))
        self.assertTrue(transaction.is_recurring)

    def test_generate_multiple_due_periods(self):
        """Test generating transactions for multiple missed periods."""
        # Create a recurring template that was due 2 months ago
        today = date.today()
        two_months_ago = today - timedelta(days=60)

        template = RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('10.00'),
            description='Monthly Service',
            vendor='Service Co',
            frequency='monthly',
            day_of_month=two_months_ago.day,
            start_date=two_months_ago - timedelta(days=30),
            next_due=two_months_ago
        )

        # Run the command
        out = StringIO()
        call_command('generate_recurring', stdout=out)

        # Should have created at least 2 transactions (for the 2+ months)
        self.assertGreaterEqual(Transaction.objects.count(), 2)

    def test_dry_run_no_creation(self):
        """Test that dry run doesn't create transactions."""
        today = date.today()
        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('5.00'),
            description='Test Subscription',
            vendor='Test Vendor',
            frequency='monthly',
            day_of_month=today.day,
            start_date=today - timedelta(days=30),
            next_due=today
        )

        # Run with dry-run flag
        out = StringIO()
        call_command('generate_recurring', '--dry-run', stdout=out)

        # Verify no transactions were created
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertIn('DRY RUN', out.getvalue())

    def test_skip_inactive_templates(self):
        """Test that inactive templates are skipped."""
        today = date.today()
        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('5.00'),
            description='Inactive Subscription',
            vendor='Inactive Vendor',
            frequency='monthly',
            day_of_month=today.day,
            start_date=today - timedelta(days=30),
            next_due=today,
            is_active=False
        )

        # Run the command
        out = StringIO()
        call_command('generate_recurring', stdout=out)

        # Verify no transactions were created
        self.assertEqual(Transaction.objects.count(), 0)

    def test_skip_future_due_dates(self):
        """Test that templates with future due dates are not processed."""
        tomorrow = date.today() + timedelta(days=1)
        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('5.00'),
            description='Future Subscription',
            vendor='Future Vendor',
            frequency='monthly',
            day_of_month=tomorrow.day,
            start_date=date.today(),
            next_due=tomorrow
        )

        # Run the command
        out = StringIO()
        call_command('generate_recurring', stdout=out)

        # Verify no transactions were created
        self.assertEqual(Transaction.objects.count(), 0)

    def test_respect_end_date(self):
        """Test that end_date is respected."""
        today = date.today()
        yesterday = today - timedelta(days=1)

        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('5.00'),
            description='Ended Subscription',
            vendor='Ended Vendor',
            frequency='monthly',
            day_of_month=today.day,
            start_date=today - timedelta(days=60),
            next_due=today,
            end_date=yesterday  # Ended yesterday
        )

        # Run the command
        out = StringIO()
        call_command('generate_recurring', stdout=out)

        # Verify no transactions were created (end date passed)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_updates_next_due_date(self):
        """Test that next_due is updated after generation."""
        today = date.today()
        template = RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('9.99'),
            description='Monthly Sub',
            vendor='Test',
            frequency='monthly',
            day_of_month=today.day,
            start_date=today - timedelta(days=30),
            next_due=today
        )

        # Run the command
        call_command('generate_recurring', stdout=StringIO())

        # Refresh and check next_due was updated
        template.refresh_from_db()
        self.assertGreater(template.next_due, today)
        self.assertEqual(template.last_generated, today)

    def test_quarterly_frequency(self):
        """Test quarterly recurring transactions."""
        today = date.today()
        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('100.00'),
            description='Quarterly Service',
            vendor='Quarterly Co',
            frequency='quarterly',
            day_of_month=today.day,
            start_date=today - timedelta(days=90),
            next_due=today
        )

        # Run the command
        call_command('generate_recurring', stdout=StringIO())

        # Verify transaction was created
        self.assertEqual(Transaction.objects.count(), 1)
        transaction = Transaction.objects.first()
        self.assertEqual(transaction.amount, Decimal('100.00'))

    def test_annual_frequency(self):
        """Test annual recurring transactions."""
        today = date.today()
        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('500.00'),
            description='Annual Service',
            vendor='Annual Co',
            frequency='annually',
            day_of_month=today.day,
            start_date=today - timedelta(days=365),
            next_due=today
        )

        # Run the command
        call_command('generate_recurring', stdout=StringIO())

        # Verify transaction was created
        self.assertEqual(Transaction.objects.count(), 1)
        transaction = Transaction.objects.first()
        self.assertEqual(transaction.amount, Decimal('500.00'))

    def test_custom_date_parameter(self):
        """Test processing with a custom date."""
        # Create a template due on a specific future date
        future_date = date(2026, 6, 15)
        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('25.00'),
            description='Future Test',
            vendor='Future Test Co',
            frequency='monthly',
            day_of_month=15,
            start_date=date(2026, 5, 1),
            next_due=future_date
        )

        # Run with custom date
        call_command('generate_recurring', '--date=2026-06-15', stdout=StringIO())

        # Verify transaction was created
        self.assertEqual(Transaction.objects.count(), 1)
