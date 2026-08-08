"""Service layer for Core HR writes.

All auditable mutations go through here: validate (`full_clean`, incl. tenant
consistency), persist, and record an immutable `AuditEvent`. Nobody calls
`.save()` on these models directly for auditable operations. Writes are wrapped in
a transaction on the platform database.
"""
from django.db import transaction

from aegis.core import audit
from aegis.core.context import tenant_context
from aegis.core_hr.models import (
    Employee,
    SystemStatusCategory,
)

PLATFORM_DB = 'platform'

# Employee field → specific audit action for relationship/status changes.
_TRACKED_CHANGE_EVENTS = {
    'employment_status_id': 'employee.status_changed',
    'job_id': 'employee.job_changed',
    'department_id': 'employee.department_changed',
    'company_id': 'employee.company_changed',
    'location_id': 'employee.location_changed',
    'manager_id': 'employee.manager_changed',
    'employee_type_id': 'employee.type_changed',
}


def _snapshot(employee):
    return {field: getattr(employee, field) for field in _TRACKED_CHANGE_EVENTS}


# --- Employee ---------------------------------------------------------------

def create_employee(*, tenant, actor=None, request=None, **fields):
    with tenant_context(tenant.id), transaction.atomic(using=PLATFORM_DB):
        employee = Employee(tenant=tenant, **fields)
        employee.full_clean()
        employee.save()
        audit.record_event(
            action='employee.created', tenant=tenant, actor=actor, request=request,
            obj=employee, detail={'employee_number': employee.employee_number},
        )
    return employee


def update_employee(employee, *, actor=None, request=None, **changes):
    with tenant_context(employee.tenant_id), transaction.atomic(using=PLATFORM_DB):
        before = _snapshot(employee)
        for field, value in changes.items():
            setattr(employee, field, value)
        employee.full_clean()
        employee.save()
        after = _snapshot(employee)

        changed = {k: [str(before[k]), str(after[k])] for k in before if before[k] != after[k]}
        audit.record_event(
            action='employee.updated', tenant=employee.tenant, actor=actor, request=request,
            obj=employee, detail={'changed': changed},
        )
        # Emit specific events for tracked relationship/status changes.
        for key, action in _TRACKED_CHANGE_EVENTS.items():
            if before[key] != after[key]:
                audit.record_event(
                    action=action, tenant=employee.tenant, actor=actor, request=request,
                    obj=employee, detail={key: [str(before[key]), str(after[key])]},
                )
    return employee


def terminate_employee(employee, *, terminated_status, termination_date, actor=None, request=None):
    """Set a TERMINATED-category status + termination date."""
    if terminated_status.system_category != SystemStatusCategory.TERMINATED:
        raise ValueError('terminate_employee requires a status in the TERMINATED category.')
    with tenant_context(employee.tenant_id), transaction.atomic(using=PLATFORM_DB):
        employee.employment_status = terminated_status
        employee.termination_date = termination_date
        employee.full_clean()
        employee.save()
        audit.record_event(
            action='employee.terminated', tenant=employee.tenant, actor=actor, request=request,
            obj=employee, detail={'termination_date': str(termination_date)},
        )
    return employee


def reactivate_employee(employee, *, active_status, actor=None, request=None):
    """Return an employee to an ACTIVE-category status and clear termination date."""
    if active_status.system_category != SystemStatusCategory.ACTIVE:
        raise ValueError('reactivate_employee requires a status in the ACTIVE category.')
    with tenant_context(employee.tenant_id), transaction.atomic(using=PLATFORM_DB):
        employee.employment_status = active_status
        employee.termination_date = None
        employee.full_clean()
        employee.save()
        audit.record_event(
            action='employee.reactivated', tenant=employee.tenant, actor=actor, request=request,
            obj=employee,
        )
    return employee


# --- Reference data (generic) ----------------------------------------------

def create_reference(model, *, tenant, actor=None, request=None, **fields):
    with tenant_context(tenant.id), transaction.atomic(using=PLATFORM_DB):
        obj = model(tenant=tenant, **fields)
        obj.full_clean()
        obj.save()
        audit.record_event(
            action=f'{model._meta.model_name}.created', tenant=tenant, actor=actor,
            request=request, obj=obj,
        )
    return obj


def update_reference(obj, *, actor=None, request=None, **changes):
    with tenant_context(obj.tenant_id), transaction.atomic(using=PLATFORM_DB):
        for field, value in changes.items():
            setattr(obj, field, value)
        obj.full_clean()
        obj.save()
        audit.record_event(
            action=f'{obj._meta.model_name}.updated', tenant=obj.tenant, actor=actor,
            request=request, obj=obj,
        )
    return obj


def set_reference_active(obj, *, is_active, actor=None, request=None):
    """Deactivate/reactivate a reference record (never delete)."""
    with tenant_context(obj.tenant_id), transaction.atomic(using=PLATFORM_DB):
        obj.is_active = is_active
        obj.full_clean()
        obj.save()
        action = 'activated' if is_active else 'deactivated'
        audit.record_event(
            action=f'{obj._meta.model_name}.{action}', tenant=obj.tenant, actor=actor,
            request=request, obj=obj,
        )
    return obj
