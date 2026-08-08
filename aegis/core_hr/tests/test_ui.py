"""Console smoke + access-control tests for the Core HR UI.

Uses the real /platform/hr/ routes through the Phase 0 middleware + access gate.
The request tenant resolves to PLATFORM_TENANT_CODE (BEACON).
"""
from django.contrib.auth.models import User
from django.test import TestCase

from aegis.core.auth.beacon_session import PROVIDER_NAME, beacon_subject_for
from aegis.core.constants import ROLE_PLATFORM_ADMIN
from aegis.core.context import tenant_context
from aegis.core.models import (
    Membership,
    PlatformUser,
    ProviderIdentity,
    Role,
    Tenant,
)
from aegis.core_hr.models import Employee
from aegis.core_hr.tests.base import make_reference


class ConsoleTests(TestCase):
    databases = {'default', 'platform'}

    @classmethod
    def setUpTestData(cls):
        cls.tenant = Tenant.objects.create(tenant_code='BEACON', name='Beacon')
        cls.refs = make_reference(cls.tenant, suffix='X')
        cls.beacon_user = User.objects.create_user('owner', password='x')
        cls.pu = PlatformUser.objects.create(email='owner@beacon.local', display_name='Owner')
        ProviderIdentity.objects.create(
            provider=PROVIDER_NAME, subject=beacon_subject_for(cls.beacon_user), platform_user=cls.pu)
        with tenant_context(cls.tenant.id):
            role = Role.objects.create(tenant=cls.tenant, code=ROLE_PLATFORM_ADMIN, name='Admin')
            Membership.objects.create(tenant=cls.tenant, platform_user=cls.pu, role=role, is_active=True)

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get('/platform/hr/employees/').status_code, 403)

    def test_member_can_list_employees(self):
        self.client.force_login(self.beacon_user)
        self.assertEqual(self.client.get('/platform/hr/employees/').status_code, 200)

    def test_member_can_list_reference(self):
        self.client.force_login(self.beacon_user)
        self.assertEqual(self.client.get('/platform/hr/reference/companies/').status_code, 200)
        self.assertEqual(self.client.get('/platform/hr/reference/employment-statuses/').status_code, 200)

    def test_create_employee_through_console(self):
        self.client.force_login(self.beacon_user)
        r = self.refs
        data = {
            'employee_number': 'UI001', 'first_name': 'Ui', 'middle_name': '',
            'last_name': 'Test', 'preferred_name': '',
            'company': str(r['company'].id), 'department': '', 'job': '', 'location': '',
            'manager': '', 'employment_status': str(r['active'].id),
            'employee_type': str(r['etype'].id), 'hire_date': '2026-01-01',
            'original_hire_date': '', 'termination_date': '', 'email': '',
        }
        resp = self.client.post('/platform/hr/employees/add/', data)
        self.assertEqual(resp.status_code, 302)
        with tenant_context(self.tenant.id):
            self.assertTrue(Employee.objects.filter(employee_number='UI001').exists())

    def test_unknown_reference_slug_404(self):
        self.client.force_login(self.beacon_user)
        self.assertEqual(self.client.get('/platform/hr/reference/nonsense/').status_code, 404)
