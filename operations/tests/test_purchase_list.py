"""Tests for the Purchases list usability upgrade.

The list now shows each ordered item's description + quantity with its own receiving
status and action (reusing the dashboard's fast-receive endpoints/services via a safe
``next`` redirect), a whole-order "receive remaining" action for multi-item orders, and
keeps canceled lines visibly canceled and unreceivable. These tests cover single-item,
multi-item, partially received and canceled orders, the receive-and-stay-here round
trip, the description fallback, and that access stays active-superuser-only.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from operations import models as m
from operations import services

ZERO = Decimal('0')


def _filament_material(name='Cyan', sku='C1'):
    return m.Material.objects.create(material_type='filament', manufacturer='Bambu Lab',
                                     product_type='PLA Basic', name=name, sku=sku)


def _stock_material(name='Bubble mailer', sku='S1'):
    return m.Material.objects.create(material_type='packaging', name=name, sku=sku)


class PurchaseListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin@x.com', password='pw', is_superuser=True,
                                             is_staff=True, is_active=True)
        cls.regular = User.objects.create_user('reg@x.com', password='pw')
        m.Location.objects.create(name='Home Office / Print Room', kind='room')

    def _login(self):
        self.client.login(username='admin@x.com', password='pw')

    def test_requires_admin(self):
        url = reverse('operations:purchase_list')
        self.assertEqual(self.client.get(url).status_code, 302)          # anon → login
        self.client.login(username='reg@x.com', password='pw')
        self.assertEqual(self.client.get(url).status_code, 404)          # non-admin hidden

    def test_single_item_shows_description_qty_and_receive_control(self):
        mat = _stock_material('Bubble mailer 6x9', 'BM1')
        purchase = m.Purchase.objects.create(supplier_name='Amazon', order_number='A-1')
        line = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='Bubble mailers 6x9 (100pk)',
            material=mat, quantity_ordered=Decimal('100'), unit='each', unit_cost=Decimal('0.15'))
        self._login()
        resp = self.client.get(reverse('operations:purchase_list'))
        self.assertContains(resp, 'Bubble mailers 6x9 (100pk)')         # description readable inline
        self.assertContains(resp, reverse('operations:dashboard_receive_line', args=[line.id]))
        self.assertContains(resp, 'Not received')

    def test_multi_item_shows_each_line_and_whole_order_action(self):
        purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='B-1')
        lines = []
        for i, c in enumerate(['Cyan', 'Magenta', 'Yellow']):
            mat = _filament_material(c, f'C{i}')
            lines.append(m.PurchaseLine.objects.create(
                purchase=purchase, item_type='filament', description=f'PLA {c} refill',
                material=mat, quantity_ordered=Decimal('1'), unit='roll', unit_cost=Decimal('9.74')))
        self._login()
        resp = self.client.get(reverse('operations:purchase_list'))
        for ln in lines:
            self.assertContains(resp, ln.description)
            self.assertContains(resp, reverse('operations:dashboard_receive_line', args=[ln.id]))
        # 3 quick-receivable lines → whole-order action offered, scoped to this order.
        self.assertContains(resp, reverse('operations:dashboard_receive_purchase', args=[purchase.id]))
        self.assertContains(resp, 'Receive remaining on this entire order')

    def test_single_item_order_has_no_whole_order_button(self):
        mat = _filament_material('Only', 'O1')
        purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='B-solo')
        m.PurchaseLine.objects.create(
            purchase=purchase, item_type='filament', description='PLA only refill',
            material=mat, quantity_ordered=Decimal('1'), unit='roll', unit_cost=Decimal('9'))
        self._login()
        resp = self.client.get(reverse('operations:purchase_list'))
        self.assertNotContains(resp, reverse('operations:dashboard_receive_purchase', args=[purchase.id]))

    def test_partially_received_order_only_offers_receive_on_outstanding_line(self):
        purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='B-2')
        mat_a = _filament_material('A', 'A1')
        mat_b = _filament_material('B', 'B1')
        done = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='filament', description='PLA A refill',
            material=mat_a, quantity_ordered=Decimal('1'), unit='roll', unit_cost=Decimal('9'))
        todo = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='filament', description='PLA B refill',
            material=mat_b, quantity_ordered=Decimal('1'), unit='roll', unit_cost=Decimal('9'))
        services.quick_receive_line(line=done, actor=self.admin)        # receive the first line
        self._login()
        resp = self.client.get(reverse('operations:purchase_list'))
        self.assertContains(resp, reverse('operations:dashboard_receive_line', args=[todo.id]))
        self.assertNotContains(resp, reverse('operations:dashboard_receive_line', args=[done.id]))
        self.assertContains(resp, 'Partial')                            # order-level badge

    def test_unconfirmed_line_offers_confirm_received(self):
        purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='B-unc')
        mat = _filament_material('Unc', 'U1')
        line = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='filament', description='PLA unconfirmed',
            material=mat, quantity_ordered=Decimal('1'), unit='roll', unit_cost=Decimal('9'))
        line.delivery = 'unconfirmed'
        line.quantity_received = Decimal('1')
        line.save(update_fields=['delivery', 'quantity_received'])
        m.FilamentSpool.objects.create(material=mat, spool_uid='UC-1', starting_weight_g=0,
                                       remaining_unknown=True, delivery_confirmed=False,
                                       source_line=line, status='sealed')
        self._login()
        resp = self.client.get(reverse('operations:purchase_list'))
        self.assertContains(resp, reverse('operations:dashboard_confirm_line', args=[line.id]))
        self.assertContains(resp, 'Delivery unconfirmed')

    def test_canceled_line_is_visible_and_not_receivable(self):
        purchase = m.Purchase.objects.create(supplier_name='Home Depot', order_number='HD-1')
        mat_live = _stock_material('Shelf', 'SH1')
        mat_cx = _stock_material('Countertop', 'CT1')
        live = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='Shelf', material=mat_live,
            quantity_ordered=Decimal('1'), unit='each', unit_cost=Decimal('104'))
        canceled = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='Countertop', material=mat_cx,
            quantity_ordered=Decimal('1'), unit='each', unit_cost=Decimal('259.93'))
        services.cancel_line(line=canceled, actor=self.admin, reason='returned at register')
        self._login()
        resp = self.client.get(reverse('operations:purchase_list'))
        self.assertContains(resp, 'Countertop')                         # still visible
        self.assertContains(resp, 'Canceled')
        # No receive control for the canceled line; the live line still has one.
        self.assertNotContains(resp, reverse('operations:dashboard_receive_line', args=[canceled.id]))
        self.assertContains(resp, reverse('operations:dashboard_receive_line', args=[live.id]))
        # Belt-and-braces: a direct POST to receive the canceled line changes nothing.
        resp2 = self.client.post(reverse('operations:dashboard_receive_line', args=[canceled.id]),
                                 {'idempotency_key': 'x'})
        self.assertEqual(resp2.status_code, 302)
        canceled.refresh_from_db()
        self.assertEqual(canceled.quantity_received, ZERO)

    def test_fully_canceled_order_shows_canceled_badge(self):
        purchase = m.Purchase.objects.create(supplier_name='Home Depot', order_number='HD-2')
        mat = _stock_material('Thing', 'TH1')
        m.PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='Thing', material=mat,
            quantity_ordered=Decimal('1'), unit='each', unit_cost=Decimal('10'))
        services.cancel_purchase(purchase=purchase, actor=self.admin, reason='supplier canceled')
        self._login()
        resp = self.client.get(reverse('operations:purchase_list'))
        self.assertContains(resp, 'canceled — excluded')
        self.assertContains(resp, 'Canceled')

    def test_receive_from_list_stays_on_list(self):
        mat = _stock_material('Tape', 'T1')
        purchase = m.Purchase.objects.create(supplier_name='Amazon', order_number='A-9')
        line = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='Packing tape', material=mat,
            quantity_ordered=Decimal('6'), unit='each', unit_cost=Decimal('2'))
        self._login()
        list_url = reverse('operations:purchase_list')
        resp = self.client.post(reverse('operations:dashboard_receive_line', args=[line.id]),
                                {'idempotency_key': 'k', 'next': list_url})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, list_url)                            # back to the list, not dashboard
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('6'))

    def test_receive_ignores_unsafe_next(self):
        mat = _stock_material('Tape2', 'T2')
        purchase = m.Purchase.objects.create(supplier_name='Amazon', order_number='A-10')
        line = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='More tape', material=mat,
            quantity_ordered=Decimal('1'), unit='each', unit_cost=Decimal('2'))
        self._login()
        resp = self.client.post(reverse('operations:dashboard_receive_line', args=[line.id]),
                                {'idempotency_key': 'k', 'next': 'https://evil.example.com/x'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('operations:dashboard'), resp.url)        # falls back to dashboard
        self.assertNotIn('evil.example.com', resp.url)

    def test_catalog_shown_only_when_it_adds_info(self):
        from operations.views import _catalog_adds_info
        # Near-duplicate of the description → suppressed.
        self.assertFalse(_catalog_adds_info('Bambu PLA Basic Cyan (1 kg refill) — gift',
                                            'Bambu Lab PLA Basic Cyan'))
        self.assertFalse(_catalog_adds_info('Cable ties', 'Cable ties'))
        # Genuinely different catalog name → shown.
        self.assertTrue(_catalog_adds_info('MarsWork Quick-Swap Reusable Spool, 4 pcs',
                                           'Quick-swap reusable spools (4-pack, empty cores)'))
        self.assertTrue(_catalog_adds_info('BNUOK 120pcs hex socket head cap screws',
                                           'M3×40mm cap screws (120-pack)'))
        # No material → nothing to show.
        self.assertFalse(_catalog_adds_info('Some item', ''))

    def test_description_falls_back_to_material_name(self):
        mat = _stock_material('Named Material', 'NM1')
        purchase = m.Purchase.objects.create(supplier_name='Amazon', order_number='A-11')
        m.PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='', material=mat,
            quantity_ordered=Decimal('1'), unit='each', unit_cost=Decimal('1'))
        self._login()
        resp = self.client.get(reverse('operations:purchase_list'))
        self.assertContains(resp, 'Named Material')
