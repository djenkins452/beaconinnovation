"""
Tests for CSV import functionality (Phase 7).
"""
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from finance.importers import AmexCSVParser, CSVImporter, validate_csv_file
from finance.models import Account, Category, Transaction, CSVImport


# Sample Amex CSV content
SAMPLE_AMEX_CSV = """Date,Description,Amount,Extended Details,Appears On Your Statement As,Address,City/State,Zip Code,Country,Reference,Category
01/15/2026,AMAZON.COM,49.99,AMAZON PURCHASE,AMAZON.COM*A12345,410 TERRY AVE N,SEATTLE/WA,98109,US,320262012345678,Merchandise & Supplies
01/16/2026,ADOBE SYSTEMS,14.99,CREATIVE CLOUD,ADOBE *CREATIVE CLO,345 PARK AVE,SAN JOSE/CA,95110,US,320262012345679,Software
01/17/2026,DELTA AIRLINES,299.00,FLIGHT DL1234,DELTA AIR LINES,1030 DELTA BLVD,ATLANTA/GA,30354,US,320262012345680,Travel
01/18/2026,CHIPOTLE,-10.50,REFUND,CHIPOTLE MEXICAN,123 MAIN ST,DENVER/CO,80202,US,320262012345681,Restaurant
"""

SAMPLE_AMEX_CSV_NO_HEADER = """01/15/2026,AMAZON.COM,49.99,AMAZON PURCHASE,AMAZON.COM*A12345,410 TERRY AVE N,SEATTLE/WA,98109,US,320262012345678,Merchandise & Supplies
01/16/2026,ADOBE SYSTEMS,14.99,CREATIVE CLOUD,ADOBE *CREATIVE CLO,345 PARK AVE,SAN JOSE/CA,95110,US,320262012345679,Software
"""

INVALID_CSV = """not,a,valid,csv,with,missing,columns
bad data here
"""


