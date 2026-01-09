"""
CSV import functionality for the finance app.

Supports American Express statement CSV format.
"""
import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import transaction as db_transaction

from .models import Account, Category, Transaction, CSVImport


# Amex CSV columns
AMEX_COLUMNS = [
    'Date',
    'Description',
    'Amount',
    'Extended Details',
    'Appears On Your Statement As',
    'Address',
    'City/State',
    'Zip Code',
    'Country',
    'Reference',
    'Category',
]


@dataclass
class ParsedRow:
    """Represents a parsed CSV row ready for import."""
    row_number: int
    date: Optional[datetime.date]
    description: str
    amount: Optional[Decimal]
    vendor: str
    reference: str
    amex_category: str
    suggested_category_id: Optional[str]
    is_duplicate: bool
    duplicate_transaction_id: Optional[str]
    error: Optional[str]
    raw_data: dict

    @property
    def is_valid(self) -> bool:
        """Check if row can be imported."""
        return self.error is None and self.date is not None and self.amount is not None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'row_number': self.row_number,
            'date': self.date.isoformat() if self.date else None,
            'description': self.description,
            'amount': str(self.amount) if self.amount else None,
            'vendor': self.vendor,
            'reference': self.reference,
            'amex_category': self.amex_category,
            'suggested_category_id': self.suggested_category_id,
            'is_duplicate': self.is_duplicate,
            'duplicate_transaction_id': self.duplicate_transaction_id,
            'error': self.error,
        }


