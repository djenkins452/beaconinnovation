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

No password is ever stored in source control.

    python manage.py bootstrap_portal
"""
import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from products.models import Product
from products.views import PASSWORD_CHANGE_REQUIRED_GROUP

ADMIN_USERNAME = 'dannyjenkins71@gmail.com'
ADMIN_EMAIL = 'dannyjenkins71@gmail.com'
AIMS_SLUG = 'aims'


class Command(BaseCommand):
    help = "Bootstrap the download portal (admin, AIMS product) for new deployments."

    def handle(self, *args, **options):
        import os

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
        self.stdout.write(self.style.SUCCESS('Portal bootstrap complete.'))
