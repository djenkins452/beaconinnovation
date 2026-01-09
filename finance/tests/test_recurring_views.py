"""
Tests for recurring transaction views (Phase 11).
"""
from datetime import date, timedelta
from decimal import Decimal
import uuid

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from finance.models import Account, Category, RecurringTransaction, Transaction


class RecurringTransactionViewTestCase(TestCase):
    """Base test case for recurring transaction views."""

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

        # Create test category
        self.category = Category.objects.create(
            name='Software & Subscriptions',
            category_type='expense',
            is_system=True,
        )

        # Create test recurring transaction
        self.recurring = RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('9.99'),
            description='Monthly GitHub subscription',
            vendor='GitHub',
            frequency='monthly',
            day_of_month=15,
            start_date=date.today(),
            next_due=date.today().replace(day=15),
            is_active=True,
            created_by=self.user,
        )


class RecurringListViewTests(RecurringTransactionViewTestCase):
    """Tests for recurring_list view."""

    def test_list_view_requires_login(self):
        """Test that list view requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:recurring_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_list_view_returns_200(self):
        """Test that list view returns 200 for authenticated user."""
        response = self.client.get(reverse('finance:recurring_list'))
        self.assertEqual(response.status_code, 200)

    def test_list_view_shows_active_recurring(self):
        """Test that list view shows active recurring transactions."""
        response = self.client.get(reverse('finance:recurring_list'))
        self.assertContains(response, 'GitHub')
        self.assertContains(response, '9.99')

    def test_list_view_separates_active_inactive(self):
        """Test that list view separates active and inactive."""
        # Create inactive recurring
        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('19.99'),
            description='Old subscription',
            vendor='OldService',
            frequency='monthly',
            day_of_month=1,
            start_date=date.today(),
            next_due=date.today(),
            is_active=False,
            created_by=self.user,
        )

        response = self.client.get(reverse('finance:recurring_list'))
        self.assertContains(response, 'Active')
        self.assertContains(response, 'Inactive')
        self.assertContains(response, 'OldService')

    def test_list_view_calculates_monthly_totals(self):
        """Test that list view calculates monthly totals."""
        response = self.client.get(reverse('finance:recurring_list'))
        self.assertEqual(response.context['total_monthly'], Decimal('9.99'))

    def test_list_view_calculates_estimated_monthly(self):
        """Test that list view calculates estimated monthly cost."""
        # Add quarterly recurring
        RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('30.00'),
            description='Quarterly service',
            vendor='QuarterlyService',
            frequency='quarterly',
            day_of_month=1,
            start_date=date.today(),
            next_due=date.today(),
            is_active=True,
            created_by=self.user,
        )

        response = self.client.get(reverse('finance:recurring_list'))
        # 9.99 (monthly) + 30/3 (quarterly) = 19.99
        self.assertEqual(response.context['estimated_monthly'], Decimal('19.99'))


class RecurringCreateViewTests(RecurringTransactionViewTestCase):
    """Tests for recurring_create view."""

    def test_create_view_requires_login(self):
        """Test that create view requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:recurring_create'))
        self.assertEqual(response.status_code, 302)

    def test_create_view_returns_200(self):
        """Test that create view returns 200 for authenticated user."""
        response = self.client.get(reverse('finance:recurring_create'))
        self.assertEqual(response.status_code, 200)

    def test_create_view_shows_form(self):
        """Test that create view shows form."""
        response = self.client.get(reverse('finance:recurring_create'))
        self.assertContains(response, 'New Recurring Transaction')
        self.assertContains(response, 'form')

    def test_create_recurring_success(self):
        """Test successful recurring transaction creation."""
        data = {
            'account': str(self.account.id),
            'category': str(self.category.id),
            'amount': '14.99',
            'description': 'Netflix subscription',
            'vendor': 'Netflix',
            'frequency': 'monthly',
            'day_of_month': '1',
            'start_date': date.today().isoformat(),
            'is_active': True,
        }

        response = self.client.post(reverse('finance:recurring_create'), data)
        self.assertEqual(response.status_code, 302)

        # Check it was created
        self.assertTrue(
            RecurringTransaction.objects.filter(vendor='Netflix').exists()
        )

    def test_create_recurring_sets_next_due(self):
        """Test that create sets next_due correctly."""
        data = {
            'account': str(self.account.id),
            'category': str(self.category.id),
            'amount': '14.99',
            'description': 'Netflix subscription',
            'vendor': 'Netflix',
            'frequency': 'monthly',
            'day_of_month': '15',
            'start_date': date.today().isoformat(),
            'is_active': True,
        }

        self.client.post(reverse('finance:recurring_create'), data)
        recurring = RecurringTransaction.objects.get(vendor='Netflix')
        self.assertIsNotNone(recurring.next_due)

    def test_create_recurring_invalid_day_of_month(self):
        """Test validation of day_of_month."""
        data = {
            'account': str(self.account.id),
            'category': str(self.category.id),
            'amount': '14.99',
            'description': 'Test subscription',
            'vendor': 'Test',
            'frequency': 'monthly',
            'day_of_month': '32',  # Invalid
            'start_date': date.today().isoformat(),
            'is_active': True,
        }

        response = self.client.post(reverse('finance:recurring_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Day of month must be between 1 and 31')

    def test_create_recurring_end_date_before_start(self):
        """Test validation of end_date after start_date."""
        data = {
            'account': str(self.account.id),
            'category': str(self.category.id),
            'amount': '14.99',
            'description': 'Test subscription',
            'vendor': 'Test',
            'frequency': 'monthly',
            'day_of_month': '15',
            'start_date': date.today().isoformat(),
            'end_date': (date.today() - timedelta(days=30)).isoformat(),
            'is_active': True,
        }

        response = self.client.post(reverse('finance:recurring_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'End date must be after start date')


class RecurringEditViewTests(RecurringTransactionViewTestCase):
    """Tests for recurring_edit view."""

    def test_edit_view_requires_login(self):
        """Test that edit view requires authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:recurring_edit', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_edit_view_returns_200(self):
        """Test that edit view returns 200 for authenticated user."""
        response = self.client.get(
            reverse('finance:recurring_edit', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_view_shows_existing_data(self):
        """Test that edit view shows existing data."""
        response = self.client.get(
            reverse('finance:recurring_edit', args=[self.recurring.id])
        )
        self.assertContains(response, 'GitHub')
        self.assertContains(response, '9.99')

    def test_edit_view_404_invalid_id(self):
        """Test that edit view returns 404 for invalid id."""
        response = self.client.get(
            reverse('finance:recurring_edit', args=[uuid.uuid4()])
        )
        self.assertEqual(response.status_code, 404)

    def test_edit_recurring_success(self):
        """Test successful recurring transaction update."""
        data = {
            'account': str(self.account.id),
            'category': str(self.category.id),
            'amount': '19.99',  # Changed
            'description': 'Monthly GitHub Pro subscription',  # Changed
            'vendor': 'GitHub',
            'frequency': 'monthly',
            'day_of_month': '15',
            'start_date': self.recurring.start_date.isoformat(),
            'is_active': True,
        }

        response = self.client.post(
            reverse('finance:recurring_edit', args=[self.recurring.id]),
            data
        )
        self.assertEqual(response.status_code, 302)

        # Check it was updated
        self.recurring.refresh_from_db()
        self.assertEqual(self.recurring.amount, Decimal('19.99'))
        self.assertEqual(self.recurring.description, 'Monthly GitHub Pro subscription')


class RecurringDetailViewTests(RecurringTransactionViewTestCase):
    """Tests for recurring_detail view."""

    def test_detail_view_requires_login(self):
        """Test that detail view requires authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:recurring_detail', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_detail_view_returns_200(self):
        """Test that detail view returns 200 for authenticated user."""
        response = self.client.get(
            reverse('finance:recurring_detail', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 200)

    def test_detail_view_shows_recurring_info(self):
        """Test that detail view shows recurring information."""
        response = self.client.get(
            reverse('finance:recurring_detail', args=[self.recurring.id])
        )
        self.assertContains(response, 'GitHub')
        self.assertContains(response, '9.99')
        self.assertContains(response, 'Monthly')

    def test_detail_view_shows_generated_transactions(self):
        """Test that detail view shows generated transactions."""
        # Create a generated transaction
        Transaction.objects.create(
            account=self.account,
            category=self.category,
            transaction_type='expense',
            amount=Decimal('9.99'),
            transaction_date=date.today(),
            description='Monthly GitHub subscription',
            vendor='GitHub',
            is_recurring=True,
            recurring_source=self.recurring,
            created_by=self.user,
        )

        response = self.client.get(
            reverse('finance:recurring_detail', args=[self.recurring.id])
        )
        self.assertContains(response, 'Generated Transactions')
        self.assertEqual(response.context['generated_count'], 1)


class RecurringToggleActiveViewTests(RecurringTransactionViewTestCase):
    """Tests for recurring_toggle_active view."""

    def test_toggle_requires_post(self):
        """Test that toggle requires POST method."""
        response = self.client.get(
            reverse('finance:recurring_toggle_active', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 405)

    def test_toggle_active_to_inactive(self):
        """Test toggling from active to inactive."""
        self.assertTrue(self.recurring.is_active)

        response = self.client.post(
            reverse('finance:recurring_toggle_active', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 302)

        self.recurring.refresh_from_db()
        self.assertFalse(self.recurring.is_active)

    def test_toggle_inactive_to_active(self):
        """Test toggling from inactive to active."""
        self.recurring.is_active = False
        self.recurring.save()

        response = self.client.post(
            reverse('finance:recurring_toggle_active', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 302)

        self.recurring.refresh_from_db()
        self.assertTrue(self.recurring.is_active)


class RecurringDeleteViewTests(RecurringTransactionViewTestCase):
    """Tests for recurring_delete view."""

    def test_delete_requires_post(self):
        """Test that delete requires POST method."""
        response = self.client.get(
            reverse('finance:recurring_delete', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 405)

    def test_delete_success(self):
        """Test successful deletion."""
        recurring_id = self.recurring.id

        response = self.client.post(
            reverse('finance:recurring_delete', args=[recurring_id])
        )
        self.assertEqual(response.status_code, 302)

        # Check it was deleted
        self.assertFalse(
            RecurringTransaction.objects.filter(id=recurring_id).exists()
        )

    def test_delete_does_not_delete_generated_transactions(self):
        """Test that deletion does not delete generated transactions."""
        # Create a generated transaction
        transaction = Transaction.objects.create(
            account=self.account,
            category=self.category,
            transaction_type='expense',
            amount=Decimal('9.99'),
            transaction_date=date.today(),
            description='Monthly GitHub subscription',
            vendor='GitHub',
            is_recurring=True,
            recurring_source=self.recurring,
            created_by=self.user,
        )

        self.client.post(
            reverse('finance:recurring_delete', args=[self.recurring.id])
        )

        # Transaction should still exist
        self.assertTrue(Transaction.objects.filter(id=transaction.id).exists())


class RecurringGenerateViewTests(RecurringTransactionViewTestCase):
    """Tests for recurring_generate view."""

    def test_generate_requires_post(self):
        """Test that generate requires POST method."""
        response = self.client.get(
            reverse('finance:recurring_generate', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 405)

    def test_generate_creates_transaction(self):
        """Test that generate creates a transaction."""
        initial_count = Transaction.objects.count()

        response = self.client.post(
            reverse('finance:recurring_generate', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 302)

        # Check transaction was created
        self.assertEqual(Transaction.objects.count(), initial_count + 1)

        # Check transaction details
        transaction = Transaction.objects.filter(
            recurring_source=self.recurring
        ).latest('created_at')
        self.assertEqual(transaction.amount, Decimal('9.99'))
        self.assertEqual(transaction.vendor, 'GitHub')
        self.assertEqual(transaction.transaction_type, 'expense')
        self.assertTrue(transaction.is_recurring)

    def test_generate_updates_last_generated(self):
        """Test that generate updates last_generated date."""
        self.assertIsNone(self.recurring.last_generated)

        self.client.post(
            reverse('finance:recurring_generate', args=[self.recurring.id])
        )

        self.recurring.refresh_from_db()
        self.assertEqual(self.recurring.last_generated, date.today())

    def test_generate_updates_next_due(self):
        """Test that generate updates next_due date."""
        original_next_due = self.recurring.next_due

        self.client.post(
            reverse('finance:recurring_generate', args=[self.recurring.id])
        )

        self.recurring.refresh_from_db()
        self.assertNotEqual(self.recurring.next_due, original_next_due)

    def test_generate_fails_for_inactive(self):
        """Test that generate fails for inactive recurring."""
        self.recurring.is_active = False
        self.recurring.save()

        response = self.client.post(
            reverse('finance:recurring_generate', args=[self.recurring.id])
        )
        self.assertEqual(response.status_code, 302)

        # No transaction should be created
        self.assertFalse(
            Transaction.objects.filter(recurring_source=self.recurring).exists()
        )


class RecurringTransactionFormTests(RecurringTransactionViewTestCase):
    """Tests for RecurringTransactionForm."""

    def test_form_filters_expense_categories_only(self):
        """Test that form only shows expense categories."""
        # Create an income category
        income_category = Category.objects.create(
            name='Service Revenue',
            category_type='income',
            is_system=True,
        )

        response = self.client.get(reverse('finance:recurring_create'))

        # Form should show expense category (HTML escapes & to &amp;)
        self.assertContains(response, 'Software &amp; Subscriptions')

        # Form should not show income category in the dropdown
        form = response.context['form']
        category_choices = list(form.fields['category'].queryset)
        category_names = [c.name for c in category_choices]
        self.assertIn('Software & Subscriptions', category_names)
        self.assertNotIn('Service Revenue', category_names)

    def test_form_filters_active_accounts_only(self):
        """Test that form only shows active accounts."""
        # Create an inactive account
        inactive_account = Account.objects.create(
            name='Inactive Account',
            account_type='checking',
            institution='Test Bank',
            is_active=False,
            created_by=self.user,
        )

        response = self.client.get(reverse('finance:recurring_create'))

        form = response.context['form']
        account_choices = list(form.fields['account'].queryset)
        account_names = [a.name for a in account_choices]
        self.assertIn('Test Checking', account_names)
        self.assertNotIn('Inactive Account', account_names)
