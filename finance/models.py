import uuid
from decimal import Decimal
from django.db import models
from django.db.models import Sum, Case, When, F, Value, DecimalField as DjangoDecimalField
from django.db.models.functions import Coalesce
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError


class AccountManager(models.Manager):
    """Custom manager for Account model with optimized balance calculations."""

    def with_balances(self):
        """
        Return accounts annotated with calculated balances.
        This avoids N+1 queries by calculating all balances in a single query.
        """
        from finance.models import Transaction

        # Subquery for income
        income_subquery = Transaction.objects.filter(
            account=models.OuterRef('pk'),
            transaction_type='income'
        ).values('account').annotate(
            total=Sum('amount')
        ).values('total')

        # Subquery for expenses
        expense_subquery = Transaction.objects.filter(
            account=models.OuterRef('pk'),
            transaction_type='expense'
        ).values('account').annotate(
            total=Sum('amount')
        ).values('total')

        # Subquery for owner's draws
        draws_subquery = Transaction.objects.filter(
            account=models.OuterRef('pk'),
            transaction_type='owners_draw'
        ).values('account').annotate(
            total=Sum('amount')
        ).values('total')

        # Subquery for transfers out
        transfers_out_subquery = Transaction.objects.filter(
            account=models.OuterRef('pk'),
            transaction_type='transfer'
        ).values('account').annotate(
            total=Sum('amount')
        ).values('total')

        # Subquery for transfers in
        transfers_in_subquery = Transaction.objects.filter(
            transfer_to_account=models.OuterRef('pk')
        ).values('transfer_to_account').annotate(
            total=Sum('amount')
        ).values('total')

        return self.annotate(
            _income=Coalesce(models.Subquery(income_subquery), Value(Decimal('0.00'))),
            _expenses=Coalesce(models.Subquery(expense_subquery), Value(Decimal('0.00'))),
            _draws=Coalesce(models.Subquery(draws_subquery), Value(Decimal('0.00'))),
            _transfers_out=Coalesce(models.Subquery(transfers_out_subquery), Value(Decimal('0.00'))),
            _transfers_in=Coalesce(models.Subquery(transfers_in_subquery), Value(Decimal('0.00'))),
            calculated_balance=Case(
                # For checking/savings: opening + income - expenses - draws - transfers_out + transfers_in
                When(
                    account_type__in=['checking', 'savings'],
                    then=F('opening_balance') + F('_income') - F('_expenses') - F('_draws') - F('_transfers_out') + F('_transfers_in')
                ),
                # For credit cards: opening + expenses - payments (transfers_in)
                default=F('opening_balance') + F('_expenses') - F('_transfers_in'),
                output_field=DjangoDecimalField(max_digits=12, decimal_places=2)
            )
        )


