"""
Tests for audit log views (Phase 13).
"""
from datetime import date, timedelta
from decimal import Decimal
import uuid

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone

from finance.models import AuditLog


class AuditLogViewTestCase(TestCase):
    """Base test case for audit log views."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        # Create test audit logs
        self.log1 = AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Transaction',
            object_id=uuid.uuid4(),
            object_repr='2026-01-09 - Office supplies ($50.00)',
            changes={
                'after': {
                    'amount': '50.00',
                    'description': 'Office supplies',
                    'transaction_type': 'expense',
                }
            },
            ip_address='127.0.0.1',
            user_agent='Test Browser',
        )

        self.log2 = AuditLog.objects.create(
            user=self.user,
            action='update',
            model_name='Account',
            object_id=uuid.uuid4(),
            object_repr='Business Checking (*1234)',
            changes={
                'before': {'name': 'Old Name'},
                'after': {'name': 'Business Checking'},
            },
            ip_address='127.0.0.1',
        )

        self.log3 = AuditLog.objects.create(
            user=self.other_user,
            action='delete',
            model_name='Category',
            object_id=uuid.uuid4(),
            object_repr='Old Category (Expense)',
            changes={
                'before': {
                    'name': 'Old Category',
                    'category_type': 'expense',
                }
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

    def test_list_view_shows_logs(self):
        """Test that list view shows audit logs."""
        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertContains(response, 'Transaction')
        self.assertContains(response, 'Account')
        self.assertContains(response, 'Category')

    def test_list_view_shows_stats(self):
        """Test that list view shows statistics."""
        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertIn('total_logs', response.context)
        self.assertEqual(response.context['total_logs'], 3)

    def test_list_view_filter_by_model(self):
        """Test filtering by model name."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'model': 'Transaction'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 1)
        self.assertEqual(response.context['page_obj'][0].model_name, 'Transaction')

    def test_list_view_filter_by_action(self):
        """Test filtering by action."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'action': 'create'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 1)
        self.assertEqual(response.context['page_obj'][0].action, 'create')

    def test_list_view_filter_by_user(self):
        """Test filtering by user."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'user': str(self.other_user.id)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 1)
        self.assertEqual(response.context['page_obj'][0].user, self.other_user)

    def test_list_view_filter_by_date_range(self):
        """Test filtering by date range."""
        today = date.today()
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {
                'date_from': today.isoformat(),
                'date_to': today.isoformat()
            }
        )
        self.assertEqual(response.status_code, 200)
        # All logs were created today
        self.assertEqual(len(response.context['page_obj']), 3)

    def test_list_view_filter_by_date_excludes_old(self):
        """Test date filter excludes older logs."""
        tomorrow = date.today() + timedelta(days=1)
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'date_from': tomorrow.isoformat()}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 0)

    def test_list_view_search(self):
        """Test search functionality."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'search': 'Office supplies'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 1)
        self.assertContains(response, 'Office supplies')

    def test_list_view_combined_filters(self):
        """Test combining multiple filters."""
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {
                'model': 'Transaction',
                'action': 'create',
                'user': str(self.user.id),
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 1)

    def test_list_view_provides_filter_options(self):
        """Test that filter dropdowns are populated."""
        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertIn('model_names', response.context)
        self.assertIn('users', response.context)
        self.assertIn('Transaction', list(response.context['model_names']))
        self.assertIn('Account', list(response.context['model_names']))

    def test_list_view_pagination(self):
        """Test pagination works."""
        # Create many logs
        for i in range(60):
            AuditLog.objects.create(
                user=self.user,
                action='create',
                model_name='Test',
                object_id=uuid.uuid4(),
                object_repr=f'Test object {i}',
            )

        response = self.client.get(reverse('finance:audit_log_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['page_obj'].has_next())
        self.assertEqual(len(response.context['page_obj']), 50)

        # Get page 2
        response = self.client.get(
            reverse('finance:audit_log_list'),
            {'page': '2'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['page_obj'].has_previous())


class AuditLogDetailViewTests(AuditLogViewTestCase):
    """Tests for audit_log_detail view."""

    def test_detail_view_requires_login(self):
        """Test that detail view requires authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.log1.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_detail_view_returns_200(self):
        """Test that detail view returns 200 for authenticated user."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.log1.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_detail_view_shows_log_info(self):
        """Test that detail view shows log information."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.log1.id])
        )
        self.assertContains(response, 'Transaction')
        self.assertContains(response, 'Create')
        self.assertContains(response, 'testuser')
        self.assertContains(response, '127.0.0.1')

    def test_detail_view_shows_changes_for_create(self):
        """Test that detail view shows changes for create action."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.log1.id])
        )
        self.assertContains(response, 'amount')
        self.assertContains(response, '50.00')

    def test_detail_view_shows_changes_for_update(self):
        """Test that detail view shows before/after for update action."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.log2.id])
        )
        self.assertContains(response, 'Old Name')
        self.assertContains(response, 'Business Checking')

    def test_detail_view_shows_changes_for_delete(self):
        """Test that detail view shows previous values for delete."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.log3.id])
        )
        self.assertContains(response, 'Old Category')

    def test_detail_view_404_invalid_id(self):
        """Test that detail view returns 404 for invalid id."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[uuid.uuid4()])
        )
        self.assertEqual(response.status_code, 404)

    def test_detail_view_parses_field_changes(self):
        """Test that field changes are properly parsed."""
        response = self.client.get(
            reverse('finance:audit_log_detail', args=[self.log2.id])
        )
        self.assertIn('field_changes', response.context)
        field_changes = response.context['field_changes']
        self.assertEqual(len(field_changes), 1)
        self.assertEqual(field_changes[0]['field'], 'name')
        self.assertEqual(field_changes[0]['before'], 'Old Name')
        self.assertEqual(field_changes[0]['after'], 'Business Checking')


class AuditLogImmutabilityTests(TestCase):
    """Tests for audit log immutability."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.log = AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Test',
            object_id=uuid.uuid4(),
            object_repr='Test object',
        )

    def test_audit_log_cannot_be_modified(self):
        """Test that audit logs cannot be modified."""
        from django.core.exceptions import ValidationError

        self.log.action = 'update'
        with self.assertRaises(ValidationError):
            self.log.save()

    def test_audit_log_cannot_be_deleted(self):
        """Test that audit logs cannot be deleted."""
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.log.delete()


class AuditLogModelTests(TestCase):
    """Tests for AuditLog model."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_audit_log_str(self):
        """Test audit log string representation."""
        log = AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Transaction',
            object_id=uuid.uuid4(),
            object_repr='Test transaction',
        )
        self.assertIn('create', str(log))
        self.assertIn('Transaction', str(log))
        self.assertIn('testuser', str(log))

    def test_audit_log_ordering(self):
        """Test audit logs are ordered by created_at descending."""
        log1 = AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Test1',
            object_id=uuid.uuid4(),
            object_repr='First',
        )
        log2 = AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Test2',
            object_id=uuid.uuid4(),
            object_repr='Second',
        )

        logs = list(AuditLog.objects.all())
        self.assertEqual(logs[0], log2)  # Most recent first
        self.assertEqual(logs[1], log1)

    def test_audit_log_with_null_user(self):
        """Test audit log can be created with null user (system actions)."""
        log = AuditLog.objects.create(
            user=None,
            action='create',
            model_name='Test',
            object_id=uuid.uuid4(),
            object_repr='System created object',
        )
        self.assertIsNone(log.user)
        self.assertIn('None', str(log))
