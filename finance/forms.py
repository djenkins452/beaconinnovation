"""
Forms for the finance app.
"""
from datetime import date

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from .models import Receipt, Transaction, Account, Category


class ReceiptUploadForm(forms.ModelForm):
    """Form for uploading receipt files."""

    class Meta:
        model = Receipt
        fields = ['file']

    def clean_file(self):
        """Validate uploaded file type and size."""
        file = self.cleaned_data.get('file')

        if not file:
            raise ValidationError('No file was uploaded.')

        # Check file size
        max_size_bytes = settings.FINANCE_RECEIPT_MAX_SIZE_MB * 1024 * 1024
        if file.size > max_size_bytes:
            raise ValidationError(
                f'File too large. Maximum size is {settings.FINANCE_RECEIPT_MAX_SIZE_MB}MB.'
            )

        # Get file extension
        filename = file.name.lower()
        extension = filename.rsplit('.', 1)[-1] if '.' in filename else ''

        # Check file type
        allowed_types = settings.FINANCE_ALLOWED_RECEIPT_TYPES
        if extension not in allowed_types:
            raise ValidationError(
                f'Invalid file type. Allowed types: {", ".join(allowed_types)}'
            )

        return file


def get_file_type(filename: str) -> str:
    """
    Get the file type from a filename.

    Returns 'jpg' for both .jpg and .jpeg extensions.
    """
    extension = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''

    if extension == 'jpeg':
        return 'jpg'

    return extension


def validate_receipt_file(file) -> dict:
    """
    Validate a receipt file and return file info.

    Args:
        file: Uploaded file object

    Returns:
        Dictionary with:
        - valid: bool
        - error: str or None
        - file_type: str (if valid)
        - file_size: int (if valid)
        - original_filename: str (if valid)

    Raises:
        ValidationError if file is invalid
    """
    if not file:
        return {
            'valid': False,
            'error': 'No file was uploaded.',
        }

    # Check file size
    max_size_bytes = settings.FINANCE_RECEIPT_MAX_SIZE_MB * 1024 * 1024
    if file.size > max_size_bytes:
        return {
            'valid': False,
            'error': f'File too large. Maximum size is {settings.FINANCE_RECEIPT_MAX_SIZE_MB}MB.',
        }

    # Get file extension
    filename = file.name
    extension = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''

    # Check file type
    allowed_types = settings.FINANCE_ALLOWED_RECEIPT_TYPES
    if extension not in allowed_types:
        return {
            'valid': False,
            'error': f'Invalid file type. Allowed types: {", ".join(allowed_types)}',
        }

    # Normalize extension
    file_type = 'jpg' if extension == 'jpeg' else extension

    return {
        'valid': True,
        'error': None,
        'file_type': file_type,
        'file_size': file.size,
        'original_filename': filename,
    }


