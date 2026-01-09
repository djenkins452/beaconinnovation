"""
Tests for tax alert views (Phase 12).
"""
from datetime import date, timedelta
from decimal import Decimal
import uuid

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone

from finance.models import Account, Category, Transaction, TaxAlert


class TaxAlertViewTestCase(TestCase):
    """Base test case for tax alert views."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        # Create test account
        self.account = Account.objects.create(
            name='Test Checking',
            account_type='checking',
            institution='Test Bank',
            opening_balance=Decimal('1000.00'),
            created_by=self.user,
        )

        # Create test categories
        self.income_category = Category.objects.create(
            name='Service Revenue',
            category_type='income',
            is_system=True,
        )
        self.expense_category = Category.objects.create(
            name='Software & Subscriptions',
            category_type='expense',
            is_system=True,
        )

        # Create a triggered alert
        self.triggered_alert = TaxAlert.objects.create(
            quarter=1,
            year=2026,
            threshold_amount=Decimal('1000.00'),
            actual_net_profit=Decimal('1500.00'),
            alert_triggered=True,
            alert_date=timezone.now(),
            acknowledged=False,
        )

        # Create an acknowledged alert
        self.acknowledged_alert = TaxAlert.objects.create(
            quarter=4,
            year=2025,
            threshold_amount=Decimal('1000.00'),
            actual_net_profit=Decimal('2000.00'),
            alert_triggered=True,
            alert_date=timezone.now() - timedelta(days=30),
            acknowledged=True,
            acknowledged_at=timezone.now() - timedelta(days=15),
            notes='Paid estimated tax',
        )


class AlertListViewTests(TaxAlertViewTestCase):
    """Tests for alert_list view."""

    def test_list_view_requires_login(self):
        """Test that list view requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:alert_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_list_view_returns_200(self):
        """Test that list view returns 200 for authenticated user."""
        response = self.client.get(reverse('finance:alert_list'))
        self.assertEqual(response.status_code, 200)

    def test_list_view_shows_unacknowledged_alerts(self):
        """Test that list view shows unacknowledged alerts."""
        response = self.client.get(reverse('finance:alert_list'))
        self.assertContains(response, 'Q1 2026')
        self.assertContains(response, '1500.00')

    def test_list_view_shows_acknowledged_alerts(self):
        """Test that list view shows acknowledged alerts."""
        response = self.client.get(reverse('finance:alert_list'))
        self.assertContains(response, 'Q4 2025')
        self.assertContains(response, 'Acknowledged')

    def test_list_view_separates_alerts(self):
        """Test that list view separates unacknowledged and acknowledged."""
        response = self.client.get(reverse('finance:alert_list'))
        self.assertIn('unacknowledged_alerts', response.context)
        self.assertIn('acknowledged_alerts', response.context)
        self.assertEqual(len(response.context['unacknowledged_alerts']), 1)
        self.assertEqual(len(response.context['acknowledged_alerts']), 1)

    def test_list_view_shows_current_quarter(self):
        """Test that list view shows current quarter info."""
        response = self.client.get(reverse('finance:alert_list'))
        self.assertIn('current_quarter', response.context)
        self.assertIn('current_year', response.context)


