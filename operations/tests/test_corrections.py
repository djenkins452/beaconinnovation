"""Tests for the post-import correction behaviours and the optional-tracking helpers:
status changes without weighing, delivery confirmation, honest dates, location merge,
filament status counts, and that the correction command is marker-idempotent.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from operations import models as m
from operations import services


class ModelHelperTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.mat = m.Material.objects.create(material_type='filament', manufacturer='Bambu Lab',
                                            product_type='PLA Basic', name='Black', sku='10101')

    def _spool(self, uid, status='sealed', refill=False, confirmed=True):
        return m.FilamentSpool.objects.create(material=self.mat, spool_uid=uid, starting_weight_g=0,
                                              remaining_unknown=True, is_refill=refill, status=status,
                                              delivery_confirmed=confirmed)

    def test_remaining_display_unknown_is_not_zero(self):
        s = self._spool('S1', 'open')
        self.assertIn('Unknown', s.remaining_display)
        self.assertNotIn('0 g', s.remaining_display)

    def test_filament_status_counts(self):
        self._spool('A', 'open'); self._spool('B', 'low'); self._spool('C', 'sealed')
        self._spool('D', 'sealed', refill=True); self._spool('E', 'sealed', confirmed=False)
        c = self.mat.filament_status_counts()
        self.assertEqual(c['open'], 1)
        self.assertEqual(c['low'], 1)
        self.assertEqual(c['sealed'], 2)          # one spool + one refill, both confirmed
        self.assertEqual(c['refills'], 1)
        self.assertEqual(c['spare_unopened'], 1)  # sealed, not a refill
        self.assertEqual(c['awaiting'], 1)        # the unconfirmed one
        self.assertEqual(c['total'], 4)           # confirmed only

    def test_set_spool_status_without_weight(self):
        s = self._spool('S2', 'sealed')
        services.set_spool_status(spool=s, status='low', actor=None)
        s.refresh_from_db()
        self.assertEqual(s.status, 'low')
        self.assertEqual(s.movements.count(), 0)   # no weight / movement invented

    def test_confirm_delivery(self):
        s = self._spool('S3', 'sealed', confirmed=False)
        self.assertTrue(s.awaiting_confirmation)
        services.confirm_spool_delivery(spool=s, actor=None)
        s.refresh_from_db()
        self.assertFalse(s.awaiting_confirmation)


class DeliveryStateTests(TestCase):
    def test_line_delivery_state(self):
        p = m.Purchase.objects.create(supplier_name='X', order_number='O1')
        ln = m.PurchaseLine.objects.create(purchase=p, item_type='stock', description='thing',
                                           quantity_ordered=1, quantity_received=0)
        self.assertEqual(ln.delivery_state, 'outstanding')   # nothing received
        ln.quantity_received = Decimal('1')
        self.assertEqual(ln.delivery_state, 'received')
        ln.delivery = 'unconfirmed'                           # explicit override wins
        self.assertEqual(ln.delivery_state, 'unconfirmed')


class PrintDateTests(TestCase):
    def test_date_unknown_display_and_tracking(self):
        p = m.PrintLog.objects.create(name='Old print', is_historical=True, date_unknown=True)
        self.assertEqual(p.date_display, 'Date unknown (historical)')
        self.assertFalse(p.material_tracked)        # no material uses
        self.assertFalse(p.in_progress)
        p2 = m.PrintLog.objects.create(name='Batch', outcome='in_progress')
        self.assertTrue(p2.in_progress)


class MergeLocationTests(TestCase):
    def test_merge_repoints_and_deletes_sources(self):
        mat = m.Material.objects.create(material_type='filament', name='Blue', sku='10601')
        hw = m.Material.objects.create(material_type='hardware', name='Screws')
        target = m.Location.objects.create(name='Home Office / Print Room', kind='room')
        a = m.Location.objects.create(name='Print room', kind='shelf')
        b = m.Location.objects.create(name='Dry box', kind='drybox')
        m.FilamentSpool.objects.create(material=mat, spool_uid='SP', starting_weight_g=0,
                                       remaining_unknown=True, location=b)
        m.StockItem.objects.create(material=hw, location=a, unit='pack')
        services.merge_locations(target=target, sources=[a, b], actor=None)
        self.assertFalse(m.Location.objects.filter(name__in=['Print room', 'Dry box']).exists())
        self.assertEqual(m.FilamentSpool.objects.filter(location=target).count(), 1)
        self.assertEqual(m.StockItem.objects.filter(location=target).count(), 1)


class CorrectionCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user('dannyjenkins71@gmail.com', is_superuser=True, is_staff=True, is_active=True)

    def test_runs_and_is_marker_idempotent_on_empty_db(self):
        # With no imported records it is a safe no-op that still writes the marker.
        call_command('correct_operations', '--apply')
        self.assertTrue(m.AuditEvent.objects.filter(summary__startswith='print-history-correction').exists())
        before = m.AuditEvent.objects.count()
        call_command('correct_operations', '--apply')   # second run: marker present → no-op
        self.assertEqual(m.AuditEvent.objects.count(), before)
