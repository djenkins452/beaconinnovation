"""Schema-quality check: basic workforce reporting via straightforward ORM queries.

This is not a reporting engine — it proves the relational model answers the
required questions with plain queries and no dark data.
"""
import datetime

from django.db.models import Count

from aegis.core.context import tenant_context
from aegis.core_hr.models import (
    Department,
    Employee,
    Job,
    SystemStatusCategory,
)
from aegis.core_hr.services import create_employee, create_reference, terminate_employee
from aegis.core_hr.tests.base import HIRE, CoreHRTestCase, employee_fields


class ReportabilityTests(CoreHRTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        r = cls.ref_a
        cls.dept2 = create_reference(Department, tenant=cls.tenant_a, department_code='D2A', name='Dept 2')
        cls.job2 = create_reference(Job, tenant=cls.tenant_a, job_code='J2A', title='Job 2')
        cls.mgr = create_employee(tenant=cls.tenant_a, **employee_fields(
            r, number='M1', department=r['department'], job=r['job']))
        cls.e2 = create_employee(tenant=cls.tenant_a, **employee_fields(
            r, number='E2', department=r['department'], job=cls.job2, manager=cls.mgr))
        cls.e3 = create_employee(tenant=cls.tenant_a, **employee_fields(
            r, number='E3', department=cls.dept2, job=r['job'], manager=cls.mgr))
        terminate_employee(cls.e3, terminated_status=r['terminated'],
                           termination_date=datetime.date(2026, 9, 1))

    def test_roster_and_total_headcount(self):
        with tenant_context(self.tenant_a.id):
            self.assertEqual(Employee.objects.count(), 3)

    def test_headcount_by_department(self):
        with tenant_context(self.tenant_a.id):
            counts = dict(
                Employee.objects.values_list('department__department_code')
                .annotate(n=Count('id')).values_list('department__department_code', 'n')
            )
        self.assertEqual(counts['DA'], 2)
        self.assertEqual(counts['D2A'], 1)

    def test_headcount_by_job_and_company(self):
        with tenant_context(self.tenant_a.id):
            by_job = dict(Employee.objects.values_list('job__job_code').annotate(n=Count('id'))
                         .values_list('job__job_code', 'n'))
            company_total = Employee.objects.filter(company=self.ref_a['company']).count()
        self.assertEqual(by_job['JA'], 2)
        self.assertEqual(by_job['J2A'], 1)
        self.assertEqual(company_total, 3)

    def test_status_distribution_and_active(self):
        with tenant_context(self.tenant_a.id):
            by_cat = dict(
                Employee.objects.values_list('employment_status__system_category')
                .annotate(n=Count('id')).values_list('employment_status__system_category', 'n')
            )
            active = Employee.objects.active().count()
        self.assertEqual(by_cat[SystemStatusCategory.ACTIVE], 2)
        self.assertEqual(by_cat[SystemStatusCategory.TERMINATED], 1)
        self.assertEqual(active, 2)

    def test_employees_by_manager(self):
        with tenant_context(self.tenant_a.id):
            reports = Employee.objects.filter(manager=self.mgr).count()
        self.assertEqual(reports, 2)

    def test_hire_and_termination_date_analysis(self):
        with tenant_context(self.tenant_a.id):
            hired_2026 = Employee.objects.filter(hire_date__year=2026).count()
            terminated = Employee.objects.filter(termination_date__isnull=False).count()
        self.assertEqual(hired_2026, 3)
        self.assertEqual(terminated, 1)

    def test_type_distribution(self):
        with tenant_context(self.tenant_a.id):
            by_type = dict(Employee.objects.values_list('employee_type__type_code')
                          .annotate(n=Count('id')).values_list('employee_type__type_code', 'n'))
        self.assertEqual(by_type['FTA'], 3)
