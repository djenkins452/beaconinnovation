"""The router must isolate the two databases in BOTH directions."""
from django.contrib.auth.models import User
from django.test import SimpleTestCase

from aegis.core.models import PlatformUser, Tenant
from aegis.core.routers import PlatformRouter


class PlatformRouterTests(SimpleTestCase):
    def setUp(self):
        self.router = PlatformRouter()

    def test_platform_models_use_platform_db(self):
        self.assertEqual(self.router.db_for_read(Tenant), 'platform')
        self.assertEqual(self.router.db_for_write(Tenant), 'platform')
        self.assertEqual(self.router.db_for_write(PlatformUser), 'platform')

    def test_beacon_and_django_models_defer_to_default(self):
        # None means "no opinion" → Django falls back to 'default'.
        self.assertIsNone(self.router.db_for_read(User))
        self.assertIsNone(self.router.db_for_write(User))

    def test_platform_apps_migrate_only_on_platform(self):
        self.assertTrue(self.router.allow_migrate('platform', 'aegis_core'))
        self.assertFalse(self.router.allow_migrate('default', 'aegis_core'))

    def test_other_apps_migrate_only_on_default(self):
        for app_label in [
            'auth', 'admin', 'contenttypes', 'sessions',
            'finance', 'wlj', 'products', 'website', 'admin_console', 'distribution',
        ]:
            self.assertTrue(
                self.router.allow_migrate('default', app_label),
                f'{app_label} should migrate on default',
            )
            self.assertFalse(
                self.router.allow_migrate('platform', app_label),
                f'{app_label} must NOT migrate on platform',
            )

    def test_cross_database_relations_denied(self):
        tenant = Tenant(tenant_code='X', name='X')
        beacon_user = User(username='u')
        self.assertFalse(self.router.allow_relation(tenant, beacon_user))
        self.assertFalse(self.router.allow_relation(beacon_user, tenant))

    def test_same_side_relations_deferred(self):
        tenant = Tenant(tenant_code='X', name='X')
        platform_user = PlatformUser(email='a@b.c')
        self.assertIsNone(self.router.allow_relation(tenant, platform_user))
