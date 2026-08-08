"""Core foundation models for the Enterprise Platform.

All models live in the ``platform`` database (see :mod:`aegis.core.routers`).
Conventions:

* UUID primary keys via :func:`aegis.core.fields.new_uuid` (never exposed as the
  user-facing identifier — business keys are separate).
* Tenant-owned models inherit :class:`TenantScopedModel` (mandatory ``tenant``,
  fail-closed scoping, RLS-ready columns).
* No foreign keys to Beacon's ``auth.User`` and no ``ContentType`` usage — both
  would cross the database boundary. Platform identity is authoritative here.
"""
from django.core.exceptions import ValidationError
from django.db import models

from aegis.core.fields import new_uuid
from aegis.core.managers import AllTenantsManager, TenantScopedManager


class TimeStampedModel(models.Model):
    """Row metadata common to every platform model.

    ``created_by`` / ``updated_by`` reference a :class:`PlatformUser` by id in the
    same (platform) database. They are stored as plain UUIDs rather than FKs to
    keep the audit metadata lightweight; the authoritative account of *who did
    what* is the immutable :class:`AuditEvent`, not these columns.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.UUIDField(null=True, blank=True, editable=False)
    updated_by = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        abstract = True


class Tenant(TimeStampedModel):
    """The authoritative organization/tenant. Root of tenant ownership.

    Beacon Innovation LLC is seeded as Tenant #1. ``Tenant`` is the only
    tenant-owned concept without a ``tenant`` FK (it *is* the tenant).
    """

    STATUS_ACTIVE = 'active'
    STATUS_SUSPENDED = 'suspended'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_SUSPENDED, 'Suspended'),
    ]

    id = models.UUIDField(primary_key=True, default=new_uuid, editable=False)
    # Business key — human-facing, globally unique (e.g. "BEACON").
    tenant_code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    class Meta:
        ordering = ['tenant_code']

    def __str__(self):
        return f'{self.tenant_code} ({self.name})'


class TenantScopedModel(TimeStampedModel):
    """Abstract base for every tenant-owned model.

    Provides the mandatory ``tenant`` FK, UUID PK, and fail-closed default
    manager. ``base_manager_name = 'all_objects'`` keeps Django's internals
    (related lookups, cascade collection, ``refresh_from_db``) working with the
    unscoped manager while application code goes through the scoped ``objects``.
    """

    id = models.UUIDField(primary_key=True, default=new_uuid, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='+')

    objects = TenantScopedManager()
    all_objects = AllTenantsManager()

    class Meta:
        abstract = True
        base_manager_name = 'all_objects'


class PlatformUser(TimeStampedModel):
    """The authoritative application principal (decision B4).

    Deliberately **not** a Beacon ``auth.User`` and **not** an ``Employee``. A
    PlatformUser may belong to several tenants (via :class:`Membership`), so it is
    a global principal rather than a tenant-scoped row. Authentication is handled
    by external providers mapped through :class:`ProviderIdentity`; this table
    owns authorization/identity within the platform.
    """

    id = models.UUIDField(primary_key=True, default=new_uuid, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['email']

    def __str__(self):
        return self.display_name or self.email


class ProviderIdentity(TimeStampedModel):
    """Maps an external authentication subject to a :class:`PlatformUser`.

    ``(provider, subject)`` is the stable external identifier (e.g.
    ``beacon-session`` + ``beacon:<pk>``). Storing only a string subject — never
    an FK to ``auth.User`` — is what keeps platform identity decoupled from
    Beacon and portable on extraction.
    """

    id = models.UUIDField(primary_key=True, default=new_uuid, editable=False)
    platform_user = models.ForeignKey(
        PlatformUser, on_delete=models.CASCADE, related_name='identities'
    )
    provider = models.CharField(max_length=64)
    subject = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'subject'], name='uq_provideridentity_provider_subject'
            )
        ]

    def __str__(self):
        return f'{self.provider}:{self.subject}'


class Permission(TimeStampedModel):
    """A global capability code (e.g. ``platform.view_dashboard``).

    Permissions are the fixed vocabulary of what can be done; :class:`Role`
    groups them and :class:`Membership` grants a role within a tenant.
    """

    id = models.UUIDField(primary_key=True, default=new_uuid, editable=False)
    code = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return self.code


class Role(TenantScopedModel):
    """A tenant-defined named set of permissions."""

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    permissions = models.ManyToManyField(Permission, related_name='roles', blank=True)
    # System roles are seeded by the platform and should not be user-deleted.
    is_system = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['tenant', 'code'], name='uq_role_tenant_code')
        ]

    def __str__(self):
        return f'{self.code} @ {self.tenant_id}'


class Membership(TenantScopedModel):
    """Grants a :class:`PlatformUser` a :class:`Role` within a tenant.

    This is the object that authorizes access. Authentication alone never grants
    access — there must be an active Membership in the requested tenant.
    """

    platform_user = models.ForeignKey(
        PlatformUser, on_delete=models.CASCADE, related_name='memberships'
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name='memberships')
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'platform_user', 'role'],
                name='uq_membership_tenant_user_role',
            )
        ]

    def __str__(self):
        return f'{self.platform_user_id} → {self.role_id} @ {self.tenant_id}'


class AuditEvent(models.Model):
    """Immutable, append-only record of security-sensitive platform operations.

    Immutability is enforced in :meth:`save`/:meth:`delete`. Keyed by string
    ``model_name`` + ``object_id`` (no ``ContentType`` FK — that would cross the
    database boundary). Preserves tenant and actor attribution.
    """

    id = models.UUIDField(primary_key=True, default=new_uuid, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.PROTECT, related_name='+', null=True, blank=True
    )
    actor = models.ForeignKey(
        PlatformUser, on_delete=models.SET_NULL, related_name='+', null=True, blank=True
    )
    provider = models.CharField(max_length=64, blank=True)
    action = models.CharField(max_length=100, db_index=True)
    model_name = models.CharField(max_length=100, blank=True, db_index=True)
    object_id = models.UUIDField(null=True, blank=True, db_index=True)
    object_repr = models.CharField(max_length=500, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['tenant', '-occurred_at'], name='auditevent_tenant_time_idx'),
            models.Index(fields=['action', '-occurred_at'], name='auditevent_action_time_idx'),
        ]

    def __str__(self):
        return f'{self.action} {self.model_name} @ {self.occurred_at}'

    def save(self, *args, **kwargs):
        # Fail closed against modification: a row that already exists in the DB
        # may never be re-saved. (The UUID pk is generated at instantiation, so
        # we check existence in the DB rather than truthiness of pk.)
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError('AuditEvent records are immutable and cannot be modified.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('AuditEvent records cannot be deleted.')
