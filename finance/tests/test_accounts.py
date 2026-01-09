"""
Tests for account management functionality (Phase 8).
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from finance.forms import AccountForm
from finance.models import Account, Category, Transaction


class AccountModelTests(TestCase):
    """Tests for Account model."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.checking = Account.objects.create(
            name='Test Checking',
            account_type='checking',
            institution='Test Bank',
            opening_balance=Decimal('1000.00'),
        )
        self.credit_card = Account.objects.create(
            name='Test Credit Card',
            account_type='credit_card',
            institution='Test Bank',
            opening_balance=Decimal('0.00'),
        )
        self.expense_category = Category.objects.get(
            name='Office Supplies',
            category_type='expense'
        )
        self.income_category = Category.objects.get(
            name='Service Revenue',
            category_type='income'
        )

    def test_account_str(self):
        """Test account string representation."""
        self.assertEqual(str(self.checking), 'Test Checking')

        # With last four digits
        self.checking.last_four = '1234'
        self.checking.save()
        self.assertEqual(str(self.checking), 'Test Checking (*1234)')

    def test_checking_balance_with_income(self):
        """Test checking balance increases with income."""
        Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('500.00'),
            transaction_date=date.today(),
            description='Test income',
        )

        self.assertEqual(self.checking.current_balance, Decimal('1500.00'))

    def test_checking_balance_with_expense(self):
        """Test checking balance decreases with expense."""
        Transaction.objects.create(
            account=self.checking,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('200.00'),
            transaction_date=date.today(),
            description='Test expense',
        )

        self.assertEqual(self.checking.current_balance, Decimal('800.00'))

    def test_checking_balance_with_owners_draw(self):
        """Test checking balance decreases with owner's draw."""
        Transaction.objects.create(
            account=self.checking,
            transaction_type='owners_draw',
            amount=Decimal('300.00'),
            transaction_date=date.today(),
            description='Owner draw',
        )

        self.assertEqual(self.checking.current_balance, Decimal('700.00'))

    def test_checking_balance_with_transfer_out(self):
        """Test checking balance decreases with transfer out."""
        savings = Account.objects.create(
            name='Test Savings',
            account_type='savings',
            institution='Test Bank',
            opening_balance=Decimal('0.00'),
        )

        Transaction.objects.create(
            account=self.checking,
            transaction_type='transfer',
            transfer_to_account=savings,
            amount=Decimal('100.00'),
            transaction_date=date.today(),
            description='Transfer to savings',
        )

        self.assertEqual(self.checking.current_balance, Decimal('900.00'))
        self.assertEqual(savings.current_balance, Decimal('100.00'))

    def test_credit_card_balance_with_expense(self):
        """Test credit card balance increases with expense."""
        Transaction.objects.create(
            account=self.credit_card,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('150.00'),
            transaction_date=date.today(),
            description='Credit card expense',
        )

        self.assertEqual(self.credit_card.current_balance, Decimal('150.00'))

    def test_credit_card_balance_with_payment(self):
        """Test credit card balance decreases with payment."""
        # First add an expense
        Transaction.objects.create(
            account=self.credit_card,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('200.00'),
            transaction_date=date.today(),
            description='Credit card expense',
        )

        # Then make a payment (transfer from checking to credit card)
        Transaction.objects.create(
            account=self.checking,
            transaction_type='transfer',
            transfer_to_account=self.credit_card,
            amount=Decimal('100.00'),
            transaction_date=date.today(),
            description='Credit card payment',
        )

        self.assertEqual(self.credit_card.current_balance, Decimal('100.00'))

    def test_balance_with_multiple_transactions(self):
        """Test balance calculation with multiple transactions."""
        # Income
        Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('1000.00'),
            transaction_date=date.today(),
            description='Income 1',
        )
        # Expense
        Transaction.objects.create(
            account=self.checking,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('300.00'),
            transaction_date=date.today(),
            description='Expense 1',
        )
        # Owner's draw
        Transaction.objects.create(
            account=self.checking,
            transaction_type='owners_draw',
            amount=Decimal('200.00'),
            transaction_date=date.today(),
            description='Draw 1',
        )

        # 1000 (opening) + 1000 (income) - 300 (expense) - 200 (draw) = 1500
        self.assertEqual(self.checking.current_balance, Decimal('1500.00'))


class AccountFormTests(TestCase):
    """Tests for AccountForm."""

    def test_valid_form(self):
        """Test form with valid data."""
        data = {
            'name': 'New Account',
            'account_type': 'checking',
            'institution': 'Test Bank',
            'last_four': '5678',
            'is_personal': False,
            'is_active': True,
            'opening_balance': '1000.00',
        }
        form = AccountForm(data=data)
        self.assertTrue(form.is_valid())

    def test_last_four_digits_only(self):
        """Test that last_four accepts only digits."""
        data = {
            'name': 'New Account',
            'account_type': 'checking',
            'institution': 'Test Bank',
            'last_four': 'abcd',
            'opening_balance': '0.00',
        }
        form = AccountForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('last_four', form.errors)

    def test_negative_opening_balance(self):
        """Test that negative opening balance is rejected."""
        data = {
            'name': 'New Account',
            'account_type': 'checking',
            'institution': 'Test Bank',
            'opening_balance': '-100.00',
        }
        form = AccountForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('opening_balance', form.errors)

    def test_required_fields(self):
        """Test required field validation."""
        form = AccountForm(data={})
        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)
        self.assertIn('account_type', form.errors)
        self.assertIn('institution', form.errors)