class Account(models.Model):
    """Bank or credit card account for tracking transactions."""

    ACCOUNT_TYPE_CHOICES = [
        ('checking', 'Checking'),
        ('credit_card', 'Credit Card'),
        ('savings', 'Savings'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    institution = models.CharField(max_length=100, help_text='e.g., American Express')
    last_four = models.CharField(max_length=4, blank=True, default='', help_text='Last 4 digits')
    is_personal = models.BooleanField(
        default=False,
        help_text='True for personal cards used for business expenses'
    )
    is_active = models.BooleanField(default=True)
    opening_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Starting balance when account was added'
    )
    opening_balance_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_accounts'
    )

    objects = AccountManager()

    class Meta:
        ordering = ['name']

    def __str__(self):
        suffix = f' (*{self.last_four})' if self.last_four else ''
        return f'{self.name}{suffix}'

    @property
    def current_balance(self):
        """Calculate current balance based on transactions."""
        from django.db.models import Sum, Q

        # Start with opening balance
        balance = self.opening_balance

        # Get all transactions for this account
        transactions = self.transactions.all()

        # For checking/savings: income adds, expenses/draws subtract
        # For credit cards: expenses add (to balance owed), payments subtract
        if self.account_type in ('checking', 'savings'):
            # Income adds to balance
            income = transactions.filter(
                transaction_type='income'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            balance += income

            # Expenses subtract from balance
            expenses = transactions.filter(
                transaction_type='expense'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            balance -= expenses

            # Owner's draws subtract from balance
            draws = transactions.filter(
                transaction_type='owners_draw'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            balance -= draws

            # Transfers in add to balance
            transfers_in = Transaction.objects.filter(
                transfer_to_account=self
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            balance += transfers_in

            # Transfers out subtract from balance
            transfers_out = transactions.filter(
                transaction_type='transfer'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            balance -= transfers_out

        else:  # credit_card
            # Expenses add to balance owed
            expenses = transactions.filter(
                transaction_type='expense'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            balance += expenses

            # Payments subtract from balance owed (transfers from checking)
            payments = Transaction.objects.filter(
                transfer_to_account=self
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            balance -= payments

        return balance


class Category(models.Model):
    """Category for income or expense transactions."""

    CATEGORY_TYPE_CHOICES = [
        ('expense', 'Expense'),
        ('income', 'Income'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    category_type = models.CharField(max_length=10, choices=CATEGORY_TYPE_CHOICES)
    description = models.TextField(blank=True, default='')
    is_system = models.BooleanField(
        default=False,
        help_text='System categories cannot be deleted'
    )
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category_type', 'display_order', 'name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return f'{self.name} ({self.get_category_type_display()})'

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise ValidationError('System categories cannot be deleted.')
        super().delete(*args, **kwargs)


class Transaction(models.Model):
    """Financial transaction (income, expense, transfer, or owner's draw)."""

    TRANSACTION_TYPE_CHOICES = [
        ('expense', 'Expense'),
        ('income', 'Income'),
        ('transfer', 'Transfer'),
        ('owners_draw', "Owner's Draw"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='transactions'
    )
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='transactions',
        help_text='Required for income/expense, null for transfers'
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Always positive'
    )
    transaction_date = models.DateField()
    description = models.CharField(max_length=500)
    vendor = models.CharField(max_length=200, blank=True, default='')
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Check number, confirmation code, etc.'
    )
    is_recurring = models.BooleanField(default=False)
    recurring_source = models.ForeignKey(
        'RecurringTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_transactions'
    )
    transfer_to_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='incoming_transfers',
        help_text='For transfers only: destination account'
    )
    notes = models.TextField(blank=True, default='')
    is_reconciled = models.BooleanField(default=False)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_transactions'
    )

    class Meta:
        ordering = ['-transaction_date', '-created_at']

    def __str__(self):
        return f'{self.transaction_date} - {self.description} (${self.amount})'

    def clean(self):
        super().clean()

        # Category required for income/expense
        if self.transaction_type in ('income', 'expense') and not self.category:
            raise ValidationError({
                'category': 'Category is required for income and expense transactions.'
            })

        # Category must match transaction type
        if self.category:
            if self.transaction_type == 'income' and self.category.category_type != 'income':
                raise ValidationError({
                    'category': 'Income transactions require an income category.'
                })
            if self.transaction_type == 'expense' and self.category.category_type != 'expense':
                raise ValidationError({
                    'category': 'Expense transactions require an expense category.'
                })

        # Transfer requires destination account
        if self.transaction_type == 'transfer' and not self.transfer_to_account:
            raise ValidationError({
                'transfer_to_account': 'Transfer transactions require a destination account.'
            })

        # Can't transfer to same account
        if self.transaction_type == 'transfer' and self.transfer_to_account == self.account:
            raise ValidationError({
                'transfer_to_account': 'Cannot transfer to the same account.'
            })

        # Owner's draw must be from checking account
        if self.transaction_type == 'owners_draw' and self.account_id:
            if self.account.account_type != 'checking':
                raise ValidationError({
                    'account': "Owner's draws must come from a checking account."
                })


class Receipt(models.Model):
    """Receipt document attached to a transaction."""

    FILE_TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('jpg', 'JPEG'),
        ('png', 'PNG'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='receipts'
    )
    file = models.FileField(upload_to='receipts/%Y/%m/')
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10, choices=FILE_TYPE_CHOICES)
    file_size = models.IntegerField(help_text='File size in bytes')

    # OCR fields
    ocr_processed = models.BooleanField(default=False)
    ocr_vendor = models.CharField(max_length=200, blank=True, default='')
    ocr_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )
    ocr_date = models.DateField(null=True, blank=True)
    ocr_raw_text = models.TextField(blank=True, default='')
    ocr_confidence = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='OCR confidence score 0.00-1.00'
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_receipts'
    )

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'Receipt: {self.original_filename}'


class RecurringTransaction(models.Model):
    """Template for recurring transactions that are auto-generated."""

    FREQUENCY_CHOICES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('annually', 'Annually'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='recurring_transactions'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='recurring_transactions'
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    description = models.CharField(max_length=500)
    vendor = models.CharField(max_length=200)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    day_of_month = models.IntegerField(
        help_text='Day of month to generate (1-31)'
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text='Leave blank for ongoing')
    is_active = models.BooleanField(default=True)
    last_generated = models.DateField(null=True, blank=True)
    next_due = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_recurring_transactions'
    )

    class Meta:
        ordering = ['next_due']

    def __str__(self):
        return f'{self.vendor} - ${self.amount} ({self.get_frequency_display()})'

    def clean(self):
        super().clean()
        if self.day_of_month is not None:
            if self.day_of_month < 1 or self.day_of_month > 31:
                raise ValidationError({
                    'day_of_month': 'Day of month must be between 1 and 31.'
                })


class TaxAlert(models.Model):
    """Quarterly tax payment alert when net profit exceeds threshold."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quarter = models.IntegerField(help_text='1-4')
    year = models.IntegerField()
    threshold_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('1000.00')
    )
    actual_net_profit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00')
    )
    alert_triggered = models.BooleanField(default=False)
    alert_date = models.DateTimeField(null=True, blank=True)
    acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-year', '-quarter']
        unique_together = ['quarter', 'year']

    def __str__(self):
        return f'Q{self.quarter} {self.year} - ${self.actual_net_profit}'

    def clean(self):
        super().clean()
        if self.quarter < 1 or self.quarter > 4:
            raise ValidationError({
                'quarter': 'Quarter must be between 1 and 4.'
            })


class AuditLog(models.Model):
    """Immutable audit log for all financial data changes."""

    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=10, choices=ACTION_CHOICES, db_index=True)
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.UUIDField(db_index=True)
    object_repr = models.CharField(max_length=500)
    changes = models.JSONField(default=dict, help_text='Before/after values')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        indexes = [
            models.Index(fields=['-created_at', 'action', 'model_name'], name='audit_log_filter_idx'),
        ]

    def __str__(self):
        return f'{self.action} {self.model_name} by {self.user} at {self.created_at}'

    def save(self, *args, **kwargs):
        # Prevent updates to existing audit logs
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValidationError('Audit logs cannot be modified.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Audit logs cannot be deleted.')


class CSVImport(models.Model):
    """Record of CSV file imports."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name='csv_imports'
    )
    file = models.FileField(upload_to='csv_imports/%Y/%m/')
    original_filename = models.CharField(max_length=255)
    row_count = models.IntegerField(default=0)
    imported_count = models.IntegerField(default=0)
    skipped_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    errors = models.JSONField(default=list, help_text='List of row errors')
    imported_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='csv_imports'
    )

    class Meta:
        ordering = ['-imported_at']
        verbose_name = 'CSV Import'
        verbose_name_plural = 'CSV Imports'

    def __str__(self):
        return f'{self.original_filename} ({self.get_status_display()})'