class AmexCSVParser:
    """Parser for American Express CSV statement format."""

    def __init__(self, account: Account):
        """
        Initialize parser for a specific account.

        Args:
            account: The Account to import transactions into
        """
        self.account = account
        self.category_map = self._build_category_map()

    def _build_category_map(self) -> dict:
        """
        Build a mapping from Amex categories to our categories.

        Returns dict of amex_category_name -> Category
        """
        # Map common Amex categories to our categories
        amex_to_ours = {
            # Amex category -> Our category name
            'Business Services': 'Professional Services',
            'Business Services-Other': 'Professional Services',
            'Office Supplies': 'Office Supplies',
            'Computer Supplies': 'Equipment',
            'Telecommunications': 'Software & Subscriptions',
            'Software': 'Software & Subscriptions',
            'Advertising': 'Advertising & Marketing',
            'Marketing': 'Advertising & Marketing',
            'Education': 'Education & Training',
            'Travel': 'Travel',
            'Airlines': 'Travel',
            'Hotels': 'Travel',
            'Rental Cars': 'Travel',
            'Restaurants': 'Meals & Entertainment',
            'Restaurant': 'Meals & Entertainment',
            'Dining': 'Meals & Entertainment',
            'Fees & Adjustments': 'Bank Fees & Interest',
            'Fees': 'Bank Fees & Interest',
            'Interest': 'Bank Fees & Interest',
            'Merchandise & Supplies': 'Office Supplies',
            'Merchandise': 'Office Supplies',
            'Other': 'Miscellaneous',
        }

        # Load our categories
        our_categories = {
            c.name: c for c in Category.objects.filter(
                is_active=True,
                category_type='expense'
            )
        }

        # Build the mapping
        result = {}
        for amex_cat, our_cat_name in amex_to_ours.items():
            if our_cat_name in our_categories:
                result[amex_cat.lower()] = our_categories[our_cat_name]

        return result

    def get_suggested_category(self, amex_category: str) -> Optional[Category]:
        """
        Get suggested category based on Amex category.

        Args:
            amex_category: The category from Amex CSV

        Returns:
            Category or None if no mapping found
        """
        if not amex_category:
            return None

        # Try exact match first (case insensitive)
        key = amex_category.lower().strip()
        if key in self.category_map:
            return self.category_map[key]

        # Try partial match
        for amex_key, category in self.category_map.items():
            if amex_key in key or key in amex_key:
                return category

        return None

    def parse_date(self, date_str: str) -> Optional[datetime.date]:
        """
        Parse date from Amex format (MM/DD/YYYY or M/D/YYYY).

        Args:
            date_str: Date string from CSV

        Returns:
            date object or None if parsing fails
        """
        if not date_str:
            return None

        date_str = date_str.strip()

        # Try common formats
        formats = [
            '%m/%d/%Y',  # 01/15/2026
            '%m/%d/%y',  # 01/15/26
            '%Y-%m-%d',  # 2026-01-15
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        return None

    def parse_amount(self, amount_str: str) -> Optional[Decimal]:
        """
        Parse amount from CSV.

        Amex uses positive for charges, negative for credits/refunds.
        We store all amounts as positive.

        Args:
            amount_str: Amount string from CSV

        Returns:
            Decimal amount (always positive) or None if parsing fails
        """
        if not amount_str:
            return None

        # Clean the string
        amount_str = amount_str.strip()
        amount_str = amount_str.replace('$', '').replace(',', '')

        try:
            amount = Decimal(amount_str)
            return abs(amount)  # Always positive
        except InvalidOperation:
            return None

    def is_refund(self, amount_str: str) -> bool:
        """
        Check if transaction is a refund (negative amount in Amex).

        Args:
            amount_str: Amount string from CSV

        Returns:
            True if this is a refund/credit
        """
        if not amount_str:
            return False

        amount_str = amount_str.strip().replace('$', '').replace(',', '')

        try:
            return Decimal(amount_str) < 0
        except InvalidOperation:
            return False

    def generate_row_hash(self, row: dict) -> str:
        """
        Generate a hash for duplicate detection.

        Uses date, description, amount, and reference.

        Args:
            row: Raw CSV row dict

        Returns:
            MD5 hash string
        """
        hash_input = '|'.join([
            str(row.get('Date', '')),
            str(row.get('Description', '')),
            str(row.get('Amount', '')),
            str(row.get('Reference', '')),
        ])
        return hashlib.md5(hash_input.encode()).hexdigest()

    def check_duplicate(self, parsed_row: ParsedRow) -> tuple[bool, Optional[str]]:
        """
        Check if a transaction already exists.

        Looks for matching date, amount, and description.

        Args:
            parsed_row: The parsed row to check

        Returns:
            Tuple of (is_duplicate, existing_transaction_id)
        """
        if not parsed_row.date or not parsed_row.amount:
            return False, None

        # Look for existing transaction with same date, amount, and description
        existing = Transaction.objects.filter(
            account=self.account,
            transaction_date=parsed_row.date,
            amount=parsed_row.amount,
            description__iexact=parsed_row.description.strip()[:500],
        ).first()

        if existing:
            return True, str(existing.id)

        # Also check by reference number if available
        if parsed_row.reference:
            existing = Transaction.objects.filter(
                account=self.account,
                reference_number=parsed_row.reference,
            ).first()
            if existing:
                return True, str(existing.id)

        return False, None

    def parse_row(self, row: dict, row_number: int) -> ParsedRow:
        """
        Parse a single CSV row.

        Args:
            row: Dict of column name -> value
            row_number: 1-based row number for error messages

        Returns:
            ParsedRow with parsed data or error
        """
        error = None

        # Parse date
        date_str = row.get('Date', '')
        parsed_date = self.parse_date(date_str)
        if not parsed_date:
            error = f'Invalid date format: {date_str}'

        # Parse amount
        amount_str = row.get('Amount', '')
        parsed_amount = self.parse_amount(amount_str)
        if parsed_amount is None and error is None:
            error = f'Invalid amount format: {amount_str}'

        # Get description - use "Appears On Your Statement As" if available, else Description
        description = row.get('Appears On Your Statement As', '').strip()
        if not description:
            description = row.get('Description', '').strip()
        if not description and error is None:
            error = 'Missing description'

        # Extract vendor from description (usually first part before any codes)
        vendor = description.split('  ')[0] if description else ''

        # Get reference
        reference = row.get('Reference', '').strip()

        # Get Amex category
        amex_category = row.get('Category', '').strip()

        # Get suggested category
        suggested = self.get_suggested_category(amex_category)

        parsed = ParsedRow(
            row_number=row_number,
            date=parsed_date,
            description=description[:500] if description else '',
            amount=parsed_amount,
            vendor=vendor[:200] if vendor else '',
            reference=reference[:100] if reference else '',
            amex_category=amex_category,
            suggested_category_id=str(suggested.id) if suggested else None,
            is_duplicate=False,
            duplicate_transaction_id=None,
            error=error,
            raw_data=row,
        )

        # Check for duplicates (only if row is otherwise valid)
        if error is None:
            is_dup, dup_id = self.check_duplicate(parsed)
            parsed.is_duplicate = is_dup
            parsed.duplicate_transaction_id = dup_id

        return parsed

    def parse_csv(self, file_content: str) -> list[ParsedRow]:
        """
        Parse entire CSV file.

        Args:
            file_content: CSV file content as string

        Returns:
            List of ParsedRow objects
        """
        results = []

        # Try to detect if file has headers
        reader = csv.DictReader(io.StringIO(file_content))

        # Check if headers match expected Amex format
        if reader.fieldnames:
            # Normalize headers
            normalized = [h.strip() for h in reader.fieldnames]
            has_date = 'Date' in normalized or 'date' in [h.lower() for h in normalized]
            has_amount = 'Amount' in normalized or 'amount' in [h.lower() for h in normalized]

            if not (has_date and has_amount):
                # File might not have headers, try reading as headerless
                return self._parse_headerless_csv(file_content)

        row_number = 1
        for row in reader:
            parsed = self.parse_row(row, row_number)
            results.append(parsed)
            row_number += 1

        return results

    def _parse_headerless_csv(self, file_content: str) -> list[ParsedRow]:
        """
        Parse CSV without headers, assuming Amex column order.

        Args:
            file_content: CSV file content

        Returns:
            List of ParsedRow objects
        """
        results = []
        reader = csv.reader(io.StringIO(file_content))

        row_number = 1
        for csv_row in reader:
            # Skip empty rows
            if not csv_row or not any(csv_row):
                continue

            # Map to dict using expected Amex columns
            row = {}
            for i, col in enumerate(AMEX_COLUMNS):
                if i < len(csv_row):
                    row[col] = csv_row[i]

            parsed = self.parse_row(row, row_number)
            results.append(parsed)
            row_number += 1

        return results


class CSVImporter:
    """Handles the actual import of parsed CSV data into transactions."""

    def __init__(self, csv_import: CSVImport, user):
        """
        Initialize importer.

        Args:
            csv_import: The CSVImport record tracking this import
            user: The user performing the import
        """
        self.csv_import = csv_import
        self.user = user
        self.account = csv_import.account

    def import_rows(
        self,
        parsed_rows: list[ParsedRow],
        category_overrides: dict = None,
        skip_duplicates: bool = True,
    ) -> dict:
        """
        Import parsed rows as transactions.

        Args:
            parsed_rows: List of ParsedRow objects to import
            category_overrides: Dict of row_number -> category_id for manual overrides
            skip_duplicates: If True, skip rows marked as duplicates

        Returns:
            Dict with counts: imported, skipped, errors
        """
        category_overrides = category_overrides or {}

        imported = 0
        skipped = 0
        errors = []

        # Load categories for quick lookup
        categories = {
            str(c.id): c for c in Category.objects.filter(is_active=True)
        }

        with db_transaction.atomic():
            for row in parsed_rows:
                # Skip invalid rows
                if not row.is_valid:
                    errors.append({
                        'row': row.row_number,
                        'error': row.error or 'Invalid row data',
                    })
                    continue

                # Skip duplicates if requested
                if row.is_duplicate and skip_duplicates:
                    skipped += 1
                    continue

                # Get category (override or suggested)
                category_id = category_overrides.get(
                    str(row.row_number),
                    row.suggested_category_id
                )
                category = categories.get(category_id) if category_id else None

                # Determine transaction type
                # Amex charges are expenses, negative amounts are refunds (income)
                is_refund = row.raw_data.get('Amount', '').strip().startswith('-')
                if is_refund:
                    tx_type = 'income'
                    # For refunds, use income category if expense category was suggested
                    if category and category.category_type == 'expense':
                        # Try to find Refunds category
                        refund_cat = Category.objects.filter(
                            name='Refunds',
                            is_active=True
                        ).first()
                        category = refund_cat
                else:
                    tx_type = 'expense'

                try:
                    Transaction.objects.create(
                        account=self.account,
                        transaction_type=tx_type,
                        category=category,
                        amount=row.amount,
                        transaction_date=row.date,
                        description=row.description,
                        vendor=row.vendor,
                        reference_number=row.reference,
                        created_by=self.user,
                    )
                    imported += 1
                except Exception as e:
                    errors.append({
                        'row': row.row_number,
                        'error': str(e),
                    })

        # Update CSVImport record
        self.csv_import.imported_count = imported
        self.csv_import.skipped_count = skipped
        self.csv_import.error_count = len(errors)
        self.csv_import.errors = errors
        self.csv_import.status = 'completed' if not errors else 'completed'
        self.csv_import.save()

        return {
            'imported': imported,
            'skipped': skipped,
            'errors': errors,
        }


def validate_csv_file(file) -> dict:
    """
    Validate an uploaded CSV file.

    Args:
        file: Uploaded file object

    Returns:
        Dict with 'valid', 'error', and file info
    """
    if not file:
        return {'valid': False, 'error': 'No file uploaded'}

    # Check extension
    filename = file.name.lower()
    if not filename.endswith('.csv'):
        return {'valid': False, 'error': 'File must be a CSV file'}

    # Check size (max 5MB)
    max_size = 5 * 1024 * 1024
    if file.size > max_size:
        return {'valid': False, 'error': 'File too large. Maximum size is 5MB'}

    # Try to read and parse
    try:
        content = file.read().decode('utf-8')
        file.seek(0)  # Reset for later use

        # Check it has content
        if not content.strip():
            return {'valid': False, 'error': 'File is empty'}

        # Try parsing first few rows
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)

        if len(rows) < 2:  # Header + at least 1 data row
            return {'valid': False, 'error': 'File must have at least one data row'}

        # Validate headers - check for required columns
        header_row = rows[0] if rows else []
        normalized_headers = [h.strip().lower() for h in header_row]

        # Check for required columns (Date and Amount are essential)
        required_columns = ['date', 'amount']
        missing_columns = []
        for col in required_columns:
            if col not in normalized_headers:
                missing_columns.append(col.title())

        if missing_columns:
            return {
                'valid': False,
                'error': f'Missing required column(s): {", ".join(missing_columns)}. '
                         f'Expected Amex CSV format with Date, Amount columns.'
            }

        # Check for description column (either Description or Appears On Your Statement As)
        has_description = (
            'description' in normalized_headers or
            'appears on your statement as' in normalized_headers
        )
        if not has_description:
            return {
                'valid': False,
                'error': 'Missing description column. Expected "Description" or '
                         '"Appears On Your Statement As" column.'
            }

        # Validate maximum row count to prevent memory issues
        max_rows = 10000
        if len(rows) > max_rows:
            return {
                'valid': False,
                'error': f'File has too many rows ({len(rows)}). Maximum allowed is {max_rows}.'
            }

        return {
            'valid': True,
            'error': None,
            'row_count': len(rows) - 1,  # Exclude header
            'filename': file.name,
            'size': file.size,
            'headers': header_row,
        }

    except UnicodeDecodeError:
        return {'valid': False, 'error': 'File encoding not supported. Please use UTF-8'}
    except csv.Error as e:
        return {'valid': False, 'error': f'Invalid CSV format: {e}'}