class TransactionForm(forms.ModelForm):
    """Form for creating and editing transactions."""

    class Meta:
        model = Transaction
        fields = [
            'account',
            'transaction_type',
            'category',
            'amount',
            'transaction_date',
            'description',
            'vendor',
            'reference_number',
            'transfer_to_account',
            'notes',
        ]
        widgets = {
            'transaction_date': forms.DateInput(
                attrs={'type': 'date'},
                format='%Y-%m-%d'
            ),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'description': forms.TextInput(attrs={'placeholder': 'Description'}),
            'vendor': forms.TextInput(attrs={'placeholder': 'Vendor (optional)'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Set default date to today
        if not self.instance.pk:
            self.initial['transaction_date'] = date.today()

        # Filter accounts to active only
        self.fields['account'].queryset = Account.objects.filter(is_active=True)
        self.fields['transfer_to_account'].queryset = Account.objects.filter(is_active=True)
        self.fields['transfer_to_account'].required = False

        # Filter categories to active only
        self.fields['category'].queryset = Category.objects.filter(is_active=True)
        self.fields['category'].required = False

        # Add CSS classes for styling
        for field_name, field in self.fields.items():
            field.widget.attrs.setdefault('class', 'form-control')

    def clean(self):
        cleaned_data = super().clean()
        transaction_type = cleaned_data.get('transaction_type')
        category = cleaned_data.get('category')
        account = cleaned_data.get('account')
        transfer_to_account = cleaned_data.get('transfer_to_account')
        transaction_date = cleaned_data.get('transaction_date')

        # Validate category for income/expense
        if transaction_type in ('income', 'expense'):
            if not category:
                self.add_error('category', 'Category is required for income and expense transactions.')
            elif transaction_type == 'income' and category.category_type != 'income':
                self.add_error('category', 'Income transactions require an income category.')
            elif transaction_type == 'expense' and category.category_type != 'expense':
                self.add_error('category', 'Expense transactions require an expense category.')

        # Validate transfer
        if transaction_type == 'transfer':
            if not transfer_to_account:
                self.add_error('transfer_to_account', 'Transfer transactions require a destination account.')
            elif transfer_to_account == account:
                self.add_error('transfer_to_account', 'Cannot transfer to the same account.')

        # Validate owner's draw
        if transaction_type == 'owners_draw':
            if account and account.account_type != 'checking':
                self.add_error('account', "Owner's draws must come from a checking account.")

        # Validate date not in future
        if transaction_date and transaction_date > date.today():
            self.add_error('transaction_date', 'Transaction date cannot be in the future.')

        return cleaned_data


class TransactionFilterForm(forms.Form):
    """Form for filtering transaction list."""

    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True),
        required=False,
        empty_label='All Accounts'
    )
    transaction_type = forms.ChoiceField(
        choices=[('', 'All Types')] + list(Transaction.TRANSACTION_TYPE_CHOICES),
        required=False
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label='All Categories'
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'})
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Search description or vendor'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.setdefault('class', 'form-control')


class AccountForm(forms.ModelForm):
    """Form for creating and editing accounts."""

    class Meta:
        model = Account
        fields = [
            'name',
            'account_type',
            'institution',
            'last_four',
            'is_personal',
            'is_active',
            'opening_balance',
            'opening_balance_date',
            'notes',
        ]
        widgets = {
            'opening_balance_date': forms.DateInput(
                attrs={'type': 'date'},
                format='%Y-%m-%d'
            ),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'opening_balance': forms.NumberInput(attrs={'step': '0.01'}),
            'last_four': forms.TextInput(attrs={
                'maxlength': '4',
                'placeholder': 'Last 4 digits',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add CSS classes for styling
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                continue  # Don't add form-control to checkboxes
            field.widget.attrs.setdefault('class', 'form-control')

    def clean_last_four(self):
        """Validate last four digits."""
        last_four = self.cleaned_data.get('last_four', '')
        if last_four and not last_four.isdigit():
            raise ValidationError('Last four must contain only digits.')
        return last_four

    def clean_opening_balance(self):
        """Validate opening balance is non-negative."""
        balance = self.cleaned_data.get('opening_balance')
        if balance is not None and balance < 0:
            raise ValidationError('Opening balance cannot be negative.')
        return balance


class CategoryForm(forms.ModelForm):
    """Form for creating and editing categories."""

    class Meta:
        model = Category
        fields = [
            'name',
            'category_type',
            'description',
            'is_active',
            'display_order',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'display_order': forms.NumberInput(attrs={'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add CSS classes for styling
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                continue  # Don't add form-control to checkboxes
            field.widget.attrs.setdefault('class', 'form-control')

        # If editing a system category, prevent changing the type
        if self.instance.pk and self.instance.is_system:
            self.fields['category_type'].widget.attrs['disabled'] = True
            self.fields['category_type'].help_text = 'System categories cannot change type.'

    def clean_name(self):
        """Validate category name is unique within type."""
        name = self.cleaned_data.get('name')
        # Note: category_type validation happens in clean() after all field cleaners
        return name

    def _validate_unique_name(self, name, category_type):
        """Check that name is unique within category type."""
        if name and category_type:
            qs = Category.objects.filter(name__iexact=name, category_type=category_type)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error(
                    'name',
                    f'A {category_type} category with this name already exists.'
                )

    def clean_display_order(self):
        """Validate display order is non-negative."""
        display_order = self.cleaned_data.get('display_order')
        if display_order is not None and display_order < 0:
            raise ValidationError('Display order cannot be negative.')
        return display_order

    def clean(self):
        cleaned_data = super().clean()

        # For system categories being edited, preserve the original category_type
        if self.instance.pk and self.instance.is_system:
            cleaned_data['category_type'] = self.instance.category_type

        # Validate unique name within category type
        name = cleaned_data.get('name')
        category_type = cleaned_data.get('category_type')
        self._validate_unique_name(name, category_type)

        return cleaned_data
