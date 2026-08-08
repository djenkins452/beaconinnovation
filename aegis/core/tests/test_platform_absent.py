"""Beacon must stay functional and /platform/ must fail closed (not crash) when
the platform database is not configured (PLATFORM_DATABASE_URL unset)."""
from django.test import SimpleTestCase, override_settings

from aegis.core.middleware import TenantMiddleware

_DEFAULT_ONLY = {
    'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'},
}


class PlatformAbsentTests(SimpleTestCase):
    @override_settings(DATABASES=_DEFAULT_ONLY)
    def test_resolve_tenant_returns_none_without_platform_db(self):
        # No 'platform' connection configured → resolve to None WITHOUT querying
        # (no ConnectionDoesNotExist). SimpleTestCase forbids DB access, so this
        # also proves no query is attempted.
        middleware = TenantMiddleware(lambda request: None)
        self.assertIsNone(middleware._resolve_tenant())
