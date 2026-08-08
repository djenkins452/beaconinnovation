"""Exceptions for the Enterprise Platform core."""


class TenantContextRequired(Exception):
    """Raised when tenant-scoped data is accessed with no tenant in context.

    This is the fail-closed guarantee: rather than silently returning data from
    an unknown/unintended tenant, tenant-scoped queries refuse to run without an
    explicit tenant context. Establishing cross-tenant/no-context access is only
    possible via the deliberate ``all_objects`` escape hatch.
    """
