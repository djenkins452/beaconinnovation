"""Tests for the print-history importer and the optional-gram-tracking changes.

Covers the behaviours called out for this import:
* a completed print recorded with UNKNOWN filament grams (nothing invented);
* a no-payment internal order + fulfillment (never deducts filament, no expense);
* re-running the import is idempotent (no duplicates, no double deduction);
* outstanding (not-received) lines create no inventory;
* in-progress production stays out of finished-goods stock;
* reconciliation mismatches are caught before applying.
"""
import json
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from finance.models import Transaction
from operations import models as m


def _spec(**over):
    data = {
        'import_tag': 'test-import',
        'actor_username': 'importer',
        'suppliers': ['Amazon', 'Bambu Lab'],
        'locations': [{'name': 'Print room', 'kind': 'shelf'}],
        'filament_materials': [
            {'key': 'black', 'manufacturer': 'Bambu Lab', 'product_type': 'PLA Basic',
             'name': 'Black', 'sku': '10101', 'nominal_spool_weight_g': '1000'},
        ],
        'purchases': [
            {'supplier': 'Bambu Lab', 'order_number': 'ORD-FIL', 'order_date': '2026-10-27',
             'tax_total': '2.00', 'shipping_total': '0.00', 'discount_total': '0.00',
             'expected_total': '13.69', 'document': None, 'lines': [
                {'item_type': 'filament', 'description': 'PLA Basic Black (1 kg spool)',
                 'material_key': 'black', 'quantity': '1', 'unit': 'roll', 'unit_cost': '11.69',
                 'line_discount': '0.00', 'line_tax': '0.00', 'use_type': 'business',
                 'received': True, 'location': 'Print room',
                 'spools': [{'uid': 'T-BLACK-1', 'status': 'open', 'remaining_unknown': True,
                             'is_refill': False, 'cost': '11.69', 'starting_weight_g': '0'}]},
             ]},
            {'supplier': 'Amazon', 'order_number': 'ORD-OUT', 'order_date': '2026-10-31',
             'tax_total': '1.00', 'shipping_total': '0.00', 'discount_total': '0.00',
             'expected_total': '11.00', 'document': None, 'lines': [
                {'item_type': 'stock', 'description': 'Widget pack', 'material_name': 'Widget pack',
                 'stock_category': 'hardware', 'quantity': '1', 'unit': 'pack', 'unit_cost': '10.00',
                 'line_discount': '0.00', 'line_tax': '0.00', 'use_type': 'business',
                 'received': False, 'track_inventory': False, 'location': 'Print room'},
             ]},
        ],
        'products': [
            {'key': 'bin', 'name': 'Test Bin', 'internal_only': True, 'catalog_eligible': False,
             'variants': [{'key': 'bin_default', 'name': 'Default'}]},
        ],
        'prints': [
            {'token': 'test:print:done', 'name': 'Bin (done)', 'printed_on': '2026-10-28',
             'is_historical': True, 'printer_name': None, 'purpose': 'business', 'outcome': 'success',
             'notes': 'grams untracked', 'products': [
                 {'variant_key': 'bin_default', 'quantity_planned': 1, 'quantity_success': 1}]},
            {'token': 'test:print:wip', 'name': 'Bin batch (in progress)', 'printed_on': '2026-11-01',
             'is_historical': False, 'printer_name': None, 'purpose': 'business', 'outcome': 'in_progress',
             'notes': 'batch', 'products': [
                 {'variant_key': 'bin_default', 'quantity_planned': 10, 'quantity_success': 0}]},
        ],
        'internal_orders': [
            {'token': 'test:io:personal', 'purpose': 'personal', 'ordered_on': '2026-10-28',
             'notes': 'internal', 'lines': [{'variant_key': 'bin_default', 'quantity': 1}]},
        ],
    }
    data.update(over)
    return data


class ImportHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user('importer', is_superuser=True, is_staff=True, is_active=True)

    def _write(self, data):
        path = Path(tempfile.mkdtemp()) / 'spec.json'
        path.write_text(json.dumps(data))
        return str(path)

    def _apply(self, data=None):
        call_command('import_print_history', data=self._write(data or _spec()), apply=True)

    def test_unknown_grams_spool_has_no_movement(self):
        self._apply()
        spool = m.FilamentSpool.objects.get(spool_uid='T-BLACK-1')
        self.assertTrue(spool.remaining_unknown)
        self.assertEqual(spool.movements.count(), 0)          # no invented weight
        self.assertEqual(spool.estimated_remaining_g, 0)
        self.assertIn('Unknown', spool.remaining_display)

    def test_completed_print_then_fulfilled_nets_to_zero_no_expense(self):
        self._apply()
        variant = m.ProductVariant.objects.get(name='Default', product__name='Test Bin')
        self.assertEqual(variant.on_hand, 0)                  # produced 1, fulfilled 1
        order = m.InternalOrder.objects.get(fulfillment_token='test:io:personal')
        self.assertEqual(order.status, 'fulfilled')
        self.assertEqual(order.payment_label, 'No payment required')
        self.assertEqual(Transaction.objects.count(), 0)      # finance never touched
        self.assertFalse(m.InventoryMovement.objects.filter(movement_type='fulfillment',
                                                            spool__isnull=False).exists())

    def test_in_progress_batch_makes_no_finished_goods(self):
        self._apply()
        self.assertTrue(m.PrintLog.objects.filter(outcome='in_progress').exists())
        produced = m.InventoryMovement.objects.filter(movement_type='production_output').count()
        self.assertEqual(produced, 1)                         # only the completed print, not the batch

    def test_outstanding_line_creates_no_inventory(self):
        self._apply()
        line = m.PurchaseLine.objects.get(purchase__order_number='ORD-OUT')
        self.assertEqual(line.receipt_state, 'none')
        self.assertFalse(line.movements.exists())
        self.assertFalse(m.StockItem.objects.filter(material__name='Widget pack').exists())

    def test_rerun_is_idempotent(self):
        self._apply()
        before = {name: getattr(m, name).objects.count() for name in
                  ['Purchase', 'PurchaseLine', 'FilamentSpool', 'InventoryMovement',
                   'PrintLog', 'InternalOrder', 'ProductVariant']}
        self._apply()
        after = {name: getattr(m, name).objects.count() for name in before}
        self.assertEqual(before, after)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_reconciliation_mismatch_is_rejected(self):
        bad = _spec()
        bad['purchases'][0]['expected_total'] = '999.99'
        with self.assertRaises(CommandError):
            call_command('import_print_history', data=self._write(bad), apply=True)
        self.assertEqual(m.Purchase.objects.count(), 0)       # nothing applied
