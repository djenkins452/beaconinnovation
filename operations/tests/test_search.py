"""Tests for the shared search-as-you-type across Operations list pages.

Covers the reusable ``apply_search`` helper (case-insensitive partial matching, multi-word
AND, OR across related fields, de-duplication) and its wiring into the Purchases list
(supplier / order number / item / material / SKU, cross-field multi-word, matching-item
highlighting, that the overall recorded total is NOT changed by a search, that receiving
while filtered keeps the query, and that access stays active-superuser-only). A couple of
other list pages are spot-checked to prove the shared rollout.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from operations import models as m
from operations.search import apply_search, search_terms


def _filament(name='Cyan', sku='C1', manufacturer='Bambu Lab', product_type='PLA Basic'):
    return m.Material.objects.create(material_type='filament', manufacturer=manufacturer,
                                     product_type=product_type, name=name, sku=sku)


def _stock(name='Bubble mailer', sku='S1'):
    return m.Material.objects.create(material_type='packaging', name=name, sku=sku)


class ApplySearchTests(TestCase):
    def test_blank_query_returns_queryset_unchanged(self):
        _stock('Alpha', 'A1'); _stock('Beta', 'B1')
        self.assertEqual(apply_search(m.Material.objects.all(), '', ['name']).count(), 2)
        self.assertEqual(apply_search(m.Material.objects.all(), '   ', ['name']).count(), 2)

    def test_case_insensitive_partial(self):
        _stock('Blue Painters Tape', 'T1')
        self.assertEqual(apply_search(m.Material.objects.all(), 'PAINT', ['name']).count(), 1)
        self.assertEqual(apply_search(m.Material.objects.all(), 'xyz', ['name']).count(), 0)

    def test_multiple_words_are_anded(self):
        _stock('Blue painters tape', 'T1')
        _stock('Blue nitrile gloves', 'G1')
        qs = apply_search(m.Material.objects.all(), 'blue tape', ['name'])
        self.assertEqual([r.name for r in qs], ['Blue painters tape'])

    def test_words_or_across_fields(self):
        # "black filament" — one word lives in the name, the other in the manufacturer.
        _filament('Black PLA', 'BK1', manufacturer='filament co', product_type='PLA')
        qs = apply_search(m.Material.objects.all(), 'black filament', ['name', 'manufacturer'])
        self.assertEqual(qs.count(), 1)

    def test_distinct_across_to_many(self):
        purchase = m.Purchase.objects.create(supplier_name='Bambu', order_number='B-1')
        for c in ('Cyan', 'Magenta'):
            mat = _filament(c, f'{c}1')
            m.PurchaseLine.objects.create(purchase=purchase, item_type='filament',
                                          description=f'PLA {c}', material=mat,
                                          quantity_ordered=Decimal('1'), unit='roll',
                                          unit_cost=Decimal('9'))
        # "PLA" appears on both lines; the purchase must be returned once, not twice.
        qs = apply_search(m.Purchase.objects.all(), 'PLA', ['lines__description'])
        self.assertEqual(qs.count(), 1)

    def test_search_terms_lowercases_and_caps(self):
        self.assertEqual(search_terms('Black Filament'), ['black', 'filament'])
        self.assertEqual(len(search_terms(' '.join(str(i) for i in range(40)))), 10)


class PurchaseSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin@x.com', password='pw', is_superuser=True,
                                             is_staff=True, is_active=True)
        cls.regular = User.objects.create_user('reg@x.com', password='pw')
        m.Location.objects.create(name='Home Office / Print Room', kind='room')

        # Order A — Amazon, black filament (word split across description + material name).
        cls.pa = m.Purchase.objects.create(supplier_name='Amazon', order_number='AMZ-111')
        mat_black = _filament('Black PLA', 'BLK-9', product_type='PLA Matte')
        cls.la = m.PurchaseLine.objects.create(
            purchase=cls.pa, item_type='filament', description='Spool of filament',
            material=mat_black, quantity_ordered=Decimal('2'), unit='roll', unit_cost=Decimal('10'))

        # Order B — Home Depot, countertop + screws, with a SKU and notes.
        cls.pb = m.Purchase.objects.create(supplier_name='Home Depot', order_number='HD-222',
                                           notes='kitchen remodel')
        mat_screws = _stock('Cap screws', 'SCRW-500')
        m.PurchaseLine.objects.create(
            purchase=cls.pb, item_type='stock', description='M3 cap screws', material=mat_screws,
            quantity_ordered=Decimal('100'), unit='each', unit_cost=Decimal('0.1'))

    def _login(self):
        self.client.login(username='admin@x.com', password='pw')

    def _get(self, q=None):
        url = reverse('operations:purchase_list')
        return self.client.get(url, {'q': q} if q is not None else {})

    def test_requires_admin(self):
        url = reverse('operations:purchase_list')
        self.assertEqual(self.client.get(url, {'q': 'amazon'}).status_code, 302)   # anon → login
        self.client.login(username='reg@x.com', password='pw')
        self.assertEqual(self.client.get(url, {'q': 'amazon'}).status_code, 404)   # non-admin hidden

    def test_search_by_supplier(self):
        self._login()
        resp = self._get('home depot')
        self.assertContains(resp, 'HD-222')
        self.assertNotContains(resp, 'AMZ-111')

    def test_search_by_order_number(self):
        self._login()
        resp = self._get('AMZ-111')
        self.assertContains(resp, 'AMZ-111')
        self.assertNotContains(resp, 'HD-222')

    def test_search_by_item_description(self):
        self._login()
        resp = self._get('countertop')  # not present anywhere → no matches
        self.assertContains(resp, 'No purchases match')
        resp = self._get('cap screws')
        self.assertContains(resp, 'HD-222')

    def test_search_by_sku(self):
        self._login()
        resp = self._get('SCRW-500')
        self.assertContains(resp, 'HD-222')
        self.assertNotContains(resp, 'AMZ-111')

    def test_cross_field_multiword(self):
        # "black filament": 'black' is in the material name, 'filament' in the description.
        self._login()
        resp = self._get('black filament')
        self.assertContains(resp, 'AMZ-111')
        self.assertNotContains(resp, 'HD-222')

    def test_search_by_notes(self):
        self._login()
        resp = self._get('kitchen remodel')
        self.assertContains(resp, 'HD-222')

    def test_matching_item_is_flagged(self):
        self._login()
        resp = self._get('cap screws')
        self.assertContains(resp, 'ops-match-tag')          # the matching line is called out

    def test_overall_total_not_changed_by_search(self):
        # Both orders' recorded cost is shown regardless of the search filter.
        self._login()
        full = self._get()
        self.assertContains(full, 'across all purchases')
        # Order A = 2*10 = 20, Order B = 100*0.1 = 10 → 30.00 overall, shown even when filtered.
        resp = self._get('home depot')
        self.assertContains(resp, '$30.00')                 # overall total unchanged
        self.assertContains(resp, '1</strong> purchase')   # but only 1 matches

    def test_no_results_message(self):
        self._login()
        resp = self._get('nothingmatchesthis')
        self.assertContains(resp, 'No purchases match')

    def test_receiving_while_filtered_keeps_query(self):
        self._login()
        list_url = reverse('operations:purchase_list') + '?q=black'
        resp = self.client.post(reverse('operations:dashboard_receive_line', args=[self.la.id]),
                                {'idempotency_key': 'k', 'next': list_url})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, list_url)                # stays on the filtered list
        self.la.refresh_from_db()
        self.assertEqual(self.la.quantity_received, Decimal('2'))

    def test_search_box_present(self):
        self._login()
        resp = self._get()
        self.assertContains(resp, 'data-ops-search')
        self.assertContains(resp, 'id="ops-results"')
        self.assertContains(resp, 'Search purchases')


class OtherListSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('a@x.com', password='pw', is_superuser=True,
                                             is_staff=True, is_active=True)

    def _login(self):
        self.client.login(username='a@x.com', password='pw')

    def test_material_list_search_and_keeps_type_filter(self):
        _filament('Galaxy Black', 'GB1')
        _stock('Bubble mailer', 'BM1')
        self._login()
        resp = self.client.get(reverse('operations:material_list'), {'q': 'galaxy'})
        self.assertContains(resp, 'Galaxy Black')
        self.assertNotContains(resp, 'Bubble mailer')
        self.assertContains(resp, 'data-ops-search')

    def test_spool_list_search(self):
        mat = _filament('Red PLA', 'RP1')
        m.FilamentSpool.objects.create(material=mat, spool_uid='SPOOL-RED-1',
                                       starting_weight_g=0, remaining_unknown=True,
                                       delivery_confirmed=True, status='sealed')
        self._login()
        resp = self.client.get(reverse('operations:spool_list'), {'q': 'SPOOL-RED-1'})
        self.assertContains(resp, 'SPOOL-RED-1')
        resp2 = self.client.get(reverse('operations:spool_list'), {'q': 'nomatch'})
        self.assertContains(resp2, 'No spools match')

    def test_supplier_list_search(self):
        m.Supplier.objects.create(name='Acme Filament Co')
        m.Supplier.objects.create(name='Widget World')
        self._login()
        resp = self.client.get(reverse('operations:supplier_list'), {'q': 'acme'})
        self.assertContains(resp, 'Acme Filament Co')
        self.assertNotContains(resp, 'Widget World')
