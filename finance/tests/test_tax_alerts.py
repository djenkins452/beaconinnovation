from decimal import Decimal
from datetime import date
from io import StringIO
from django.test import TestCase, override_settings
from django.core.management import call_command
from finance.models import Account, Category, Transaction, TaxAlert


class CalculateTaxAlertsCommandTest(TestCase):
    """Tests for the calculate_tax_alerts management command."""

    def setUp(self):
        self.account = Account.objects.create(
            name='Test Checking',
            account_type='checking',
            institution='Test Bank'
        )
        self.income_category, _ = Category.objects.get_or_create(
            name='Service Revenue',
            category_type='income'
        )
        self.expense_category, _ = Category.objects.get_or_create(
            name='Software',
            category_type='expense'
        )

    def test_calculate_quarter_with_profit_above_threshold(self):
        """Test alert is triggered when profit exceeds threshold."""
        # Create income transaction in Q1 2026
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('5000.00'),
            transaction_date=date(2026, 2, 15),
            description='Client payment'
        )

        # Create expense transaction in Q1 2026
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('500.00'),
            transaction_date=date(2026, 2, 20),
            description='Software subscription'
        )

        # Run the command for Q1 2026
        out = StringIO()
        call_command('calculate_tax_alerts', '--quarter=1', '--year=2026', stdout=out)

        # Net profit should be 5000 - 500 = 4500, which exceeds 1000 threshold
        alert = TaxAlert.objects.get(quarter=1, year=2026)
        self.assertEqual(alert.actual_net_profit, Decimal('4500.00'))
        self.assertTrue(alert.alert_triggered)
        self.assertIsNotNone(alert.alert_date)
        self.assertIn('ALERT', out.getvalue())

    def test_calculate_quarter_with_profit_below_threshold(self):
        """Test alert is not triggered when profit is below threshold."""
        # Create small income transaction
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('800.00'),
            transaction_date=date(2026, 2, 15),
            description='Small payment'
        )

        # Run the command for Q1 2026
        out = StringIO()
        call_command('calculate_tax_alerts', '--quarter=1', '--year=2026', stdout=out)

        # Net profit should be 800, which is below 1000 threshold
        alert = TaxAlert.objects.get(quarter=1, year=2026)
        self.assertEqual(alert.actual_net_profit, Decimal('800.00'))
        self.assertFalse(alert.alert_triggered)
        self.assertIsNone(alert.alert_date)
        self.assertIn('below threshold', out.getvalue())

    def test_calculate_with_custom_threshold(self):
        """Test using a custom threshold amount."""
        # Create income that would trigger at $500 but not $1000
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('750.00'),
            transaction_date=date(2026, 2, 15),
            description='Payment'
        )

        # Run with custom threshold of $500
        out = StringIO()
        call_command(
            'calculate_tax_alerts',
            '--quarter=1', '--year=2026',
            '--threshold=500',
            stdout=out
        )

        alert = TaxAlert.objects.get(quarter=1, year=2026)
        self.assertTrue(alert.alert_triggered)
        self.assertEqual(alert.threshold_amount, Decimal('500'))

    def test_calculate_current_quarter(self):
        """Test calculating current quarter when no args provided."""
        today = date.today()
        current_quarter = (today.month - 1) // 3 + 1

        # Create income in current quarter
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('100.00'),
            transaction_date=today,
            description='Current quarter payment'
        )

        # Run without specifying quarter/year
        call_command('calculate_tax_alerts', stdout=StringIO())

        # Verify alert was created for current quarter
        self.assertTrue(
            TaxAlert.objects.filter(quarter=current_quarter, year=today.year).exists()
        )

    def test_update_existing_alert(self):
        """Test that existing alerts are updated, not duplicated."""
        # Create initial alert
        TaxAlert.objects.create(
            quarter=1,
            year=2026,
            threshold_amount=Decimal('1000.00'),
            actual_net_profit=Decimal('500.00'),
            alert_triggered=False
        )

        # Create income that will trigger alert
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('2000.00'),
            transaction_date=date(2026, 2, 15),
            description='Large payment'
        )

        # Run the command
        call_command('calculate_tax_alerts', '--quarter=1', '--year=2026', stdout=StringIO())

        # Should still only have one alert
        self.assertEqual(TaxAlert.objects.filter(quarter=1, year=2026).count(), 1)

        # Alert should now be triggered
        alert = TaxAlert.objects.get(quarter=1, year=2026)
        self.assertEqual(alert.actual_net_profit, Decimal('2000.00'))
        self.assertTrue(alert.alert_triggered)

    def test_no_transactions(self):
        """Test calculation with no transactions."""
        out = StringIO()
        call_command('calculate_tax_alerts', '--quarter=1', '--year=2026', stdout=out)

        alert = TaxAlert.objects.get(quarter=1, year=2026)
        self.assertEqual(alert.actual_net_profit, Decimal('0.00'))
        self.assertFalse(alert.alert_triggered)

    def test_negative_profit(self):
        """Test calculation when expenses exceed income (loss)."""
        # Create expense without income
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('500.00'),
            transaction_date=date(2026, 2, 15),
            description='Business expense'
        )

        call_command('calculate_tax_alerts', '--quarter=1', '--year=2026', stdout=StringIO())

        alert = TaxAlert.objects.get(quarter=1, year=2026)
        self.assertEqual(alert.actual_net_profit, Decimal('-500.00'))
        self.assertFalse(alert.alert_triggered)

    def test_calculate_all_quarters(self):
        """Test --all flag calculates all quarters with transactions."""
        # Create transactions in multiple quarters
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('1500.00'),
            transaction_date=date(2026, 1, 15),  # Q1
            description='Q1 payment'
        )
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('2000.00'),
            transaction_date=date(2026, 4, 15),  # Q2
            description='Q2 payment'
        )

        # Run with --all flag
        call_command('calculate_tax_alerts', '--all', stdout=StringIO())

        # Should have alerts for both quarters
        self.assertTrue(TaxAlert.objects.filter(quarter=1, year=2026).exists())
        self.assertTrue(TaxAlert.objects.filter(quarter=2, year=2026).exists())

    def test_quarter_boundaries(self):
        """Test that transactions are correctly assigned to quarters."""
        # Create transaction at end of Q1 (March 31)
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('1000.00'),
            transaction_date=date(2026, 3, 31),
            description='End of Q1'
        )

        # Create transaction at start of Q2 (April 1)
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('2000.00'),
            transaction_date=date(2026, 4, 1),
            description='Start of Q2'
        )

        # Calculate Q1
        call_command('calculate_tax_alerts', '--quarter=1', '--year=2026', stdout=StringIO())
        q1_alert = TaxAlert.objects.get(quarter=1, year=2026)
        self.assertEqual(q1_alert.actual_net_profit, Decimal('1000.00'))

        # Calculate Q2
        call_command('calculate_tax_alerts', '--quarter=2', '--year=2026', stdout=StringIO())
        q2_alert = TaxAlert.objects.get(quarter=2, year=2026)
        self.assertEqual(q2_alert.actual_net_profit, Decimal('2000.00'))

    @override_settings(FINANCE_TAX_ALERT_THRESHOLD='500')
    def test_threshold_from_settings(self):
        """Test that threshold is read from Django settings."""
        Transaction.objects.create(
            account=self.account,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('750.00'),
            transaction_date=date(2026, 2, 15),
            description='Payment'
        )

        # Run without explicit threshold (should use settings value of 500)
        call_command('calculate_tax_alerts', '--quarter=1', '--year=2026', stdout=StringIO())

        alert = TaxAlert.objects.get(quarter=1, year=2026)
        # 750 > 500, so should be triggered
        self.assertTrue(alert.alert_triggered)
