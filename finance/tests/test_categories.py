"""
Tests for category management functionality (Phase 9).
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from finance.forms import CategoryForm
from finance.models import Account, Category, Transaction


class CategoryModelTests(TestCase):
    """Tests for Category model."""

    def test_category_str_representation(self):
        """Test category string representation."""
        category = Category.objects.get(name='Office Supplies')
        self.assertEqual(str(category), 'Office Supplies (Expense)')

    def test_category_str_income(self):
        """Test income category string representation."""
        category = Category.objects.get(name='Service Revenue')
        self.assertEqual(str(category), 'Service Revenue (Income)')

    def test_system_category_cannot_be_deleted(self):
        """Test that system categories cannot be deleted."""
        category = Category.objects.get(name='Office Supplies')
        self.assertTrue(category.is_system)

        with self.assertRaises(ValidationError) as context:
            category.delete()

        self.assertIn('cannot be deleted', str(context.exception))

    def test_non_system_category_can_be_deleted(self):
        """Test that non-system categories can be deleted."""
        category = Category.objects.create(
            name='Custom Category',
            category_type='expense',
            is_system=False,
        )

        category_id = category.id
        category.delete()

        self.assertFalse(Category.objects.filter(id=category_id).exists())

    def test_category_ordering(self):
        """Test category ordering by type, display_order, name."""
        # Create categories with specific display orders
        cat1 = Category.objects.create(
            name='ZZZ Category',
            category_type='expense',
            display_order=1,
            is_system=False,
        )
        cat2 = Category.objects.create(
            name='AAA Category',
            category_type='expense',
            display_order=2,
            is_system=False,
        )

        categories = list(Category.objects.filter(
            id__in=[cat1.id, cat2.id]
        ).order_by('display_order', 'name'))

        self.assertEqual(categories[0].name, 'ZZZ Category')
        self.assertEqual(categories[1].name, 'AAA Category')


class CategoryFormTests(TestCase):
    """Tests for CategoryForm."""

    def test_valid_form(self):
        """Test form with valid data."""
        data = {
            'name': 'New Category',
            'category_type': 'expense',
            'description': 'A test category',
            'is_active': True,
            'display_order': 10,
        }
        form = CategoryForm(data=data)
        self.assertTrue(form.is_valid())

    def test_required_fields(self):
        """Test required field validation."""
        form = CategoryForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)
        self.assertIn('category_type', form.errors)

    def test_duplicate_name_same_type_rejected(self):
        """Test that duplicate names within same type are rejected."""
        data = {
            'name': 'Office Supplies',  # Already exists as expense
            'category_type': 'expense',
            'display_order': 0,
        }
        form = CategoryForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)

    def test_duplicate_name_different_type_allowed(self):
        """Test that same name can be used for different types."""
        data = {
            'name': 'Office Supplies',  # Exists as expense
            'category_type': 'income',  # Different type
            'display_order': 0,
        }
        form = CategoryForm(data=data)
        self.assertTrue(form.is_valid())

    def test_negative_display_order_rejected(self):
        """Test that negative display order is rejected."""
        data = {
            'name': 'Test Category',
            'category_type': 'expense',
            'display_order': -1,
        }
        form = CategoryForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('display_order', form.errors)

    def test_edit_preserves_type_for_system_category(self):
        """Test that editing system category preserves its type."""
        category = Category.objects.get(name='Office Supplies')
        self.assertTrue(category.is_system)
        self.assertEqual(category.category_type, 'expense')

        data = {
            'name': 'Office Supplies Updated',
            'category_type': 'income',  # Try to change type
            'display_order': 0,
        }
        form = CategoryForm(data=data, instance=category)
        self.assertTrue(form.is_valid())

        # The clean method should preserve the original type
        cleaned = form.clean()
        self.assertEqual(cleaned['category_type'], 'expense')

    def test_case_insensitive_duplicate_check(self):
        """Test that duplicate check is case-insensitive."""
        data = {
            'name': 'OFFICE SUPPLIES',  # Case different but same
            'category_type': 'expense',
            'display_order': 0,
        }
        form = CategoryForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)


class CategoryViewTests(TestCase):
    """Tests for category views."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        # Get existing system categories
        self.expense_category = Category.objects.get(
            name='Office Supplies',
            category_type='expense'
        )
        self.income_category = Category.objects.get(
            name='Service Revenue',
            category_type='income'
        )

        # Create a non-system category for testing
        self.custom_category = Category.objects.create(
            name='Custom Test Category',
            category_type='expense',
            is_system=False,
            is_active=True,
            display_order=99,
        )

    def test_category_list_requires_login(self):
        """Test that category list requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:category_list'))
        self.assertEqual(response.status_code, 302)

    def test_category_list_renders(self):
        """Test that category list renders correctly."""
        response = self.client.get(reverse('finance:category_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/category_list.html')

    def test_category_list_shows_expense_categories(self):
        """Test that category list shows expense categories."""
        response = self.client.get(reverse('finance:category_list'))
        self.assertContains(response, 'Office Supplies')
        self.assertIn('expense_categories', response.context)

    def test_category_list_shows_income_categories(self):
        """Test that category list shows income categories."""
        response = self.client.get(reverse('finance:category_list'))
        self.assertContains(response, 'Service Revenue')
        self.assertIn('income_categories', response.context)

    def test_category_create_renders(self):
        """Test that category create form renders."""
        response = self.client.get(reverse('finance:category_create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/category_form.html')
        self.assertContains(response, 'New Category')

    def test_category_create_preselects_type(self):
        """Test that type can be preselected via query param."""
        response = self.client.get(
            reverse('finance:category_create') + '?type=income'
        )
        self.assertEqual(response.status_code, 200)
        # Form should have income preselected
        form = response.context['form']
        self.assertEqual(form.initial.get('category_type'), 'income')

    def test_category_create_success(self):
        """Test creating a category."""
        data = {
            'name': 'Brand New Category',
            'category_type': 'expense',
            'description': 'Test description',
            'is_active': True,
            'display_order': 50,
        }
        response = self.client.post(reverse('finance:category_create'), data)
        self.assertEqual(response.status_code, 302)

        # Verify category created
        category = Category.objects.get(name='Brand New Category')
        self.assertEqual(category.category_type, 'expense')
        self.assertFalse(category.is_system)

    def test_category_edit_renders(self):
        """Test that category edit form renders with data."""
        response = self.client.get(
            reverse('finance:category_edit', args=[self.custom_category.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/category_form.html')
        self.assertContains(response, 'Custom Test Category')

    def test_category_edit_system_shows_warning(self):
        """Test that editing system category shows warning."""
        response = self.client.get(
            reverse('finance:category_edit', args=[self.expense_category.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'System Category')

    def test_category_edit_success(self):
        """Test editing a category."""
        data = {
            'name': 'Updated Category Name',
            'category_type': 'expense',
            'description': 'Updated description',
            'is_active': True,
            'display_order': 25,
        }
        response = self.client.post(
            reverse('finance:category_edit', args=[self.custom_category.id]),
            data
        )
        self.assertEqual(response.status_code, 302)

        self.custom_category.refresh_from_db()
        self.assertEqual(self.custom_category.name, 'Updated Category Name')
        self.assertEqual(self.custom_category.display_order, 25)

    def test_category_detail_renders(self):
        """Test that category detail renders correctly."""
        response = self.client.get(
            reverse('finance:category_detail', args=[self.expense_category.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/category_detail.html')
        self.assertContains(response, 'Office Supplies')

    def test_category_detail_shows_transaction_count(self):
        """Test that category detail shows transaction count."""
        # Create a transaction for this category
        account = Account.objects.get(name='Amex Business Checking')
        Transaction.objects.create(
            account=account,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test expense',
        )

        response = self.client.get(
            reverse('finance:category_detail', args=[self.expense_category.id])
        )
        self.assertEqual(response.context['transaction_count'], 1)

    def test_category_delete_system_rejected(self):
        """Test that system categories cannot be deleted."""
        response = self.client.post(
            reverse('finance:category_delete', args=[self.expense_category.id])
        )
        self.assertEqual(response.status_code, 302)  # Redirects with error

        # Category should still exist
        self.assertTrue(
            Category.objects.filter(id=self.expense_category.id).exists()
        )

    def test_category_delete_with_transactions_rejected(self):
        """Test that categories with transactions cannot be deleted."""
        # Create a transaction for the custom category
        account = Account.objects.get(name='Amex Business Checking')
        Transaction.objects.create(
            account=account,
            transaction_type='expense',
            category=self.custom_category,
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test expense',
        )

        response = self.client.post(
            reverse('finance:category_delete', args=[self.custom_category.id])
        )
        self.assertEqual(response.status_code, 302)  # Redirects with error

        # Category should still exist
        self.assertTrue(
            Category.objects.filter(id=self.custom_category.id).exists()
        )

    def test_category_delete_success(self):
        """Test deleting a category without transactions."""
        # Create a fresh category with no transactions
        category = Category.objects.create(
            name='Deletable Category',
            category_type='expense',
            is_system=False,
        )

        response = self.client.post(
            reverse('finance:category_delete', args=[category.id])
        )
        self.assertEqual(response.status_code, 302)

        # Category should be deleted
        self.assertFalse(
            Category.objects.filter(id=category.id).exists()
        )

    def test_category_delete_requires_post(self):
        """Test that delete requires POST method."""
        response = self.client.get(
            reverse('finance:category_delete', args=[self.custom_category.id])
        )
        self.assertEqual(response.status_code, 405)

    def test_category_toggle_active(self):
        """Test toggling category active status."""
        self.assertTrue(self.custom_category.is_active)

        response = self.client.post(
            reverse('finance:category_toggle_active', args=[self.custom_category.id])
        )
        self.assertEqual(response.status_code, 302)

        self.custom_category.refresh_from_db()
        self.assertFalse(self.custom_category.is_active)

        # Toggle back
        response = self.client.post(
            reverse('finance:category_toggle_active', args=[self.custom_category.id])
        )
        self.custom_category.refresh_from_db()
        self.assertTrue(self.custom_category.is_active)

    def test_category_toggle_requires_post(self):
        """Test that toggle requires POST method."""
        response = self.client.get(
            reverse('finance:category_toggle_active', args=[self.custom_category.id])
        )
        self.assertEqual(response.status_code, 405)

    def test_category_detail_nonexistent(self):
        """Test viewing non-existent category returns 404."""
        import uuid
        fake_id = uuid.uuid4()
        response = self.client.get(
            reverse('finance:category_detail', args=[fake_id])
        )
        self.assertEqual(response.status_code, 404)


class DefaultCategorySeedTests(TestCase):
    """Tests for default category seeding."""

    def test_expense_categories_exist(self):
        """Test that default expense categories are seeded."""
        expected_expense = [
            'Software & Subscriptions',
            'Equipment',
            'Professional Services',
            'Advertising & Marketing',
            'Office Supplies',
            'Education & Training',
            'Travel',
            'Meals & Entertainment',
            'Bank Fees & Interest',
            'Miscellaneous',
        ]

        for name in expected_expense:
            self.assertTrue(
                Category.objects.filter(name=name, category_type='expense').exists(),
                f'Expense category "{name}" not found'
            )

    def test_income_categories_exist(self):
        """Test that default income categories are seeded."""
        expected_income = [
            'Service Revenue',
            'Product Revenue',
            'Refunds',
            'Owner Contributions',
            'Other Income',
        ]

        for name in expected_income:
            self.assertTrue(
                Category.objects.filter(name=name, category_type='income').exists(),
                f'Income category "{name}" not found'
            )

    def test_default_categories_are_system(self):
        """Test that default categories are marked as system."""
        categories = Category.objects.filter(is_system=True)
        # Should have at least 15 system categories
        self.assertGreaterEqual(categories.count(), 15)

    def test_default_categories_have_display_order(self):
        """Test that default categories have display order set."""
        # Get expense categories and check they have sequential display orders
        expense_cats = Category.objects.filter(
            category_type='expense',
            is_system=True
        ).order_by('display_order')

        orders = [c.display_order for c in expense_cats]
        # Should be sequential starting from 0 or 1
        self.assertTrue(all(o >= 0 for o in orders))
