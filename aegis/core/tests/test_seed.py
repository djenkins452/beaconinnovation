"""seed_platform_tenant must be safe to run repeatedly (every deploy)."""
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from aegis.core.models import Membership, PlatformUser, Role, Tenant


class SeedTests(TestCase):
    databases = {'default', 'platform'}

    def _run(self):
        call_command('seed_platform_tenant', stdout=StringIO(), stderr=StringIO())

    def test_seed_is_idempotent_with_bootstrap_admin(self):
        User.objects.create_superuser('owner', 'owner@beacon.local', 'x')
        self._run()
        self._run()  # second run must not duplicate anything

        beacon = Tenant.objects.get(tenant_code='BEACON')
        self.assertEqual(Tenant.objects.filter(tenant_code='BEACON').count(), 1)
        # platform-admin + credential-admin (reserved) system roles
        self.assertEqual(Role.all_objects.filter(tenant=beacon).count(), 2)
        self.assertEqual(Membership.all_objects.filter(tenant=beacon).count(), 1)
        self.assertEqual(PlatformUser.objects.count(), 1)

    def test_seed_without_superuser_skips_admin_but_seeds_tenant(self):
        # Beacon's own data migrations seed superusers into the default DB, so
        # clear them to actually exercise the "no Beacon admin to map" branch.
        User.objects.filter(is_superuser=True).delete()
        self._run()
        self.assertEqual(Tenant.objects.filter(tenant_code='BEACON').count(), 1)
        self.assertEqual(Membership.all_objects.count(), 0)
        self.assertEqual(PlatformUser.objects.count(), 0)
