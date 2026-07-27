"""
Tests for the secure product download portal.

Focus: authorization. Users must only see and download products granted to
them; unauthorized and anonymous users must not.
"""
import os
import plistlib
import shutil
import tempfile
from io import StringIO
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .management.commands.bootstrap_portal import ADMIN_USERNAME, AIMS_SLUG, read_ipa_metadata
from .models import Product
from .views import PASSWORD_CHANGE_REQUIRED_GROUP, make_ota_token

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
class OTAInstallTests(TestCase):
    """Apple over-the-air install: device-aware page + token-gated,
    cookieless manifest/IPA endpoints that still enforce authorization."""

    IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
    DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120 Safari/537.36")

    @classmethod
    def setUpTestData(cls):
        Product.objects.all().delete()
        cls.user = User.objects.create_user('otauser', password='pw-ota-123')
        cls.other = User.objects.create_user('otaother', password='pw-other-123')
        cls.app = Product.objects.create(
            name='AIMS', slug='aims',
            current_version='0.3.0', current_build='3',
            bundle_id='com.beaconinnovation.aims.field',
            download_file=SimpleUploadedFile('AIMSField.ipa', b'PK-fake-ipa-bytes'),
        )
        cls.app.authorized_users.add(cls.user)

    # A fresh cookieless client models the iOS installer (itunesstored).
    def installer(self):
        return Client()

    def manifest_url(self):
        return reverse('products:manifest', args=['aims'])

    def ota_url(self):
        return reverse('products:ota_download', args=['aims'])

    # --- device-aware product page ---

    def test_ota_capable(self):
        self.assertTrue(self.app.ota_capable)

    def test_iphone_shows_install_and_itms_link(self):
        self.client.login(username='otauser', password='pw-ota-123')
        r = self.client.get(reverse('products:detail', args=['aims']), HTTP_USER_AGENT=self.IPHONE)
        self.assertContains(r, 'itms-services://?action=download-manifest')
        self.assertContains(r, 'Install AIMS')
        self.assertContains(r, 'Download IPA')

    def test_desktop_hides_install_serverside(self):
        self.client.login(username='otauser', password='pw-ota-123')
        r = self.client.get(reverse('products:detail', args=['aims']), HTTP_USER_AGENT=self.DESKTOP)
        # Install stays in the DOM (JS reveals it for iPad-as-Mac) but hidden by default.
        self.assertContains(r, 'id="btn-install" class="btn btn-lg btn-primary d-none"')

    def test_non_ios_product_has_no_ota(self):
        exe = Product.objects.create(
            name='Tool', slug='tool',
            download_file=SimpleUploadedFile('tool.exe', b'MZ-fake'))
        exe.authorized_users.add(self.user)
        self.client.login(username='otauser', password='pw-ota-123')
        r = self.client.get(reverse('products:detail', args=['tool']))
        self.assertNotContains(r, 'itms-services://')
        self.assertContains(r, 'Download Latest Version')

    # --- manifest (cookieless, token-gated) ---

    def test_manifest_valid_token(self):
        token = make_ota_token(self.user, self.app)
        r = self.installer().get(self.manifest_url(), {'token': token})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'text/xml; charset=utf-8')
        self.assertIn('no-store', r['Cache-Control'])
        pl = plistlib.loads(r.content)
        meta = pl['items'][0]['metadata']
        self.assertEqual(meta['bundle-identifier'], 'com.beaconinnovation.aims.field')
        self.assertEqual(meta['bundle-version'], '0.3.0')
        self.assertEqual(meta['title'], 'AIMS')
        self.assertEqual(pl['items'][0]['assets'][0]['kind'], 'software-package')
        url = pl['items'][0]['assets'][0]['url']
        self.assertTrue(url.startswith('https://'))
        self.assertIn('/products/aims/ota-download/', url)
        self.assertIn('token=', url)

    def test_manifest_requires_valid_token(self):
        self.assertEqual(self.installer().get(self.manifest_url()).status_code, 403)
        self.assertEqual(self.installer().get(self.manifest_url(), {'token': 'garbage'}).status_code, 403)

    def test_manifest_rejects_foreign_signature(self):
        import django.core.signing as signing
        forged = signing.dumps({'u': self.user.pk, 'p': 'aims'}, salt='not.the.salt')
        self.assertEqual(self.installer().get(self.manifest_url(), {'token': forged}).status_code, 403)

    def test_manifest_unauthorized_users_token_forbidden(self):
        token = make_ota_token(self.other, self.app)  # signed, but user isn't authorized
        self.assertEqual(self.installer().get(self.manifest_url(), {'token': token}).status_code, 403)

    def test_manifest_token_scoped_to_product(self):
        # A token minted for AIMS must not work on another product's manifest.
        other = Product.objects.create(
            name='Other', slug='other', bundle_id='com.x.y',
            download_file=SimpleUploadedFile('o.ipa', b'x'))
        other.authorized_users.add(self.user)
        token = make_ota_token(self.user, self.app)  # scoped to 'aims'
        r = self.installer().get(reverse('products:manifest', args=['other']), {'token': token})
        self.assertEqual(r.status_code, 403)

    # --- IPA (cookieless, token-gated) ---

    def test_ota_download_valid_token(self):
        token = make_ota_token(self.user, self.app)
        r = self.installer().get(self.ota_url(), {'token': token})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/octet-stream')
        self.assertIn('no-store', r['Cache-Control'])
        self.assertEqual(b''.join(r.streaming_content), b'PK-fake-ipa-bytes')

    def test_ota_download_requires_token(self):
        self.assertEqual(self.installer().get(self.ota_url()).status_code, 403)
        self.assertEqual(self.installer().get(self.ota_url(), {'token': 'nope'}).status_code, 403)

    def test_ota_download_unauthorized_users_token_forbidden(self):
        token = make_ota_token(self.other, self.app)
        self.assertEqual(self.installer().get(self.ota_url(), {'token': token}).status_code, 403)


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
