# Generated migration to create initial superuser on production

from django.db import migrations


def create_superuser(apps, schema_editor):
    """Create the initial superuser for production."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    # Only create if user doesn't exist
    if not User.objects.filter(username='dannyjenkins71@gmail.com').exists():
        User.objects.create_superuser(
            username='dannyjenkins71@gmail.com',
            email='dannyjenkins71@gmail.com',
            password='Beacon2026'
        )
        print('Created superuser: dannyjenkins71@gmail.com')
    else:
        print('Superuser already exists')


def remove_superuser(apps, schema_editor):
    """Remove the superuser (for rollback)."""
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
