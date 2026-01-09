from decimal import Decimal
from datetime import date, timedelta
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from finance.models import (
    Account, Category, Transaction, Receipt,
    RecurringTransaction, TaxAlert, AuditLog, CSVImport
)


class AccountModelTest(TestCase):
    """Tests for the Account model."""

    def setUp(self):
        self.checking = Account.objects.create(
            name='Business Checking',
            account_type='checking',
            institution='Amex',
            last_four='1234',
            opening_balance=Decimal('1000.00')
        )
        self.credit_card = Account.objects.create(
            name='Business Credit Card',
            account_type='credit_card',
            institution='Amex',
            last_four='5678',
            opening_balance=Decimal('0.00')
        )

    def test_create_account(self):
        """Test creating an account."""
        self.assertEqual(self.checking.name, 'Business Checking')
        self.assertEqual(self.checking.account_type, 'checking')
        self.assertEqual(self.checking.opening_balance, Decimal('1000.00'))

    def test_str_representation(self):
        """Test string representation."""
        self.assertEqual(str(self.checking), 'Business Checking (*1234)')

    def test_str_without_last_four(self):
        """Test string representation without last four digits."""
        account = Account.objects.create(
            name='Test Account',
            account_type='savings',
            institution='Test Bank'
        )
        self.assertEqual(str(account), 'Test Account')

    def test_current_balance_checking(self):
        """Test current balance calculation for checking account."""
        # Create categories
        income_cat = Category.objects.create(
            name='Income',
            category_type='income'
        )
        expense_cat = Category.objects.create(
            name='Expense',
            category_type='expense'
        )

        # Add income
        Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=income_cat,
            amount=Decimal('500.00'),
            transaction_date=date.today(),
            description='Test income'
        )

        # Add expense
        Transaction.objects.create(
            account=self.checking,
            transaction_type='expense',
            category=expense_cat,
            amount=Decimal('200.00'),
            transaction_date=date.today(),
            description='Test expense'
        )

        # Balance should be: 1000 + 500 - 200 = 1300
        self.assertEqual(self.checking.current_balance, Decimal('1300.00'))

    def test_current_balance_credit_card(self):
        """Test current balance calculation for credit card."""
        expense_cat = Category.objects.create(
            name='Expense',
            category_type='expense'
        )

        # Add expense to credit card
        Transaction.objects.create(
            account=self.credit_card,
            transaction_type='expense',
            category=expense_cat,
            amount=Decimal('100.00'),
            transaction_date=date.today(),
            description='Test expense'
        )

        # Balance owed should be: 0 + 100 = 100
        self.assertEqual(self.credit_card.current_balance, Decimal('100.00'))


class CategoryModelTest(TestCase):
    """Tests for the Category model."""

    def test_create_category(self):
        """Test creating a category."""
        category = Category.objects.create(
            name='Test Category',
            category_type='expense'
        )
        self.assertEqual(category.name, 'Test Category')
        self.assertEqual(category.category_type, 'expense')

    def test_str_representation(self):
        """Test string representation."""
        category = Category.objects.create(
            name='Software',
            category_type='expense'
        )
        self.assertEqual(str(category), 'Software (Expense)')

    def test_system_category_cannot_be_deleted(self):
        """Test that system categories cannot be deleted."""
        category = Category.objects.create(
            name='System Category',
            category_type='expense',
            is_system=True
        )
        with self.assertRaises(ValidationError):
            category.delete()

    def test_non_system_category_can_be_deleted(self):
        """Test that non-system categories can be deleted."""
        category = Category.objects.create(
            name='Custom Category',
            category_type='expense',
            is_system=False
        )
        category_id = category.pk
        category.delete()
        self.assertFalse(Category.objects.filter(pk=category_id).exists())

    def test_default_categories_seeded(self):
        """Test that default categories are seeded via migration."""
        # Check expense categories
        expense_count = Category.objects.filter(category_type='expense', is_system=True).count()
        self.assertEqual(expense_count, 10)

        # Check income categories
        income_count = Category.objects.filter(category_type='income', is_system=True).count()
        self.assertEqual(income_count, 5)


