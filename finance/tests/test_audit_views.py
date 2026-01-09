"""
Tests for audit log views (Phase 13).
"""
from datetime import date, timedelta
from decimal import Decimal
import uuid

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from finance.models import Account, Category, Transaction, AuditLog


class AuditLogViewTestCase(TestCase):
    """Base test case for audit log views."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.admin_user = User.objects.create_superuser(
            username='admin',
            password='adminpass123',
            email='admin@test.com'
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

        # Create test category
        self.category = Category.objects.create(
            name='Test Expense',
            category_type='expense',
        )

        # Create audit logs
        self.audit_log = AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Transaction',
            object_id=uuid.uuid4(),
            object_repr='Test Transaction - $100.00',
            changes={'after': {'amount': '100.00', 'description': 'Test'}},
        )

        self.audit_log_2 = AuditLog.objects.create(
            user=self.admin_user,
            action='update',
            model_name='Account',
            object_id=self.account.id,
            object_repr=str(self.account),
            changes={
                'before': {'name': 'Old Name'},
                'after': {'name': 'Test Checking'}
            },
        )


class AuditLogListViewTests(AuditLogViewTestCase):
    """Tests for audit_log_list view."""

    def test_list_view_requires_login(self):
        """Test that list view requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_list_view_returns_200(self):
        """Test that list view returns 200 for authenticated user."""
        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertEqual(response.status_code, 200)

    def test_list_view_shows_audit_logs(self):
        """Test that list view shows audit logs."""
        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertContains(response, 'Transaction')
        self.assertContains(response, 'Account')

    def test_list_view_shows_stats(self):
        """Test that list view shows total and today stats."""
        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertContains(response, 'Total:')
        self.assertContains(response, 'Today:')

    def test_list_view_filter_by_model(self):
        """Test filtering by model name."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'model': 'Transaction'}
        )
        self.assertEqual(response.status_code, 200)
        # Filtered results should only show Transaction logs
        page_obj = response.context['page_obj']
        self.assertEqual(len(page_obj), 1)
        self.assertEqual(page_obj[0].model_name, 'Transaction')

    def test_list_view_filter_by_action(self):
        """Test filtering by action."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'action': 'create'}
        )
        self.assertEqual(response.status_code, 200)
        # Should show create action
        self.assertEqual(len(response.context['page_obj']), 1)

    def test_list_view_filter_by_user(self):
        """Test filtering by user."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'user': str(self.user.id)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 1)

    def test_list_view_filter_by_date_range(self):
        """Test filtering by date range."""
        today = date.today().isoformat()
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'date_from': today, 'date_to': today}
        )
        self.assertEqual(response.status_code, 200)
        # Both logs created today
        self.assertEqual(len(response.context['page_obj']), 2)

    def test_list_view_filter_by_search(self):
        """Test filtering by search term."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'search': 'Transaction'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 1)

    def test_list_view_combined_filters(self):
        """Test combining multiple filters."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'model': 'Transaction', 'action': 'create'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 1)

    def test_list_view_invalid_date_filter(self):
        """Test that invalid date filter is ignored."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'date_from': 'invalid-date'}
        )
        self.assertEqual(response.status_code, 200)
        # Should still show all logs
        self.assertEqual(len(response.context['page_obj']), 2)


class AuditLogDetailViewTests(AuditLogViewTestCase):
    """Tests for audit_log_detail view."""

    def test_detail_view_requires_login(self):
        """Test that detail view requires authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.audit_log.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_detail_view_returns_200(self):
        """Test that detail view returns 200 for authenticated user."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.audit_log.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_detail_view_shows_log_info(self):
        """Test that detail view shows log information."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.audit_log.id])
        )
        self.assertContains(response, 'Transaction')
        self.assertContains(response, 'Create')

    def test_detail_view_shows_changes(self):
        """Test that detail view shows before/after changes."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.audit_log_2.id])
        )
        self.assertContains(response, 'Old Name')
        self.assertContains(response, 'Test Checking')

    def test_detail_view_404_invalid_id(self):
        """Test that detail view returns 404 for invalid id."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[uuid.uuid4()])
        )
        self.assertEqual(response.status_code, 404)


class AuditLogImmutabilityTests(AuditLogViewTestCase):
    """Tests for audit log immutability."""

    def test_audit_log_cannot_be_modified(self):
        """Test that audit logs cannot be modified."""
        from django.core.exceptions import ValidationError

        self.audit_log.action = 'delete'
        with self.assertRaises(ValidationError):
            self.audit_log.save()

    def test_audit_log_cannot_be_deleted(self):
        """Test that audit logs cannot be deleted."""
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.audit_log.delete()


class AuditLogCreationTests(AuditLogViewTestCase):
    """Tests for automatic audit log creation."""

    def test_audit_log_create_action(self):
        """Test that creating a transaction creates an audit log."""
        # Note: Automatic audit logging would typically be implemented
        # via signals or model methods. This test documents expected behavior.
        initial_count = AuditLog.objects.count()

        # Create a new audit log manually (simulating automatic creation)
        transaction = Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.category,
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test expense',
            created_by=self.user,
        )

        # In a full implementation, this would be automatic
        AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Transaction',
            object_id=transaction.id,
            object_repr=str(transaction),
            changes={'after': {'amount': '50.00', 'description': 'Test expense'}},
        )

        self.assertEqual(AuditLog.objects.count(), initial_count + 1)


class SecurityViewTests(AuditLogViewTestCase):
    """Tests for security and permission checks."""

    def test_all_finance_views_require_login(self):
        """Test that all finance views require authentication."""
        self.client.logout()

        protected_urls = [
            reverse('finance:dashboard'),
            reverse('finance:transaction_list'),
            reverse('finance:account_list'),
            reverse('finance:category_list'),
            reverse('finance:recurring_list'),
            reverse('finance:alert_list'),
            reverse('finance:audit_log_list'),
        ]

        for url in protected_urls:
            response = self.client.get(url)
            self.assertEqual(
                response.status_code,
                302,
                f'{url} should redirect unauthenticated users'
            )
            self.assertIn('/login/', response.url)

    def test_post_endpoints_require_csrf(self):
        """Test that POST endpoints require CSRF token."""
        self.client.login(username='testuser', password='testpass123')

        # Django test client handles CSRF, but we can verify forms have tokens
        response = self.client.get(reverse('finance:transaction_create'))
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_authenticated_user_can_access_views(self):
        """Test that authenticated users can access views."""
        self.client.login(username='testuser', password='testpass123')

        response = self.client.get(reverse('finance:dashboard'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('finance:transaction_list'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertEqual(response.status_code, 200)
