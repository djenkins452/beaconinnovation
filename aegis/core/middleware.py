"""Tenant/identity middleware for platform requests.

For requests under the platform route prefix it: resolves the active tenant,
resolves the request's :class:`PlatformUser` via the authentication providers,
binds both into the request-scoped context (:mod:`aegis.core.context`), and
exposes them as ``request.platform_tenant`` / ``request.platform_user``. Context
is always cleared in ``finally`` so it never leaks between requests.

Non-platform (Beacon) requests are passed straight through untouched — Beacon's
existing behavior is unaffected.
"""
from django.conf import settings

from aegis.core.auth import resolve_platform_user
from aegis.core.context import (
    reset_current_platform_user_id,
    reset_current_tenant_id,
    set_current_platform_user_id,
    set_current_tenant_id,
)


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.prefix = getattr(settings, 'PLATFORM_URL_PREFIX', '/platform/')

    def _resolve_tenant(self):
        """Resolve the active tenant.

        During single-tenant incubation this is the configured default tenant
        (Beacon). The mechanism is already multi-tenant: a real deployment would
        resolve by host/subdomain/path. Returns ``None`` if the tenant is not
        provisioned yet — in which case access fails closed downstream.
        """
        # If the platform database is not configured (PLATFORM_DATABASE_URL
        # unset), the platform is simply unavailable. Return None so /platform/
        # fails closed (403) instead of raising ConnectionDoesNotExist (500).
        # Beacon requests are unaffected either way (they never reach here).
        if 'platform' not in settings.DATABASES:
            return None

        # Imported lazily so this module is import-safe before apps are ready.
        from aegis.core.models import Tenant

        code = getattr(settings, 'PLATFORM_TENANT_CODE', 'BEACON')
        return Tenant.objects.filter(
            tenant_code=code, status=Tenant.STATUS_ACTIVE
        ).first()

    def __call__(self, request):
        if not request.path.startswith(self.prefix):
            return self.get_response(request)

        tenant = self._resolve_tenant()
        request.platform_tenant = tenant
        request.platform_user = None

        tenant_token = None
        user_token = None
        try:
            if tenant is not None:
                tenant_token = set_current_tenant_id(tenant.id)
                platform_user = resolve_platform_user(request)
                if platform_user is not None:
                    request.platform_user = platform_user
                    user_token = set_current_platform_user_id(platform_user.id)
            return self.get_response(request)
        finally:
            if user_token is not None:
                reset_current_platform_user_id(user_token)
            if tenant_token is not None:
                reset_current_tenant_id(tenant_token)
