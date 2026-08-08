"""Tenant isolation and cross-tenant reference rejection (the core invariant).

Cross-tenant attempts use raw *_id injection and all_objects — not just UI
dropdowns — per the approved validation requirements. DB-level enforcement is
intentionally deferred to RLS (Phase 7); Phase 1 enforces at the app layer.
"""
from django.core.exceptions import ValidationError

from aegis.core.context import tenant_context
from aegis.core.exceptions import TenantContextRequired
from aegis.core_hr.models import Company, Department, Employee
from aegis.core_hr.services import create_employee
from aegis.core_hr.tests.base import CoreHRTestCase, employee_fields


class TenantScopingTests(CoreHRTestCase):
    def test_missing_tenant_context_fails_closed(self):
        with self.assertRaises(TenantContextRequired):
            list(Employee.objects.all())
        with self.assertRaises(TenantContextRequired):
            list(Company.objects.all())

    def test_scoped_reads_only_return_current_tenant(self):
        create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='EMP-A'))
        create_employee(tenant=self.tenant_b, **employee_fields(self.ref_b, number='EMP-B'))
        with tenant_context(self.tenant_a.id):
            numbers = set(Employee.objects.values_list('employee_number', flat=True))
        self.assertEqual(numbers, {'EMP-A'})

    def test_all_objects_escape_hatch_sees_all(self):
        create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='EMP-A'))
        create_employee(tenant=self.tenant_b, **employee_fields(self.ref_b, number='EMP-B'))
        self.assertEqual(Employee.all_objects.count(), 2)


class CrossTenantReferenceTests(CoreHRTestCase):
    """Tenant A Employee must never reference Tenant B data — by ANY path."""

    def _assert_cross_tenant_rejected(self, **cross_fields):
        fields = employee_fields(self.ref_a, **cross_fields)
        with self.assertRaises(ValidationError):
            create_employee(tenant=self.tenant_a, **fields)

    def test_cross_tenant_company_rejected(self):
        self._assert_cross_tenant_rejected(company=self.ref_b['company'])

    def test_cross_tenant_department_rejected(self):
        self._assert_cross_tenant_rejected(department=self.ref_b['department'])

    def test_cross_tenant_job_rejected(self):
        self._assert_cross_tenant_rejected(job=self.ref_b['job'])

    def test_cross_tenant_location_rejected(self):
        self._assert_cross_tenant_rejected(location=self.ref_b['location'])

    def test_cross_tenant_status_rejected(self):
        self._assert_cross_tenant_rejected(employment_status=self.ref_b['active'])

    def test_cross_tenant_type_rejected(self):
        self._assert_cross_tenant_rejected(employee_type=self.ref_b['etype'])

    def test_cross_tenant_manager_rejected(self):
        mgr_b = create_employee(tenant=self.tenant_b, **employee_fields(self.ref_b, number='MGR-B'))
        self._assert_cross_tenant_rejected(manager=mgr_b)

    def test_cross_tenant_via_raw_id_injection_rejected(self):
        # Bypass the ORM object and inject a raw cross-tenant department id.
        fields = employee_fields(self.ref_a)
        fields['department_id'] = self.ref_b['department'].id
        with self.assertRaises(ValidationError):
            create_employee(tenant=self.tenant_a, **fields)

    def test_cross_tenant_parent_department_rejected(self):
        with tenant_context(self.tenant_a.id):
            child = Department(tenant=self.tenant_a, department_code='CHILD', name='Child',
                              parent_department_id=self.ref_b['department'].id)
            with self.assertRaises(ValidationError):
                child.full_clean()