class AlertDetailViewTests(TaxAlertViewTestCase):
    """Tests for alert_detail view."""

    def test_detail_view_requires_login(self):
        """Test that detail view requires authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:alert_detail', args=[self.triggered_alert.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_detail_view_returns_200(self):
        """Test that detail view returns 200 for authenticated user."""
        response = self.client.get(
            reverse('finance:alert_detail', args=[self.triggered_alert.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_detail_view_shows_alert_info(self):
        """Test that detail view shows alert information."""
        response = self.client.get(
            reverse('finance:alert_detail', args=[self.triggered_alert.id])
        )
        self.assertContains(response, 'Q1 2026')
        self.assertContains(response, '1500.00')
        self.assertContains(response, '1000.00')

    def test_detail_view_404_invalid_id(self):
        """Test that detail view returns 404 for invalid id."""
        response = self.client.get(
            reverse('finance:alert_detail', args=[uuid.uuid4()])
        )
        self.assertEqual(response.status_code, 404)

    def test_detail_view_shows_transactions(self):
        """Test that detail view shows quarter transactions."""
        # Create transactions in Q1 2026
        Transaction.objects.create(
            account=self.account,
            category=self.income_category,
            transaction_type='income',
            amount=Decimal('2000.00'),
            transaction_date=date(2026, 2, 15),
            description='Client payment',
            created_by=self.user,
        )
        Transaction.objects.create(
            account=self.account,
            category=self.expense_category,
            transaction_type='expense',
            amount=Decimal('500.00'),
            transaction_date=date(2026, 1, 20),
            description='Software expense',
            created_by=self.user,
        )

        response = self.client.get(
            reverse('finance:alert_detail', args=[self.triggered_alert.id])
        )
        self.assertContains(response, 'Client payment')
        self.assertContains(response, 'Software expense')

    def test_detail_view_shows_due_date(self):
        """Test that detail view shows IRS due date for triggered alert."""
        response = self.client.get(
            reverse('finance:alert_detail', args=[self.triggered_alert.id])
        )
        # Q1 2026 due date is April 15, 2026
        self.assertContains(response, 'April 15, 2026')


class AlertAcknowledgeViewTests(TaxAlertViewTestCase):
    """Tests for alert_acknowledge view."""

    def test_acknowledge_requires_post(self):
        """Test that acknowledge requires POST method."""
        response = self.client.get(
            reverse('finance:alert_acknowledge', args=[self.triggered_alert.id])
        )
        self.assertEqual(response.status_code, 405)

    def test_acknowledge_success(self):
        """Test successful acknowledgment."""
        self.assertFalse(self.triggered_alert.acknowledged)

        response = self.client.post(
            reverse('finance:alert_acknowledge', args=[self.triggered_alert.id])
        )
        self.assertEqual(response.status_code, 302)

        self.triggered_alert.refresh_from_db()
        self.assertTrue(self.triggered_alert.acknowledged)
        self.assertIsNotNone(self.triggered_alert.acknowledged_at)

    def test_acknowledge_with_notes(self):
        """Test acknowledgment with notes."""
        response = self.client.post(
            reverse('finance:alert_acknowledge', args=[self.triggered_alert.id]),
            {'notes': 'Paid $400 estimated tax'}
        )
        self.assertEqual(response.status_code, 302)

        self.triggered_alert.refresh_from_db()
        self.assertEqual(self.triggered_alert.notes, 'Paid $400 estimated tax')

    def test_acknowledge_non_triggered_alert_fails(self):
        """Test that acknowledging non-triggered alert fails."""
        # Create non-triggered alert
        non_triggered = TaxAlert.objects.create(
            quarter=2,
            year=2026,
            threshold_amount=Decimal('1000.00'),
            actual_net_profit=Decimal('500.00'),
            alert_triggered=False,
        )

        response = self.client.post(
            reverse('finance:alert_acknowledge', args=[non_triggered.id])
        )
        self.assertEqual(response.status_code, 302)

        non_triggered.refresh_from_db()
        self.assertFalse(non_triggered.acknowledged)


class AlertUnacknowledgeViewTests(TaxAlertViewTestCase):
    """Tests for alert_unacknowledge view."""

    def test_unacknowledge_requires_post(self):
        """Test that unacknowledge requires POST method."""
        response = self.client.get(
            reverse('finance:alert_unacknowledge', args=[self.acknowledged_alert.id])
        )
        self.assertEqual(response.status_code, 405)

    def test_unacknowledge_success(self):
        """Test successful unacknowledgment."""
        self.assertTrue(self.acknowledged_alert.acknowledged)

        response = self.client.post(
            reverse('finance:alert_unacknowledge', args=[self.acknowledged_alert.id])
        )
        self.assertEqual(response.status_code, 302)

        self.acknowledged_alert.refresh_from_db()
        self.assertFalse(self.acknowledged_alert.acknowledged)
        self.assertIsNone(self.acknowledged_alert.acknowledged_at)


class AlertCalculateViewTests(TaxAlertViewTestCase):
    """Tests for alert_calculate view."""

    def test_calculate_requires_post(self):
        """Test that calculate requires POST method."""
        response = self.client.get(reverse('finance:alert_calculate'))
        self.assertEqual(response.status_code, 405)

    def test_calculate_current_quarter(self):
        """Test calculation for current quarter."""
        response = self.client.post(reverse('finance:alert_calculate'))
        self.assertEqual(response.status_code, 302)

        # Should create an alert for current quarter
        today = date.today()
        current_quarter = (today.month - 1) // 3 + 1
        self.assertTrue(
            TaxAlert.objects.filter(
                quarter=current_quarter,
                year=today.year
            ).exists()
        )

    def test_calculate_specific_quarter(self):
        """Test calculation for specific quarter."""
        response = self.client.post(
            reverse('finance:alert_calculate'),
            {'quarter': '3', 'year': '2026'}
        )
        self.assertEqual(response.status_code, 302)

        # Should create an alert for Q3 2026
        self.assertTrue(
            TaxAlert.objects.filter(quarter=3, year=2026).exists()
        )

    def test_calculate_invalid_quarter(self):
        """Test calculation with invalid quarter."""
        response = self.client.post(
            reverse('finance:alert_calculate'),
            {'quarter': '5', 'year': '2026'}
        )
        self.assertEqual(response.status_code, 302)
        # Should redirect to alert_list with error

    def test_calculate_triggers_alert(self):
        """Test calculation triggers alert when threshold exceeded."""
        # Create income and expense in Q2 2026
        Transaction.objects.create(
            account=self.account,
            category=self.income_category,
            transaction_type='income',
            amount=Decimal('3000.00'),
            transaction_date=date(2026, 5, 15),
            description='Big client payment',
            created_by=self.user,
        )
        Transaction.objects.create(
            account=self.account,
            category=self.expense_category,
            transaction_type='expense',
            amount=Decimal('500.00'),
            transaction_date=date(2026, 4, 10),
            description='Software expense',
            created_by=self.user,
        )

        response = self.client.post(
            reverse('finance:alert_calculate'),
            {'quarter': '2', 'year': '2026'}
        )
        self.assertEqual(response.status_code, 302)

        # Check alert was created and triggered
        alert = TaxAlert.objects.get(quarter=2, year=2026)
        self.assertTrue(alert.alert_triggered)
        self.assertEqual(alert.actual_net_profit, Decimal('2500.00'))

    def test_calculate_no_alert_below_threshold(self):
        """Test calculation does not trigger alert below threshold."""
        # Create income and expense in Q3 2026 with net profit < $1000
        Transaction.objects.create(
            account=self.account,
            category=self.income_category,
            transaction_type='income',
            amount=Decimal('800.00'),
            transaction_date=date(2026, 8, 15),
            description='Small payment',
            created_by=self.user,
        )
        Transaction.objects.create(
            account=self.account,
            category=self.expense_category,
            transaction_type='expense',
            amount=Decimal('100.00'),
            transaction_date=date(2026, 7, 10),
            description='Expense',
            created_by=self.user,
        )

        response = self.client.post(
            reverse('finance:alert_calculate'),
            {'quarter': '3', 'year': '2026'}
        )
        self.assertEqual(response.status_code, 302)

        # Check alert was created but not triggered
        alert = TaxAlert.objects.get(quarter=3, year=2026)
        self.assertFalse(alert.alert_triggered)
        self.assertEqual(alert.actual_net_profit, Decimal('700.00'))

    def test_calculate_updates_existing_alert(self):
        """Test calculation updates existing alert."""
        original_profit = self.triggered_alert.actual_net_profit

        # Add more income to Q1 2026
        Transaction.objects.create(
            account=self.account,
            category=self.income_category,
            transaction_type='income',
            amount=Decimal('5000.00'),
            transaction_date=date(2026, 3, 15),
            description='Additional income',
            created_by=self.user,
        )

        response = self.client.post(
            reverse('finance:alert_calculate'),
            {'quarter': '1', 'year': '2026'}
        )
        self.assertEqual(response.status_code, 302)

        self.triggered_alert.refresh_from_db()
        self.assertNotEqual(self.triggered_alert.actual_net_profit, original_profit)


class TaxAlertHelperFunctionTests(TestCase):
    """Tests for tax alert helper functions."""

    def test_get_quarter_dates_q1(self):
        """Test quarter date calculation for Q1."""
        from finance.views import _get_quarter_dates
        start, end = _get_quarter_dates(1, 2026)
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 3, 31))

    def test_get_quarter_dates_q2(self):
        """Test quarter date calculation for Q2."""
        from finance.views import _get_quarter_dates
        start, end = _get_quarter_dates(2, 2026)
        self.assertEqual(start, date(2026, 4, 1))
        self.assertEqual(end, date(2026, 6, 30))

    def test_get_quarter_dates_q3(self):
        """Test quarter date calculation for Q3."""
        from finance.views import _get_quarter_dates
        start, end = _get_quarter_dates(3, 2026)
        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 9, 30))

    def test_get_quarter_dates_q4(self):
        """Test quarter date calculation for Q4."""
        from finance.views import _get_quarter_dates
        start, end = _get_quarter_dates(4, 2026)
        self.assertEqual(start, date(2026, 10, 1))
        self.assertEqual(end, date(2026, 12, 31))

    def test_get_tax_due_date_q1(self):
        """Test IRS due date for Q1."""
        from finance.views import _get_tax_due_date
        due = _get_tax_due_date(1, 2026)
        self.assertEqual(due, date(2026, 4, 15))

    def test_get_tax_due_date_q2(self):
        """Test IRS due date for Q2."""
        from finance.views import _get_tax_due_date
        due = _get_tax_due_date(2, 2026)
        self.assertEqual(due, date(2026, 6, 15))

    def test_get_tax_due_date_q3(self):
        """Test IRS due date for Q3."""
        from finance.views import _get_tax_due_date
        due = _get_tax_due_date(3, 2026)
        self.assertEqual(due, date(2026, 9, 15))

    def test_get_tax_due_date_q4(self):
        """Test IRS due date for Q4 (next year)."""
        from finance.views import _get_tax_due_date
        due = _get_tax_due_date(4, 2026)
        self.assertEqual(due, date(2027, 1, 15))
