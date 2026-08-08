"""Core HR relational model (Phase 1).

Design: `docs/architecture/PHASE_1_CORE_HR_DESIGN.md` (v1.0). All entities are
tenant-scoped (inherit Phase 0 `TenantScopedModel`), UUID PK + per-tenant business
code, current-state only. Tenant consistency is enforced in the application layer
(`TenantConsistencyMixin` + service/form validation + fail-closed managers) plus
Django-native CheckConstraints — deliberately NOT composite FKs. Every model keeps
a uniform `tenant` ownership so PostgreSQL RLS can be applied uniformly later.
"""
from django.core.exceptions import ValidationError
from django.db import models

from aegis.core.managers import AllTenantsManager, TenantScopedManager
from aegis.core.models import TenantScopedModel


# --- canonical enumerations -------------------------------------------------

class SystemStatusCategory(models.TextChoices):
    """Small, deliberate canonical categories that drive platform behavior.
    Tenants define their own status codes/labels mapped onto one of these."""
    ACTIVE = 'ACTIVE', 'Active'
    LEAVE = 'LEAVE', 'Leave'
    TERMINATED = 'TERMINATED', 'Terminated'


class EmployeeClassification(models.TextChoices):
    """Coarse workforce classification for downstream behavior (e.g. future
    credential/benefit eligibility). Tenants define granular types on top."""
    EMPLOYEE = 'EMPLOYEE', 'Employee'
    CONTINGENT = 'CONTINGENT', 'Contingent'


# --- tenant-consistency seam ------------------------------------------------

class TenantConsistencyMixin:
    """Assert that every listed FK points at a record in the SAME tenant.

    Related objects are fetched via the base manager (``all_objects``), so this
    catches cross-tenant references even when they were injected via raw ``*_id``
    or ``all_objects`` — not just when UI dropdowns filter. Call sites run this
    via ``full_clean()`` in the service layer.
    """

    #: FK field names that must share this row's tenant.
    tenant_consistent_fields: tuple = ()

    def _check_tenant_consistency(self):
        errors = {}
        for field_name in self.tenant_consistent_fields:
            related = getattr(self, field_name, None)
            if related is not None and related.tenant_id != self.tenant_id:
                errors[field_name] = ValidationError(
                    f'{field_name} belongs to a different tenant.', code='cross_tenant'
                )
        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _walk_would_cycle(start, parent_attr, target_pk):
        """Return True if following ``parent_attr`` from ``start`` reaches
        ``target_pk`` (i.e. assigning it would create a cycle)."""
        seen = set()
        current = start
        while current is not None:
            if current.pk == target_pk:
                return True
            if current.pk in seen:
                break
            seen.add(current.pk)
            current = getattr(current, parent_attr)
        return False


# --- reference entities -----------------------------------------------------

class Company(TenantConsistencyMixin, TenantScopedModel):
    """A legal entity within a tenant. Tenant != Company."""
    company_code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    objects = TenantScopedManager()
    all_objects = AllTenantsManager()

    class Meta:
        base_manager_name = 'all_objects'
        default_manager_name = 'all_objects'
        ordering = ['company_code']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'company_code'], name='uq_company_tenant_code'),
        ]

    def __str__(self):
        return f'{self.company_code} — {self.name}'


class Location(TenantConsistencyMixin, TenantScopedModel):
    location_code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    # Minimal inline address (no generalized Address framework in Phase 1).
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=128, blank=True)
    region_state = models.CharField(max_length=128, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)
    country = models.CharField(max_length=64, blank=True)

    objects = TenantScopedManager()
    all_objects = AllTenantsManager()

    class Meta:
        base_manager_name = 'all_objects'
        default_manager_name = 'all_objects'
        ordering = ['location_code']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'location_code'], name='uq_location_tenant_code'),
        ]

    def __str__(self):
        return f'{self.location_code} — {self.name}'


class Department(TenantConsistencyMixin, TenantScopedModel):
    department_code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    parent_department = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT, related_name='children'
    )
    is_active = models.BooleanField(default=True)

    tenant_consistent_fields = ('parent_department',)

    objects = TenantScopedManager()
    all_objects = AllTenantsManager()

    class Meta:
        base_manager_name = 'all_objects'
        default_manager_name = 'all_objects'
        ordering = ['department_code']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'department_code'], name='uq_department_tenant_code'),
            models.CheckConstraint(
                condition=~models.Q(parent_department=models.F('id')),
                name='ck_department_parent_not_self',
            ),
        ]

    def clean(self):
        super().clean()
        self._check_tenant_consistency()
        if self.parent_department_id is not None:
            if self.parent_department_id == self.pk:
                raise ValidationError({'parent_department': 'A department cannot be its own parent.'})
            if self._walk_would_cycle(self.parent_department, 'parent_department', self.pk):
                raise ValidationError({'parent_department': 'Circular department hierarchy is not allowed.'})

    def __str__(self):
        return f'{self.department_code} — {self.name}'


class Job(TenantConsistencyMixin, TenantScopedModel):
    """Job classification — NOT an assignment. Deliberately small."""
    job_code = models.CharField(max_length=32)
    title = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    objects = TenantScopedManager()
    all_objects = AllTenantsManager()

    class Meta:
        base_manager_name = 'all_objects'
        default_manager_name = 'all_objects'
        ordering = ['job_code']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'job_code'], name='uq_job_tenant_code'),
        ]

    def __str__(self):
        return f'{self.job_code} — {self.title}'


