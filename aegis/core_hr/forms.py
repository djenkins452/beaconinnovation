"""Console forms. FK choices are scoped to the current tenant (via the fail-closed
managers) and to active reference rows. Writes are performed by the service layer
(for audit) — these forms validate and render only."""
from django import forms

from aegis.core_hr.models import (
    Company,
    Department,
    Employee,
    EmploymentStatus,
    EmployeeType,
    Job,
    Location,
)

_DATE = forms.DateInput(attrs={'type': 'date'})


def scope_modelchoice_fields(form):
    """Point every ModelChoiceField at active, current-tenant rows only, and set
    the instance's tenant from the request context so model-level tenant
    validation (run during form._post_clean) sees the correct tenant."""
    from aegis.core.context import get_current_tenant_id

    tenant_id = get_current_tenant_id()
    if tenant_id and getattr(form.instance, 'tenant_id', None) is None:
        form.instance.tenant_id = tenant_id
    for name, field in form.fields.items():
        if isinstance(field, forms.ModelChoiceField):
            model = field.queryset.model
            qs = model.objects.all()
            if any(f.name == 'is_active' for f in model._meta.fields):
                qs = qs.filter(is_active=True)
            field.queryset = qs


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            'employee_number', 'first_name', 'middle_name', 'last_name', 'preferred_name',
            'company', 'department', 'job', 'location', 'manager',
            'employment_status', 'employee_type',
            'hire_date', 'original_hire_date', 'termination_date', 'email',
        ]
        widgets = {'hire_date': _DATE, 'original_hire_date': _DATE, 'termination_date': _DATE}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        scope_modelchoice_fields(self)
        # A manager cannot be the employee being edited.
        if self.instance and self.instance.pk:
            self.fields['manager'].queryset = self.fields['manager'].queryset.exclude(pk=self.instance.pk)


# Reference entities → editable fields (is_active handled via a separate action).
REFERENCE_FORMS = {
    'companies': (Company, ['company_code', 'name'], 'Companies'),
    'locations': (Location, ['location_code', 'name', 'address_line1', 'address_line2',
                             'city', 'region_state', 'postal_code', 'country'], 'Locations'),
    'departments': (Department, ['department_code', 'name', 'parent_department'], 'Departments'),
    'jobs': (Job, ['job_code', 'title'], 'Jobs'),
    'employment-statuses': (EmploymentStatus, ['status_code', 'label', 'system_category'],
                            'Employment Statuses'),
    'employee-types': (EmployeeType, ['type_code', 'label', 'classification'], 'Employee Types'),
}