class AmexCSVParserTests(TestCase):
    """Tests for AmexCSVParser class."""

    def setUp(self):
        """Set up test data."""
        self.account = Account.objects.create(
            name='Test Amex',
            account_type='credit_card',
            institution='American Express',
        )
        # Categories are seeded by migration
        self.parser = AmexCSVParser(self.account)

    def test_parse_date_mm_dd_yyyy(self):
        """Test parsing date in MM/DD/YYYY format."""
        result = self.parser.parse_date('01/15/2026')
        self.assertEqual(result, date(2026, 1, 15))

    def test_parse_date_m_d_yyyy(self):
        """Test parsing date in M/D/YYYY format."""
        result = self.parser.parse_date('1/5/2026')
        self.assertEqual(result, date(2026, 1, 5))

    def test_parse_date_iso_format(self):
        """Test parsing date in ISO format."""
        result = self.parser.parse_date('2026-01-15')
        self.assertEqual(result, date(2026, 1, 15))

    def test_parse_date_invalid(self):
        """Test parsing invalid date returns None."""
        self.assertIsNone(self.parser.parse_date('invalid'))
        self.assertIsNone(self.parser.parse_date(''))

    def test_parse_amount_positive(self):
        """Test parsing positive amount."""
        result = self.parser.parse_amount('49.99')
        self.assertEqual(result, Decimal('49.99'))

    def test_parse_amount_with_dollar_sign(self):
        """Test parsing amount with dollar sign."""
        result = self.parser.parse_amount('$49.99')
        self.assertEqual(result, Decimal('49.99'))

    def test_parse_amount_with_comma(self):
        """Test parsing amount with comma."""
        result = self.parser.parse_amount('1,234.56')
        self.assertEqual(result, Decimal('1234.56'))

    def test_parse_amount_negative(self):
        """Test parsing negative amount returns positive."""
        result = self.parser.parse_amount('-10.50')
        self.assertEqual(result, Decimal('10.50'))

    def test_parse_amount_invalid(self):
        """Test parsing invalid amount returns None."""
        self.assertIsNone(self.parser.parse_amount('invalid'))
        self.assertIsNone(self.parser.parse_amount(''))

    def test_is_refund_negative(self):
        """Test is_refund returns True for negative amounts."""
        self.assertTrue(self.parser.is_refund('-10.50'))
        self.assertTrue(self.parser.is_refund('-$10.50'))

    def test_is_refund_positive(self):
        """Test is_refund returns False for positive amounts."""
        self.assertFalse(self.parser.is_refund('49.99'))
        self.assertFalse(self.parser.is_refund('$49.99'))

    def test_parse_csv_with_headers(self):
        """Test parsing complete CSV with headers."""
        results = self.parser.parse_csv(SAMPLE_AMEX_CSV)

        self.assertEqual(len(results), 4)

        # Check first row
        row1 = results[0]
        self.assertEqual(row1.row_number, 1)
        self.assertEqual(row1.date, date(2026, 1, 15))
        self.assertEqual(row1.amount, Decimal('49.99'))
        self.assertIn('AMAZON', row1.description)
        self.assertTrue(row1.is_valid)

        # Check refund row
        row4 = results[3]
        self.assertEqual(row4.date, date(2026, 1, 18))
        self.assertEqual(row4.amount, Decimal('10.50'))  # Positive

    def test_parse_row_missing_date(self):
        """Test parsing row with missing date returns error."""
        row = {
            'Date': '',
            'Description': 'Test',
            'Amount': '10.00',
        }
        result = self.parser.parse_row(row, 1)
        self.assertFalse(result.is_valid)
        self.assertIn('date', result.error.lower())

    def test_parse_row_missing_amount(self):
        """Test parsing row with missing amount returns error."""
        row = {
            'Date': '01/15/2026',
            'Description': 'Test',
            'Amount': '',
        }
        result = self.parser.parse_row(row, 1)
        self.assertFalse(result.is_valid)
        self.assertIn('amount', result.error.lower())

    def test_parse_row_missing_description(self):
        """Test parsing row with missing description returns error."""
        row = {
            'Date': '01/15/2026',
            'Description': '',
            'Amount': '10.00',
            'Appears On Your Statement As': '',
        }
        result = self.parser.parse_row(row, 1)
        self.assertFalse(result.is_valid)
        self.assertIn('description', result.error.lower())

    def test_category_mapping(self):
        """Test Amex to local category mapping."""
        results = self.parser.parse_csv(SAMPLE_AMEX_CSV)

        # Travel should map to Travel category
        travel_row = results[2]
        if travel_row.suggested_category_id:
            category = Category.objects.get(id=travel_row.suggested_category_id)
            self.assertEqual(category.name, 'Travel')

    def test_duplicate_detection(self):
        """Test duplicate detection finds existing transactions."""
        # Create existing transaction
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            amount=Decimal('49.99'),
            transaction_date=date(2026, 1, 15),
            description='AMAZON.COM*A12345',
        )

        results = self.parser.parse_csv(SAMPLE_AMEX_CSV)

        # First row should be marked as duplicate
        self.assertTrue(results[0].is_duplicate)
        self.assertIsNotNone(results[0].duplicate_transaction_id)

        # Other rows should not be duplicates
        self.assertFalse(results[1].is_duplicate)


