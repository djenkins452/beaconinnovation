"""
Tests for receipt upload and management functionality.
"""
import io
from datetime import date
from decimal import Decimal

from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from finance.models import Account, Category, Transaction, Receipt
from finance.forms import validate_receipt_file, get_file_type, ReceiptUploadForm


class ValidateReceiptFileTests(TestCase):
    """Tests for the validate_receipt_file function."""

    def test_valid_jpg_file(self):
        """Should accept valid JPG file."""
        file = SimpleUploadedFile(
            'receipt.jpg',
            b'fake image content',
            content_type='image/jpeg'
        )
        result = validate_receipt_file(file)
        self.assertTrue(result['valid'])
        self.assertEqual(result['file_type'], 'jpg')
        self.assertEqual(result['original_filename'], 'receipt.jpg')

    def test_valid_jpeg_file(self):
        """Should normalize jpeg to jpg."""
        file = SimpleUploadedFile(
            'receipt.jpeg',
            b'fake image content',
            content_type='image/jpeg'
        )
        result = validate_receipt_file(file)
        self.assertTrue(result['valid'])
        self.assertEqual(result['file_type'], 'jpg')

    def test_valid_png_file(self):
        """Should accept valid PNG file."""
        file = SimpleUploadedFile(
            'receipt.png',
            b'fake image content',
            content_type='image/png'
        )
        result = validate_receipt_file(file)
        self.assertTrue(result['valid'])
        self.assertEqual(result['file_type'], 'png')

    def test_valid_pdf_file(self):
        """Should accept valid PDF file."""
        file = SimpleUploadedFile(
            'receipt.pdf',
            b'%PDF-1.4 fake pdf content',
            content_type='application/pdf'
        )
        result = validate_receipt_file(file)
        self.assertTrue(result['valid'])
        self.assertEqual(result['file_type'], 'pdf')

    def test_invalid_file_type(self):
        """Should reject invalid file types."""
        file = SimpleUploadedFile(
            'document.doc',
            b'fake doc content',
            content_type='application/msword'
        )
        result = validate_receipt_file(file)
        self.assertFalse(result['valid'])
        self.assertIn('Invalid file type', result['error'])

    @override_settings(FINANCE_RECEIPT_MAX_SIZE_MB=1)
    def test_file_too_large(self):
        """Should reject files exceeding size limit."""
        # Create file larger than 1MB
        large_content = b'x' * (1024 * 1024 + 1)
        file = SimpleUploadedFile(
            'large.jpg',
            large_content,
            content_type='image/jpeg'
        )
        result = validate_receipt_file(file)
        self.assertFalse(result['valid'])
        self.assertIn('too large', result['error'])

    def test_no_file(self):
        """Should handle None file."""
        result = validate_receipt_file(None)
        self.assertFalse(result['valid'])
        self.assertIn('No file', result['error'])


class GetFileTypeTests(TestCase):
    """Tests for the get_file_type function."""

    def test_jpg_extension(self):
        self.assertEqual(get_file_type('receipt.jpg'), 'jpg')

    def test_jpeg_extension(self):
        self.assertEqual(get_file_type('receipt.jpeg'), 'jpg')

    def test_png_extension(self):
        self.assertEqual(get_file_type('receipt.png'), 'png')

    def test_pdf_extension(self):
        self.assertEqual(get_file_type('receipt.pdf'), 'pdf')

    def test_uppercase_extension(self):
        self.assertEqual(get_file_type('receipt.JPG'), 'jpg')

    def test_no_extension(self):
        self.assertEqual(get_file_type('receipt'), '')


class ReceiptUploadFormTests(TestCase):
    """Tests for the ReceiptUploadForm."""

    def test_valid_file(self):
        """Should accept valid file."""
        file = SimpleUploadedFile(
            'receipt.jpg',
            b'fake image content',
            content_type='image/jpeg'
        )
        form = ReceiptUploadForm(files={'file': file})
        self.assertTrue(form.is_valid())

    def test_invalid_file_type(self):
        """Should reject invalid file type."""
        file = SimpleUploadedFile(
            'document.exe',
            b'fake exe content',
            content_type='application/x-executable'
        )
        form = ReceiptUploadForm(files={'file': file})
        self.assertFalse(form.is_valid())
        self.assertIn('file', form.errors)


