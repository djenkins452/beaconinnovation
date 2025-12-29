# ==============================================================================
# File: create_wlj_superuser.py
# Project: Beacon Innovations - WLJ Financial Dashboard
# Description: Management command to create superuser from environment variables
# Owner: Danny Jenkins (dannyjenkins71@gmail.com)
# Created: 2025-12-28
# ==============================================================================

import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Create a superuser from environment variables if one does not exist'

    def handle(self, *args, **options):
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'danny')
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'dannyjenkins71@gmail.com')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

        if not password:
            self.stdout.write(self.style.WARNING(
                'DJANGO_SUPERUSER_PASSWORD not set. Skipping superuser creation.'
            ))
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.SUCCESS(
                f'Superuser "{username}" already exists. Skipping.'
            ))
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(
            f'Superuser "{username}" created successfully.'
        ))