class CSVImporterTests(TestCase):
    """Tests for CSVImporter class."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.account = Account.objects.create(
            name='Test Amex',
            account_type='credit_card',
            institution='American Express',
        )
        # Create CSV import record
        self.csv_import = CSVImport.objects.create(
            account=self.account,
            original_filename='test.csv',
            row_count=4,
            status='pending',
            imported_by=self.user,
        )

    def test_import_rows_creates_transactions(self):
        """Test that import creates transaction records."""
        parser = AmexCSVParser(self.account)
        parsed_rows = parser.parse_csv(SAMPLE_AMEX_CSV)

        importer = CSVImporter(self.csv_import, self.user)
        results = importer.import_rows(parsed_rows)

        # Should import all 4 rows
        self.assertEqual(results['imported'], 4)
        self.assertEqual(results['skipped'], 0)
        self.assertEqual(results['errors'], [])

        # Verify transactions created
        transactions = Transaction.objects.filter(account=self.account)
        self.assertEqual(transactions.count(), 4)

    def test_import_skips_duplicates(self):
        """Test that import skips duplicate transactions."""
        # Create existing transaction
        Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            amount=Decimal('49.99'),
            transaction_date=date(2026, 1, 15),
            description='AMAZON.COM*A12345',
        )

        parser = AmexCSVParser(self.account)
        parsed_rows = parser.parse_csv(SAMPLE_AMEX_CSV)

        importer = CSVImporter(self.csv_import, self.user)
        results = importer.import_rows(parsed_rows, skip_duplicates=True)

        # Should skip the duplicate
        self.assertEqual(results['imported'], 3)
        self.assertEqual(results['skipped'], 1)

    def test_import_with_category_override(self):
        """Test import with manual category override."""
        # Get a category
        category = Category.objects.filter(
            is_active=True,
            category_type='expense'
        ).first()

        parser = AmexCSVParser(self.account)
        parsed_rows = parser.parse_csv(SAMPLE_AMEX_CSV)

        importer = CSVImporter(self.csv_import, self.user)
        results = importer.import_rows(
            parsed_rows,
            category_overrides={'1': str(category.id)}
        )

        # Check first transaction has the overridden category
        first_tx = Transaction.objects.filter(
            account=self.account,
            transaction_date=date(2026, 1, 15)
        ).first()
        self.assertEqual(first_tx.category, category)

    def test_import_sets_refund_as_income(self):
        """Test that negative amounts are imported as income."""
        parser = AmexCSVParser(self.account)
        parsed_rows = parser.parse_csv(SAMPLE_AMEX_CSV)

        importer = CSVImporter(self.csv_import, self.user)
        importer.import_rows(parsed_rows)

        # Find the refund transaction (Chipotle -10.50)
        refund_tx = Transaction.objects.filter(
            account=self.account,
            amount=Decimal('10.50')
        ).first()
        self.assertEqual(refund_tx.transaction_type, 'income')

    def test_import_updates_csv_import_record(self):
        """Test that import updates CSVImport record."""
        parser = AmexCSVParser(self.account)
        parsed_rows = parser.parse_csv(SAMPLE_AMEX_CSV)

        importer = CSVImporter(self.csv_import, self.user)
        importer.import_rows(parsed_rows)

        self.csv_import.refresh_from_db()
        self.assertEqual(self.csv_import.status, 'completed')
        self.assertEqual(self.csv_import.imported_count, 4)


class ValidateCSVFileTests(TestCase):
    """Tests for validate_csv_file function."""

    def test_validate_valid_csv(self):
        """Test validating a valid CSV file."""
        content = SAMPLE_AMEX_CSV.encode('utf-8')
        file = SimpleUploadedFile('test.csv', content, content_type='text/csv')

        result = validate_csv_file(file)
        self.assertTrue(result['valid'])
        self.assertEqual(result['row_count'], 4)  # 4 data rows

    def test_validate_no_file(self):
        """Test validating with no file."""
        result = validate_csv_file(None)
        self.assertFalse(result['valid'])
        self.assertIn('No file', result['error'])

    def test_validate_wrong_extension(self):
        """Test validating file with wrong extension."""
        file = SimpleUploadedFile('test.txt', b'content', content_type='text/plain')

        result = validate_csv_file(file)
        self.assertFalse(result['valid'])
        self.assertIn('CSV', result['error'])

    def test_validate_empty_file(self):
        """Test validating empty file."""
        file = SimpleUploadedFile('test.csv', b'', content_type='text/csv')

        result = validate_csv_file(file)
        self.assertFalse(result['valid'])
        self.assertIn('empty', result['error'].lower())

    def test_validate_file_too_large(self):
        """Test validating file that's too large."""
        # Create 6MB file
        content = b'x' * (6 * 1024 * 1024)
        file = SimpleUploadedFile('test.csv', content, content_type='text/csv')

        result = validate_csv_file(file)
        self.assertFalse(result['valid'])
        self.assertIn('large', result['error'].lower())


