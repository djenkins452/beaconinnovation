"""Shared fixtures/helpers for Core HR tests."""
import datetime

from django.test import TestCase

from aegis.core.context import tenant_context
from aegis.core.models import Tenant
from aegis.core_hr.models import (
    Company,
    Department,
    EmployeeClassification,
    EmployeeType,
    EmploymentStatus,
    Job,
    Location,
    SystemStatusCategory,
)

HIRE = datetime.date(2026, 1, 1)


def make_tenant(code):
    return Tenant.objects.create(tenant_code=code, name=f'Tenant {code}')


def make_reference(tenant, suffix=''):
    """Create a full set of reference data for a tenant (fixtures, no audit)."""
    with tenant_context(tenant.id):
        return {
            'company': Company.objects.create(tenant=tenant, company_code=f'C{suffix}', name='Company'),
            'department': Department.objects.create(tenant=tenant, department_code=f'D{suffix}', name='Dept'),
            'job': Job.objects.create(tenant=tenant, job_code=f'J{suffix}', title='Job'),
            'location': Location.objects.create(tenant=tenant, location_code=f'L{suffix}', name='Loc'),
            'active': EmploymentStatus.objects.create(
                tenant=tenant, status_code=f'A{suffix}', label='Active',
                system_category=SystemStatusCategory.ACTIVE),
            'leave': EmploymentStatus.objects.create(
                tenant=tenant, status_code=f'LOA{suffix}', label='Leave',
                system_category=SystemStatusCategory.LEAVE),
            'terminated': EmploymentStatus.objects.create(
                tenant=tenant, status_code=f'T{suffix}', label='Terminated',
                system_category=SystemStatusCategory.TERMINATED),
            'etype': EmployeeType.objects.create(
                tenant=tenant, type_code=f'FT{suffix}', label='Full-Time',
                classification=EmployeeClassification.EMPLOYEE),
        }


def employee_fields(refs, number='EMP0001', **overrides):
    data = {
        'employee_number': number,
        'first_name': 'Jane',
        'last_name': 'Doe',
        'company': refs['company'],
        'employment_status': refs['active'],
        'employee_type': refs['etype'],
        'hire_date': HIRE,
    }
    data.update(overrides)
    return data


class CoreHRTestCase(TestCase):
    databases = {'default', 'platform'}

    @classmethod
    def setUpTestData(cls):
        cls.tenant_a = make_tenant('AAA')
        cls.tenant_b = make_tenant('BBB')
        cls.ref_a = make_reference(cls.tenant_a, suffix='A')
        cls.ref_b = make_reference(cls.tenant_b, suffix='B')
