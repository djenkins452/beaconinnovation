"""Managers that enforce tenant scoping at the query layer.

``TenantScopedManager`` is the default manager for every tenant-owned model. It
fails closed: any query with no tenant in context raises
:class:`~aegis.core.exceptions.TenantContextRequired` instead of returning
cross-tenant rows. ``AllTenantsManager`` is the deliberate, unscoped escape
hatch for administrative/bootstrap/ops paths.
"""
from django.db import models

from aegis.core.context import get_current_tenant_id
from aegis.core.exceptions import TenantContextRequired


class AllTenantsManager(models.Manager):
    """Unscoped manager — sees every tenant's rows.

    Used deliberately for bootstrap/seed, admin/ops, and framework internals
    (via ``Meta.base_manager_name``). Never wire this to user-facing queries.
    """

    use_in_migrations = False


class TenantScopedQuerySet(models.QuerySet):
    pass


class TenantScopedManager(models.Manager.from_queryset(TenantScopedQuerySet)):
    """Default manager for tenant-owned models; filters by the current tenant.

    Fail-closed: with no tenant in context, ``get_queryset`` raises rather than
    exposing another tenant's data.
    """

    use_in_migrations = False

    def get_queryset(self):
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise TenantContextRequired(
                'Tenant-scoped access attempted with no tenant in context. '
                'Set a tenant (middleware/tenant_context) or use all_objects.'
            )
        return super().get_queryset().filter(tenant_id=tenant_id)
