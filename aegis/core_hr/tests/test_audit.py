"""Core HR operations produce immutable AuditEvents with attribution."""
import datetime

from aegis.core.models import AuditEvent
from aegis.core_hr.models import Company
from aegis.core_hr.services import (
    create_employee,
    create_reference,
    terminate_employee,
    update_employee,
)
from aegis.core_hr.tests.base import CoreHRTestCase, employee_fields


class AuditWiringTests(CoreHRTestCase):
    def _actions(self, **filters):
        return set(AuditEvent.objects.filter(**filters).values_list('action', flat=True))

    def test_employee_create_emits_event_with_tenant(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='AE1'))
        events = AuditEvent.objects.filter(action='employee.created', object_id=emp.id)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().tenant_id, self.tenant_a.id)

    def test_relationship_change_emits_specific_events(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='AE2'))
        update_employee(emp, job=self.ref_a['job'], department=self.ref_a['department'])
        actions = self._actions(object_id=emp.id)
        self.assertIn('employee.updated', actions)
        self.assertIn('employee.job_changed', actions)
        self.assertIn('employee.department_changed', actions)

    def test_terminate_emits_event(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='AE3'))
        terminate_employee(emp, terminated_status=self.ref_a['terminated'],
                           termination_date=datetime.date(2026, 7, 1))
        self.assertIn('employee.terminated', self._actions(object_id=emp.id))

    def test_reference_create_emits_event(self):
        obj = create_reference(Company, tenant=self.tenant_a, company_code='NEWCO', name='New Co')
        self.assertIn('company.created', self._actions(object_id=obj.id))

    def test_audit_event_is_immutable(self):
        emp = create_employee(tenant=self.tenant_a, **employee_fields(self.ref_a, number='AE4'))
        event = AuditEvent.objects.filter(object_id=emp.id).first()
        event.action = 'tampered'
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            event.save()
