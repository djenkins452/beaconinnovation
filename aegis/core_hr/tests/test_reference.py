"""Reference data: per-tenant code uniqueness, canonical behavior, deactivate-not-delete."""
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from aegis.core.context import tenant_context
from aegis.core_hr.models import (
    Company,
    Department,
    EmployeeClassification,
    Job,
    SystemStatusCategory,
)
from aegis.core_hr.services import (
    create_employee,
    create_reference,
    set_reference_active,
)
from aegis.core_hr.tests.base import CoreHRTestCase, employee_fields


class ReferenceCodeUniquenessTests(CoreHRTestCase):
    def test_duplicate_company_code_same_tenant_rejected(self):
        with self.assertRaises(ValidationError):
            create_reference(Company, tenant=self.tenant_a, company_code='CA', name='dup')  # CA exists

    def test_same_code_allowed_across_tenants(self):
        # ref_a uses 'CA', ref_b uses 'CB'; create matching codes cross-tenant.
        create_reference(Company, tenant=self.tenant_a, company_code='SHARED', name='A')
        create_reference(Company, tenant=self.tenant_b, company_code='SHARED', name='B')
        self.assertEqual(Company.all_objects.filter(company_code='SHARED').count(), 2)


class CanonicalBehaviorTests(CoreHRTestCase):
    def test_status_maps_to_canonical_category(self):
        self.assertEqual(self.ref_a['active'].system_category, SystemStatusCategory.ACTIVE)
        self.assertEqual(self.ref_a['terminated'].system_category, SystemStatusCategory.TERMINATED)

    def test_type_maps_to_canonical_classification(self):
        self.assertEqual(self.ref_a['etype'].classification, EmployeeClassification.EMPLOYEE)

    def test_tenant_specific_labels_are_free(self):
        # A tenant may label the ACTIVE category however it likes.
        s = create_reference(self.ref_a['active'].__class__, tenant=self.tenant_a,
                             status_code='WORKING', label='Currently Working',
                             system_category=SystemStatusCategory.ACTIVE)
        self.assertEqual(s.system_category, SystemStatusCategory.ACTIVE)


class DeactivationTests(CoreHRTestCase):
    def test_deactivate_reference_does_not_delete_employees(self):
        emp = create_employee(tenant=self.tenant_a,
                              **employee_fields(self.ref_a, number='R1', job=self.ref_a['job']))
        set_reference_active(self.ref_a['job'], is_active=False)
        self.ref_a['job'].refresh_from_db()
        self.assertFalse(self.ref_a['job'].is_active)
        # Employee still exists and still references the (now-inactive) job.
        emp.refresh_from_db()
        self.assertEqual(emp.job_id, self.ref_a['job'].id)

    def test_referenced_job_cannot_be_deleted(self):
        create_employee(tenant=self.tenant_a,
                        **employee_fields(self.ref_a, number='R2', job=self.ref_a['job']))
        with tenant_context(self.tenant_a.id):
            with self.assertRaises(ProtectedError):
                Job.all_objects.get(pk=self.ref_a['job'].id).delete()
