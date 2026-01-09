"""
Tests for dashboard and reporting functionality (Phase 10).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from finance.models import Account, Category, Transaction, TaxAlert


class DashboardViewTests(TestCase):
    """Tests for the main dashboard view."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        # Get existing seeded accounts
        self.checking = Account.objects.get(name='Amex Business Checking')
        self.credit_card = Account.objects.get(name='Amex Blue Business Cash')

        # Get categories
        self.income_category = Category.objects.get(
            name='Service Revenue',
            category_type='income'
        )
        self.expense_category = Category.objects.get(
            name='Office Supplies',
            category_type='expense'
        )

    def test_dashboard_requires_login(self):
        """Test that dashboard requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_renders(self):
        """Test that dashboard renders correctly."""
        response = self.client.get(reverse('finance:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/dashboard.html')

    def test_dashboard_shows_account_balances(self):
        """Test that dashboard shows account balance totals."""
        response = self.client.get(reverse('finance:dashboard'))
        self.assertIn('total_checking', response.context)
        self.assertIn('total_credit', response.context)
        self.assertIn('net_position', response.context)

    def test_dashboard_shows_mtd_summary(self):
        """Test that dashboard shows month-to-date summary."""
        # Create a transaction for this month
        Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('500.00'),
            transaction_date=date.today(),
            description='Test income',
        )

        response = self.client.get(reverse('finance:dashboard'))
        self.assertIn('mtd_summary', response.context)
        self.assertEqual(response.context['mtd_summary']['income'], Decimal('500.00'))

    def test_dashboard_shows_qtd_summary(self):
        """Test that dashboard shows quarter-to-date summary."""
        response = self.client.get(reverse('finance:dashboard'))
        self.assertIn('qtd_summary', response.context)
        self.assertIn('current_quarter', response.context)

    def test_dashboard_shows_recent_transactions(self):
        """Test that dashboard shows recent transactions."""
        Transaction.objects.create(
            account=self.checking,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('100.00'),
            transaction_date=date.today(),
            description='Recent expense',
        )

        response = self.client.get(reverse('finance:dashboard'))
        self.assertIn('recent_transactions', response.context)
        self.assertContains(response, 'Recent expense')

    def test_dashboard_shows_tax_alerts(self):
        """Test that dashboard shows active tax alerts."""
        TaxAlert.objects.create(
            quarter=1,
            year=date.today().year,
            threshold_amount=Decimal('1000.00'),
            actual_net_profit=Decimal('1500.00'),
            alert_triggered=True,
            acknowledged=False,
        )

        response = self.client.get(reverse('finance:dashboard'))
        self.assertIn('tax_alerts', response.context)
        self.assertEqual(len(response.context['tax_alerts']), 1)

    def test_dashboard_shows_spending_by_category(self):
        """Test that dashboard shows MTD spending by category."""
        Transaction.objects.create(
            account=self.credit_card,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('75.00'),
            transaction_date=date.today(),
            description='Category expense',
        )

        response = self.client.get(reverse('finance:dashboard'))
        self.assertIn('mtd_spending', response.context)
        self.assertIn('top_spending', response.context)

    def test_dashboard_calculates_net_position(self):
        """Test net position calculation."""
        # Add income to checking
        Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('2000.00'),
            transaction_date=date.today(),
            description='Income',
        )
        # Add expense to credit card
        Transaction.objects.create(
            account=self.credit_card,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('500.00'),
            transaction_date=date.today(),
            description='Expense',
        )

        response = self.client.get(reverse('finance:dashboard'))
        # Checking: 1000 + 2000 = 3000
        # Credit: 0 + 500 = 500 owed
        # Net: 3000 - 500 = 2500
        self.assertEqual(response.context['total_checking'], Decimal('3000.00'))
        self.assertEqual(response.context['total_credit'], Decimal('500.00'))
        self.assertEqual(response.context['net_position'], Decimal('2500.00'))


class SpendingReportTests(TestCase):
    """Tests for the spending report."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        self.account = Account.objects.get(name='Amex Blue Business Cash')
        self.category1 = Category.objects.get(name='Office Supplies')
        self.category2 = Category.objects.get(name='Software & Subscriptions')

    def test_spending_report_requires_login(self):
        """Test that spending report requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:spending_report'))
        self.assertEqual(response.status_code, 302)

    def test_spending_report_renders(self):
        """Test that spending report renders correctly."""
        response = self.client.get(reverse('finance:spending_report'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/reports/spending.html')

    def test_spending_report_default_period_mtd(self):
        """Test that default period is month-to-date."""
        response = self.client.get(reverse('finance:spending_report'))
        self.assertEqual(response.context['period'], 'mtd')

    def test_spending_report_custom_period(self):
        """Test spending report with custom period."""
        response = self.client.get(
            reverse('finance:spending_report') + '?period=qtd'
        )
        self.assertEqual(response.context['period'], 'qtd')

    def test_spending_report_custom_date_range(self):
        """Test spending report with custom date range."""
        start = (date.today() - timedelta(days=30)).isoformat()
        end = date.today().isoformat()
        response = self.client.get(
            reverse('finance:spending_report') + f'?start_date={start}&end_date={end}'
        )
        self.assertEqual(response.context['period'], 'custom')

    def test_spending_report_shows_categories(self):
        """Test that spending report shows spending by category."""
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.category1,
            amount=Decimal('100.00'),
            transaction_date=date.today(),
            description='Expense 1',
        )
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.category2,
            amount=Decimal('200.00'),
            transaction_date=date.today(),
            description='Expense 2',
        )

        response = self.client.get(reverse('finance:spending_report'))
        self.assertIn('spending', response.context)
        self.assertEqual(len(response.context['spending']), 2)
        self.assertEqual(response.context['total_spending'], Decimal('300.00'))

    def test_spending_report_calculates_percentages(self):
        """Test that spending report calculates percentages."""
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.category1,
            amount=Decimal('75.00'),
            transaction_date=date.today(),
            description='Expense 1',
        )
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.category2,
            amount=Decimal('25.00'),
            transaction_date=date.today(),
            description='Expense 2',
        )

        response = self.client.get(reverse('finance:spending_report'))
        spending = response.context['spending']
        # First should be category1 with 75% (75/100)
        self.assertEqual(spending[0]['total'], Decimal('75.00'))
        self.assertEqual(spending[0]['percentage'], Decimal('75'))


class IncomeStatementTests(TestCase):
    """Tests for the income statement (P&L) report."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        self.checking = Account.objects.get(name='Amex Business Checking')
        self.credit_card = Account.objects.get(name='Amex Blue Business Cash')
        self.income_category = Category.objects.get(name='Service Revenue')
        self.expense_category = Category.objects.get(name='Office Supplies')

    def test_income_statement_requires_login(self):
        """Test that income statement requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:income_statement'))
        self.assertEqual(response.status_code, 302)

    def test_income_statement_renders(self):
        """Test that income statement renders correctly."""
        response = self.client.get(reverse('finance:income_statement'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/reports/income_statement.html')

    def test_income_statement_shows_income(self):
        """Test that income statement shows income by category."""
        Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('1000.00'),
            transaction_date=date.today(),
            description='Revenue',
        )

        response = self.client.get(reverse('finance:income_statement'))
        self.assertIn('income_by_category', response.context)
        self.assertEqual(response.context['total_income'], Decimal('1000.00'))

    def test_income_statement_shows_expenses(self):
        """Test that income statement shows expenses by category."""
        Transaction.objects.create(
            account=self.credit_card,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('300.00'),
            transaction_date=date.today(),
            description='Expense',
        )

        response = self.client.get(reverse('finance:income_statement'))
        self.assertIn('expenses_by_category', response.context)
        self.assertEqual(response.context['total_expenses'], Decimal('300.00'))

    def test_income_statement_calculates_net_profit(self):
        """Test that income statement calculates net profit."""
        Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('1000.00'),
            transaction_date=date.today(),
            description='Revenue',
        )
        Transaction.objects.create(
            account=self.credit_card,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('300.00'),
            transaction_date=date.today(),
            description='Expense',
        )

        response = self.client.get(reverse('finance:income_statement'))
        self.assertEqual(response.context['net_profit'], Decimal('700.00'))

    def test_income_statement_shows_owners_draw(self):
        """Test that income statement shows owner's draws."""
        Transaction.objects.create(
            account=self.checking,
            transaction_type='owners_draw',
            amount=Decimal('200.00'),
            transaction_date=date.today(),
            description="Owner's draw",
        )

        response = self.client.get(reverse('finance:income_statement'))
        self.assertEqual(response.context['owners_draw'], Decimal('200.00'))

    def test_income_statement_calculates_retained_earnings(self):
        """Test that income statement calculates retained earnings."""
        Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('1000.00'),
            transaction_date=date.today(),
            description='Revenue',
        )
        Transaction.objects.create(
            account=self.credit_card,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('300.00'),
            transaction_date=date.today(),
            description='Expense',
        )
        Transaction.objects.create(
            account=self.checking,
            transaction_type='owners_draw',
            amount=Decimal('200.00'),
            transaction_date=date.today(),
            description="Owner's draw",
        )

        response = self.client.get(reverse('finance:income_statement'))
        # Net profit: 1000 - 300 = 700
        # Retained: 700 - 200 = 500
        self.assertEqual(response.context['net_profit'], Decimal('700.00'))
        self.assertEqual(response.context['retained_earnings'], Decimal('500.00'))


