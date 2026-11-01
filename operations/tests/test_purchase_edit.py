"""Tests for owner self-service purchase/line corrections.

Covers: editing an unreceived line freely; cost/classification edits allowed on a
received line while structural fields are locked; quantity-ordered floor on received
lines; purchase-header edits (incl. funding); correct total recalculation with no
double-counted tax; and that editing never posts a movement, payment, or expense.
Also the browser-level Edit actions, their permission gate, and the whole-number
quantity stepping that prevents the decimal-arrow mistake.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from operations import models as m
from operations import services


class EditPurchaseLineServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('dannyjenkins71@gmail.com', is_superuser=True,
                                            is_staff=True, is_active=True)
        cls.filament = m.Material.objects.create(material_type='filament', manufacturer='Bambu',
                                                 product_type='PLA', name='Black', sku='F1')
        cls.other_filament = m.Material.objects.create(material_type='filament', name='White', sku='F2')

    def _purchase(self):
        return m.Purchase.objects.create(supplier_name='Amazon', order_number='111-TEST')

    def _line(self, **kw):
        defaults = dict(item_type='filament', description='PLA spool', material=self.filament,
                        quantity_ordered=Decimal('0.001'), unit='each', unit_cost=Decimal('15.99'))
        defaults.update(kw)
        return m.PurchaseLine.objects.create(purchase=self._purchase(), **defaults)

    def test_unreceived_line_fully_editable(self):
        line = self._line()
        services.edit_purchase_line(
            line=line, actor=self.user, item_type='filament', description='PLA spool (fixed)',
            material=self.other_filament, quantity_ordered=Decimal('1'), unit='roll',
            unit_cost=Decimal('15.99'), line_discount=Decimal('0'), line_tax=Decimal('0'),
            use_type='business', business_pct=Decimal('100'))
        line.refresh_from_db()
        self.assertEqual(line.quantity_ordered, Decimal('1'))
        self.assertEqual(line.unit, 'roll')
        self.assertEqual(line.material_id, self.other_filament.id)
        self.assertEqual(line.line_total, Decimal('15.99'))
        self.assertTrue(m.AuditEvent.objects.filter(model_name='PurchaseLine', action='update').exists())

    def test_edit_posts_no_inventory_movement(self):
        line = self._line()
        services.edit_purchase_line(line=line, actor=self.user, quantity_ordered=Decimal('1'),
                                    unit='roll')
        self.assertEqual(m.InventoryMovement.objects.count(), 0)

    def test_received_line_locks_structural_fields(self):
        line = self._line(quantity_ordered=Decimal('1'), quantity_received=Decimal('1'))
        with self.assertRaises(services.ValidationError):
            services.edit_purchase_line(line=line, actor=self.user, unit='roll')
        with self.assertRaises(services.ValidationError):
            services.edit_purchase_line(line=line, actor=self.user, material=self.other_filament)
        with self.assertRaises(services.ValidationError):
            services.edit_purchase_line(line=line, actor=self.user, item_type='stock')

    def test_received_line_allows_cost_and_classification(self):
        line = self._line(quantity_ordered=Decimal('1'), quantity_received=Decimal('1'))
        services.edit_purchase_line(
            line=line, actor=self.user, description='corrected', unit_cost=Decimal('16.49'),
            line_discount=Decimal('1.00'), line_tax=Decimal('0.50'), use_type='shared',
            business_pct=Decimal('60'))
        line.refresh_from_db()
        self.assertEqual(line.unit_cost, Decimal('16.49'))
        self.assertEqual(line.use_type, 'shared')
        self.assertEqual(line.business_pct, Decimal('60.00'))
        # (1 * 16.49) - 1.00 + 0.50
        self.assertEqual(line.line_total, Decimal('15.99'))

    def test_received_line_quantity_floor(self):
        line = self._line(quantity_ordered=Decimal('2'), quantity_received=Decimal('2'))
        with self.assertRaises(services.ValidationError):
            services.edit_purchase_line(line=line, actor=self.user, quantity_ordered=Decimal('1'))
        # equal to received is allowed
        services.edit_purchase_line(line=line, actor=self.user, quantity_ordered=Decimal('2'),
                                    unit_cost=Decimal('5'))
        line.refresh_from_db()
        self.assertEqual(line.unit_cost, Decimal('5'))

    def test_use_type_business_resets_pct(self):
        line = self._line(use_type='shared', business_pct=Decimal('40'))
        services.edit_purchase_line(line=line, actor=self.user, use_type='business',
                                    business_pct=Decimal('40'))
        line.refresh_from_db()
        self.assertEqual(line.business_pct, Decimal('100.00'))


class EditPurchaseServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('dannyjenkins71@gmail.com', is_superuser=True,
                                            is_staff=True, is_active=True)

    def test_edit_header_and_funding_no_side_effects(self):
        p = m.Purchase.objects.create(supplier_name='Amazon', order_number='OLD',
                                      shipping_total=Decimal('0'), tax_total=Decimal('0'))
        services.edit_purchase(purchase=p, actor=self.user, supplier=None, supplier_name='Amazon.com',
                               order_number='NEW-123', shipping_total=Decimal('4.99'),
                               tax_total=Decimal('2.00'), discount_total=Decimal('1.00'),
                               funding='personal', notes='fixed', product_links='')
        p.refresh_from_db()
        self.assertEqual(p.order_number, 'NEW-123')
        self.assertEqual(p.funding, 'personal')
        self.assertEqual(p.shipping_total, Decimal('4.99'))
        self.assertEqual(m.InventoryMovement.objects.count(), 0)
        self.assertEqual(p.payments.count(), 0)
        self.assertTrue(m.AuditEvent.objects.filter(model_name='Purchase', action='update').exists())

    def test_order_total_separates_order_and_line_tax(self):
        p = m.Purchase.objects.create(supplier_name='X', tax_total=Decimal('3.00'),
                                      shipping_total=Decimal('5.00'), discount_total=Decimal('2.00'))
        m.PurchaseLine.objects.create(purchase=p, item_type='stock', description='thing',
                                      quantity_ordered=Decimal('2'), unit='each',
                                      unit_cost=Decimal('10.00'), line_tax=Decimal('1.00'))
        # line_total = 2*10 - 0 + 1 = 21 ; order_total = 21 + 5 + 3 - 2 = 27 (line tax NOT re-added)
        self.assertEqual(p.lines_subtotal(), Decimal('21.00'))
        self.assertEqual(p.order_total(), Decimal('27.00'))


class EditViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin@x.com', password='pw', is_superuser=True,
                                             is_staff=True, is_active=True)
        cls.regular = User.objects.create_user('reg@x.com', password='pw')
        cls.mat = m.Material.objects.create(material_type='filament', name='Black', sku='F9')
        cls.purchase = m.Purchase.objects.create(supplier_name='Amazon', order_number='111-9')
        cls.line = m.PurchaseLine.objects.create(
            purchase=cls.purchase, item_type='filament', description='PLA', material=cls.mat,
            quantity_ordered=Decimal('0.001'), unit='each', unit_cost=Decimal('15.99'))

    def test_edit_pages_require_admin(self):
        line_url = reverse('operations:line_edit', args=[self.line.id])
        purchase_url = reverse('operations:purchase_edit', args=[self.purchase.id])
        # anonymous → redirect to login
        self.assertEqual(self.client.get(line_url).status_code, 302)
        # non-admin → 404
        self.client.login(username='reg@x.com', password='pw')
        self.assertEqual(self.client.get(line_url).status_code, 404)
        self.assertEqual(self.client.get(purchase_url).status_code, 404)

    def test_admin_can_load_and_submit_line_edit(self):
        self.client.login(username='admin@x.com', password='pw')
        url = reverse('operations:line_edit', args=[self.line.id])
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url, {
            'item_type': 'filament', 'description': 'PLA (fixed)', 'material': str(self.mat.id),
            'quantity_ordered': '1', 'unit': 'roll', 'unit_cost': '15.99',
            'line_discount': '0', 'line_tax': '0', 'use_type': 'business', 'business_pct': '100',
        })
        self.assertEqual(resp.status_code, 302)
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity_ordered, Decimal('1'))
        self.assertEqual(self.line.unit, 'roll')

    def test_add_line_form_quantity_steps_in_whole_numbers(self):
        from operations.forms import PurchaseLineForm
        form = PurchaseLineForm()
        self.assertEqual(form.fields['quantity_ordered'].widget.attrs.get('step'), '1')

    def test_received_line_form_locks_structural(self):
        from operations.forms import PurchaseLineEditForm
        self.line.quantity_received = Decimal('1')
        self.line.save(update_fields=['quantity_received'])
        form = PurchaseLineEditForm(instance=self.line)
        self.assertTrue(form.fields['unit'].disabled)
        self.assertTrue(form.fields['material'].disabled)
        self.assertTrue(form.fields['item_type'].disabled)