class TransactionModelTest(TestCase):
    """Tests for the Transaction model."""

    def setUp(self):
        self.checking = Account.objects.create(
            name='Checking',
            account_type='checking',
            institution='Test Bank'
        )
        self.credit_card = Account.objects.create(
            name='Credit Card',
            account_type='credit_card',
            institution='Test Bank'
        )
        self.expense_category = Category.objects.create(
            name='Test Expense',
            category_type='expense'
        )
        self.income_category = Category.objects.create(
            name='Test Income',
            category_type='income'
        )

    def test_create_expense_transaction(self):
        """Test creating an expense transaction."""
        transaction = Transaction.objects.create(
            account=self.checking,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test expense'
        )
        self.assertEqual(transaction.amount, Decimal('50.00'))

    def test_create_income_transaction(self):
        """Test creating an income transaction."""
        transaction = Transaction.objects.create(
            account=self.checking,
            transaction_type='income',
            category=self.income_category,
            amount=Decimal('100.00'),
            transaction_date=date.today(),
            description='Test income'
        )
        self.assertEqual(transaction.amount, Decimal('100.00'))

    def test_expense_requires_category(self):
        """Test that expense transactions require a category."""
        transaction = Transaction(
            account=self.checking,
            transaction_type='expense',
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test'
        )
        with self.assertRaises(ValidationError):
            transaction.full_clean()

    def test_income_requires_category(self):
        """Test that income transactions require a category."""
        transaction = Transaction(
            account=self.checking,
            transaction_type='income',
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test'
        )
        with self.assertRaises(ValidationError):
            transaction.full_clean()

    def test_income_requires_income_category(self):
        """Test that income transactions require an income category."""
        transaction = Transaction(
            account=self.checking,
            transaction_type='income',
            category=self.expense_category,  # Wrong category type
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test'
        )
        with self.assertRaises(ValidationError):
            transaction.full_clean()

    def test_expense_requires_expense_category(self):
        """Test that expense transactions require an expense category."""
        transaction = Transaction(
            account=self.checking,
            transaction_type='expense',
            category=self.income_category,  # Wrong category type
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test'
        )
        with self.assertRaises(ValidationError):
            transaction.full_clean()

    def test_transfer_requires_destination(self):
        """Test that transfers require a destination account."""
        transaction = Transaction(
            account=self.checking,
            transaction_type='transfer',
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test transfer'
        )
        with self.assertRaises(ValidationError):
            transaction.full_clean()

    def test_transfer_cannot_be_same_account(self):
        """Test that transfers cannot have the same source and destination."""
        transaction = Transaction(
            account=self.checking,
            transaction_type='transfer',
            transfer_to_account=self.checking,
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test transfer'
        )
        with self.assertRaises(ValidationError):
            transaction.full_clean()

    def test_owners_draw_requires_checking(self):
        """Test that owner's draws must come from checking account."""
        transaction = Transaction(
            account=self.credit_card,
            transaction_type='owners_draw',
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test draw'
        )
        with self.assertRaises(ValidationError):
            transaction.full_clean()

    def test_str_representation(self):
        """Test string representation."""
        transaction = Transaction.objects.create(
            account=self.checking,
            transaction_type='expense',
            category=self.expense_category,
            amount=Decimal('50.00'),
            transaction_date=date(2026, 1, 8),
            description='Test expense'
        )
        self.assertEqual(str(transaction), '2026-01-08 - Test expense ($50.00)')


class TaxAlertModelTest(TestCase):
    """Tests for the TaxAlert model."""

    def test_create_tax_alert(self):
        """Test creating a tax alert."""
        alert = TaxAlert.objects.create(
            quarter=1,
            year=2026,
            threshold_amount=Decimal('1000.00'),
            actual_net_profit=Decimal('1500.00'),
            alert_triggered=True
        )
        self.assertEqual(alert.quarter, 1)
        self.assertEqual(alert.year, 2026)
        self.assertTrue(alert.alert_triggered)

    def test_invalid_quarter(self):
        """Test that invalid quarter raises validation error."""
        alert = TaxAlert(
            quarter=5,  # Invalid
            year=2026,
            threshold_amount=Decimal('1000.00')
        )
        with self.assertRaises(ValidationError):
            alert.full_clean()

    def test_str_representation(self):
        """Test string representation."""
        alert = TaxAlert.objects.create(
            quarter=2,
            year=2026,
            actual_net_profit=Decimal('1500.00')
        )
        self.assertEqual(str(alert), 'Q2 2026 - $1500.00')


class AuditLogModelTest(TestCase):
    """Tests for the AuditLog model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )

    def test_create_audit_log(self):
        """Test creating an audit log entry."""
        import uuid
        log = AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Account',
            object_id=uuid.uuid4(),
            object_repr='Test Account',
            changes={'new': {'name': 'Test'}}
        )
        self.assertEqual(log.action, 'create')
        self.assertEqual(log.model_name, 'Account')

    def test_audit_log_cannot_be_modified(self):
        """Test that existing audit logs cannot be modified."""
        import uuid
        log = AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Account',
            object_id=uuid.uuid4(),
            object_repr='Test Account',
            changes={}
        )

        log.action = 'update'
        with self.assertRaises(ValidationError):
            log.save()

    def test_audit_log_cannot_be_deleted(self):
        """Test that audit logs cannot be deleted."""
        import uuid
        log = AuditLog.objects.create(
            user=self.user,
            action='create',
            model_name='Account',
            object_id=uuid.uuid4(),
            object_repr='Test Account',
            changes={}
        )

        with self.assertRaises(ValidationError):
            log.delete()


class RecurringTransactionModelTest(TestCase):
    """Tests for the RecurringTransaction model."""

    def setUp(self):
        self.account = Account.objects.create(
            name='Checking',
            account_type='checking',
            institution='Test Bank'
        )
        self.category = Category.objects.create(
            name='Subscriptions',
            category_type='expense'
        )

    def test_create_recurring_transaction(self):
        """Test creating a recurring transaction."""
        recurring = RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('9.99'),
            description='Monthly subscription',
            vendor='Netflix',
            frequency='monthly',
            day_of_month=15,
            start_date=date.today(),
            next_due=date.today() + timedelta(days=30)
        )
        self.assertEqual(recurring.vendor, 'Netflix')
        self.assertEqual(recurring.frequency, 'monthly')

    def test_invalid_day_of_month(self):
        """Test that invalid day of month raises validation error."""
        recurring = RecurringTransaction(
            account=self.account,
            category=self.category,
            amount=Decimal('9.99'),
            description='Test',
            vendor='Test',
            frequency='monthly',
            day_of_month=32,  # Invalid
            start_date=date.today(),
            next_due=date.today()
        )
        with self.assertRaises(ValidationError):
            recurring.full_clean()

    def test_str_representation(self):
        """Test string representation."""
        recurring = RecurringTransaction.objects.create(
            account=self.account,
            category=self.category,
            amount=Decimal('9.99'),
            description='Monthly subscription',
            vendor='Netflix',
            frequency='monthly',
            day_of_month=15,
            start_date=date.today(),
            next_due=date.today()
        )
        self.assertEqual(str(recurring), 'Netflix - $9.99 (Monthly)')
