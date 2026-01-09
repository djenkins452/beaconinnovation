"""
Tests for CSV export functionality (Phase 14).
"""
import csv
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from finance.models import Account, Category, Transaction


class ExportTestCase(TestCase):
    """Base test case for export tests."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        # Create test account
        self.account = Account.objects.create(
            name='Test Checking',
            account_type='checking',
            institution='Test Bank'
        )

        # Create test categories (use get_or_create for uniqueness constraint compatibility)
        self.income_category, _ = Category.objects.get_or_create(
            name='Consulting',
            category_type='income'
        )
        self.expense_category, _ = Category.objects.get_or_create(
            name='Office Supplies',
            category_type='expense'
        )
        self.expense_category2, _ = Category.objects.get_or_create(
            name='Software',
            category_type='expense'
        )

        # Create test transactions
        today = date.today()
        self.income_transaction = Transaction.objects.create(
            transaction_date=today,
            transaction_type='income',
            account=self.account,
            category=self.income_category,
            vendor='Client A',
            description='Consulting work',
            amount=Decimal('5000.00')
        )
        self.expense_transaction1 = Transaction.objects.create(
            transaction_date=today,
            transaction_type='expense',
            account=self.account,
            category=self.expense_category,
            vendor='Office Depot',
            description='Paper and pens',
            amount=Decimal('150.00')
        )
        self.expense_transaction2 = Transaction.objects.create(
            transaction_date=today,
            transaction_type='expense',
            account=self.account,
            category=self.expense_category2,
            vendor='Adobe',
            description='Creative Cloud subscription',
            amount=Decimal('55.00')
        )


class TransactionExportTests(ExportTestCase):
    """Tests for transaction export."""

    def test_export_transactions_requires_login(self):
        """Export transactions requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:export_transactions'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_export_transactions_returns_csv(self):
        """Export transactions returns a CSV file."""
        response = self.client.get(reverse('finance:export_transactions'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('.csv', response['Content-Disposition'])

    def test_export_transactions_includes_header_row(self):
        """CSV includes proper header row."""
        response = self.client.get(reverse('finance:export_transactions'))
        content = response.content.decode('utf-8')
        reader = csv.reader(StringIO(content))
        header = next(reader)

        self.assertIn('Date', header)
        self.assertIn('Type', header)
        self.assertIn('Account', header)
        self.assertIn('Category', header)
        self.assertIn('Vendor', header)
        self.assertIn('Amount', header)

    def test_export_transactions_includes_data(self):
        """CSV includes transaction data."""
        response = self.client.get(reverse('finance:export_transactions'))
        content = response.content.decode('utf-8')
        reader = csv.reader(StringIO(content))
        rows = list(reader)

        # Header + 3 transactions
        self.assertEqual(len(rows), 4)

        # Check that our transactions are in the data
        vendors = [row[4] for row in rows[1:]]  # Vendor is column 5 (index 4)
        self.assertIn('Client A', vendors)
        self.assertIn('Office Depot', vendors)
        self.assertIn('Adobe', vendors)

    def test_export_transactions_filter_by_type(self):
        """Export can filter by transaction type."""
        response = self.client.get(reverse('finance:export_transactions') + '?transaction_type=expense')
        content = response.content.decode('utf-8')
        reader = csv.reader(StringIO(content))
        rows = list(reader)

        # Header row + at least 2 expense transactions (we created 2)
        self.assertGreaterEqual(len(rows), 3)

        # All data rows should be expenses
        types = [row[1] for row in rows[1:]]
        for t in types:
            self.assertEqual(t, 'Expense')

    def test_export_transactions_filter_by_account(self):
        """Export can filter by account."""
        other_account = Account.objects.create(
            name='Other Account',
            account_type='checking',
            institution='Other Bank'
        )
        Transaction.objects.create(
            transaction_date=date.today(),
            transaction_type='expense',
            account=other_account,
            category=self.expense_category,
            vendor='Other Vendor',
            description='Other purchase',
            amount=Decimal('25.00')
        )

        response = self.client.get(
            reverse('finance:export_transactions') + f'?account={self.account.id}'
        )
        content = response.content.decode('utf-8')
        reader = csv.reader(StringIO(content))
        rows = list(reader)

        # Should only include original 3 transactions
        self.assertEqual(len(rows), 4)

    def test_export_transactions_filter_by_date_range(self):
        """Export can filter by date range."""
        # Create old transaction
        old_date = date.today() - timedelta(days=60)
        Transaction.objects.create(
            transaction_date=old_date,
            transaction_type='expense',
            account=self.account,
            category=self.expense_category,
            vendor='Old Vendor',
            description='Old purchase',
            amount=Decimal('100.00')
        )

        # Filter to current month only
        today = date.today()
        start = today.replace(day=1)

        response = self.client.get(
            reverse('finance:export_transactions') + f'?date_from={start.isoformat()}'
        )
        content = response.content.decode('utf-8')
        reader = csv.reader(StringIO(content))
        rows = list(reader)

        # Should only include original 3 transactions (not the old one)
        self.assertEqual(len(rows), 4)


class SpendingReportExportTests(ExportTestCase):
    """Tests for spending report export."""

    def test_export_spending_requires_login(self):
        """Export spending report requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:export_spending_report'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_export_spending_returns_csv(self):
        """Export spending returns a CSV file."""
        response = self.client.get(reverse('finance:export_spending_report'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('spending_report', response['Content-Disposition'])

    def test_export_spending_includes_categories(self):
        """CSV includes spending by category."""
        response = self.client.get(reverse('finance:export_spending_report'))
        content = response.content.decode('utf-8')

        self.assertIn('Office Supplies', content)
        self.assertIn('Software', content)
        self.assertIn('150', content)
        self.assertIn('55', content)

    def test_export_spending_includes_total(self):
        """CSV includes total spending."""
        response = self.client.get(reverse('finance:export_spending_report'))
        content = response.content.decode('utf-8')

        self.assertIn('Total', content)
        self.assertIn('205', content)  # 150 + 55

    def test_export_spending_includes_percentages(self):
        """CSV includes percentages."""
        response = self.client.get(reverse('finance:export_spending_report'))
        content = response.content.decode('utf-8')

        self.assertIn('%', content)

    def test_export_spending_with_period(self):
        """Export can use different periods."""
        response = self.client.get(reverse('finance:export_spending_report') + '?period=ytd')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')

    def test_export_spending_with_custom_dates(self):
        """Export can use custom date range."""
        today = date.today()
        start = today.replace(day=1)

        response = self.client.get(
            reverse('finance:export_spending_report') +
            f'?period=custom&start_date={start.isoformat()}&end_date={today.isoformat()}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')


class IncomeStatementExportTests(ExportTestCase):
    """Tests for income statement export."""

    def test_export_income_statement_requires_login(self):
        """Export income statement requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:export_income_statement'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_export_income_statement_returns_csv(self):
        """Export income statement returns a CSV file."""
        response = self.client.get(reverse('finance:export_income_statement'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('income_statement', response['Content-Disposition'])

    def test_export_income_statement_includes_income_section(self):
        """CSV includes income section."""
        response = self.client.get(reverse('finance:export_income_statement'))
        content = response.content.decode('utf-8')

        self.assertIn('INCOME', content)
        self.assertIn('Consulting', content)
        self.assertIn('5000', content)

    def test_export_income_statement_includes_expense_section(self):
        """CSV includes expense section."""
        response = self.client.get(reverse('finance:export_income_statement'))
        content = response.content.decode('utf-8')

        self.assertIn('EXPENSES', content)
        self.assertIn('Office Supplies', content)
        self.assertIn('Software', content)

    def test_export_income_statement_includes_totals(self):
        """CSV includes totals and net profit."""
        response = self.client.get(reverse('finance:export_income_statement'))
        content = response.content.decode('utf-8')

        self.assertIn('Total Income', content)
        self.assertIn('Total Expenses', content)
        self.assertIn('NET PROFIT', content)

    def test_export_income_statement_includes_owners_draw(self):
        """CSV includes owner's draws."""
        # Create owner's draw
        draw_category, _ = Category.objects.get_or_create(
            name="Owner's Draw",
            category_type='owners_draw'
        )
        Transaction.objects.create(
            transaction_date=date.today(),
            transaction_type='owners_draw',
            account=self.account,
            category=draw_category,
            vendor='Owner',
            description='Monthly draw',
            amount=Decimal('1000.00')
        )

        response = self.client.get(reverse('finance:export_income_statement'))
        content = response.content.decode('utf-8')

        self.assertIn("Owner's Draws", content)
        self.assertIn('RETAINED EARNINGS', content)

    def test_export_income_statement_with_period(self):
        """Export can use different periods."""
        response = self.client.get(reverse('finance:export_income_statement') + '?period=qtd')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')

    def test_export_income_statement_with_custom_dates(self):
        """Export can use custom date range."""
        today = date.today()
        start = today.replace(day=1)

        response = self.client.get(
            reverse('finance:export_income_statement') +
            f'?period=custom&start_date={start.isoformat()}&end_date={today.isoformat()}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