class ReceiptUploadViewTests(TestCase):
    """Tests for receipt upload views."""

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
            name='Test Category Receipt Upload',
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

    def test_upload_receipt_success(self):
        """Should successfully upload a receipt."""
        file = SimpleUploadedFile(
            'receipt.jpg',
            b'fake image content',
            content_type='image/jpeg'
        )
        response = self.client.post(
            reverse('finance:upload_receipt', args=[self.transaction.id]),
            {'file': file}
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('receipt', data)
        self.assertEqual(data['receipt']['filename'], 'receipt.jpg')

        # Verify receipt was created
        self.assertEqual(Receipt.objects.count(), 1)
        receipt = Receipt.objects.first()
        self.assertEqual(receipt.transaction, self.transaction)
        self.assertEqual(receipt.file_type, 'jpg')

    def test_upload_receipt_no_file(self):
        """Should return error when no file uploaded."""
        response = self.client.post(
            reverse('finance:upload_receipt', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('No file', data['error'])

    def test_upload_receipt_invalid_type(self):
        """Should reject invalid file types."""
        file = SimpleUploadedFile(
            'malware.exe',
            b'fake exe content',
            content_type='application/x-executable'
        )
        response = self.client.post(
            reverse('finance:upload_receipt', args=[self.transaction.id]),
            {'file': file}
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])

    def test_upload_receipt_requires_login(self):
        """Should require authentication."""
        self.client.logout()
        file = SimpleUploadedFile(
            'receipt.jpg',
            b'fake image content',
            content_type='image/jpeg'
        )
        response = self.client.post(
            reverse('finance:upload_receipt', args=[self.transaction.id]),
            {'file': file}
        )
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_upload_receipt_invalid_transaction(self):
        """Should return 404 for invalid transaction."""
        import uuid
        fake_id = uuid.uuid4()
        file = SimpleUploadedFile(
            'receipt.jpg',
            b'fake image content',
            content_type='image/jpeg'
        )
        response = self.client.post(
            reverse('finance:upload_receipt', args=[fake_id]),
            {'file': file}
        )
        self.assertEqual(response.status_code, 404)


class ReceiptViewDownloadTests(TestCase):
    """Tests for receipt view and download endpoints."""

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
            name='Test Category Receipt View',
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
        # Create receipt with actual file
        file = SimpleUploadedFile(
            'receipt.jpg',
            b'fake image content for testing',
            content_type='image/jpeg'
        )
        self.receipt = Receipt.objects.create(
            transaction=self.transaction,
            file=file,
            original_filename='receipt.jpg',
            file_type='jpg',
            file_size=30,
            uploaded_by=self.user
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')

    def tearDown(self):
        # Clean up uploaded files
        if self.receipt.file:
            self.receipt.file.delete()

    def test_get_receipt_info(self):
        """Should return receipt information."""
        response = self.client.get(
            reverse('finance:receipt_info', args=[self.receipt.id])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['filename'], 'receipt.jpg')
        self.assertEqual(data['file_type'], 'jpg')
        self.assertEqual(str(data['transaction_id']), str(self.transaction.id))

    def test_view_receipt(self):
        """Should return file for inline viewing."""
        response = self.client.get(
            reverse('finance:view_receipt', args=[self.receipt.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertIn('inline', response['Content-Disposition'])

    def test_download_receipt(self):
        """Should return file as attachment."""
        response = self.client.get(
            reverse('finance:download_receipt', args=[self.receipt.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])

    def test_view_receipt_requires_login(self):
        """Should require authentication."""
        self.client.logout()
        response = self.client.get(
            reverse('finance:view_receipt', args=[self.receipt.id])
        )
        self.assertEqual(response.status_code, 302)


class ReceiptDeleteTests(TestCase):
    """Tests for receipt deletion."""

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
            name='Test Category Receipt Delete',
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
        file = SimpleUploadedFile(
            'receipt.jpg',
            b'fake image content',
            content_type='image/jpeg'
        )
        self.receipt = Receipt.objects.create(
            transaction=self.transaction,
            file=file,
            original_filename='receipt.jpg',
            file_type='jpg',
            file_size=20,
            uploaded_by=self.user
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')

    def test_delete_receipt(self):
        """Should delete receipt successfully."""
        receipt_id = self.receipt.id
        response = self.client.post(
            reverse('finance:delete_receipt', args=[receipt_id])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Verify receipt was deleted
        self.assertFalse(Receipt.objects.filter(id=receipt_id).exists())

    def test_delete_receipt_requires_post(self):
        """Should require POST method."""
        response = self.client.get(
            reverse('finance:delete_receipt', args=[self.receipt.id])
        )
        self.assertEqual(response.status_code, 405)


class ListTransactionReceiptsTests(TestCase):
    """Tests for listing receipts by transaction."""

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
            name='Test Category Receipt List',
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

    def test_list_empty_receipts(self):
        """Should return empty list when no receipts."""
        response = self.client.get(
            reverse('finance:transaction_receipts', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['receipts'], [])

    def test_list_multiple_receipts(self):
        """Should return all receipts for transaction."""
        # Create multiple receipts
        for i in range(3):
            file = SimpleUploadedFile(
                f'receipt{i}.jpg',
                b'fake content',
                content_type='image/jpeg'
            )
            Receipt.objects.create(
                transaction=self.transaction,
                file=file,
                original_filename=f'receipt{i}.jpg',
                file_type='jpg',
                file_size=12,
                uploaded_by=self.user
            )

        response = self.client.get(
            reverse('finance:transaction_receipts', args=[self.transaction.id])
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['count'], 3)
        self.assertEqual(len(data['receipts']), 3)

    def tearDown(self):
        # Clean up uploaded files
        for receipt in Receipt.objects.all():
            if receipt.file:
                receipt.file.delete()
