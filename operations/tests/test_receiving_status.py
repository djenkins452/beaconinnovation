"""Tests for consistent receiving status and the delivery-status correction workflow.

Covers the bug where the purchases list (quantity-based) and the detail screen
(explicit delivery flag) disagreed: both now read one derived ``receiving_status``.
Also covers marking an assumed/unconfirmed delivery as not received (safely, with
history preserved and used inventory protected), confirming a delivery later,
repeated submissions, partial receipts, that notes are never the source of truth,
and that corrections never touch costs/funding/payments/documents.
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


class StatusConsistencyTests(TestCase):
    """The list and the detail must never disagree — both use receiving_status."""

    def setUp(self):
        self.mat = _filament_material()
        self.purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='B-1')

    def _line(self, **kw):
        defaults = dict(purchase=self.purchase, item_type='filament', description='PLA refill',
                        material=self.mat, quantity_ordered=Decimal('1'), unit='roll',
                        unit_cost=Decimal('9.74'))
        defaults.update(kw)
        return m.PurchaseLine.objects.create(**defaults)

    def test_assumed_delivery_is_unconfirmed_on_both_screens(self):
        # Reproduce the imported Bambu state: received counter advanced AND an
        # explicit 'unconfirmed' flag, with an unconfirmed (not-on-hand) spool.
        line = self._line(quantity_received=Decimal('1'), delivery='unconfirmed')
        m.FilamentSpool.objects.create(material=self.mat, spool_uid='SP-1', starting_weight_g=0,
                                       remaining_unknown=True, delivery_confirmed=False,
                                       source_line=line)
        # Line badge and order badge agree — no more "Received" vs "Unconfirmed" split.
        self.assertEqual(line.receiving_status, 'unconfirmed')
        self.assertEqual(self.purchase.receiving_status, 'unconfirmed')
        # And the legacy list alias now reflects the same single source.
        self.assertEqual(self.purchase.receipt_status, 'unconfirmed')

    def test_unconfirmed_spool_excluded_from_available_inventory(self):
        line = self._line(quantity_received=Decimal('1'), delivery='unconfirmed')
        m.FilamentSpool.objects.create(material=self.mat, spool_uid='SP-2', starting_weight_g=0,
                                       remaining_unknown=True, delivery_confirmed=False,
                                       source_line=line)
        counts = self.mat.filament_status_counts()
        self.assertEqual(counts['total'], 0)      # nothing confirmed on-hand
        self.assertEqual(counts['awaiting'], 1)   # shown separately as awaiting

    def test_notes_are_not_the_source_of_truth(self):
        # Notes claim it was received; delivery flag says outstanding → outstanding.
        self.purchase.notes = 'Received sealed/unopened.'
        self.purchase.save(update_fields=['notes'])
        line = self._line(quantity_received=ZERO, delivery='')
        self.assertEqual(line.receiving_status, 'outstanding')
        self.assertEqual(self.purchase.receiving_status, 'none')

    def test_confirmed_receipt_reads_received(self):
        line = self._line(quantity_received=Decimal('1'), delivery='')
        m.FilamentSpool.objects.create(material=self.mat, spool_uid='SP-3', starting_weight_g=0,
                                       remaining_unknown=True, delivery_confirmed=True,
                                       source_line=line)
        self.assertEqual(line.receiving_status, 'received')
        self.assertEqual(self.purchase.receiving_status, 'received')

    def test_partial_order_mixed_lines(self):
        self._line(quantity_received=ZERO, delivery='')                      # outstanding
        self._line(quantity_received=Decimal('1'), delivery='unconfirmed')   # unconfirmed
        self.assertEqual(self.purchase.receiving_status, 'partial')

    def test_other_line_has_nothing_to_receive(self):
        line = self._line(item_type='other', material=None, quantity_received=ZERO)
        self.assertEqual(line.receiving_status, 'na')
        # An order of only 'other' lines has no receivable lines.
        self.assertEqual(self.purchase.receiving_status, 'empty')


class MarkNotReceivedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('admin@x.com', is_superuser=True, is_staff=True,
                                             is_active=True)
        self.mat = _filament_material()
        self.purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='B-2',
                                                  funding='personal')

    def _unconfirmed_filament_line(self, uid='SP-A', qty=Decimal('1')):
        line = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='filament', description='PLA refill',
            material=self.mat, quantity_ordered=qty, quantity_received=qty, unit='roll',
            unit_cost=Decimal('9.74'), delivery='unconfirmed')
        spool = m.FilamentSpool.objects.create(
            material=self.mat, spool_uid=uid, starting_weight_g=0, remaining_unknown=True,
            delivery_confirmed=False, source_line=line, status='sealed')
        return line, spool

    def test_removes_phantom_spool_and_resets_line(self):
        line, spool = self._unconfirmed_filament_line()
        services.mark_line_not_received(line=line, actor=self.user)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, ZERO)
        self.assertEqual(line.delivery, 'outstanding')
        self.assertEqual(line.receiving_status, 'outstanding')
        self.assertFalse(m.FilamentSpool.objects.filter(pk=spool.pk).exists())  # phantom removed
        self.assertEqual(m.InventoryMovement.objects.count(), 0)  # none created
        self.assertTrue(m.AuditEvent.objects.filter(action='delete', model_name='FilamentSpool').exists())
        self.assertTrue(m.AuditEvent.objects.filter(model_name='PurchaseLine', action='update').exists())

    def test_does_not_touch_costs_funding_or_payments(self):
        line, _ = self._unconfirmed_filament_line()
        total_before = self.purchase.order_total()
        services.mark_line_not_received(line=line, actor=self.user)
        line.refresh_from_db()
        self.purchase.refresh_from_db()
        self.assertEqual(line.unit_cost, Decimal('9.74'))      # cost basis unchanged
        self.assertEqual(self.purchase.order_total(), total_before)
        self.assertEqual(self.purchase.funding, 'personal')    # funding unchanged
        self.assertEqual(self.purchase.payments.count(), 0)    # no payment created

    def test_idempotent_second_call_is_noop(self):
        line, _ = self._unconfirmed_filament_line()
        services.mark_line_not_received(line=line, actor=self.user)
        services.mark_line_not_received(line=line, actor=self.user)  # no error
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, ZERO)
        self.assertEqual(line.delivery, 'outstanding')

    def test_protects_spool_already_used(self):
        # A confirmed spool with real grams that have been consumed cannot be undone.
        line = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='filament', description='PLA spool',
            material=self.mat, quantity_ordered=Decimal('1'), unit='roll', unit_cost=Decimal('20'))
        spool = services.receive_filament_spool(
            line=line, spool_uid='USED-1', actor=self.user, starting_weight_g=Decimal('1000'),
            remaining_unknown=False, status='open')
        services.post_movement(movement_type='consumption', spool=spool, quantity=Decimal('-200'),
                               unit='g', actor=self.user, reason='print')
        with self.assertRaises(services.ValidationError):
            services.mark_line_not_received(line=line, actor=self.user)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('1'))  # untouched

    def test_stock_receipt_is_reversed_not_deleted(self):
        stock_mat = _stock_material()
        line = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='stock', description='mailers',
            material=stock_mat, quantity_ordered=Decimal('10'), unit='each', unit_cost=Decimal('0.25'))
        services.receive_stock_line(line=line, quantity=Decimal('10'), actor=self.user)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal('10'))
        services.mark_line_not_received(line=line, actor=self.user)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, ZERO)
        self.assertEqual(line.delivery, 'outstanding')
        si = m.StockItem.objects.get(material=stock_mat)
        self.assertEqual(si.on_hand, ZERO)                 # reversed to zero
        self.assertFalse(si.delivery_confirmed)
        # History preserved: the original receipt + its reversal both remain.
        self.assertEqual(si.movements.count(), 2)

    def test_protects_stock_already_drawn_down(self):
        stock_mat = _stock_material('Screws', 'SC1')
        line = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='stock', description='screws',
            material=stock_mat, quantity_ordered=Decimal('5'), unit='each', unit_cost=Decimal('1'))
        services.receive_stock_line(line=line, quantity=Decimal('5'), actor=self.user)
        si = m.StockItem.objects.get(material=stock_mat)
        services.post_movement(movement_type='consumption', stock_item=si, quantity=Decimal('-3'),
                               unit='each', actor=self.user, reason='used')
        with self.assertRaises(services.ValidationError):
            services.mark_line_not_received(line=line, actor=self.user)


class ConfirmReceivedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('admin@x.com', is_superuser=True, is_staff=True,
                                             is_active=True)
        self.mat = _filament_material()
        self.purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='B-3')

    def _line(self, uid='SP-C'):
        line = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='filament', description='PLA refill',
            material=self.mat, quantity_ordered=Decimal('1'), quantity_received=Decimal('1'),
            unit='roll', unit_cost=Decimal('9.74'), delivery='unconfirmed')
        spool = m.FilamentSpool.objects.create(
            material=self.mat, spool_uid=uid, starting_weight_g=0, remaining_unknown=True,
            delivery_confirmed=False, source_line=line, status='sealed')
        return line, spool

    def test_confirm_flips_records_and_status(self):
        line, spool = self._line()
        services.confirm_line_received(line=line, actor=self.user)
        line.refresh_from_db(); spool.refresh_from_db()
        self.assertEqual(line.delivery, 'received')
        self.assertTrue(spool.delivery_confirmed)
        self.assertEqual(line.receiving_status, 'received')
        self.assertEqual(m.InventoryMovement.objects.count(), 0)  # no new movement
        # Now counted as on-hand.
        self.assertEqual(self.mat.filament_status_counts()['total'], 1)

    def test_confirm_idempotent(self):
        line, _ = self._line()
        services.confirm_line_received(line=line, actor=self.user)
        services.confirm_line_received(line=line, actor=self.user)  # no error
        line.refresh_from_db()
        self.assertEqual(line.delivery, 'received')

    def test_confirm_nothing_recorded_is_rejected(self):
        line = m.PurchaseLine.objects.create(
            purchase=self.purchase, item_type='filament', description='nothing here',
            material=self.mat, quantity_ordered=Decimal('1'), unit='roll', delivery='unconfirmed')
        with self.assertRaises(services.ValidationError):
            services.confirm_line_received(line=line, actor=self.user)


class PurchaseLevelCorrectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('admin@x.com', is_superuser=True, is_staff=True,
                                             is_active=True)
        self.mat = _filament_material()
        self.purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number='B-4')
        for i in range(3):
            line = m.PurchaseLine.objects.create(
                purchase=self.purchase, item_type='filament', description=f'refill {i}',
                material=self.mat, quantity_ordered=Decimal('1'), quantity_received=Decimal('1'),
                unit='roll', unit_cost=Decimal('9.74'), delivery='unconfirmed')
            m.FilamentSpool.objects.create(material=self.mat, spool_uid=f'SP-{i}', starting_weight_g=0,
                                           remaining_unknown=True, delivery_confirmed=False,
                                           source_line=line, status='sealed')

    def test_mark_whole_order_not_received(self):
        n = services.mark_purchase_not_received(purchase=self.purchase, actor=self.user)
        self.assertEqual(n, 3)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.receiving_status, 'none')
        self.assertEqual(m.FilamentSpool.objects.filter(source_line__purchase=self.purchase).count(), 0)

    def test_confirm_whole_order(self):
        n = services.confirm_purchase_received(purchase=self.purchase, actor=self.user)
        self.assertEqual(n, 3)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.receiving_status, 'received')


class CorrectionViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin@x.com', password='pw', is_superuser=True,
                                             is_staff=True, is_active=True)
        cls.regular = User.objects.create_user('reg@x.com', password='pw')
        cls.mat = _filament_material()

    def _line(self, order='V-1', uid='SPV-1'):
        purchase = m.Purchase.objects.create(supplier_name='Bambu Lab', order_number=order)
        line = m.PurchaseLine.objects.create(
            purchase=purchase, item_type='filament', description='PLA refill', material=self.mat,
            quantity_ordered=Decimal('1'), quantity_received=Decimal('1'), unit='roll',
            unit_cost=Decimal('9.74'), delivery='unconfirmed')
        m.FilamentSpool.objects.create(material=self.mat, spool_uid=uid, starting_weight_g=0,
                                       remaining_unknown=True, delivery_confirmed=False,
                                       source_line=line, status='sealed')
        return purchase, line

    def test_endpoints_require_admin(self):
        _, line = self._line()
        url = reverse('operations:line_mark_not_received', args=[line.id])
        self.assertEqual(self.client.post(url).status_code, 302)   # anon → login
        self.client.login(username='reg@x.com', password='pw')
        self.assertEqual(self.client.post(url).status_code, 404)   # non-admin hidden

    def test_admin_marks_line_not_received(self):
        _, line = self._line()
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.post(reverse('operations:line_mark_not_received', args=[line.id]))
        self.assertEqual(resp.status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, ZERO)
        self.assertEqual(line.delivery, 'outstanding')

    def test_admin_confirms_whole_order(self):
        purchase, _ = self._line(order='V-2', uid='SPV-2')
        self.client.login(username='admin@x.com', password='pw')
        resp = self.client.post(reverse('operations:purchase_confirm_received', args=[purchase.id]))
        self.assertEqual(resp.status_code, 302)
        purchase.refresh_from_db()
        self.assertEqual(purchase.receiving_status, 'received')
