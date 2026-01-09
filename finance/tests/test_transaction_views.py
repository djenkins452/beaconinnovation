"""
Tests for transaction views (Phase 6).
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from finance.models import Account, Category, Transaction


class TransactionViewTestCase(TestCase):
    """Base test case with common setup for transaction views."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        # Create accounts
        self.checking = Account.objects.create(
            name='Test Checking',
            account_type='checking',
            institution='Test Bank',
            opening_balance=Decimal('5000.00')
        )
        self.savings = Account.objects.create(
            name='Test Savings',
            account_type='savings',
            institution='Test Bank',
            opening_balance=Decimal('10000.00')
        )
        self.credit_card = Account.objects.create(
            name='Test Credit Card',
            account_type='credit_card',
            institution='Test Bank',
            opening_balance=Decimal('500.00')
        )

        # Create categories (use get_or_create for uniqueness constraint compatibility)
        self.expense_category, _ = Category.objects.get_or_create(
            name='Office Supplies',
            category_type='expense'
        )
        self.income_category, _ = Category.objects.get_or_create(
            name='Client Income',
            category_type='income'
        )

        # Create a sample transaction
        self.transaction = Transaction.objects.create(
            account=self.checking,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('100.00'),
            transaction_date=date.today(),
            description='Test expense',
            vendor='Test Vendor',
            created_by=self.user
        )


