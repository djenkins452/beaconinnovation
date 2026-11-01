"""Production / products / internal-orders tests (synthetic data only).

Covers the full validation sequence from the task:
  1. start a spool at 1,000 g
  2. print a batch using product material + waste
  3. confirm calculated remaining grams
  4. add successful finished units
  5. fulfill a no-payment internal order
  6. fulfillment changes finished inventory without another filament deduction
  7. reverse/correct an entry without corrupting either inventory
  8. duplicate submissions do not duplicate movements
plus recipe-version history, all-inclusive totals, and failed-print behaviour.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from operations import services
from operations.models import (
    FilamentSpool, InternalOrder, InventoryMovement, Material, PhysicalProduct,
    PrintLog, PrintProduct, ProductionRecipe, ProductVariant,
)

D = Decimal


class ProductionTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ops', 'ops@example.com', 'pw', is_staff=True, is_superuser=True)
        self.black = Material.objects.create(
            material_type='filament', manufacturer='Bambu', product_type='PLA',
            name='Matte Black', default_unit='g', nominal_spool_weight_g=D('1000'))
        self.red = Material.objects.create(
            material_type='filament', manufacturer='Bambu', product_type='PLA',
            name='Matte Red', default_unit='g', nominal_spool_weight_g=D('1000'))
        # A product + variant + recipe: 20 g into part + 3 g waste per unit (black).
        self.product = PhysicalProduct.objects.create(name='Desk bin', internal_only=True)
        self.variant = ProductVariant.objects.create(product=self.product, name='Default')
        self.recipe = services.create_recipe_version(
            variant=self.variant, actor=self.user,
            materials=[{'material': self.black, 'grams_per_unit': D('20'), 'waste_per_unit': D('3')}])

    def _spool(self, uid, material=None, grams=D('1000')):
        return services.enter_opening_spool(
            material=material or self.black, spool_uid=uid, starting_weight_g=grams, actor=self.user)


class FullSequenceTests(ProductionTestBase):
    def test_full_validation_sequence(self):
        # 1. Start a spool at 1,000 g.
        spool = self._spool('SP-1', grams=D('1000'))
        self.assertEqual(spool.estimated_remaining_g, D('1000.00'))

        # 2. Print a batch of 4 using product material + a shared batch purge.
        #    Recipe estimate for 4 = 4*20 into part + 4*3 per-unit waste = 80 + 12,
        #    plus a shared 10 g purge entered once (does not scale per unit).
        print_log = services.log_print(
            name='bin batch', printer=None, purpose='business', outcome='success',
            notes='', actor=self.user,
            uses=[{'spool': spool, 'grams_consumed': D('80'), 'waste_grams': D('22')}],
            products=[{'variant': self.variant, 'recipe': self.recipe,
                       'quantity_planned': 4, 'quantity_success': 4}])

        # 3. Confirm calculated remaining grams = 1000 - (80 + 22) = 898.
        self.assertEqual(spool.estimated_remaining_g, D('898.00'))
        self.assertEqual(print_log.total_filament_g, D('102.00'))

        # 4. Successful units are in finished inventory.
        self.assertEqual(self.variant.on_hand, 4)

        # 5 & 6. Fulfill a no-payment internal order for 3 units.
        order = services.create_internal_order(
            purpose='office', actor=self.user,
            lines=[{'variant': self.variant, 'quantity': 3}])
        self.assertEqual(order.payment_label, 'No payment required')
        remaining_before = spool.estimated_remaining_g
        services.fulfill_internal_order(order=order, actor=self.user)
        order.refresh_from_db()
        self.assertEqual(order.status, 'fulfilled')
        # Finished inventory dropped by 3; FILAMENT UNCHANGED (no second deduction).
        self.assertEqual(self.variant.on_hand, 1)
        self.assertEqual(spool.estimated_remaining_g, remaining_before)
        # No consumption/waste movement was created by fulfillment.
        self.assertFalse(InventoryMovement.objects.filter(
            movement_type__in=['consumption', 'waste'], product_variant__isnull=False).exists())

        # 7. Reverse the production output → finished inventory corrected, spool intact.
        prod_mv = InventoryMovement.objects.get(movement_type='production_output')
        # Can't drive finished below zero: on_hand is 1, output was +4; reversing -4
        # would make it -3 → rejected, keeping inventory consistent.
        with self.assertRaises(services.InsufficientStockError):
            services.reverse_movement(prod_mv, actor=self.user)
        # Reverse a filament consumption instead — spool restored, finished untouched.
        cons_mv = InventoryMovement.objects.get(movement_type='consumption')
        services.reverse_movement(cons_mv, actor=self.user, reason='mislogged')
        self.assertEqual(spool.estimated_remaining_g, D('978.00'))  # 898 + 80 back
        self.assertEqual(self.variant.on_hand, 1)  # finished untouched
        self.assertTrue(InventoryMovement.objects.filter(pk=cons_mv.pk).exists())  # original kept

    def test_duplicate_submissions_do_not_duplicate(self):
        spool = self._spool('SP-1')
        token = 'print-tok-xyz'
        for _ in range(2):
            services.log_print(
                name='x', printer=None, purpose='business', outcome='success',
                notes='', actor=self.user, submission_token=token,
                uses=[{'spool': spool, 'grams_consumed': D('50'), 'waste_grams': D('5')}],
                products=[{'variant': self.variant, 'recipe': self.recipe,
                           'quantity_planned': 2, 'quantity_success': 2}])
        self.assertEqual(PrintLog.objects.count(), 1)
        self.assertEqual(spool.estimated_remaining_g, D('945.00'))  # deducted once
        self.assertEqual(self.variant.on_hand, 2)  # produced once

        # Duplicate fulfillment doesn't double-remove finished goods.
        order = services.create_internal_order(
            purpose='personal', actor=self.user, lines=[{'variant': self.variant, 'quantity': 1}])
        ftok = 'ful-tok-1'
        services.fulfill_internal_order(order=order, actor=self.user, fulfillment_token=ftok)
        services.fulfill_internal_order(order=order, actor=self.user, fulfillment_token=ftok)
        self.assertEqual(self.variant.on_hand, 1)  # removed once (2 - 1)


class AllInclusiveAndFailureTests(ProductionTestBase):
    def test_all_inclusive_total_not_double_counted(self):
        spool = self._spool('SP-1')
        # Slicer total of 60 g ALREADY includes supports/purge.
        services.log_print(
            name='slicer', printer=None, purpose='business', outcome='success', notes='',
            actor=self.user,
            uses=[{'spool': spool, 'grams_consumed': D('60'), 'waste_grams': D('99'),
                   'basis': 'slicer', 'all_inclusive': True}],
            products=[{'variant': self.variant, 'recipe': self.recipe,
                       'quantity_planned': 2, 'quantity_success': 2}])
        # Only 60 g removed; the 99 g waste was ignored because all-inclusive.
        self.assertEqual(spool.estimated_remaining_g, D('940.00'))
        self.assertFalse(InventoryMovement.objects.filter(movement_type='waste').exists())

    def test_failed_print_consumes_actual_and_produces_nothing(self):
        spool = self._spool('SP-1')
        services.log_print(
            name='fail', printer=None, purpose='prototype', outcome='failed', notes='',
            actor=self.user,
            uses=[{'spool': spool, 'grams_consumed': D('18'), 'waste_grams': D('4')}],
            products=[{'variant': self.variant, 'recipe': self.recipe,
                       'quantity_planned': 2, 'quantity_success': 0}])
        self.assertEqual(spool.estimated_remaining_g, D('978.00'))  # actual used, not full plan
        self.assertEqual(self.variant.on_hand, 0)  # no finished units from a failed print
        self.assertFalse(InventoryMovement.objects.filter(movement_type='production_output').exists())


class RecipeVersionTests(ProductionTestBase):
    def test_new_recipe_version_preserves_history(self):
        # The initial recipe is v1.
        self.assertEqual(self.recipe.version, 1)
        self.assertTrue(self.recipe.is_current)
        # A print snapshots v1.
        spool = self._spool('SP-1')
        pl = services.log_print(
            name='p', printer=None, purpose='business', outcome='success', notes='',
            actor=self.user, uses=[{'spool': spool, 'grams_consumed': D('20'), 'waste_grams': D('3')}],
            products=[{'variant': self.variant, 'recipe': self.variant.current_recipe,
                       'quantity_planned': 1, 'quantity_success': 1}])
        pp = PrintProduct.objects.get(print_log=pl)
        self.assertEqual(pp.recipe.version, 1)
        # Create v2 with different usage.
        v2 = services.create_recipe_version(
            variant=self.variant, actor=self.user,
            materials=[{'material': self.black, 'grams_per_unit': D('25'), 'waste_per_unit': D('5')}])
        self.assertEqual(v2.version, 2)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.current_recipe.version, 2)
        # v1 still exists and the past print still points at v1 (history intact).
        self.assertTrue(ProductionRecipe.objects.filter(version=1, is_current=False).exists())
        pp.refresh_from_db()
        self.assertEqual(pp.recipe.version, 1)

    def test_expected_for_quantity(self):
        rows = self.recipe.expected_for(5)
        self.assertEqual(rows[0]['grams_consumed'], D('100'))  # 5 * 20
        self.assertEqual(rows[0]['waste_grams'], D('15'))      # 5 * 3


class HistoricalReconstructionTests(ProductionTestBase):
    def test_historical_print_is_backdated_and_combined_fulfillment(self):
        spool = self._spool('SP-1')
        five_days_ago = date.today() - timedelta(days=5)
        # Combined: historical print + immediate internal-order fulfillment (view path).
        pl = services.log_print(
            name='old bin', printer=None, purpose='business', outcome='success',
            notes='reconstructed', actor=self.user, is_historical=True, printed_on=five_days_ago,
            uses=[{'spool': spool, 'grams_consumed': D('40'), 'waste_grams': D('6')}],
            products=[{'variant': self.variant, 'recipe': self.recipe,
                       'quantity_planned': 2, 'quantity_success': 2}])
        self.assertTrue(pl.is_historical)
        # Movements are back-dated to the print date.
        cons = InventoryMovement.objects.get(movement_type='consumption')
        self.assertEqual(cons.occurred_at.date(), five_days_ago)
        # Produced 2, then fulfill both as an internal order — separate records, filament once.
        order = services.create_and_fulfill_internal_order(
            purpose='office', actor=self.user,
            lines=[{'variant': self.variant, 'quantity': 2}],
            occurred_at=services._historical_timestamp(five_days_ago))
        self.assertEqual(order.status, 'fulfilled')
        self.assertEqual(self.variant.on_hand, 0)  # produced 2, fulfilled 2
        self.assertEqual(spool.estimated_remaining_g, D('954.00'))  # 1000 - 46, filament once
        # Production and fulfillment are distinct records.
        self.assertTrue(InventoryMovement.objects.filter(movement_type='production_output').exists())
        self.assertTrue(InventoryMovement.objects.filter(movement_type='fulfillment').exists())


class ViewPostTests(ProductionTestBase):
    """Exercise the print + internal-order views end to end (formset wiring)."""

    def _mgmt(self, prefix, total=3):
        return {
            f'{prefix}-TOTAL_FORMS': str(total), f'{prefix}-INITIAL_FORMS': '0',
            f'{prefix}-MIN_NUM_FORMS': '0', f'{prefix}-MAX_NUM_FORMS': '1000',
        }

    def test_print_create_view_produces_finished_goods(self):
        self.client.force_login(self.user)
        spool = self._spool('SP-V1', grams=D('1000'))
        data = {
            'submission_token': 'view-tok-1',
            'name': 'View batch', 'printed_on': '2026-11-01', 'printer': '',
            'purpose': 'business', 'outcome': 'success', 'notes': '',
        }
        data.update(self._mgmt('prod'))
        data.update(self._mgmt('use'))
        data.update({'prod-0-variant': str(self.variant.id),
                     'prod-0-quantity_planned': '4', 'prod-0-quantity_success': '4'})
        data.update({'use-0-spool': str(spool.id), 'use-0-grams_consumed': '80',
                     'use-0-waste_grams': '22', 'use-0-basis': 'slicer'})
        resp = self.client.post(reverse('operations:print_create'), data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(PrintLog.objects.filter(name='View batch').count(), 1)
        self.assertEqual(self.variant.on_hand, 4)
        self.assertEqual(spool.estimated_remaining_g, D('898.00'))

    def test_internal_order_create_and_fulfill_views(self):
        self.client.force_login(self.user)
        # Produce 3 finished units first.
        spool = self._spool('SP-V2')
        services.log_print(name='stock up', printer=None, purpose='business', outcome='success',
                           notes='', actor=self.user,
                           uses=[{'spool': spool, 'grams_consumed': D('60'), 'waste_grams': D('9')}],
                           products=[{'variant': self.variant, 'recipe': self.recipe,
                                      'quantity_planned': 3, 'quantity_success': 3}])
        self.assertEqual(self.variant.on_hand, 3)
        # Create an internal order via the view.
        data = {'purpose': 'office', 'ordered_on': '2026-11-01', 'notes': 'room setup'}
        data.update(self._mgmt('line'))
        data.update({'line-0-variant': str(self.variant.id), 'line-0-quantity': '2'})
        resp = self.client.post(reverse('operations:order_create'), data, follow=True)
        self.assertEqual(resp.status_code, 200)
        order = InternalOrder.objects.latest('created_at')
        self.assertEqual(order.status, 'open')
        # Fulfill via the view.
        self.client.post(reverse('operations:order_fulfill', args=[order.id]),
                         {'fulfillment_token': 'view-ful-1'}, follow=True)
        order.refresh_from_db()
        self.assertEqual(order.status, 'fulfilled')
        self.assertEqual(self.variant.on_hand, 1)  # 3 - 2, filament untouched
        self.assertEqual(spool.estimated_remaining_g, D('931.00'))  # 1000 - 69, unchanged by fulfill
