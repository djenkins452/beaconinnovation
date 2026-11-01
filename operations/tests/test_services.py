"""Service-layer / invariant tests for Operations, using synthetic data only.

Covers the acceptance criteria from the task and the discovery report (§7):
on-hand == Σ(movements); opening inventory creates no expense; partial receipts;
no double-counted expense; multicolor + failed prints; waste counted once;
idempotent submissions; auditable corrections; insufficient-stock rejection.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase

from finance.models import Account, Category, Transaction
from operations import services
from operations.models import (
    AuditEvent, FilamentSpool, InventoryMovement, Material, PrintLog,
    Purchase, PurchaseLine, PurchasePayment, StockItem,
)

D = Decimal


class OpsTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ops', 'ops@example.com', 'pw', is_staff=True)
        self.filament = Material.objects.create(
            material_type='filament', manufacturer='Bambu', product_type='PLA',
            name='Matte Black', default_unit='g', nominal_spool_weight_g=D('1000'),
            reorder_threshold=D('500'))
        self.hardware = Material.objects.create(
            material_type='hardware', name='M3x8 bolt', default_unit='each',
            reorder_threshold=D('50'))
        self.account = Account.objects.create(name='Amex', account_type='credit_card', created_by=self.user)
        self.expense_cat = Category.objects.create(name='Materials', category_type='expense')


class OpeningInventoryTests(OpsTestBase):
    def test_opening_spool_creates_stock_without_expense(self):
        spool = services.enter_opening_spool(
            material=self.filament, spool_uid='SP-1', starting_weight_g=D('750'),
            actor=self.user)
        self.assertEqual(spool.estimated_remaining_g, D('750.00'))
        # Ledger invariant: on hand == Σ movements.
        total = spool.movements.aggregate(t=Sum('quantity'))['t']
        self.assertEqual(total, D('750.00'))
        # No finance expense was created.
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(spool.movements.first().movement_type, 'opening_balance')

    def test_opening_stock_creates_stock_without_expense(self):
        item = services.enter_opening_stock(
            material=self.hardware, quantity=D('100'), unit='each', actor=self.user)
        self.assertEqual(item.on_hand, D('100.000'))
        self.assertEqual(Transaction.objects.count(), 0)


class ReceivingTests(OpsTestBase):
    def _purchase(self):
        return Purchase.objects.create(supplier_name='McMaster', order_date=date(2026, 1, 2),
                                       created_by=self.user)

    def test_partial_then_full_receipt(self):
        purchase = self._purchase()
        line = PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='M3 bolts', material=self.hardware,
            quantity_ordered=D('100'), unit='each', unit_cost=D('0.10'))
        services.receive_stock_line(line=line, quantity=D('40'), actor=self.user)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, D('40.000'))
        self.assertEqual(line.receipt_state, 'partial')
        services.receive_stock_line(line=line, quantity=D('60'), actor=self.user)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, D('100.000'))
        self.assertEqual(line.receipt_state, 'received')
        # Stock on hand equals total received; no expense created by receiving.
        item = StockItem.objects.get(material=self.hardware)
        self.assertEqual(item.on_hand, D('100.000'))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_receiving_filament_creates_spools_no_expense(self):
        purchase = self._purchase()
        line = PurchaseLine.objects.create(
            purchase=purchase, item_type='filament', description='PLA x2', material=self.filament,
            quantity_ordered=D('2'), unit='roll', unit_cost=D('20'))
        spools = services.receive_filament_line(
            line=line, actor=self.user,
            spool_specs=[{'spool_uid': 'R-1', 'starting_weight_g': D('1000')},
                         {'spool_uid': 'R-2', 'starting_weight_g': D('1000')}])
        self.assertEqual(len(spools), 2)
        self.assertEqual(FilamentSpool.objects.count(), 2)
        for s in spools:
            self.assertEqual(s.estimated_remaining_g, D('1000.00'))
        self.assertEqual(Transaction.objects.count(), 0)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, D('2.000'))

    def test_equipment_receipt_is_asset_not_inventory(self):
        purchase = self._purchase()
        line = PurchaseLine.objects.create(
            purchase=purchase, item_type='equipment', description='Bambu P2S',
            quantity_ordered=D('1'), unit='each', unit_cost=D('1200'))
        services.receive_equipment_line(line=line, actor=self.user, name='P2S #1',
                                        equipment_type='printer')
        # Equipment creates NO inventory movement and NO expense.
        self.assertEqual(InventoryMovement.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)


class FinanceBridgeTests(OpsTestBase):
    def test_purchase_creates_exactly_one_expense_and_links_it(self):
        purchase = Purchase.objects.create(supplier_name='X', created_by=self.user)
        line = PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='bolts', material=self.hardware,
            quantity_ordered=D('100'), unit='each', unit_cost=D('0.10'))
        # Receive first (asset side) — must NOT create an expense.
        services.receive_stock_line(line=line, quantity=D('100'), actor=self.user)
        self.assertEqual(Transaction.objects.count(), 0)
        # Then record the money side exactly once.
        txn, payment = services.create_expense_for_purchase(
            purchase=purchase, account=self.account, category=self.expense_cat,
            amount=D('10.00'), transaction_date=date(2026, 1, 2), description='bolts',
            actor=self.user)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(PurchasePayment.objects.count(), 1)
        self.assertEqual(payment.transaction, txn)

    def test_same_transaction_cannot_be_linked_twice(self):
        purchase = Purchase.objects.create(supplier_name='X', created_by=self.user)
        txn = Transaction.objects.create(
            account=self.account, transaction_type='expense', category=self.expense_cat,
            amount=D('10'), transaction_date=date(2026, 1, 2), description='x', created_by=self.user)
        services.link_payment(purchase=purchase, transaction_obj=txn, actor=self.user)
        with self.assertRaises(Exception):
            services.link_payment(purchase=purchase, transaction_obj=txn, actor=self.user)


class PrintingTests(OpsTestBase):
    def _spool(self, uid, grams=D('1000')):
        return services.enter_opening_spool(material=self.filament, spool_uid=uid,
                                            starting_weight_g=grams, actor=self.user)

    def test_waste_counted_once_and_separately(self):
        spool = self._spool('SP-1')
        services.log_print(
            name='bracket', printer=None, purpose='business', outcome='success',
            success_quantity=1, notes='', actor=self.user,
            uses=[{'spool': spool, 'grams_consumed': D('50'), 'waste_grams': D('10')}])
        # 1000 − 50 − 10 = 940; consumed and waste each deducted exactly once.
        self.assertEqual(spool.estimated_remaining_g, D('940.00'))
        self.assertEqual(spool.movements.filter(movement_type='consumption').count(), 1)
        self.assertEqual(spool.movements.filter(movement_type='waste').count(), 1)

    def test_multicolor_print_deducts_each_spool(self):
        black = self._spool('BLK')
        red = self._spool('RED')
        services.log_print(
            name='logo', printer=None, purpose='business', outcome='success',
            success_quantity=1, notes='', actor=self.user,
            uses=[{'spool': black, 'grams_consumed': D('30'), 'waste_grams': D('5')},
                  {'spool': red, 'grams_consumed': D('20'), 'waste_grams': D('5')}])
        self.assertEqual(black.estimated_remaining_g, D('965.00'))
        self.assertEqual(red.estimated_remaining_g, D('975.00'))

    def test_failed_print_consumes_material_and_reprint_consumes_more(self):
        spool = self._spool('SP-1')
        services.log_print(
            name='fail1', printer=None, purpose='prototype', outcome='failed',
            success_quantity=0, notes='clog', actor=self.user,
            uses=[{'spool': spool, 'grams_consumed': D('40'), 'waste_grams': D('15')}])
        self.assertEqual(spool.estimated_remaining_g, D('945.00'))  # failed still consumes
        # Reprint consumes additional material.
        services.log_print(
            name='reprint', printer=None, purpose='prototype', outcome='success',
            success_quantity=1, notes='', actor=self.user,
            uses=[{'spool': spool, 'grams_consumed': D('40'), 'waste_grams': D('5')}])
        self.assertEqual(spool.estimated_remaining_g, D('900.00'))

    def test_insufficient_stock_is_rejected(self):
        spool = self._spool('SP-1', grams=D('30'))
        with self.assertRaises(services.InsufficientStockError):
            services.log_print(
                name='toobig', printer=None, purpose='business', outcome='success',
                success_quantity=0, notes='', actor=self.user,
                uses=[{'spool': spool, 'grams_consumed': D('100'), 'waste_grams': D('0')}])


class IdempotencyTests(OpsTestBase):
    def test_duplicate_receive_does_not_double_count(self):
        purchase = Purchase.objects.create(supplier_name='X', created_by=self.user)
        line = PurchaseLine.objects.create(
            purchase=purchase, item_type='stock', description='bolts', material=self.hardware,
            quantity_ordered=D('100'), unit='each', unit_cost=D('0.10'))
        key = 'tok-123'
        services.receive_stock_line(line=line, quantity=D('40'), actor=self.user, idempotency_key=key)
        services.receive_stock_line(line=line, quantity=D('40'), actor=self.user, idempotency_key=key)
        line.refresh_from_db()
        self.assertEqual(line.quantity_received, D('40.000'))  # once, not 80
        item = StockItem.objects.get(material=self.hardware)
        self.assertEqual(item.on_hand, D('40.000'))

    def test_duplicate_print_submission_does_not_double_deduct(self):
        spool = services.enter_opening_spool(material=self.filament, spool_uid='SP-1',
                                             starting_weight_g=D('1000'), actor=self.user)
        token = 'print-tok-1'
        for _ in range(2):
            services.log_print(
                name='x', printer=None, purpose='business', outcome='success',
                success_quantity=1, notes='', actor=self.user, submission_token=token,
                uses=[{'spool': spool, 'grams_consumed': D('50'), 'waste_grams': D('0')}])
        self.assertEqual(PrintLog.objects.count(), 1)
        self.assertEqual(spool.estimated_remaining_g, D('950.00'))


class CorrectionAndImmutabilityTests(OpsTestBase):
    def test_movement_is_immutable(self):
        spool = services.enter_opening_spool(material=self.filament, spool_uid='SP-1',
                                             starting_weight_g=D('1000'), actor=self.user)
        mv = spool.movements.first()
        mv.quantity = D('5')
        with self.assertRaises(ValidationError):
            mv.save()
        with self.assertRaises(ValidationError):
            mv.delete()

    def test_reversal_is_auditable_and_preserves_original(self):
        spool = services.enter_opening_spool(material=self.filament, spool_uid='SP-1',
                                             starting_weight_g=D('1000'), actor=self.user)
        print_log = services.log_print(
            name='x', printer=None, purpose='business', outcome='success',
            success_quantity=1, notes='', actor=self.user,
            uses=[{'spool': spool, 'grams_consumed': D('100'), 'waste_grams': D('0')}])
        consumption = spool.movements.get(movement_type='consumption')
        self.assertEqual(spool.estimated_remaining_g, D('900.00'))
        rev = services.reverse_movement(consumption, actor=self.user, reason='mistake')
        # Original remains; reversal negates it; net back to 1000.
        self.assertTrue(InventoryMovement.objects.filter(pk=consumption.pk).exists())
        self.assertEqual(rev.reverses_id, consumption.pk)
        self.assertEqual(spool.estimated_remaining_g, D('1000.00'))
        # Cannot reverse twice.
        with self.assertRaises(ValidationError):
            services.reverse_movement(consumption, actor=self.user)
        # Audit events exist for the movement and its reversal.
        self.assertTrue(AuditEvent.objects.filter(action='reverse').exists())

    def test_reconciliation_adjusts_to_measured(self):
        spool = services.enter_opening_spool(material=self.filament, spool_uid='SP-1',
                                             starting_weight_g=D('1000'), actor=self.user)
        services.log_print(
            name='x', printer=None, purpose='business', outcome='success', success_quantity=1,
            notes='', actor=self.user,
            uses=[{'spool': spool, 'grams_consumed': D('200'), 'waste_grams': D('0')}])
        self.assertEqual(spool.estimated_remaining_g, D('800.00'))
        # Scale says 780 remaining (tare 180, gross 960).
        m = services.weigh_spool(spool=spool, gross_grams=D('960'), tare_grams=D('180'), actor=self.user)
        self.assertEqual(m.net_g, D('780.00'))
        self.assertEqual(spool.measured_remaining_g, D('780.00'))
        delta = services.reconcile_spool_from_measurement(measurement=m, actor=self.user)
        self.assertEqual(delta, D('-20.00'))
        self.assertEqual(spool.estimated_remaining_g, D('780.00'))