class EmploymentStatus(TenantConsistencyMixin, TenantScopedModel):
    """Tenant-configurable status code/label mapped to a canonical category."""
    status_code = models.CharField(max_length=32)
    label = models.CharField(max_length=255)
    system_category = models.CharField(max_length=16, choices=SystemStatusCategory.choices)
    is_active = models.BooleanField(default=True)

    objects = TenantScopedManager()
    all_objects = AllTenantsManager()

    class Meta:
        base_manager_name = 'all_objects'
        default_manager_name = 'all_objects'
        ordering = ['status_code']
        verbose_name_plural = 'employment statuses'
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'status_code'], name='uq_empstatus_tenant_code'),
        ]

    def __str__(self):
        return f'{self.status_code} — {self.label}'


class EmployeeType(TenantConsistencyMixin, TenantScopedModel):
    """Tenant-configurable employee type mapped to a coarse classification."""
    type_code = models.CharField(max_length=32)
    label = models.CharField(max_length=255)
    classification = models.CharField(max_length=16, choices=EmployeeClassification.choices)
    is_active = models.BooleanField(default=True)

    objects = TenantScopedManager()
    all_objects = AllTenantsManager()

    class Meta:
        base_manager_name = 'all_objects'
        default_manager_name = 'all_objects'
        ordering = ['type_code']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'type_code'], name='uq_emptype_tenant_code'),
        ]

    def __str__(self):
        return f'{self.type_code} — {self.label}'


# --- Employee ---------------------------------------------------------------

class EmployeeQuerySet(models.QuerySet):
    def active(self):
        """Workforce-active = current status maps to the canonical ACTIVE category."""
        return self.filter(employment_status__system_category=SystemStatusCategory.ACTIVE)


class EmployeeManager(TenantScopedManager.from_queryset(EmployeeQuerySet)):
    """Tenant-scoped (fail-closed) manager with the Employee queryset methods."""
    use_in_migrations = False


class Employee(TenantConsistencyMixin, TenantScopedModel):
    employee_number = models.CharField(max_length=32)
    first_name = models.CharField(max_length=128)
    middle_name = models.CharField(max_length=128, blank=True)  # full middle name, not an initial
    last_name = models.CharField(max_length=128)
    preferred_name = models.CharField(max_length=128, blank=True)

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name='employees')
    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name='employees'
    )
    job = models.ForeignKey(
        Job, null=True, blank=True, on_delete=models.PROTECT, related_name='employees'
    )
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name='employees'
    )
    manager = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='direct_reports'
    )
    employment_status = models.ForeignKey(EmploymentStatus, on_delete=models.PROTECT, related_name='employees')
    employee_type = models.ForeignKey(EmployeeType, on_delete=models.PROTECT, related_name='employees')

    hire_date = models.DateField()
    original_hire_date = models.DateField(null=True, blank=True)
    termination_date = models.DateField(null=True, blank=True)
    email = models.EmailField(null=True, blank=True)  # optional attribute, NOT unique

    tenant_consistent_fields = (
        'company', 'department', 'job', 'location',
        'employment_status', 'employee_type', 'manager',
    )

    objects = EmployeeManager()
    all_objects = AllTenantsManager()

    class Meta:
        base_manager_name = 'all_objects'
        default_manager_name = 'all_objects'
        ordering = ['employee_number']
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'employee_number'], name='uq_employee_tenant_number'),
            models.CheckConstraint(
                condition=~models.Q(manager=models.F('id')), name='ck_employee_manager_not_self'
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(termination_date__isnull=True)
                    | models.Q(termination_date__gte=models.F('hire_date'))
                ),
                name='ck_employee_term_after_hire',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'hire_date'], name='emp_tenant_hire_idx'),
            models.Index(fields=['tenant', 'termination_date'], name='emp_tenant_term_idx'),
        ]

    def __str__(self):
        return f'{self.employee_number} — {self.display_name}'

    # --- derived values (never stored) ---
    @property
    def display_name(self):
        if self.preferred_name:
            return self.preferred_name
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def is_workforce_active(self):
        return self.employment_status.system_category == SystemStatusCategory.ACTIVE

    # --- validation ---
    def clean(self):
        super().clean()
        self._check_tenant_consistency()
        # Manager rules (DB CheckConstraint also guards manager != self).
        if self.manager_id is not None:
            if self.manager_id == self.pk:
                raise ValidationError({'manager': 'An employee cannot be their own manager.'})
            if self._walk_would_cycle(self.manager, 'manager', self.pk):
                raise ValidationError({'manager': 'Circular management relationship is not allowed.'})
        # Termination rules driven by canonical status category.
        if self.termination_date and self.hire_date and self.termination_date < self.hire_date:
            raise ValidationError({'termination_date': 'Termination date cannot precede hire date.'})
        if self.employment_status_id is not None:
            is_terminated = self.employment_status.system_category == SystemStatusCategory.TERMINATED
            if is_terminated and not self.termination_date:
                raise ValidationError(
                    {'termination_date': 'Termination date is required when status is Terminated.'}
                )