class DashboardDataAPITests(TestCase):
    """Tests for the dashboard data API."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        self.account = Account.objects.get(name='Amex Blue Business Cash')
        self.category = Category.objects.get(name='Office Supplies')
        self.income_category = Category.objects.get(name='Service Revenue')

    def test_api_requires_login(self):
        """Test that API requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:dashboard_data'))
        self.assertEqual(response.status_code, 302)

    def test_api_spending_by_category(self):
        """Test spending by category chart data."""
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.category,
            amount=Decimal('100.00'),
            transaction_date=date.today(),
            description='Expense',
        )

        response = self.client.get(
            reverse('finance:dashboard_data') + '?chart=spending_by_category'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('labels', data)
        self.assertIn('data', data)

    def test_api_income_vs_expense(self):
        """Test income vs expense chart data."""
        checking = Account.objects.get(name='Amex Business Checking')
        Transaction.objects.create(
            account=checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('500.00'),
            transaction_date=date.today(),
            description='Income',
        )
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.category,
            amount=Decimal('200.00'),
            transaction_date=date.today(),
            description='Expense',
        )

        response = self.client.get(
            reverse('finance:dashboard_data') + '?chart=income_vs_expense'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['labels'], ['Income', 'Expenses'])
        # Data is returned as strings for precision - verify values are correct
        self.assertEqual(Decimal(data['data'][0]), Decimal('500'))
        self.assertEqual(Decimal(data['data'][1]), Decimal('200'))

    def test_api_monthly_trend(self):
        """Test monthly trend chart data."""
        response = self.client.get(
            reverse('finance:dashboard_data') + '?chart=monthly_trend'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('labels', data)
        self.assertIn('income', data)
        self.assertIn('expenses', data)
        self.assertEqual(len(data['labels']), 6)  # 6 months

    def test_api_invalid_chart_type(self):
        """Test invalid chart type returns error."""
        response = self.client.get(
            reverse('finance:dashboard_data') + '?chart=invalid'
        )
        self.assertEqual(response.status_code, 400)


class DateRangeHelperTests(TestCase):
    """Tests for date range calculation helpers."""

    def test_mtd_period(self):
        """Test month-to-date period calculation."""
        from finance.views import _get_date_range_for_period
        start, end = _get_date_range_for_period('mtd')

        today = date.today()
        self.assertEqual(start.day, 1)
        self.assertEqual(start.month, today.month)
        self.assertEqual(start.year, today.year)
        self.assertEqual(end, today)

    def test_qtd_period(self):
        """Test quarter-to-date period calculation."""
        from finance.views import _get_date_range_for_period
        start, end = _get_date_range_for_period('qtd')

        today = date.today()
        quarter = (today.month - 1) // 3
        expected_start_month = quarter * 3 + 1
        self.assertEqual(start.month, expected_start_month)
        self.assertEqual(start.day, 1)
        self.assertEqual(end, today)

    def test_ytd_period(self):
        """Test year-to-date period calculation."""
        from finance.views import _get_date_range_for_period
        start, end = _get_date_range_for_period('ytd')

        today = date.today()
        self.assertEqual(start.month, 1)
        self.assertEqual(start.day, 1)
        self.assertEqual(start.year, today.year)
        self.assertEqual(end, today)

    def test_last_month_period(self):
        """Test last month period calculation."""
        from finance.views import _get_date_range_for_period
        start, end = _get_date_range_for_period('last_month')

        today = date.today()
        # End should be last day of previous month
        self.assertEqual(end, today.replace(day=1) - timedelta(days=1))
        # Start should be first day of previous month
        self.assertEqual(start.day, 1)
        self.assertEqual(start.month, end.month)
