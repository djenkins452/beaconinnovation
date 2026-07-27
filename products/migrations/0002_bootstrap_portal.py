"""
Intentionally a no-op.

Portal bootstrap (creating the administrator with a generated temporary
password, creating the AIMS product, and granting access) is performed by the
dedicated management command instead of a migration, so that:

  * migrations stay free of side effects and secrets, and
  * bootstrap can run idempotently on every deploy.

    python manage.py bootstrap_portal

This empty migration is kept to preserve the migration chain (0003 depends on
it) for databases that already applied an earlier version of this migration.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0001_initial'),
    ]

    operations = []
