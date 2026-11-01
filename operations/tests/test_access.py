"""Access-control tests: Operations is ADMIN-ONLY (is_active + is_superuser).

Anonymous, regular, and non-admin staff users are all denied — pages, private
attachments, and mutation endpoints alike. Only active superusers get in.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from operations import services
from operations.models import Material, Purchase, PurchaseDocument, PurchaseLine

D = Decimal

PDF_BYTES = b'%PDF-1.4 operations purchase doc \x00\x01 end'


def _make_users():
    return {
        'admin': User.objects.create_user('admin', 'a@example.com', 'pw', is_staff=True, is_superuser=True),
        'regular': User.objects.create_user('cust', 'c@example.com', 'pw'),
        'nonadmin_staff': User.objects.create_user('stf', 's@example.com', 'pw', is_staff=True),
        'inactive_admin': User.objects.create_user('ia', 'ia@example.com', 'pw',
                                                   is_staff=True, is_superuser=True, is_active=False),
    }


class AdminGateTests(TestCase):
    def setUp(self):
        self.users = _make_users()

    def _urls(self):
        return [
            reverse('operations:dashboard'),
            reverse('operations:purchase_list'),
            reverse('operations:spool_list'),
            reverse('operations:material_list'),
            reverse('operations:product_list'),
            reverse('operations:finished_goods'),
            reverse('operations:order_list'),
            reverse('operations:movement_list'),
            reverse('operations:print_create'),  # a mutation endpoint (GET form)
        ]

    def test_anonymous_is_redirected(self):
        for url in self._urls():
            self.assertIn(self.client.get(url).status_code, (301, 302), msg=url)

    def test_regular_user_denied(self):
        self.client.force_login(self.users['regular'])
        for url in self._urls():
            self.assertEqual(self.client.get(url).status_code, 404, msg=url)

    def test_non_admin_staff_denied(self):
        # The key correction: is_staff alone is NOT enough.
        self.client.force_login(self.users['nonadmin_staff'])
        for url in self._urls():
            self.assertEqual(self.client.get(url).status_code, 404, msg=url)

    def test_inactive_admin_denied(self):
        self.client.force_login(self.users['inactive_admin'])
        for url in self._urls():
            # Inactive users are logged out by the auth backend (302) or 404'd by the
            # gate — either way, never 200.
            self.assertNotEqual(self.client.get(url).status_code, 200, msg=url)

    def test_admin_allowed(self):
        self.client.force_login(self.users['admin'])
        for url in self._urls():
            self.assertEqual(self.client.get(url).status_code, 200, msg=url)

    def test_non_admin_staff_denied_mutation_post(self):
        """A non-admin staff user cannot POST to a mutation endpoint."""
        self.client.force_login(self.users['nonadmin_staff'])
        resp = self.client.post(reverse('operations:print_create'), {})
        self.assertEqual(resp.status_code, 404)


class DocumentAccessTests(TestCase):
    def setUp(self):
        self.users = _make_users()
        self.purchase = Purchase.objects.create(supplier_name='X', created_by=self.users['admin'])
        self.doc = PurchaseDocument(
            purchase=self.purchase, original_filename='r.pdf', file_type='pdf',
            file_size=len(PDF_BYTES), uploaded_by=self.users['admin'])
        self.doc.file.save('operations/purchase_docs/2026/01/r.pdf', ContentFile(PDF_BYTES), save=True)

    def test_document_has_no_public_url(self):
        self.assertEqual(self.doc.file.url, '')

    def test_admin_can_view_and_download(self):
        self.client.force_login(self.users['admin'])
        view = self.client.get(reverse('operations:document_view', args=[self.doc.id]))
        self.assertEqual(view.status_code, 200)
        self.assertEqual(b''.join(view.streaming_content), PDF_BYTES)
        dl = self.client.get(reverse('operations:document_download', args=[self.doc.id]))
        self.assertEqual(dl.status_code, 200)

    def test_non_admin_denied_document(self):
        for key in ('regular', 'nonadmin_staff'):
            self.client.force_login(self.users[key])
            self.assertEqual(
                self.client.get(reverse('operations:document_view', args=[self.doc.id])).status_code, 404, msg=key)
            self.assertEqual(
                self.client.get(reverse('operations:document_download', args=[self.doc.id])).status_code, 404, msg=key)


class RenderSmokeTests(TestCase):
    """Every GET-able screen renders for staff (catches template/reverse errors)."""

    def setUp(self):
        self.staff = User.objects.create_user('staff', 'staff@example.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.staff)
        self.filament = Material.objects.create(
            material_type='filament', name='Matte Black', default_unit='g')
        self.hardware = Material.objects.create(
            material_type='hardware', name='M3 bolt', default_unit='each')
        self.spool = services.enter_opening_spool(
            material=self.filament, spool_uid='SP-1', starting_weight_g=D('1000'), actor=self.staff)
        self.purchase = Purchase.objects.create(supplier_name='X', created_by=self.staff)
        self.stock_line = PurchaseLine.objects.create(
            purchase=self.purchase, item_type='stock', description='bolts', material=self.hardware,
            quantity_ordered=D('100'), unit='each', unit_cost=D('0.10'))
        self.fil_line = PurchaseLine.objects.create(
            purchase=self.purchase, item_type='filament', description='PLA', material=self.filament,
            quantity_ordered=D('2'), unit='roll', unit_cost=D('20'))
        self.equip_line = PurchaseLine.objects.create(
            purchase=self.purchase, item_type='equipment', description='Printer',
            quantity_ordered=D('1'), unit='each', unit_cost=D('1200'))

    def test_all_get_screens_render(self):
        urls = [
            reverse('operations:supplier_create'),
            reverse('operations:location_create'),
            reverse('operations:material_create'),
            reverse('operations:material_detail', args=[self.filament.id]),
            reverse('operations:material_detail', args=[self.hardware.id]),
            reverse('operations:equipment_create'),
            reverse('operations:equipment_list'),
            reverse('operations:stock_list'),
            reverse('operations:supplier_list'),
            reverse('operations:location_list'),
            reverse('operations:opening_index'),
            reverse('operations:opening_spool'),
            reverse('operations:opening_stock'),
            reverse('operations:purchase_create'),
            reverse('operations:purchase_detail', args=[self.purchase.id]),
            reverse('operations:spool_detail', args=[self.spool.id]),
            reverse('operations:print_create'),
            reverse('operations:line_receive', args=[self.stock_line.id]),
            reverse('operations:line_receive', args=[self.fil_line.id]),
            reverse('operations:line_receive', args=[self.equip_line.id]),
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, msg=f'{url} -> {resp.status_code}')


class Phase1bRenderSmokeTests(TestCase):
    """New product/recipe/order/finished/reconstruct screens render for staff."""

    def setUp(self):
        from operations.models import PhysicalProduct, ProductVariant, InternalOrder
        from operations import services
        self.staff = User.objects.create_user('staff2', 's2@example.com', 'pw', is_staff=True, is_superuser=True)
        self.client.force_login(self.staff)
        self.product = PhysicalProduct.objects.create(name='Desk bin', internal_only=True)
        self.variant = ProductVariant.objects.create(product=self.product, name='Default')
        self.order = services.create_internal_order(
            purpose='personal', actor=self.staff,
            lines=[{'variant': self.variant, 'quantity': 1}])

    def test_new_screens_render(self):
        urls = [
            reverse('operations:product_list'),
            reverse('operations:product_create'),
            reverse('operations:product_detail', args=[self.product.id]),
            reverse('operations:recipe_create', args=[self.variant.id]),
            reverse('operations:finished_goods'),
            reverse('operations:print_create'),
            reverse('operations:reconstruct_guide'),
            reverse('operations:order_list'),
            reverse('operations:order_create'),
            reverse('operations:order_detail', args=[self.order.id]),
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, msg=f'{url} -> {resp.status_code}')

    def test_recipe_expected_json(self):
        resp = self.client.get(reverse('operations:recipe_expected'),
                               {'variant': str(self.variant.id), 'qty': '2'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['rows'], [])  # no recipe yet