class TransactionListViewTests(TransactionViewTestCase):
    """Tests for transaction list view."""

    def test_list_view_requires_login(self):
        """Test that list view requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:transaction_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_list_view_renders(self):
        """Test that list view renders successfully."""
        response = self.client.get(reverse('finance:transaction_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/transaction_list.html')

    def test_list_view_shows_transactions(self):
        """Test that transactions appear in list."""
        response = self.client.get(reverse('finance:transaction_list'))
        self.assertContains(response, 'Test expense')
        self.assertContains(response, 'Test Vendor')

    def test_list_view_filter_by_account(self):
        """Test filtering by account."""
        # Create transaction in different account
        Transaction.objects.create(
            account=self.savings,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('500.00'),
            transaction_date=date.today(),
            description='Savings income',
            created_by=self.user
        )

        response = self.client.get(
            reverse('finance:transaction_list'),
            {'account': self.checking.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test expense')
        self.assertNotContains(response, 'Savings income')

    def test_list_view_filter_by_type(self):
        """Test filtering by transaction type."""
        # Create income transaction
        Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('500.00'),
            transaction_date=date.today(),
            description='Income transaction',
            created_by=self.user
        )

        response = self.client.get(
            reverse('finance:transaction_list'),
            {'transaction_type': 'expense'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test expense')
        self.assertNotContains(response, 'Income transaction')

    def test_list_view_filter_by_category(self):
        """Test filtering by category."""
        response = self.client.get(
            reverse('finance:transaction_list'),
            {'category': self.expense_category.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test expense')

    def test_list_view_filter_by_date_range(self):
        """Test filtering by date range."""
        # Create old transaction
        old_date = date.today() - timedelta(days=30)
        Transaction.objects.create(
            account=self.checking,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('50.00'),
            transaction_date=old_date,
            description='Old expense',
            created_by=self.user
        )

        response = self.client.get(
            reverse('finance:transaction_list'),
            {
                'date_from': date.today().isoformat(),
                'date_to': date.today().isoformat()
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test expense')
        self.assertNotContains(response, 'Old expense')

    def test_list_view_search(self):
        """Test search by description or vendor."""
        Transaction.objects.create(
            account=self.checking,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('75.00'),
            transaction_date=date.today(),
            description='Office supplies purchase',
            vendor='Staples',
            created_by=self.user
        )

        # Search by description
        response = self.client.get(
            reverse('finance:transaction_list'),
            {'search': 'Office supplies'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Office supplies purchase')

        # Search by vendor
        response = self.client.get(
            reverse('finance:transaction_list'),
            {'search': 'Staples'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Staples')

    def test_list_view_pagination(self):
        """Test pagination works correctly."""
        # Create 30 transactions (more than page size of 25)
        for i in range(30):
            Transaction.objects.create(
                account=self.checking,
                transaction_type='expense',
                category=self.expense_category,
                amount=Decimal('10.00'),
                transaction_date=date.today(),
                description=f'Transaction {i}',
                created_by=self.user
            )

        response = self.client.get(reverse('finance:transaction_list'))
        self.assertEqual(response.status_code, 200)
        # Should have pagination
        self.assertIn('transactions', response.context)

        # Check page 2
        response = self.client.get(
            reverse('finance:transaction_list'),
            {'page': 2}
        )
        self.assertEqual(response.status_code, 200)


class TransactionCreateViewTests(TransactionViewTestCase):
    """Tests for transaction create view."""

    def test_create_view_requires_login(self):
        """Test that create view requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:transaction_create'))
        self.assertEqual(response.status_code, 302)

    def test_create_view_renders(self):
        """Test that create view renders form."""
        response = self.client.get(reverse('finance:transaction_create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/transaction_form.html')
        self.assertContains(response, 'New Transaction')

    def test_create_expense_transaction(self):
        """Test creating an expense transaction."""
        data = {
            'account': self.checking.id,
            'transaction_type': 'expense',
            'category': self.expense_category.id,
            'amount': '250.00',
            'transaction_date': date.today().isoformat(),
            'description': 'New office equipment',
            'vendor': 'Amazon',
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 302)

        # Verify transaction was created
        transaction = Transaction.objects.get(description='New office equipment')
        self.assertEqual(transaction.amount, Decimal('250.00'))
        self.assertEqual(transaction.vendor, 'Amazon')
        self.assertEqual(transaction.created_by, self.user)

    def test_create_income_transaction(self):
        """Test creating an income transaction."""
        data = {
            'account': self.checking.id,
            'transaction_type': 'income',
            'category': self.income_category.id,
            'amount': '1500.00',
            'transaction_date': date.today().isoformat(),
            'description': 'Client payment',
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 302)

        transaction = Transaction.objects.get(description='Client payment')
        self.assertEqual(transaction.transaction_type, 'income')

    def test_create_transfer_transaction(self):
        """Test creating a transfer transaction."""
        data = {
            'account': self.checking.id,
            'transaction_type': 'transfer',
            'amount': '500.00',
            'transaction_date': date.today().isoformat(),
            'description': 'Transfer to savings',
            'transfer_to_account': self.savings.id,
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 302)

        transaction = Transaction.objects.get(description='Transfer to savings')
        self.assertEqual(transaction.transfer_to_account, self.savings)

    def test_create_owners_draw_transaction(self):
        """Test creating an owner's draw transaction."""
        data = {
            'account': self.checking.id,
            'transaction_type': 'owners_draw',
            'amount': '2000.00',
            'transaction_date': date.today().isoformat(),
            'description': 'Monthly owner draw',
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 302)

        transaction = Transaction.objects.get(description='Monthly owner draw')
        self.assertEqual(transaction.transaction_type, 'owners_draw')

    def test_create_expense_requires_category(self):
        """Test that expense transactions require a category."""
        data = {
            'account': self.checking.id,
            'transaction_type': 'expense',
            'amount': '100.00',
            'transaction_date': date.today().isoformat(),
            'description': 'Missing category expense',
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 200)  # Form error, not redirect
        # Form has validation error on category field
        self.assertTrue(response.context['form'].errors.get('category'))
        self.assertIn(
            'Category is required for income and expense transactions.',
            response.context['form'].errors['category']
        )

    def test_create_expense_requires_expense_category(self):
        """Test that expense transactions require an expense category."""
        data = {
            'account': self.checking.id,
            'transaction_type': 'expense',
            'category': self.income_category.id,  # Wrong type!
            'amount': '100.00',
            'transaction_date': date.today().isoformat(),
            'description': 'Wrong category type',
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 200)
        # Form has validation error on category field
        self.assertTrue(response.context['form'].errors.get('category'))
        self.assertIn(
            'Expense transactions require an expense category.',
            response.context['form'].errors['category']
        )

    def test_create_transfer_requires_destination(self):
        """Test that transfer transactions require destination account."""
        data = {
            'account': self.checking.id,
            'transaction_type': 'transfer',
            'amount': '500.00',
            'transaction_date': date.today().isoformat(),
            'description': 'Missing destination',
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 200)
        # Form has validation error on transfer_to_account field
        self.assertTrue(response.context['form'].errors.get('transfer_to_account'))
        self.assertIn(
            'Transfer transactions require a destination account.',
            response.context['form'].errors['transfer_to_account']
        )

    def test_create_transfer_cannot_transfer_to_same_account(self):
        """Test that cannot transfer to same account."""
        data = {
            'account': self.checking.id,
            'transaction_type': 'transfer',
            'amount': '500.00',
            'transaction_date': date.today().isoformat(),
            'description': 'Same account transfer',
            'transfer_to_account': self.checking.id,  # Same account!
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 200)
        # Form has validation error on transfer_to_account field
        self.assertTrue(response.context['form'].errors.get('transfer_to_account'))
        self.assertIn(
            'Cannot transfer to the same account.',
            response.context['form'].errors['transfer_to_account']
        )

    def test_create_owners_draw_requires_checking(self):
        """Test that owner's draw must come from checking account."""
        data = {
            'account': self.credit_card.id,  # Not checking!
            'transaction_type': 'owners_draw',
            'amount': '1000.00',
            'transaction_date': date.today().isoformat(),
            'description': 'Invalid owner draw',
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'],
            'account',
            "Owner's draws must come from a checking account."
        )

    def test_create_future_date_not_allowed(self):
        """Test that future dates are not allowed."""
        future_date = date.today() + timedelta(days=7)
        data = {
            'account': self.checking.id,
            'transaction_type': 'expense',
            'category': self.expense_category.id,
            'amount': '100.00',
            'transaction_date': future_date.isoformat(),
            'description': 'Future expense',
        }
        response = self.client.post(
            reverse('finance:transaction_create'),
            data
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'],
            'transaction_date',
            'Transaction date cannot be in the future.'
        )


class TransactionEditViewTests(TransactionViewTestCase):
    """Tests for transaction edit view."""

    def test_edit_view_requires_login(self):
        """Test that edit view requires authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:transaction_edit', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_edit_view_renders(self):
        """Test that edit view renders with existing data."""
        response = self.client.get(
            reverse('finance:transaction_edit', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/transaction_form.html')
        self.assertContains(response, 'Edit Transaction')
        self.assertContains(response, 'Test expense')

    def test_edit_transaction(self):
        """Test editing a transaction."""
        data = {
            'account': self.checking.id,
            'transaction_type': 'expense',
            'category': self.expense_category.id,
            'amount': '150.00',  # Changed
            'transaction_date': date.today().isoformat(),
            'description': 'Updated expense',  # Changed
            'vendor': 'Updated Vendor',  # Changed
        }
        response = self.client.post(
            reverse('finance:transaction_edit', args=[self.transaction.id]),
            data
        )
        self.assertEqual(response.status_code, 302)

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.amount, Decimal('150.00'))
        self.assertEqual(self.transaction.description, 'Updated expense')
        self.assertEqual(self.transaction.vendor, 'Updated Vendor')

    def test_edit_nonexistent_transaction(self):
        """Test editing non-existent transaction returns 404."""
        import uuid
        fake_id = uuid.uuid4()
        response = self.client.get(
            reverse('finance:transaction_edit', args=[fake_id])
        )
        self.assertEqual(response.status_code, 404)


class TransactionDetailViewTests(TransactionViewTestCase):
    """Tests for transaction detail view."""

    def test_detail_view_requires_login(self):
        """Test that detail view requires authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:transaction_detail', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_detail_view_renders(self):
        """Test that detail view renders correctly."""
        response = self.client.get(
            reverse('finance:transaction_detail', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/transaction_detail.html')
        self.assertContains(response, 'Test expense')
        self.assertContains(response, 'Test Vendor')
        self.assertContains(response, '100')  # Amount

    def test_detail_view_shows_receipts_section(self):
        """Test that receipts section is shown."""
        response = self.client.get(
            reverse('finance:transaction_detail', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Receipts')
        self.assertContains(response, 'Upload Receipt')

    def test_detail_nonexistent_transaction(self):
        """Test viewing non-existent transaction returns 404."""
        import uuid
        fake_id = uuid.uuid4()
        response = self.client.get(
            reverse('finance:transaction_detail', args=[fake_id])
        )
        self.assertEqual(response.status_code, 404)


class TransactionDeleteViewTests(TransactionViewTestCase):
    """Tests for transaction delete view."""

    def test_delete_requires_login(self):
        """Test that delete requires authentication."""
        self.client.logout()
        response = self.client.post(
            reverse('finance:transaction_delete', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_delete_requires_post(self):
        """Test that delete requires POST method."""
        response = self.client.get(
            reverse('finance:transaction_delete', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 405)  # Method not allowed

    def test_delete_transaction(self):
        """Test deleting a transaction."""
        transaction_id = self.transaction.id
        response = self.client.post(
            reverse('finance:transaction_delete', args=[transaction_id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('finance:transaction_list'))

        # Verify transaction was deleted
        self.assertFalse(
            Transaction.objects.filter(id=transaction_id).exists()
        )

    def test_delete_nonexistent_transaction(self):
        """Test deleting non-existent transaction returns 404."""
        import uuid
        fake_id = uuid.uuid4()
        response = self.client.post(
            reverse('finance:transaction_delete', args=[fake_id])
        )
        self.assertEqual(response.status_code, 404)


class VendorSuggestAPITests(TransactionViewTestCase):
    """Tests for vendor auto-suggest API."""

    def setUp(self):
        super().setUp()
        # Create transactions with different vendors
        vendors = ['Amazon', 'Apple Store', 'Staples', 'Office Depot', 'Best Buy']
        for vendor in vendors:
            Transaction.objects.create(
                account=self.checking,
                transaction_type='expense',
                category=self.expense_category,
                amount=Decimal('100.00'),
                transaction_date=date.today(),
                description=f'Purchase from {vendor}',
                vendor=vendor,
                created_by=self.user
            )

    def test_vendor_suggest_requires_login(self):
        """Test that vendor suggest requires authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:vendor_suggest'),
            {'q': 'Amaz'}
        )
        self.assertEqual(response.status_code, 302)

    def test_vendor_suggest_returns_matches(self):
        """Test that vendor suggest returns matching vendors."""
        response = self.client.get(
            reverse('finance:vendor_suggest'),
            {'q': 'Amaz'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('vendors', data)
        self.assertIn('Amazon', data['vendors'])

    def test_vendor_suggest_case_insensitive(self):
        """Test that search is case insensitive."""
        response = self.client.get(
            reverse('finance:vendor_suggest'),
            {'q': 'apple'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('Apple Store', data['vendors'])

    def test_vendor_suggest_minimum_query_length(self):
        """Test that queries under 2 chars return empty."""
        response = self.client.get(
            reverse('finance:vendor_suggest'),
            {'q': 'A'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['vendors'], [])

    def test_vendor_suggest_empty_query(self):
        """Test empty query returns empty list."""
        response = self.client.get(
            reverse('finance:vendor_suggest'),
            {'q': ''}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['vendors'], [])

    def test_vendor_suggest_no_matches(self):
        """Test no matches returns empty list."""
        response = self.client.get(
            reverse('finance:vendor_suggest'),
            {'q': 'XYZ Company'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['vendors'], [])


class CategoriesByTypeAPITests(TransactionViewTestCase):
    """Tests for categories by type API."""

    def test_categories_requires_login(self):
        """Test that categories API requires authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:categories_by_type'),
            {'type': 'expense'}
        )
        self.assertEqual(response.status_code, 302)

    def test_get_expense_categories(self):
        """Test getting expense categories."""
        response = self.client.get(
            reverse('finance:categories_by_type'),
            {'type': 'expense'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('categories', data)
        category_names = [c['name'] for c in data['categories']]
        self.assertIn('Office Supplies', category_names)

    def test_get_income_categories(self):
        """Test getting income categories."""
        response = self.client.get(
            reverse('finance:categories_by_type'),
            {'type': 'income'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('categories', data)
        category_names = [c['name'] for c in data['categories']]
        self.assertIn('Client Income', category_names)

    def test_invalid_type_returns_empty(self):
        """Test invalid type returns empty list."""
        response = self.client.get(
            reverse('finance:categories_by_type'),
            {'type': 'invalid'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['categories'], [])

    def test_missing_type_returns_empty(self):
        """Test missing type returns empty list."""
        response = self.client.get(reverse('finance:categories_by_type'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['categories'], [])

    def test_inactive_categories_excluded(self):
        """Test that inactive categories are not returned."""
        # Create inactive category
        Category.objects.get_or_create(
            name='Inactive Category',
            category_type='expense',
            defaults={'is_active': False}
        )
        response = self.client.get(
            reverse('finance:categories_by_type'),
            {'type': 'expense'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        category_names = [c['name'] for c in data['categories']]
        self.assertNotIn('Inactive Category', category_names)
