# Create the initial superuser on production.
#
# No password is hardcoded here. The password is read from the
# DJANGO_SUPERUSER_PASSWORD environment variable; if it is unset this migration
# does nothing and the products portal bootstrap (products/0002_bootstrap_portal)
# creates the administrator with a generated temporary password instead.

import os

from django.db import migrations

ADMIN_USERNAME = 'dannyjenkins71@gmail.com'


def create_superuser(apps, schema_editor):
    """Create the initial superuser from environment configuration."""
    from django.contrib.auth import get_user_model
    User = get_user_model()

    if User.objects.filter(username=ADMIN_USERNAME).exists():
        print('Superuser already exists')
        return

    password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
    if not password:
        print('DJANGO_SUPERUSER_PASSWORD not set. Skipping superuser creation '
              '(portal bootstrap will create the admin).')
        return

    User.objects.create_superuser(
        username=ADMIN_USERNAME,
        email=ADMIN_USERNAME,
        password=password,
    )
    print(f'Created superuser: {ADMIN_USERNAME}')


def remove_superuser(apps, schema_editor):
    """Remove the superuser (for rollback)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    User.objects.filter(username=ADMIN_USERNAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0005_add_category_unique_constraint'),
    ]

    operations = [
        migrations.RunPython(create_superuser, remove_superuser),
    ]
