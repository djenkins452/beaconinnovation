"""
Tests for OCR processing and receipt parsing.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock
import io

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse

from finance.models import Account, Category, Transaction, Receipt
from finance.parsers import ReceiptParser, parse_receipt_text
from finance.ocr import is_tesseract_available


class ReceiptParserTests(TestCase):
    """Tests for the ReceiptParser class."""

    def setUp(self):
        self.parser = ReceiptParser()

    # Amount extraction tests
    def test_extract_amount_with_dollar_sign(self):
        """Should extract amount with dollar sign."""
        text = "Your total is $45.99"
        result = self.parser.extract_amount(text)
        self.assertEqual(result, Decimal('45.99'))

    def test_extract_amount_with_total_label(self):
        """Should extract amount after 'Total:' label."""
        text = "Subtotal: $40.00\nTax: $5.99\nTotal: $45.99"
        result = self.parser.extract_amount(text)
        self.assertEqual(result, Decimal('45.99'))

    def test_extract_amount_grand_total(self):
        """Should extract grand total amount."""
        text = "Grand Total $123.45"
        result = self.parser.extract_amount(text)
        self.assertEqual(result, Decimal('123.45'))

    def test_extract_amount_with_commas(self):
        """Should handle amounts with thousands separator."""
        text = "Total: $1,234.56"
        result = self.parser.extract_amount(text)
        self.assertEqual(result, Decimal('1234.56'))

    def test_extract_amount_usd(self):
        """Should extract amount followed by USD."""
        text = "Amount: 99.99 USD"
        result = self.parser.extract_amount(text)
        self.assertEqual(result, Decimal('99.99'))

    def test_extract_amount_no_amount(self):
        """Should return None when no amount found."""
        text = "Thank you for shopping with us!"
        result = self.parser.extract_amount(text)
        self.assertIsNone(result)

    def test_extract_amount_multiple_returns_largest(self):
        """Should return largest reasonable amount when multiple found."""
        text = "Item 1: $10.00\nItem 2: $20.00\nTotal: $30.00"
        result = self.parser.extract_amount(text)
        self.assertEqual(result, Decimal('30.00'))

    # Date extraction tests
    def test_extract_date_mm_dd_yyyy(self):
        """Should extract date in MM/DD/YYYY format."""
        text = "Date: 01/15/2026"
        result = self.parser.extract_date(text)
        self.assertEqual(result, date(2026, 1, 15))

    def test_extract_date_mm_dd_yy(self):
        """Should extract date in MM/DD/YY format."""
        text = "Date: 01/15/26"
        result = self.parser.extract_date(text)
        self.assertEqual(result, date(2026, 1, 15))

    def test_extract_date_yyyy_mm_dd(self):
        """Should extract date in YYYY-MM-DD format."""
        text = "Transaction: 2026-01-15"
        result = self.parser.extract_date(text)
        self.assertEqual(result, date(2026, 1, 15))

    def test_extract_date_month_name(self):
        """Should extract date with full month name."""
        text = "January 15, 2026"
        result = self.parser.extract_date(text)
        self.assertEqual(result, date(2026, 1, 15))

    def test_extract_date_month_abbr(self):
        """Should extract date with abbreviated month."""
        text = "Jan 15, 2026"
        result = self.parser.extract_date(text)
        self.assertEqual(result, date(2026, 1, 15))

    def test_extract_date_dmy_format(self):
        """Should extract date in DD Mon YYYY format."""
        text = "15 Jan 2026"
        result = self.parser.extract_date(text)
        self.assertEqual(result, date(2026, 1, 15))

    def test_extract_date_with_dashes(self):
        """Should extract date with dashes."""
        text = "Date: 01-15-2026"
        result = self.parser.extract_date(text)
        self.assertEqual(result, date(2026, 1, 15))

    def test_extract_date_no_date(self):
        """Should return None when no date found."""
        text = "Thank you for your purchase!"
        result = self.parser.extract_date(text)
        self.assertIsNone(result)

    def test_extract_date_rejects_future_dates(self):
        """Should reject dates too far in future."""
        text = "Date: 01/15/2030"
        result = self.parser.extract_date(text)
        self.assertIsNone(result)

    def test_extract_date_rejects_old_dates(self):
        """Should reject dates too far in past."""
        text = "Date: 01/15/2010"
        result = self.parser.extract_date(text)
        self.assertIsNone(result)

    # Vendor extraction tests
    def test_extract_vendor_first_line(self):
        """Should use first line as vendor name."""
        text = "ACME Store\n123 Main St\nTotal: $50.00"
        result = self.parser.extract_vendor(text)
        self.assertEqual(result, 'Acme Store')

    def test_extract_vendor_merchant_label(self):
        """Should extract vendor from 'Merchant:' label."""
        text = "Receipt\nMerchant: Best Buy\nTotal: $100.00"
        result = self.parser.extract_vendor(text)
        self.assertEqual(result, 'Best Buy')

    def test_extract_vendor_store_label(self):
        """Should extract vendor from 'Store:' label."""
        text = "Store: Target\nDate: 01/15/2026"
        result = self.parser.extract_vendor(text)
        self.assertEqual(result, 'Target')

    def test_extract_vendor_skips_date_line(self):
        """Should skip first line if it looks like a date."""
        text = "01/15/2026\nWalmart\nTotal: $25.00"
        result = self.parser.extract_vendor(text)
        self.assertEqual(result, 'Walmart')

    def test_extract_vendor_removes_suffix(self):
        """Should clean up Inc/LLC suffixes."""
        text = "ACME Corp Inc.\n123 Main St"
        result = self.parser.extract_vendor(text)
        self.assertEqual(result, 'Acme Corp')

    def test_extract_vendor_empty_text(self):
        """Should return None for empty text."""
        result = self.parser.extract_vendor("")
        self.assertIsNone(result)

    def test_extract_vendor_no_valid_lines(self):
        """Should return None when no valid vendor found."""
        text = "$50.00\n01/15/2026"
        result = self.parser.extract_vendor(text)
        self.assertIsNone(result)

    # Full parsing tests
    def test_parse_full_receipt(self):
        """Should parse a complete receipt."""
        text = """
        Walmart
        123 Main Street
        Anytown, USA

        Date: 01/15/2026

        Item 1          $10.00
        Item 2          $15.00
        -----------------------
        Subtotal        $25.00
        Tax              $2.00
        Total:          $27.00

        Thank you for shopping!
        """
        result = self.parser.parse(text)

        self.assertEqual(result['vendor'], 'Walmart')
        self.assertEqual(result['amount'], Decimal('27.00'))
        self.assertEqual(result['date'], date(2026, 1, 15))

    def test_parse_receipt_text_convenience_function(self):
        """Should work via convenience function."""
        text = "Store: Amazon\nDate: 2026-01-15\nTotal: $99.99"
        result = parse_receipt_text(text)

        self.assertEqual(result['vendor'], 'Amazon')
        self.assertEqual(result['amount'], Decimal('99.99'))
        self.assertEqual(result['date'], date(2026, 1, 15))


class OCRIntegrationTests(TestCase):
    """Tests for OCR processing with mocked Tesseract."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.account = Account.objects.create(
            name='Test Account',
            account_type='checking',
            institution='Test Bank',
            created_by=self.user
        )
        self.category, _ = Category.objects.get_or_create(
            name='Test Category OCR',
            category_type='expense'
        )
        self.transaction = Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.category,
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test transaction',
            created_by=self.user
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')

    def test_tesseract_availability_check(self):
        """Should correctly report Tesseract availability."""
        # This will return True or False based on actual system
        result = is_tesseract_available()
        self.assertIsInstance(result, bool)


