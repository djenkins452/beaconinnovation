"""Idempotently seed generic Core HR default reference data for a tenant.

Usage: manage.py seed_core_hr_defaults <TENANT_CODE>
Safe to re-run (every deploy). Seeds default EmploymentStatus and EmployeeType
rows only; Companies/Departments/Jobs/Locations/Employees are tenant-specific data
entered via the console/import, not defaults.
"""
from django.core.management.base import BaseCommand, CommandError

from aegis.core.context import tenant_context
from aegis.core.models import Tenant
from aegis.core_hr.models import EmployeeType, EmploymentStatus
from aegis.core_hr.seed import DEFAULT_EMPLOYEE_TYPES, DEFAULT_EMPLOYMENT_STATUSES


class Command(BaseCommand):
    help = 'Idempotently seed default EmploymentStatus/EmployeeType for a tenant.'

    def add_arguments(self, parser):
        parser.add_argument('tenant_code', help='Business code of the tenant (e.g. BEACON).')

    def handle(self, *args, **options):
        code = options['tenant_code']
        tenant = Tenant.objects.filter(tenant_code=code).first()
        if tenant is None:
            raise CommandError(f'Tenant "{code}" not found. Seed the tenant first.')

        with tenant_context(tenant.id):
            for status_code, label, category in DEFAULT_EMPLOYMENT_STATUSES:
                EmploymentStatus.objects.get_or_create(
                    tenant=tenant, status_code=status_code,
                    defaults={'label': label, 'system_category': category},
                )
            for type_code, label, classification in DEFAULT_EMPLOYEE_TYPES:
                EmployeeType.objects.get_or_create(
                    tenant=tenant, type_code=type_code,
                    defaults={'label': label, 'classification': classification},
                )

        self.stdout.write(self.style.SUCCESS(
            f'Core HR defaults ensured for tenant {code}: '
            f'{len(DEFAULT_EMPLOYMENT_STATUSES)} statuses, {len(DEFAULT_EMPLOYEE_TYPES)} types.'
        ))
