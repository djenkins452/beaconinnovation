"""Access control: authentication never implies access; membership is required.

Exercises the /platform/ dashboard through the full middleware + provider +
membership stack, including cross-tenant attempts.
"""
from django.apps import apps
from django.contrib.auth.models import User
from django.test import Client, TestCase

from aegis.core.auth.beacon_session import PROVIDER_NAME, beacon_subject_for
from aegis.core.constants import PERM_VIEW_DASHBOARD, ROLE_PLATFORM_ADMIN
from aegis.core.context import tenant_context
from aegis.core.models import (
    Membership,
    Permission,
    PlatformUser,
    ProviderIdentity,
    Role,
    Tenant,
)


class AccessControlTests(TestCase):
    databases = {'default', 'platform'}

    @classmethod
    def setUpTestData(cls):
        # The middleware resolves the request tenant to PLATFORM_TENANT_CODE=BEACON.
        cls.beacon = Tenant.objects.create(tenant_code='BEACON', name='Beacon')
        cls.other = Tenant.objects.create(tenant_code='OTHER', name='Other Corp')
        cls.perm = Permission.objects.create(code=PERM_VIEW_DASHBOARD, description='view')
        with tenant_context(cls.beacon.id):
            cls.beacon_role = Role.objects.create(
                tenant=cls.beacon, code=ROLE_PLATFORM_ADMIN, name='Platform Administrator'
            )
            cls.beacon_role.permissions.add(cls.perm)
        with tenant_context(cls.other.id):
            cls.other_role = Role.objects.create(
                tenant=cls.other, code=ROLE_PLATFORM_ADMIN, name='Platform Administrator'
            )

    def _map(self, beacon_user, tenant=None, role=None, active=True):
        pu = PlatformUser.objects.create(
            email=f'{beacon_user.username}@beacon.local', display_name=beacon_user.username
        )
        ProviderIdentity.objects.create(
            provider=PROVIDER_NAME, subject=beacon_subject_for(beacon_user), platform_user=pu
        )
        if tenant is not None and role is not None:
            with tenant_context(tenant.id):
                Membership.objects.create(
                    tenant=tenant, platform_user=pu, role=role, is_active=active
                )
        return pu

    def _client_for(self, beacon_user):
        c = Client()
        c.force_login(beacon_user)
        return c

    def test_unauthenticated_request_denied(self):
        self.assertEqual(Client().get('/platform/').status_code, 403)

    def test_beacon_authenticated_but_unmapped_denied(self):
        u = User.objects.create_user('unmapped', password='x')
        self.assertEqual(self._client_for(u).get('/platform/').status_code, 403)

    def test_provider_identity_alone_without_membership_denied(self):
        u = User.objects.create_user('nomember', password='x')
        self._map(u)  # mapped PlatformUser + ProviderIdentity, but NO membership
        self.assertEqual(self._client_for(u).get('/platform/').status_code, 403)

    def test_membership_in_other_tenant_does_not_authorize_beacon(self):
        u = User.objects.create_user('otheronly', password='x')
        self._map(u, tenant=self.other, role=self.other_role)
        self.assertEqual(self._client_for(u).get('/platform/').status_code, 403)

    def test_inactive_membership_denied(self):
        u = User.objects.create_user('inactive', password='x')
        self._map(u, tenant=self.beacon, role=self.beacon_role, active=False)
        self.assertEqual(self._client_for(u).get('/platform/').status_code, 403)

    def test_valid_membership_authorized(self):
        u = User.objects.create_user('good', password='x')
        self._map(u, tenant=self.beacon, role=self.beacon_role)
        response = self._client_for(u).get('/platform/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enterprise Platform')

    def test_platform_user_and_employee_are_independent(self):
        # Employee is not implemented in Phase 0; nothing couples the two.
        self.assertFalse(apps.is_installed('aegis.people'))
        field_names = {f.name for f in PlatformUser._meta.get_fields()}
        self.assertNotIn('employee', field_names)