class OCRViewTests(TestCase):
    """Tests for OCR-related views."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.account = Account.objects.create(
            name='Test Account',
            account_type='checking',
            institution='Test Bank',
            created_by=self.user
        )
        self.category, _ = Category.objects.get_or_create(
            name='Test Category OCR Views',
            category_type='expense'
        )
        self.transaction = Transaction.objects.create(
            account=self.account,
            transaction_type='expense',
            category=self.category,
            amount=Decimal('50.00'),
            transaction_date=date.today(),
            description='Test transaction',
            created_by=self.user
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')

    def test_tesseract_status_endpoint(self):
        """Should return Tesseract availability status."""
        response = self.client.get(reverse('finance:tesseract_status'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('available', data)
        self.assertIn('message', data)

    def test_ocr_status_requires_login(self):
        """Should require authentication."""
        self.client.logout()
        response = self.client.get(reverse('finance:tesseract_status'))
        self.assertEqual(response.status_code, 302)  # Redirect to login

    @patch('finance.views.is_tesseract_available')
    def test_process_ocr_without_tesseract(self, mock_available):
        """Should return error when Tesseract not available."""
        mock_available.return_value = False

        # Create a receipt
        receipt = Receipt.objects.create(
            transaction=self.transaction,
            file='receipts/test.jpg',
            original_filename='test.jpg',
            file_type='jpg',
            file_size=1024,
            uploaded_by=self.user
        )

        response = self.client.post(
            reverse('finance:process_ocr', args=[receipt.id])
        )
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not available', data['error'])

    def test_ocr_status_unprocessed_receipt(self):
        """Should indicate receipt not processed."""
        receipt = Receipt.objects.create(
            transaction=self.transaction,
            file='receipts/test.jpg',
            original_filename='test.jpg',
            file_type='jpg',
            file_size=1024,
            uploaded_by=self.user
        )

        response = self.client.get(
            reverse('finance:ocr_status', args=[receipt.id])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['processed'])
        self.assertIsNone(data['data'])

    def test_ocr_status_processed_receipt(self):
        """Should return OCR data for processed receipt."""
        receipt = Receipt.objects.create(
            transaction=self.transaction,
            file='receipts/test.jpg',
            original_filename='test.jpg',
            file_type='jpg',
            file_size=1024,
            uploaded_by=self.user,
            ocr_processed=True,
            ocr_vendor='Test Vendor',
            ocr_amount=Decimal('50.00'),
            ocr_date=date(2026, 1, 15),
            ocr_confidence=Decimal('0.85'),
            ocr_raw_text='Test Vendor\nTotal: $50.00'
        )

        response = self.client.get(
            reverse('finance:ocr_status', args=[receipt.id])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['processed'])
        self.assertEqual(data['data']['vendor'], 'Test Vendor')
        self.assertEqual(data['data']['amount'], '50.00')
        self.assertEqual(data['data']['date'], '2026-01-15')
        self.assertEqual(data['data']['confidence'], 0.85)

    def test_process_ocr_pdf_not_supported(self):
        """Should reject PDF files for OCR."""
        receipt = Receipt.objects.create(
            transaction=self.transaction,
            file='receipts/test.pdf',
            original_filename='test.pdf',
            file_type='pdf',
            file_size=1024,
            uploaded_by=self.user
        )

        with patch('finance.views.is_tesseract_available', return_value=True):
            response = self.client.post(
                reverse('finance:process_ocr', args=[receipt.id])
            )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('pdf', data['error'].lower())
