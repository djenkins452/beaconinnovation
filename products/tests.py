"""
Tests for the secure product download portal.

Focus: authorization. Users must only see and download products granted to
them; unauthorized and anonymous users must not.
"""
import os
import shutil
import tempfile
from io import StringIO
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .management.commands.bootstrap_portal import ADMIN_USERNAME, AIMS_SLUG, read_ipa_metadata
from .models import Product
from .views import PASSWORD_CHANGE_REQUIRED_GROUP

_TEST_MEDIA = tempfile.mkdtemp(prefix='beacon-portal-test-')


def tearDownModule():
    shutil.rmtree(_TEST_MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class PortalAuthorizationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Start from a clean slate (the bootstrap migration seeds an 'aims' product).
        Product.objects.all().delete()
        cls.danny = User.objects.create_user('danny', password='pw-danny-123')
        cls.parker = User.objects.create_user('parker', password='pw-parker-123')

        cls.aims = Product.objects.create(
            name='AIMS',
            current_version='1.0.4',
            current_build='28',
            download_file=SimpleUploadedFile('AIMSField.ipa', b'fake-ipa-bytes'),
        )
        cls.wlj = Product.objects.create(
            name='Whole Life Journey',
            current_version='2.0.0',
            download_file=SimpleUploadedFile('wlj.zip', b'fake-zip-bytes'),
        )

        # Danny can access both; Parker only AIMS.
        cls.aims.authorized_users.add(cls.danny, cls.parker)
        cls.wlj.authorized_users.add(cls.danny)

    # --- My Products ---------------------------------------------------------

    def test_my_products_shows_only_authorized(self):
        self.client.login(username='parker', password='pw-parker-123')
        resp = self.client.get(reverse('products:my_products'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'AIMS')
        self.assertNotContains(resp, 'Whole Life Journey')

    def test_my_products_requires_login(self):
        resp = self.client.get(reverse('products:my_products'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('products:login'), resp.url)

    # --- Product detail ------------------------------------------------------

    def test_authorized_user_sees_detail(self):
        self.client.login(username='parker', password='pw-parker-123')
        resp = self.client.get(reverse('products:detail', args=['aims']))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Download Latest Version')

    def test_detail_shows_version_and_build(self):
        self.client.login(username='parker', password='pw-parker-123')
        resp = self.client.get(reverse('products:detail', args=['aims']))
        self.assertContains(resp, 'Current Version')
        self.assertContains(resp, '1.0.4')
        self.assertContains(resp, 'Current Build')
        self.assertContains(resp, '28')

    def test_unauthorized_user_detail_is_404(self):
        self.client.login(username='parker', password='pw-parker-123')
        resp = self.client.get(reverse('products:detail', args=[self.wlj.slug]))
        self.assertEqual(resp.status_code, 404)

    # --- Downloads -----------------------------------------------------------

    def test_authorized_download_succeeds(self):
        self.client.login(username='danny', password='pw-danny-123')
        resp = self.client.get(reverse('products:download', args=['aims']))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertEqual(b''.join(resp.streaming_content), b'fake-ipa-bytes')

    def test_unauthorized_download_is_404(self):
        self.client.login(username='parker', password='pw-parker-123')
        resp = self.client.get(reverse('products:download', args=[self.wlj.slug]))
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_download_redirects_to_login(self):
        resp = self.client.get(reverse('products:download', args=['aims']))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('products:login'), resp.url)

    def test_disabled_download_is_404_even_for_authorized(self):
        self.aims.download_enabled = False
        self.aims.save()
        self.client.login(username='danny', password='pw-danny-123')
        resp = self.client.get(reverse('products:download', args=['aims']))
        self.assertEqual(resp.status_code, 404)


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class ProductModelTests(TestCase):
    def setUp(self):
        # The bootstrap migration seeds an 'aims' product; start clean.
        Product.objects.all().delete()

    def test_slug_autogenerated_from_name(self):
        p = Product.objects.create(name='Finance Tracker')
        self.assertEqual(p.slug, 'finance-tracker')

    def test_replacing_build_deletes_old_file(self):
        p = Product.objects.create(
            name='Brother Willies',
            download_file=SimpleUploadedFile('old.zip', b'old'),
        )
        old_storage = p.download_file.storage
        old_name = p.download_file.name
        self.assertTrue(old_storage.exists(old_name))

        p.download_file = SimpleUploadedFile('new.zip', b'new')
        p.save()

        self.assertFalse(old_storage.exists(old_name))
        self.assertTrue(p.download_file.storage.exists(p.download_file.name))

    def test_is_available_requires_file_and_enabled(self):
        p = Product.objects.create(name='No File')
        self.assertFalse(p.is_available)
        p.download_file = SimpleUploadedFile('x.exe', b'bytes')
        p.save()
        self.assertTrue(p.is_available)
        p.download_enabled = False
        self.assertFalse(p.is_available)

    def test_file_extension(self):
        p = Product.objects.create(
            name='Ext Test',
            download_file=SimpleUploadedFile('build.APK', b'bytes'),
        )
        self.assertEqual(p.file_extension, 'apk')


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class ForcedPasswordChangeTests(TestCase):
    def setUp(self):
        self.group, _ = Group.objects.get_or_create(name=PASSWORD_CHANGE_REQUIRED_GROUP)
        self.user = User.objects.create_user('newadmin', password='temp-pass-123')
        self.user.groups.add(self.group)

    def test_flagged_user_redirected_from_portal(self):
        self.client.login(username='newadmin', password='temp-pass-123')
        resp = self.client.get(reverse('products:my_products'))
        self.assertRedirects(resp, reverse('products:password_change'))

    def test_flagged_user_can_reach_change_page(self):
        self.client.login(username='newadmin', password='temp-pass-123')
        resp = self.client.get(reverse('products:password_change'))
        self.assertEqual(resp.status_code, 200)

    def test_changing_password_clears_flag_and_unblocks_portal(self):
        self.client.login(username='newadmin', password='temp-pass-123')
        resp = self.client.post(reverse('products:password_change'), {
            'old_password': 'temp-pass-123',
            'new_password1': 'Str0ng-New-Pass!42',
            'new_password2': 'Str0ng-New-Pass!42',
        })
        self.assertRedirects(resp, reverse('products:password_change_done'))
        self.user.refresh_from_db()
        self.assertFalse(self.user.groups.filter(name=PASSWORD_CHANGE_REQUIRED_GROUP).exists())
        # Portal is now accessible (session kept alive after password change).
        resp = self.client.get(reverse('products:my_products'))
        self.assertEqual(resp.status_code, 200)

    def test_unflagged_user_not_redirected(self):
        User.objects.create_user('plainuser', password='pw-plain-123')
        self.client.login(username='plainuser', password='pw-plain-123')
        resp = self.client.get(reverse('products:my_products'))
        self.assertEqual(resp.status_code, 200)


@override_settings(MEDIA_ROOT=_TEST_MEDIA)
class BootstrapCommandTests(TestCase):
    """`manage.py bootstrap_portal` performs all bootstrap — no migration side
    effects, no hardcoded passwords."""

    def _run(self):
        out = StringIO()
        call_command('bootstrap_portal', stdout=out)
        return out.getvalue()

    def test_creates_admin_with_temp_password_and_forces_change(self):
        User.objects.filter(username=ADMIN_USERNAME).delete()
        out = self._run()
        admin = User.objects.get(username=ADMIN_USERNAME)
        self.assertTrue(admin.is_superuser and admin.is_staff)
        self.assertTrue(admin.has_usable_password())
        self.assertTrue(admin.groups.filter(name=PASSWORD_CHANGE_REQUIRED_GROUP).exists())
        self.assertIn('Temporary password', out)

    def test_creates_and_grants_aims(self):
        User.objects.filter(username=ADMIN_USERNAME).delete()
        self._run()
        aims = Product.objects.get(slug='aims')
        admin = User.objects.get(username=ADMIN_USERNAME)
        self.assertTrue(aims.authorized_users.filter(pk=admin.pk).exists())

    def test_leaves_existing_admin_completely_unchanged(self):
        # finance/0006 already created this admin in the migrated test DB.
        admin = User.objects.get(username=ADMIN_USERNAME)
        old_password_hash = admin.password
        out = self._run()
        admin.refresh_from_db()
        self.assertEqual(admin.password, old_password_hash)
        self.assertFalse(admin.groups.filter(name=PASSWORD_CHANGE_REQUIRED_GROUP).exists())
        self.assertIn('left unchanged', out)

    def test_idempotent(self):
        self._run()
        self._run()  # must not raise or duplicate
        self.assertEqual(Product.objects.filter(slug=AIMS_SLUG).count(), 1)

    def test_publishes_committed_aims_build(self):
        self._run()
        aims = Product.objects.get(slug=AIMS_SLUG)
        self.assertTrue(aims.is_available)
        self.assertEqual(aims.filename, 'AIMSField.ipa')
        # Version/build are read from the committed IPA's own metadata.
        expected = read_ipa_metadata(
            os.path.join(settings.BASE_DIR, 'static', 'downloads', 'AIMSField.ipa'))
        self.assertEqual(aims.current_version, expected['version'])
        self.assertEqual(aims.current_build, expected['build'])
        self.assertEqual(expected['bundle_id'], 'com.beaconinnovation.aims.field')

    def test_env_var_password_is_used(self):
        User.objects.filter(username=ADMIN_USERNAME).delete()
        with mock.patch.dict(os.environ, {'BEACON_ADMIN_PASSWORD': 'Env-Provided-Pass-42!'}):
            self._run()
        admin = User.objects.get(username=ADMIN_USERNAME)
        self.assertTrue(admin.check_password('Env-Provided-Pass-42!'))

    def test_no_hardcoded_password_in_bootstrap_sources(self):
        import products.management.commands.bootstrap_portal as cmd_mod
        with open(cmd_mod.__file__) as f:
            command_src = f.read()
        self.assertNotIn('Beacon!Temp2026', command_src)
        self.assertNotIn('Beacon2026', command_src)

        # The bootstrap migration must be a side-effect-free no-op.
        import products.migrations as mig_pkg
        mpath = os.path.join(os.path.dirname(mig_pkg.__file__), '0002_bootstrap_portal.py')
        with open(mpath) as f:
            migration_src = f.read()
        self.assertNotIn('Beacon', migration_src)
        self.assertNotIn('create_user', migration_src)
        self.assertNotIn('create_superuser', migration_src)