class CSVImportViewTests(TestCase):
    """Tests for CSV import views."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        self.account = Account.objects.create(
            name='Test Amex',
            account_type='credit_card',
            institution='American Express',
        )

    def test_upload_view_requires_login(self):
        """Test that upload view requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:csv_import_upload'))
        self.assertEqual(response.status_code, 302)

    def test_upload_view_renders(self):
        """Test that upload view renders correctly."""
        response = self.client.get(reverse('finance:csv_import_upload'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/csv_import.html')

    def test_upload_view_shows_accounts(self):
        """Test that upload view shows account options."""
        response = self.client.get(reverse('finance:csv_import_upload'))
        self.assertContains(response, self.account.name)

    def test_upload_creates_import_record(self):
        """Test that upload creates CSVImport record."""
        content = SAMPLE_AMEX_CSV.encode('utf-8')
        file = SimpleUploadedFile('test.csv', content, content_type='text/csv')

        response = self.client.post(
            reverse('finance:csv_import_upload'),
            {
                'account': self.account.id,
                'file': file,
            }
        )

        # Should redirect to preview
        self.assertEqual(response.status_code, 302)

        # Should create import record
        import_record = CSVImport.objects.first()
        self.assertIsNotNone(import_record)
        self.assertEqual(import_record.account, self.account)
        self.assertEqual(import_record.status, 'pending')

    def test_upload_without_account(self):
        """Test upload without account shows error."""
        content = SAMPLE_AMEX_CSV.encode('utf-8')
        file = SimpleUploadedFile('test.csv', content, content_type='text/csv')

        response = self.client.post(
            reverse('finance:csv_import_upload'),
            {'file': file}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'select an account')

    def test_upload_without_file(self):
        """Test upload without file shows error."""
        response = self.client.post(
            reverse('finance:csv_import_upload'),
            {'account': self.account.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'select a CSV file')

    def test_preview_view_requires_login(self):
        """Test that preview view requires authentication."""
        import_record = CSVImport.objects.create(
            account=self.account,
            original_filename='test.csv',
            row_count=4,
            status='pending',
            imported_by=self.user,
        )
        self.client.logout()
        response = self.client.get(
            reverse('finance:csv_import_preview', args=[import_record.id])
        )
        self.assertEqual(response.status_code, 302)

    def test_preview_view_renders(self):
        """Test that preview view renders correctly."""
        content = SAMPLE_AMEX_CSV.encode('utf-8')
        file = SimpleUploadedFile('test.csv', content, content_type='text/csv')

        import_record = CSVImport.objects.create(
            account=self.account,
            file=file,
            original_filename='test.csv',
            row_count=4,
            status='pending',
            imported_by=self.user,
        )

        response = self.client.get(
            reverse('finance:csv_import_preview', args=[import_record.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/csv_preview.html')

    def test_preview_shows_parsed_rows(self):
        """Test that preview shows parsed CSV rows."""
        content = SAMPLE_AMEX_CSV.encode('utf-8')
        file = SimpleUploadedFile('test.csv', content, content_type='text/csv')

        import_record = CSVImport.objects.create(
            account=self.account,
            file=file,
            original_filename='test.csv',
            row_count=4,
            status='pending',
            imported_by=self.user,
        )

        response = self.client.get(
            reverse('finance:csv_import_preview', args=[import_record.id])
        )

        self.assertContains(response, 'AMAZON')
        self.assertContains(response, '49.99')

    def test_preview_post_performs_import(self):
        """Test that POST to preview performs import."""
        content = SAMPLE_AMEX_CSV.encode('utf-8')
        file = SimpleUploadedFile('test.csv', content, content_type='text/csv')

        import_record = CSVImport.objects.create(
            account=self.account,
            file=file,
            original_filename='test.csv',
            row_count=4,
            status='pending',
            imported_by=self.user,
        )

        response = self.client.post(
            reverse('finance:csv_import_preview', args=[import_record.id]),
            {'skip_duplicates': 'on'}
        )

        # Should redirect to results
        self.assertEqual(response.status_code, 302)

        # Should create transactions
        transactions = Transaction.objects.filter(account=self.account)
        self.assertEqual(transactions.count(), 4)

        # Import record should be updated
        import_record.refresh_from_db()
        self.assertEqual(import_record.status, 'completed')

    def test_results_view_renders(self):
        """Test that results view renders correctly."""
        import_record = CSVImport.objects.create(
            account=self.account,
            original_filename='test.csv',
            row_count=4,
            imported_count=4,
            status='completed',
            imported_by=self.user,
        )

        response = self.client.get(
            reverse('finance:csv_import_results', args=[import_record.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/csv_results.html')
        self.assertContains(response, '4')  # Imported count

    def test_import_list_view_renders(self):
        """Test that import list view renders correctly."""
        CSVImport.objects.create(
            account=self.account,
            original_filename='test.csv',
            row_count=4,
            status='completed',
            imported_by=self.user,
        )

        response = self.client.get(reverse('finance:csv_import_list'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'finance/csv_import_list.html')
        self.assertContains(response, 'test.csv')
