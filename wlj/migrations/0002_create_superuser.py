# ==============================================================================
# File: 0002_create_superuser.py
# Project: Beacon Innovations - WLJ Financial Dashboard
# Description: Data migration to create initial superuser
# Owner: Danny Jenkins (dannyjenkins71@gmail.com)
# Created: 2025-12-28
# ==============================================================================

import os
from django.db import migrations
from django.contrib.auth.hashers import make_password


def create_superuser(apps, schema_editor):
    User = apps.get_model('auth', 'User')

    username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'danny')
    email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'dannyjenkins71@gmail.com')
    password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

    if not password:
        print('DJANGO_SUPERUSER_PASSWORD not set. Skipping superuser creation.')
        return

    if User.objects.filter(username=username).exists():
        print(f'Superuser "{username}" already exists. Skipping.')
        return

    # Create superuser using make_password (set_password not available on historical model)
    User.objects.create(
        username=username,
        email=email,
        password=make_password(password),
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    print(f'Superuser "{username}" created successfully.')


def reverse_superuser(apps, schema_editor):
    # Don't delete the superuser on reverse migration
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('wlj', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_superuser, reverse_superuser),
    ]
