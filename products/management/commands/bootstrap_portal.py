"""
Bootstrap the product download portal for a new deployment.

Idempotent and safe to run on every deploy. It performs the bootstrap behavior
that must NOT live in migrations (which are immutable once committed):

  * Administrator account (dannyjenkins71@gmail.com):
      - If it already exists -> left completely unchanged.
      - If it does not exist -> created with a strong TEMPORARY password taken
        from the BEACON_ADMIN_PASSWORD environment variable, or randomly
        generated if that is unset. A generated password is displayed once.
        A newly created admin is flagged to require a password change on first
        login (portal_must_change_password group).
  * Ensures the initial AIMS product exists.
  * Grants the administrator access to AIMS.
  * Publishes the current AIMS build: attaches the committed IPA
    (static/downloads/AIMSField.ipa) to the AIMS product's download and sets
    Current Version / Current Build from the IPA's own metadata. This is
    idempotent and also survives Railway's ephemeral filesystem (the committed
    IPA is the source of truth, re-attached whenever the stored file is missing
    or differs).

No password is ever stored in source control.

    python manage.py bootstrap_portal
"""
import os
import plistlib
import secrets
import zipfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files import File
from django.core.management.base import BaseCommand

from products.models import Product
from products.views import PASSWORD_CHANGE_REQUIRED_GROUP

ADMIN_USERNAME = 'dannyjenkins71@gmail.com'
ADMIN_EMAIL = 'dannyjenkins71@gmail.com'
AIMS_SLUG = 'aims'

# The committed, signed AIMS build that the portal publishes. Kept in the
# static tree (also served over-the-air at /static/downloads/AIMSField.ipa).
AIMS_IPA_PATH = os.path.join(settings.BASE_DIR, 'static', 'downloads', 'AIMSField.ipa')
AIMS_STORED_NAME = 'product_downloads/AIMSField.ipa'


def read_ipa_metadata(ipa_path):
    """Return {'version', 'build', 'bundle_id'} from an IPA's Info.plist."""
    with zipfile.ZipFile(ipa_path) as zf:
        info_name = next(
            name for name in zf.namelist()
            if name.startswith('Payload/') and name.endswith('.app/Info.plist')
        )
        plist = plistlib.loads(zf.read(info_name))
    return {
        'version': plist.get('CFBundleShortVersionString', ''),
        'build': plist.get('CFBundleVersion', ''),
        'bundle_id': plist.get('CFBundleIdentifier', ''),
    }


class Command(BaseCommand):
    help = "Bootstrap the download portal (admin, AIMS product, current build)."

    def handle(self, *args, **options):
        User = get_user_model()

        # 1. Administrator: create only if missing; never touch an existing one.
        admin = User.objects.filter(username=ADMIN_USERNAME).first()
        if admin is None:
            env_password = os.environ.get('BEACON_ADMIN_PASSWORD')
            temp_password = env_password or secrets.token_urlsafe(18)

            admin = User.objects.create_user(
                username=ADMIN_USERNAME,
                email=ADMIN_EMAIL,
                password=temp_password,
                is_staff=True,
                is_superuser=True,
                is_active=True,
            )

            # Require a password change on first login.
            group, _ = Group.objects.get_or_create(name=PASSWORD_CHANGE_REQUIRED_GROUP)
            admin.groups.add(group)

            self.stdout.write('=' * 68)
            self.stdout.write(self.style.SUCCESS(' Beacon portal administrator created'))
            self.stdout.write(f'   Username: {ADMIN_USERNAME}')
            if env_password:
                self.stdout.write('   Temporary password: (from BEACON_ADMIN_PASSWORD env var)')
            else:
                self.stdout.write(f'   Temporary password: {temp_password}')
            self.stdout.write('   You will be required to change this on first login.')
            self.stdout.write('=' * 68)
        else:
            self.stdout.write(f'Administrator {ADMIN_USERNAME} already exists — left unchanged.')

        # 2. Ensure the AIMS product exists.
        aims, created = Product.objects.get_or_create(
            slug=AIMS_SLUG,
            defaults={
                'name': 'AIMS',
                'description': 'AIMS Field application.',
                'download_enabled': True,
            },
        )
        if created:
            self.stdout.write('Created product: AIMS')

        # 3. Grant the administrator access to AIMS.
        aims.authorized_users.add(admin)

        # 4. Publish the current AIMS build (idempotent; ephemeral-fs safe).
        self._publish_aims_build(aims)

        self.stdout.write(self.style.SUCCESS('Portal bootstrap complete.'))

    def _publish_aims_build(self, aims):
        if not os.path.exists(AIMS_IPA_PATH):
            self.stdout.write(self.style.WARNING(
                f'AIMS IPA not found at {AIMS_IPA_PATH}; skipping build publish.'))
            return

        src_size = os.path.getsize(AIMS_IPA_PATH)
        storage = aims.download_file.storage
        stored_name = aims.download_file.name

        # The stored file is current only if it physically exists and matches size.
        file_current = False
        if stored_name:
            try:
                file_current = storage.exists(stored_name) and aims.download_file.size == src_size
            except Exception:
                file_current = False

        meta = read_ipa_metadata(AIMS_IPA_PATH)
        changed = False

        # (Re)attach the file when missing or different (also handles Railway's
        # ephemeral filesystem). Stored under a stable name for a clean download.
        if not file_current:
            if storage.exists(AIMS_STORED_NAME):
                storage.delete(AIMS_STORED_NAME)
            with open(AIMS_IPA_PATH, 'rb') as fh:
                aims.download_file.name = storage.save(AIMS_STORED_NAME, File(fh))
            changed = True

        # Reconcile metadata from the IPA even when the file is unchanged — this
        # backfills fields (e.g. bundle_id) on products published before they
        # existed, which is required for OTA install.
        for field, value in (
            ('current_version', meta['version']),
            ('current_build', meta['build']),
            ('bundle_id', meta['bundle_id']),
        ):
            if getattr(aims, field) != value:
                setattr(aims, field, value)
                changed = True
        if not aims.download_enabled:
            aims.download_enabled = True
            changed = True

        if not changed:
            self.stdout.write(
                f'AIMS build already published: v{aims.current_version} '
                f'build {aims.current_build} ({meta["bundle_id"]}).')
            return

        aims.save()
        action = 'Published' if not file_current else 'Reconciled'
        self.stdout.write(self.style.SUCCESS(
            f"{action} AIMS build: v{meta['version']} build {meta['build']} "
            f"({src_size} bytes, {meta['bundle_id']})"))
