"""Tests for the audited purchase cancellation workflow.

Covers whole-order cancel (fully-outstanding orders), per-line cancel of outstanding
lines on a partially received order, the "never undo received inventory" protection,
active vs original totals, receiving restrictions (service + dashboard + direct
Receive request), that costs/funding/payments/Finance are never touched, that linked
payments are flagged not changed, idempotency of repeated submissions, and that the
endpoints stay active-superuser-only.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from finance.models import Account, Transaction
from operations import models as m
from operations import services

ZERO = Decimal('0')


def _filament_material(name='Matte Black', sku='F1'):
    return m.Material.objects.create(material_type='filament', manufacturer='Bambu Lab',
                                     product_type='PLA Basic', name=name, sku=sku)


def _stock_material(name='Countertop', sku='S1'):
    return m.Material.objects.create(material_type='hardware', name=name, sku=sku)


class CancelServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('admin@x.com', is_superuser=True, is_staff=True,
                                             is_active=True)
        self.loc = m.Location.objects.create(name='Home Office / Print Room', kind='room')
        # The Home Depot example: two items, recorded tax, nothing received.
        self.purchase = m.Purchase.objects.create(supplier_name='Home Depot',
                                                   order_number='WH49872139',
                                                   tax_total=Decimal('35.48'), funding='personal')
        self.stock_mat = _stock_material()
        self.countertop = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='stock', description='Countertop',
            material=self.stock_mat, quantity_ordered=Decimal('1'), unit='each',
            unit_cost=Decimal('259.93'))
        self.shelf = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='stock', description='Shelf',
            material=_stock_material('Shelf', 'S2'), quantity_ordered=Decimal('1'),
            unit='each', unit_cost=Decimal('104.00'))

    # --- Whole-order cancel ------------------------------------------------
    def test_cancel_whole_outstanding_order(self):
        original = self.purchase.order_total()
        self.assertEqual(original, Decimal('399.41'))  # 259.93 + 104.00 + 35.48
        result = services.cancel_purchase(purchase=self.purchase, actor=self.user,
                                          reason='Canceled with supplier')
        self.assertFalse(result['already'])
        self.assertEqual(result['lines'], 2)
        self.purchase.refresh_from_db()
        self.assertTrue(self.purchase.is_cancelled)
        self.assertEqual(self.purchase.cancelled_by, self.user)
        self.assertEqual(self.purchase.cancellation_reason, 'Canceled with supplier')
        # Every line flagged cancelled.
        for ln in self.purchase.lines.all():
            self.assertTrue(ln.is_cancelled)
            self.assertEqual(ln.receiving_status, 'cancelled')
            self.assertEqual(ln.quantity_outstanding, ZERO)
        # Original preserved for history; active excluded.
        self.assertEqual(self.purchase.order_total(), original)
        self.assertEqual(self.purchase.active_order_total(), ZERO)
        self.assertEqual(self.purchase.receiving_status, 'cancelled')

    def test_cancel_is_idempotent(self):
        services.cancel_purchase(purchase=self.purchase, actor=self.user)
        again = services.cancel_purchase(purchase=self.purchase, actor=self.user)
        self.assertTrue(again['already'])
        # No duplicate cancellation audit beyond the two (one per call is fine, but the
        # second must not re-cancel lines).
        self.assertEqual(self.purchase.lines.filter(cancelled_at__isnull=False).count(), 2)

    def test_cancel_refused_when_anything_received(self):
        services.receive_stock_line(line=self.countertop, quantity=Decimal('1'),
                                    actor=self.user, location=self.loc)
        with self.assertRaises(ValidationError):
            services.cancel_purchase(purchase=self.purchase, actor=self.user)
        self.purchase.refresh_from_db()
        self.assertFalse(self.purchase.is_cancelled)
        self.shelf.refresh_from_db()
        self.assertFalse(self.shelf.is_cancelled)  # nothing cancelled on refusal

    def test_cancel_flags_linked_payment_without_changing_it(self):
        account = Account.objects.create(name='Checking', account_type='checking',
                                         institution='Bank')
        txn = Transaction.objects.create(account=account, transaction_type='expense',
                                         amount=Decimal('399.41'), transaction_date=date.today(),
                                         description='Home Depot order')
        services.link_payment(purchase=self.purchase, transaction_obj=txn,
                              amount=Decimal('399.41'), actor=self.user)
        result = services.cancel_purchase(purchase=self.purchase, actor=self.user)
        self.assertEqual(result['linked_payments'], 1)
        # Payment + transaction untouched.
        self.assertEqual(self.purchase.payments.count(), 1)
        txn.refresh_from_db()
        self.assertEqual(txn.amount, Decimal('399.41'))
        self.assertEqual(Transaction.objects.count(), 1)

    def test_cancel_touches_no_costs_or_inventory(self):
        services.cancel_purchase(purchase=self.purchase, actor=self.user)
        # Prices intact.
        self.countertop.refresh_from_db()
        self.assertEqual(self.countertop.unit_cost, Decimal('259.93'))
        self.assertEqual(self.purchase.tax_total, Decimal('35.48'))
        # No inventory movements, no finance transactions created.
        self.assertEqual(m.InventoryMovement.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(m.FilamentSpool.objects.count(), 0)
        self.assertEqual(m.StockItem.objects.count(), 0)

    # --- Per-line cancel on a partially received order --------------------
    def test_cancel_outstanding_line_on_partially_received_order(self):
        # Receive the countertop; cancel the (still outstanding) shelf.
        services.receive_stock_line(line=self.countertop, quantity=Decimal('1'),
                                    actor=self.user, location=self.loc)
        services.cancel_line(line=self.shelf, actor=self.user, reason='Out of stock')
        self.shelf.refresh_from_db()
        self.purchase.refresh_from_db()
        self.assertTrue(self.shelf.is_cancelled)
        self.assertFalse(self.purchase.is_cancelled)  # order stays live (has received goods)
        # Active total excludes the cancelled shelf but keeps the received countertop + tax.
        self.assertEqual(self.purchase.active_order_total(),
                         Decimal('259.93') + Decimal('35.48'))
        self.assertEqual(self.purchase.order_total(), Decimal('399.41'))  # original intact
        self.assertTrue(self.purchase.has_cancelled_lines)
        # Order status reflects the live (received) line, not the cancelled one.
        self.assertEqual(self.purchase.receiving_status, 'received')

    def test_cancel_line_refused_when_line_received(self):
        services.receive_stock_line(line=self.countertop, quantity=Decimal('1'),
                                    actor=self.user, location=self.loc)
        with self.assertRaises(ValidationError):
            services.cancel_line(line=self.countertop, actor=self.user)
        self.countertop.refresh_from_db()
        self.assertFalse(self.countertop.is_cancelled)

    def test_cancel_line_idempotent(self):
        services.cancel_line(line=self.shelf, actor=self.user)
        first = self.shelf.cancelled_at or m.PurchaseLine.objects.get(pk=self.shelf.pk).cancelled_at
        services.cancel_line(line=self.shelf, actor=self.user)
        self.shelf.refresh_from_db()
        self.assertTrue(self.shelf.is_cancelled)
        self.assertEqual(self.shelf.cancelled_at, first)  # not re-stamped

    # --- Receiving restrictions -------------------------------------------
    def test_quick_receive_blocked_on_cancelled_line(self):
        services.cancel_line(line=self.shelf, actor=self.user)
        with self.assertRaises(ValidationError):
            services.quick_receive_line(line=self.shelf, actor=self.user)
        self.assertEqual(m.StockItem.objects.count(), 0)

    def test_direct_receive_blocked_on_cancelled_line(self):
        services.cancel_line(line=self.shelf, actor=self.user)
        self.shelf.refresh_from_db()  # the Receive view fetches the line fresh
        with self.assertRaises(ValidationError):
            services.receive_stock_line(line=self.shelf, quantity=Decimal('1'),
                                        actor=self.user, location=self.loc)

    def test_quick_receive_purchase_blocked_when_cancelled(self):
        services.cancel_purchase(purchase=self.purchase, actor=self.user)
        self.purchase.refresh_from_db()  # the dashboard view fetches the order fresh
        with self.assertRaises(ValidationError):
            services.quick_receive_purchase(purchase=self.purchase, actor=self.user)

    def test_quick_receive_purchase_skips_cancelled_lines(self):
        services.cancel_line(line=self.shelf, actor=self.user)
        summary = services.quick_receive_purchase(purchase=self.purchase, actor=self.user,
                                                  location=self.loc)
        # Only the countertop (still outstanding) is received; the cancelled shelf is skipped.
        self.assertEqual(summary['stock_lines'], 1)
        self.shelf.refresh_from_db()
        self.assertTrue(self.shelf.is_cancelled)
        self.assertEqual(m.StockItem.objects.count(), 1)

    def test_confirm_blocked_on_cancelled_line(self):
        services.cancel_line(line=self.shelf, actor=self.user)
        with self.assertRaises(ValidationError):
            services.confirm_line_received(line=self.shelf, actor=self.user)


class CancelViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin@x.com', password='pw', is_superuser=True,
                                              is_staff=True, is_active=True)
        self.other = User.objects.create_user('user@x.com', password='pw', is_active=True)
        self.loc = m.Location.objects.create(name='Home Office / Print Room', kind='room')
        self.purchase = m.Purchase.objects.create(supplier_name='Home Depot',
                                                   order_number='WH49872139',
                                                   tax_total=Decimal('35.48'))
        self.mat = _stock_material()
        self.line = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='stock', description='Countertop',
            material=self.mat, quantity_ordered=Decimal('1'), unit='each',
            unit_cost=Decimal('259.93'))

    def _url(self, name, **kw):
        return reverse(f'operations:{name}', kwargs=kw)

    def test_cancel_endpoints_require_admin(self):
        url = self._url('purchase_cancel', purchase_id=self.purchase.id)
        # Anonymous → login redirect.
        self.assertEqual(self.client.post(url).status_code, 302)
        # Non-admin authenticated → 404.
        self.client.login(username='user@x.com', password='pw')
        self.assertEqual(self.client.post(url).status_code, 404)
        self.purchase.refresh_from_db()
        self.assertFalse(self.purchase.is_cancelled)

    def test_admin_cancels_whole_order(self):
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.post(self._url('purchase_cancel', purchase_id=self.purchase.id),
                                {'reason': 'Canceled with supplier'})
        self.assertRedirects(resp, self._url('purchase_detail', purchase_id=self.purchase.id))
        self.purchase.refresh_from_db()
        self.assertTrue(self.purchase.is_cancelled)
        self.assertEqual(self.purchase.active_order_total(), ZERO)

    def test_admin_cancels_single_line(self):
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.post(self._url('line_cancel', line_id=self.line.id))
        self.assertRedirects(resp, self._url('purchase_detail', purchase_id=self.purchase.id))
        self.line.refresh_from_db()
        self.assertTrue(self.line.is_cancelled)

    def test_dashboard_excludes_cancelled_line(self):
        services.cancel_line(line=self.line, actor=self.admin)
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.get(reverse('operations:dashboard'))
        self.assertEqual(resp.status_code, 200)
        # The cancelled line is not offered for receiving on the dashboard.
        self.assertNotContains(resp, 'dashboard_receive_line'.replace('_', ''))  # defensive
        self.assertNotContains(resp, self._url('dashboard_receive_line', line_id=self.line.id))

    def test_direct_dashboard_receive_blocked_on_cancelled_line(self):
        services.cancel_line(line=self.line, actor=self.admin)
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.post(self._url('dashboard_receive_line', line_id=self.line.id),
                                {'idempotency_key': 'x'}, follow=True)
        self.assertEqual(m.StockItem.objects.count(), 0)  # nothing received
        self.assertContains(resp, 'canceled')

    def test_purchase_list_total_excludes_cancelled(self):
        services.cancel_purchase(purchase=self.purchase, actor=self.admin)
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.get(reverse('operations:purchase_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Canceled')
        # Active total is $0.00 (the only order is cancelled); original still shown on the row.
        self.assertContains(resp, '$0.00')
        self.assertContains(resp, '295.41')  # original: 259.93 countertop + 35.48 tax
