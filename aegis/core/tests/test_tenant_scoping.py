"""Tenant isolation is the product's most important invariant — test it hard."""
import uuid

from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase

from aegis.core.context import tenant_context
from aegis.core.exceptions import TenantContextRequired
from aegis.core.models import Role, Tenant


class TenantScopingTests(TestCase):
    databases = {'default', 'platform'}

    @classmethod
    def setUpTestData(cls):
        cls.tenant_a = Tenant.objects.create(tenant_code='A', name='Tenant A')
        cls.tenant_b = Tenant.objects.create(tenant_code='B', name='Tenant B')
        with tenant_context(cls.tenant_a.id):
            cls.role_a = Role.objects.create(tenant=cls.tenant_a, code='r', name='Role A')
        with tenant_context(cls.tenant_b.id):
            cls.role_b = Role.objects.create(tenant=cls.tenant_b, code='r', name='Role B')

    def test_scoped_query_returns_only_current_tenant(self):
        with tenant_context(self.tenant_a.id):
            ids = set(Role.objects.values_list('id', flat=True))
        self.assertIn(self.role_a.id, ids)
        self.assertNotIn(self.role_b.id, ids)

    def test_tenant_a_cannot_fetch_tenant_b_row(self):
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(ObjectDoesNotExist):
                Role.objects.get(pk=self.role_b.id)

    def test_missing_context_fails_closed(self):
        with self.assertRaises(TenantContextRequired):
            list(Role.objects.all())

    def test_invalid_context_returns_nothing(self):
        with tenant_context(uuid.uuid4()):
            self.assertEqual(Role.objects.count(), 0)

    def test_all_objects_escape_hatch_sees_every_tenant(self):
        self.assertEqual(Role.all_objects.count(), 2)

    def test_membership_uniqueness_is_per_tenant(self):
        # Same role code 'r' exists in both tenants without collision.
        self.assertEqual(Role.all_objects.filter(code='r').count(), 2)
