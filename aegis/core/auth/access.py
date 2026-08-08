"""Membership-based access control for platform views (fail closed).

Access requires all of: a resolved :class:`PlatformUser` (set on the request by
:class:`~aegis.core.middleware.TenantMiddleware`), a tenant in context, and an
active :class:`Membership` in *that* tenant. Because ``Membership.objects`` is
tenant-scoped, a membership in another tenant is invisible here — so membership
in Tenant A can never authorize access to Tenant B.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

from aegis.core.context import get_current_tenant_id
from aegis.core.models import Membership


def _resolved_user(request):
    return getattr(request, 'platform_user', None)


def _has_active_membership(platform_user, permission_code=None):
    """True iff the user has an active membership in the current tenant.

    ``Membership.objects`` is scoped to the current tenant, so this is implicitly
    "membership in *this* tenant". If ``permission_code`` is given, the role must
    also carry that permission.
    """
    qs = Membership.objects.filter(platform_user=platform_user, is_active=True)
    if permission_code is not None:
        qs = qs.filter(role__permissions__code=permission_code)
    return qs.exists()


def require_platform_access(view_func):
    """Deny (403) unless the request has a mapped user + active membership."""

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        platform_user = _resolved_user(request)
        if platform_user is None or get_current_tenant_id() is None:
            raise PermissionDenied('No platform identity/tenant for this request.')
        if not _has_active_membership(platform_user):
            raise PermissionDenied('No active membership in this tenant.')
        return view_func(request, *args, **kwargs)

    return _wrapped


def require_permission(permission_code):
    """Deny (403) unless the user's active membership grants ``permission_code``."""

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            platform_user = _resolved_user(request)
            if platform_user is None or get_current_tenant_id() is None:
                raise PermissionDenied('No platform identity/tenant for this request.')
            if not _has_active_membership(platform_user, permission_code=permission_code):
                raise PermissionDenied(f'Missing permission: {permission_code}')
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