class AccountViewTests(TestCase):
    """Tests for account views."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        self.account = Account.objects.create(
            name='Test Account',
            account_type='checking',
            institution='Test Bank',
            opening_balance=Decimal('1000.00'),
        )

    def test_account_list_requires_login(self):
        """Test that account list requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:account_list'))
        self.assertEqual(response.status_code, 302)

    def test_account_list_renders(self):
        """Test that account list renders correctly."""
        response = self.client.get(reverse('finance:account_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/account_list.html')

    def test_account_list_shows_accounts(self):
        """Test that account list shows accounts."""
        response = self.client.get(reverse('finance:account_list'))
        self.assertContains(response, 'Test Account')

    def test_account_list_shows_totals(self):
        """Test that account list shows balance totals."""
        response = self.client.get(reverse('finance:account_list'))
        self.assertIn('total_checking', response.context)
        self.assertIn('total_credit', response.context)

    def test_account_create_renders(self):
        """Test that account create form renders."""
        response = self.client.get(reverse('finance:account_create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/account_form.html')
        self.assertContains(response, 'New Account')

    def test_account_create_success(self):
        """Test creating an account."""
        data = {
            'name': 'New Checking',
            'account_type': 'checking',
            'institution': 'New Bank',
            'last_four': '9999',
            'is_personal': False,
            'is_active': True,
            'opening_balance': '500.00',
        }
        response = self.client.post(reverse('finance:account_create'), data)
        self.assertEqual(response.status_code, 302)

        # Verify account created
        account = Account.objects.get(name='New Checking')
        self.assertEqual(account.institution, 'New Bank')
        self.assertEqual(account.opening_balance, Decimal('500.00'))
        self.assertEqual(account.created_by, self.user)

    def test_account_edit_renders(self):
        """Test that account edit form renders with data."""
        response = self.client.get(
            reverse('finance:account_edit', args=[self.account.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/account_form.html')
        self.assertContains(response, 'Test Account')

    def test_account_edit_success(self):
        """Test editing an account."""
        data = {
            'name': 'Updated Account',
            'account_type': 'checking',
            'institution': 'Updated Bank',
            'is_active': True,
            'opening_balance': '2000.00',
        }
        response = self.client.post(
            reverse('finance:account_edit', args=[self.account.id]),
            data
        )
        self.assertEqual(response.status_code, 302)

        self.account.refresh_from_db()
        self.assertEqual(self.account.name, 'Updated Account')
        self.assertEqual(self.account.institution, 'Updated Bank')

    def test_account_detail_renders(self):
        """Test that account detail renders correctly."""
        response = self.client.get(
            reverse('finance:account_detail', args=[self.account.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/account_detail.html')
        self.assertContains(response, 'Test Account')

    def test_account_detail_shows_balance(self):
        """Test that account detail shows current balance."""
        response = self.client.get(
            reverse('finance:account_detail', args=[self.account.id])
        )
        # Balance displays as 1000.00 (floatformat:2 doesn't add commas)
        self.assertContains(response, '1000.00')

    def test_account_detail_shows_transactions(self):
        """Test that account detail shows transactions."""
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test transaction',
        )

        response = self.client.get(
            reverse('finance:account_detail', args=[self.account.id])
        )
        self.assertContains(response, 'Test transaction')

    def test_account_toggle_active(self):
        """Test toggling account active status."""
        self.assertTrue(self.account.is_active)

        response = self.client.post(
            reverse('finance:account_toggle_active', args=[self.account.id])
        )
        self.assertEqual(response.status_code, 302)

        self.account.refresh_from_db()
        self.assertFalse(self.account.is_active)

        # Toggle back
        response = self.client.post(
            reverse('finance:account_toggle_active', args=[self.account.id])
        )
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_active)

    def test_account_toggle_requires_post(self):
        """Test that toggle requires POST method."""
        response = self.client.get(
            reverse('finance:account_toggle_active', args=[self.account.id])
        )
        self.assertEqual(response.status_code, 405)

    def test_account_detail_nonexistent(self):
        """Test viewing non-existent account returns 404."""
        import uuid
        fake_id = uuid.uuid4()
        response = self.client.get(
            reverse('finance:account_detail', args=[fake_id])
        )
        self.assertEqual(response.status_code, 404)


class DefaultAccountSeedTests(TestCase):
    """Tests for default account seeding."""

    def test_default_accounts_exist(self):
        """Test that default accounts are seeded."""
        # The migration should have created these
        checking = Account.objects.filter(name='Amex Business Checking').first()
        credit = Account.objects.filter(name='Amex Blue Business Cash').first()
        personal = Account.objects.filter(name='Personal Amex').first()

        self.assertIsNotNone(checking)
        self.assertIsNotNone(credit)
        self.assertIsNotNone(personal)

    def test_checking_has_opening_balance(self):
        """Test that checking account has $1000 opening balance."""
        checking = Account.objects.get(name='Amex Business Checking')
        self.assertEqual(checking.opening_balance, Decimal('1000.00'))

    def test_credit_card_has_zero_balance(self):
        """Test that credit card has $0 opening balance."""
        credit = Account.objects.get(name='Amex Blue Business Cash')
        self.assertEqual(credit.opening_balance, Decimal('0.00'))

    def test_personal_card_is_marked_personal(self):
        """Test that personal card has is_personal=True."""
        personal = Account.objects.get(name='Personal Amex')
        self.assertTrue(personal.is_personal)
