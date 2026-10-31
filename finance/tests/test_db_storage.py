"""Tests for durable, private DB-backed storage of finance uploads.

Verifies that receipt files:
  * round-trip through PostgreSQL (DatabaseStorage) with bytes preserved,
  * are persisted as StoredBlob rows (not on the ephemeral filesystem),
  * are served only through the access-checked views — the owner/uploader/
    superuser get the bytes; an unauthorized user is denied (404).
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from finance.models import Account, Category, Receipt, StoredBlob, Transaction

PDF_BYTES = b"%PDF-1.4 fake receipt bytes \x00\x01\x02 end"


class DatabaseStorageReceiptTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", "owner@example.com", "pw-owner-123")
        self.other = User.objects.create_user("other", "other@example.com", "pw-other-123")
        self.admin = User.objects.create_superuser("root", "root@example.com", "pw-root-123")
        self.account = Account.objects.create(
            name="Checking", account_type="checking", created_by=self.owner,
        )
        self.category = Category.objects.create(
            name="Supplies", category_type="expense",
        )
        self.txn = Transaction.objects.create(
            account=self.account, transaction_type="expense", category=self.category,
            amount=Decimal("10.00"), transaction_date=date(2026, 1, 1),
            description="x", created_by=self.owner,
        )

    def _make_receipt(self):
        receipt = Receipt(
            transaction=self.txn, original_filename="r.pdf", file_type="pdf",
            file_size=len(PDF_BYTES), uploaded_by=self.owner,
        )
        receipt.file.save("receipts/2026/01/r.pdf", ContentFile(PDF_BYTES), save=True)
        return receipt

    def test_bytes_persist_in_database_not_filesystem(self):
        receipt = self._make_receipt()
        # A StoredBlob row holds the exact bytes.
        blob = StoredBlob.objects.get(name=receipt.file.name)
        self.assertEqual(bytes(blob.data), PDF_BYTES)
        self.assertEqual(blob.size, len(PDF_BYTES))
        # Reading back through the field returns the same bytes (durable round-trip).
        with receipt.file.open("rb") as fh:
            self.assertEqual(fh.read(), PDF_BYTES)
        # No public URL is exposed.
        self.assertEqual(receipt.file.url, "")

    def test_owner_can_view(self):
        receipt = self._make_receipt()
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("finance:view_receipt", args=[receipt.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b"".join(resp.streaming_content), PDF_BYTES)

    def test_superuser_can_view(self):
        receipt = self._make_receipt()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("finance:view_receipt", args=[receipt.id]))
        self.assertEqual(resp.status_code, 200)

    def test_unauthorized_user_denied(self):
        receipt = self._make_receipt()
        self.client.force_login(self.other)
        resp = self.client.get(reverse("finance:view_receipt", args=[receipt.id]))
        self.assertEqual(resp.status_code, 404)
        download = self.client.get(reverse("finance:download_receipt", args=[receipt.id]))
        self.assertEqual(download.status_code, 404)

    def test_delete_removes_blob(self):
        receipt = self._make_receipt()
        name = receipt.file.name
        self.assertTrue(StoredBlob.objects.filter(name=name).exists())
        receipt.file.delete(save=False)
        self.assertFalse(StoredBlob.objects.filter(name=name).exists())
