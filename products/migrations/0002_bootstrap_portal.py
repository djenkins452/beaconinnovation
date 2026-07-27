"""
Bootstrap the download portal.

Administrator account (dannyjenkins71@gmail.com):
  * If it already exists -> leave it completely alone (no password change).
  * If it does not exist -> create it with a TEMPORARY password that is either
    read from the BEACON_ADMIN_PASSWORD environment variable, or, if that is
    unset, randomly generated and printed ONCE to the deploy console/log. The
    new account is flagged (via a Django group) so the portal forces a password
    change on first login.

No password is ever stored in source control or in this migration.

Also creates the initial AIMS product (build uploaded later via the admin) and
grants the administrator access to it.
"""
import os
import secrets

from django.contrib.auth.hashers import make_password
from django.db import migrations

ADMIN_USERNAME = 'dannyjenkins71@gmail.com'
ADMIN_EMAIL = 'dannyjenkins71@gmail.com'

# Kept in sync with products.views.PASSWORD_CHANGE_REQUIRED_GROUP.
MUST_CHANGE_GROUP = 'portal_must_change_password'

AIMS_SLUG = 'aims'


def bootstrap(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Group = apps.get_model('auth', 'Group')
    Product = apps.get_model('products', 'Product')

    # 1. Administrator: create only if missing; never touch an existing account.
    admin = User.objects.filter(username=ADMIN_USERNAME).first()
    if admin is None:
        env_password = os.environ.get('BEACON_ADMIN_PASSWORD')
        temp_password = env_password or secrets.token_urlsafe(18)

        admin = User.objects.create(
            username=ADMIN_USERNAME,
            email=ADMIN_EMAIL,
            password=make_password(temp_password),
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )

        # Force a password change on first login.
        group, _ = Group.objects.get_or_create(name=MUST_CHANGE_GROUP)
        admin.groups.add(group)

        print('\n' + '=' * 68)
        print(' Beacon portal administrator created')
        print(f'   Username: {ADMIN_USERNAME}')
        if env_password:
            print('   Temporary password: (from BEACON_ADMIN_PASSWORD env var)')
        else:
            print(f'   Temporary password: {temp_password}')
        print('   You will be required to change this on first login.')
        print('=' * 68 + '\n')
    else:
        print(f'Portal administrator {ADMIN_USERNAME} already exists — left unchanged.')

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
        print('Created product: AIMS')

    # 3. Grant the administrator access to AIMS.
    aims.authorized_users.add(admin)


def unbootstrap(apps, schema_editor):
    """Only remove the AIMS product; never delete user accounts on rollback."""
    Product = apps.get_model('products', 'Product')
    Product.objects.filter(slug=AIMS_SLUG).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(bootstrap, unbootstrap),
    ]
