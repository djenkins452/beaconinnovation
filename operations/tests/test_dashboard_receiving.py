"""Tests for fast receiving straight from the Operations dashboard.

Covers the one-click line receive (full + partial), multi-colour filament orders,
the "Receive remaining order" action, confirming existing unconfirmed inventory
(no duplicates), filament defaults (sealed, grams untracked, refill vs spool, auto
location), that costs/funding/payments are never touched, duplicate submissions are
idempotent, and the dashboard endpoints stay active-superuser-only.
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


class QuickReceiveLineServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('admin@x.com', is_superuser=True, is_staff=True,
                                             is_active=True)
        self.loc = m.Location.objects.create(name='Home Office / Print Room', kind='room')
        self.mat = _filament_material()
        self.purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='B-1',
                                                   funding='personal')

    def _filament_line(self, qty=Decimal('3')):
        return m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='filament', description='PLA refill',
            material=self.mat, quantity_ordered=qty, unit='roll', unit_cost=Decimal('9.74'))

    def test_full_receive_creates_confirmed_sealed_untracked_spools(self):
        line = self._filament_line(Decimal('3'))
        result = services.quick_receive_line(line=line, actor=self.user)
        self.assertEqual(result['created'], 3)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('3'))
        self.assertEqual(line.receiving_status, 'received')
        spools = m.FilamentSpool.objects.filter(source_line=line)
        self.assertEqual(spools.count(), 3)
        for s in spools:
            self.assertTrue(s.delivery_confirmed)      # arrived → counts on hand
            self.assertEqual(s.status, 'sealed')       # sealed/new default
            self.assertTrue(s.remaining_unknown)       # grams untracked
            self.assertFalse(s.is_refill)              # physical spools by default
            self.assertEqual(s.location, self.loc)     # auto location
        # Grams untracked => no inventory movements posted for these spools.
        self.assertEqual(m.InventoryMovement.objects.filter(spool__source_line=line).count(), 0)
        # Counted as on-hand now.
        self.assertEqual(self.mat.filament_status_counts()['total'], 3)

    def test_partial_receive_then_remainder(self):
        line = self._filament_line(Decimal('3'))
        services.quick_receive_line(line=line, actor=self.user, quantity=Decimal('1'))
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('1'))
        self.assertEqual(line.receiving_status, 'partial')
        # Receiving the rest (a new submission) tops it up without duplicating.
        services.quick_receive_line(line=line, actor=self.user)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('3'))
        self.assertEqual(m.FilamentSpool.objects.filter(source_line=line).count(), 3)

    def test_refill_distinction_preserved(self):
        line = self._filament_line(Decimal('2'))
        services.quick_receive_line(line=line, actor=self.user, is_refill=True)
        spools = m.FilamentSpool.objects.filter(source_line=line)
        self.assertEqual(spools.count(), 2)
        self.assertTrue(all(s.is_refill for s in spools))

    def test_duplicate_submission_is_idempotent(self):
        line = self._filament_line(Decimal('2'))
        token = 'tok-dup-1'
        services.quick_receive_line(line=line, actor=self.user, idempotency_key=token)
        services.quick_receive_line(line=line, actor=self.user, idempotency_key=token)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('2'))         # not doubled
        self.assertEqual(m.FilamentSpool.objects.filter(source_line=line).count(), 2)

    def test_stock_receive_posts_single_movement_and_is_idempotent(self):
        stock_mat = _stock_material()
        line = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='stock', description='mailers',
            material=stock_mat, quantity_ordered=Decimal('10'), unit='each', unit_cost=Decimal('0.25'))
        token = 'tok-stock-1'
        services.quick_receive_line(line=line, actor=self.user, idempotency_key=token)
        services.quick_receive_line(line=line, actor=self.user, idempotency_key=token)  # retry
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('10'))
        si = m.StockItem.objects.get(material=stock_mat)
        self.assertEqual(si.on_hand, Decimal('10'))
        self.assertTrue(si.delivery_confirmed)
        self.assertEqual(si.movements.filter(movement_type='purchase_receipt').count(), 1)

    def test_does_not_touch_costs_funding_or_payments(self):
        line = self._filament_line(Decimal('2'))
        total_before = self.purchase.order_total()
        services.quick_receive_line(line=line, actor=self.user)
        self.purchase.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(line.unit_cost, Decimal('9.74'))
        self.assertEqual(self.purchase.order_total(), total_before)
        self.assertEqual(self.purchase.funding, 'personal')
        self.assertEqual(self.purchase.payments.count(), 0)
        from finance.models import Transaction
        self.assertEqual(Transaction.objects.count(), 0)   # no finance expense

    def test_equipment_and_other_are_rejected(self):
        eq = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='equipment', description='Printer',
            quantity_ordered=Decimal('1'), unit='each', unit_cost=Decimal('500'))
        with self.assertRaises(services.ValidationError):
            services.quick_receive_line(line=eq, actor=self.user)
        other = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='other', description='shipping',
            quantity_ordered=Decimal('1'), unit='each')
        with self.assertRaises(services.ValidationError):
            services.quick_receive_line(line=other, actor=self.user)

    def test_nothing_outstanding_is_rejected(self):
        line = self._filament_line(Decimal('1'))
        services.quick_receive_line(line=line, actor=self.user)
        with self.assertRaises(services.ValidationError):
            services.quick_receive_line(line=line, actor=self.user)  # already full


class QuickReceivePurchaseTests(TestCase):
    """The Bambu case: a multi-colour order received in one scoped action."""

    def setUp(self):
        self.user = User.objects.create_user('admin@x.com', is_superuser=True, is_staff=True,
                                             is_active=True)
        m.Location.objects.create(name='Home Office / Print Room', kind='room')
        self.bambu = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='us-792')
        self.colors = ['Cyan', 'Magenta', 'Yellow', 'Black']
        for i, c in enumerate(self.colors):
            mat = _filament_material(c, f'C{i}')
            m.PurchaseLine.objects.create(
                purchase=self.bambu, item_type='filament', description=f'PLA {c} refill',
                material=mat, quantity_ordered=Decimal('1'), unit='roll', unit_cost=Decimal('9.74'))
        # An unrelated order that must NOT be touched by the scoped action.
        self.other = m.Purchase.objects.create(supplier_name='Amazon', order_number='A-1')
        om = _stock_material('Tape', 'T1')
        self.other_line = m.PurchaseLine.objects.create(
            purchase=self.other, item_type='stock', description='tape', material=om,
            quantity_ordered=Decimal('5'), unit='each', unit_cost=Decimal('1'))

    def test_receive_remaining_order_is_scoped_and_complete(self):
        s = services.quick_receive_purchase(purchase=self.bambu, actor=self.user, is_refill=True)
        self.assertEqual(s['spools'], 4)
        self.bambu.refresh_from_db()
        self.assertEqual(self.bambu.receiving_status, 'received')
        # Four refills, one per colour, all confirmed on-hand.
        spools = m.FilamentSpool.objects.filter(source_line__purchase=self.bambu)
        self.assertEqual(spools.count(), 4)
        self.assertTrue(all(sp.is_refill and sp.delivery_confirmed for sp in spools))
        # The unrelated order is untouched.
        self.other_line.refresh_from_db()
        self.assertEqual(self.other_line.quantity_received, ZERO)

    def test_receive_remaining_is_idempotent(self):
        services.quick_receive_purchase(purchase=self.bambu, actor=self.user,
                                        is_refill=True, idempotency_key='ord-1')
        services.quick_receive_purchase(purchase=self.bambu, actor=self.user,
                                        is_refill=True, idempotency_key='ord-1')
        self.assertEqual(m.FilamentSpool.objects.filter(source_line__purchase=self.bambu).count(), 4)

    def test_skips_already_unconfirmed_lines(self):
        # Make one line already delivery-unconfirmed (recorded, not confirmed).
        line = self.bambu.lines.first()
        line.delivery = 'unconfirmed'
        line.quantity_received = Decimal('1')
        line.save(update_fields=['delivery', 'quantity_received'])
        m.FilamentSpool.objects.create(material=line.material, spool_uid='PRE-1',
                                       starting_weight_g=0, remaining_unknown=True,
                                       delivery_confirmed=False, source_line=line, status='sealed')
        s = services.quick_receive_purchase(purchase=self.bambu, actor=self.user, is_refill=True)
        self.assertEqual(s['spools'], 3)   # only the 3 outstanding lines received
        # The unconfirmed line keeps its single pre-existing spool (not duplicated).
        self.assertEqual(m.FilamentSpool.objects.filter(source_line=line).count(), 1)


class DashboardReceiveViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin@x.com', password='pw', is_superuser=True,
                                             is_staff=True, is_active=True)
        cls.regular = User.objects.create_user('reg@x.com', password='pw')
        m.Location.objects.create(name='Home Office / Print Room', kind='room')
        cls.mat = _filament_material()

    def _line(self, order='V-1', qty=Decimal('2')):
        purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number=order)
        line = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='filament', description='PLA refill', material=self.mat,
            quantity_ordered=qty, unit='roll', unit_cost=Decimal('9.74'))
        return purchase, line

    def test_endpoints_require_admin(self):
        _, line = self._line()
        url = reverse('operations:dashboard_receive_line', args=[line.id])
        self.assertEqual(self.client.post(url).status_code, 302)   # anon → login
        self.client.login(username='reg@x.com', password='pw')
        self.assertEqual(self.client.post(url).status_code, 404)   # non-admin hidden

    def test_admin_receives_line_and_lands_back_on_dashboard(self):
        _, line = self._line()
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.post(reverse('operations:dashboard_receive_line', args=[line.id]),
                                {'idempotency_key': 'k1'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('operations:dashboard'), resp.url)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('2'))

    def test_admin_partial_receive_via_form(self):
        _, line = self._line(order='V-2', qty=Decimal('3'))
        self.client.login(username='admin@x.com', password='pw')
        self.client.post(reverse('operations:dashboard_receive_line', args=[line.id]),
                         {'quantity': '1', 'is_refill': 'on', 'idempotency_key': 'k2'})
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('1'))
        sp = m.FilamentSpool.objects.filter(source_line=line)
        self.assertEqual(sp.count(), 1)
        self.assertTrue(sp.first().is_refill)

    def test_dashboard_double_post_same_token_is_idempotent(self):
        _, line = self._line(order='V-3', qty=Decimal('2'))
        self.client.login(username='admin@x.com', password='pw')
        url = reverse('operations:dashboard_receive_line', args=[line.id])
        self.client.post(url, {'idempotency_key': 'dup'})
        self.client.post(url, {'idempotency_key': 'dup'})
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('2'))
        self.assertEqual(m.FilamentSpool.objects.filter(source_line=line).count(), 2)

    def test_admin_confirms_unconfirmed_line_from_dashboard(self):
        purchase, line = self._line(order='V-4', qty=Decimal('1'))
        line.delivery = 'unconfirmed'
        line.quantity_received = Decimal('1')
        line.save(update_fields=['delivery', 'quantity_received'])
        spool = m.FilamentSpool.objects.create(
            material=self.mat, spool_uid='UC-1', starting_weight_g=0, remaining_unknown=True,
            delivery_confirmed=False, source_line=line, status='sealed')
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.post(reverse('operations:dashboard_confirm_line', args=[line.id]))
        self.assertEqual(resp.status_code, 302)
        spool.refresh_from_db(); line.refresh_from_db()
        self.assertTrue(spool.delivery_confirmed)
        self.assertEqual(line.receiving_status, 'received')
        # No duplicate spool created by confirming.
        self.assertEqual(m.FilamentSpool.objects.filter(source_line=line).count(), 1)

    def test_dashboard_lists_outstanding_with_receive_controls(self):
        _, line = self._line(order='V-5', qty=Decimal('2'))
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.get(reverse('operations:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Not received yet')
        self.assertContains(resp, reverse('operations:dashboard_receive_line', args=[line.id]))

    def test_receive_remaining_order_button_posts(self):
        purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='V-6')
        for i in range(3):
            mat = _filament_material(f'Col{i}', f'K{i}')
            m.PurchaseLine.objects.create(
                purchase=purchase, item_type='filament', description=f'refill {i}',
                material=mat, quantity_ordered=Decimal('1'), unit='roll', unit_cost=Decimal('9'))
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.post(reverse('operations:dashboard_receive_purchase', args=[purchase.id]),
                                {'is_refill': 'on', 'idempotency_key': 'ord-view-1'})
        self.assertEqual(resp.status_code, 302)
        purchase.refresh_from_db()
        self.assertEqual(purchase.receiving_status, 'received')
        self.assertEqual(m.FilamentSpool.objects.filter(source_line__purchase=purchase).count(), 3)
