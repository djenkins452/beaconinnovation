"""Employee: identifiers, manager rules, derived values, termination, email."""
import datetime

from django.core.exceptions import ValidationError

from aegis.core.context import tenant_context
from aegis.core_hr.models import Employee
from aegis.core_hr.services import (
    create_employee,
    terminate_employee,
    update_employee,
)
from aegis.core_hr.tests.base import HIRE, CoreHRTestCase, employee_fields


class EmployeeNumberTests(CoreHRTestCase):
    def test_duplicate_number_in_same_tenant_rejected(self):
        create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='DUP'))
        with self.assertRaises(ValidationError):
            create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='DUP'))

    def test_same_number_allowed_across_tenants(self):
        a = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='EMP0001'))
        b = create_employee(tenant=self.tenant_b, **employee_fields(self.ref_b, number='EMP0001'))
        self.assertEqual(a.employee_number, b.employee_number)
        self.assertNotEqual(a.tenant_id, b.tenant_id)


class RequiredOptionalTests(CoreHRTestCase):
    def test_minimal_required_fields_create(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='MIN'))
        self.assertIsNone(emp.department_id)
        self.assertIsNone(emp.job_id)
        self.assertIsNone(emp.location_id)
        self.assertIsNone(emp.manager_id)

    def test_optional_relationships_set(self):
        emp = create_employee(
            tenant=self.tenant_a,
            **employee_fields(self.ref_a, number='FULL',
                              department=self.ref_a['department'], job=self.ref_a['job'],
                              location=self.ref_a['location']),
        )
        self.assertEqual(emp.department_id, self.ref_a['department'].id)


class ManagerRuleTests(CoreHRTestCase):
    def test_top_level_employee_has_no_manager(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='TOP'))
        self.assertIsNone(emp.manager_id)

    def test_employee_cannot_manage_self(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='SELF'))
        with self.assertRaises(ValidationError):
            update_employee(emp, manager=emp)

    def test_circular_management_rejected(self):
        a = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='MA'))
        b = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='MB', manager=a))
        # a→b would close the loop a→b→a
        with self.assertRaises(ValidationError):
            update_employee(a, manager=b)


class DerivedValueTests(CoreHRTestCase):
    def test_display_name_prefers_preferred_name(self):
        emp = create_employee(tenant=self.tenant_a,
                              **employee_fields(self.ref_a, number='D1', preferred_name='JD'))
        self.assertEqual(emp.display_name, 'JD')

    def test_display_name_defaults_to_first_last(self):
        emp = create_employee(tenant=self.tenant_a,
                              **employee_fields(self.ref_a, number='D2', first_name='Ann', last_name='Lee'))
        self.assertEqual(emp.display_name, 'Ann Lee')

    def test_workforce_active_derives_from_status(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='ACT'))
        self.assertTrue(emp.is_workforce_active)


class EmailTests(CoreHRTestCase):
    def test_email_is_optional_and_not_unique(self):
        create_employee(tenant=self.tenant_a,
                        **employee_fields(self.ref_a, number='E1', email='shared@x.com'))
        # Same email again in same tenant must be allowed (no uniqueness).
        create_employee(tenant=self.tenant_a,
                        **employee_fields(self.ref_a, number='E2', email='shared@x.com'))
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Employee.objects.filter(email='shared@x.com').count(), 2)


class TerminationTests(CoreHRTestCase):
    def test_terminated_status_requires_termination_date(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='T1'))
        with self.assertRaises(ValidationError):
            update_employee(emp, employment_status=self.ref_a['terminated'])  # no date

    def test_terminate_service_sets_date(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='T2'))
        terminate_employee(emp, terminated_status=self.ref_a['terminated'],
                           termination_date=datetime.date(2026, 6, 1))
        self.assertEqual(emp.termination_date, datetime.date(2026, 6, 1))
        self.assertFalse(emp.is_workforce_active)

    def test_termination_date_before_hire_rejected(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='T3'))
        with self.assertRaises(ValidationError):
            terminate_employee(emp, terminated_status=self.ref_a['terminated'],
                               termination_date=HIRE - datetime.timedelta(days=1))

    def test_leave_is_not_termination(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='T4'))
        # Moving to LEAVE requires no termination date and must succeed.
        update_employee(emp, employment_status=self.ref_a['leave'])
        self.assertIsNone(emp.termination_date)
        self.assertFalse(emp.is_workforce_active)
