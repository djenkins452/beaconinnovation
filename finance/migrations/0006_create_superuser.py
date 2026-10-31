# Data migration for the initial superuser.
#
# SECURITY: this migration previously created a superuser with a HARDCODED password.
# That secret lived in source (and remains in git history for the old revision), so
# it must be treated as compromised wherever it was ever applied — rotate those
# credentials (see docs/architecture/PHASE_0_DURABILITY.md, "Legacy admin
# credential"). The hardcoded password has been removed: creation is now gated on an
# environment variable and is skipped when it is unset, matching wlj/0002 and the
# bootstrap command. Editing this already-applied migration does not re-run it, so it
# does not change any existing account; it only governs fresh migrations.

from django.db import migrations


def create_superuser(apps, schema_editor):
    """Create the initial superuser only when a password is supplied via env."""
    import os

    from django.contrib.auth import get_user_model

    User = get_user_model()
    username = 'dannyjenkins71@gmail.com'
    password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
    if not password:
        print('DJANGO_SUPERUSER_PASSWORD not set. Skipping superuser creation.')
        return
    if User.objects.filter(username=username).exists():
        print('Superuser already exists')
        return
    User.objects.create_superuser(username=username, email=username, password=password)
    print('Created superuser from DJANGO_SUPERUSER_PASSWORD')


def remove_superuser(apps, schema_editor):
    """Reverse: remove the superuser (for rollback)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    User.objects.filter(username='dannyjenkins71@gmail.com').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0005_add_category_unique_constraint'),
    ]

    operations = [
        migrations.RunPython(create_superuser, remove_superuser),
    ]
