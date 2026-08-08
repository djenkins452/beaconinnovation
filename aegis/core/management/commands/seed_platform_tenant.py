"""Idempotent seed for the Enterprise Platform foundation.

Creates (and safely re-runs against) Beacon = Tenant #1, the Phase 0 permission
vocabulary, the system roles, and — optionally — a bootstrap platform-admin
mapped to an existing Beacon superuser so the owner can reach the shell.

This command is the clearly-separated bootstrap path referenced in decision B2:
it is the ONE place (besides ``BeaconSessionProvider``) that reads Beacon's
``auth.User``, and it does so only to establish the initial ProviderIdentity
mapping. It is safe to run on every deploy (mirrors ``bootstrap_portal``).
"""
from django.core.management.base import BaseCommand

from aegis.core import audit
from aegis.core.auth.beacon_session import PROVIDER_NAME, beacon_subject_for
from aegis.core.constants import (
    PERM_ADMINISTER_CREDENTIALS,
    PERM_MANAGE_TENANT,
    PERM_VIEW_DASHBOARD,
    PHASE0_PERMISSIONS,
    ROLE_CREDENTIAL_ADMIN,
    ROLE_PLATFORM_ADMIN,
)
from aegis.core.context import tenant_context
from aegis.core.models import (
    Membership,
    Permission,
    PlatformUser,
    ProviderIdentity,
    Role,
    Tenant,
)


class Command(BaseCommand):
    help = 'Idempotently seed Beacon as Tenant #1 plus Phase 0 roles/permissions.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-code', default='BEACON')
        parser.add_argument('--tenant-name', default='Beacon Innovation, LLC')
        parser.add_argument(
            '--beacon-username',
            default=None,
            help='Beacon auth.User username to map as the bootstrap platform admin. '
            'If omitted, the first Beacon superuser is used (if any).',
        )
        parser.add_argument(
            '--admin-email',
            default=None,
            help='Email for the bootstrap PlatformUser (defaults to the Beacon '
            "user's email, then <username>@beacon.local).",
        )

    def handle(self, *args, **options):
        tenant = self._seed_tenant(options['tenant_code'], options['tenant_name'])
        permissions = self._seed_permissions()

        with tenant_context(tenant.id):
            roles = self._seed_roles(tenant, permissions)
            self._seed_bootstrap_admin(
                tenant,
                roles[ROLE_PLATFORM_ADMIN],
                options['beacon_username'],
                options['admin_email'],
            )

        self.stdout.write(self.style.SUCCESS(
            f'Platform seed complete for tenant {tenant.tenant_code}.'
        ))

    # --- steps -----------------------------------------------------------

    def _seed_tenant(self, code, name):
        tenant, created = Tenant.objects.get_or_create(
            tenant_code=code, defaults={'name': name}
        )
        if created:
            audit.record_event(
                action='tenant.created', tenant=tenant, obj=tenant,
                detail={'tenant_code': code}, provider='seed',
            )
            self.stdout.write(f'  + created tenant {code}')
        else:
            self.stdout.write(f'  = tenant {code} already exists')
        return tenant

    def _seed_permissions(self):
        result = {}
        for code, description in PHASE0_PERMISSIONS:
            perm, _ = Permission.objects.get_or_create(
                code=code, defaults={'description': description}
            )
            result[code] = perm
        self.stdout.write(f'  = {len(result)} permissions ensured')
        return result

    def _seed_roles(self, tenant, permissions):
        roles = {}

        admin_role, created = Role.objects.get_or_create(
            tenant=tenant, code=ROLE_PLATFORM_ADMIN,
            defaults={'name': 'Platform Administrator', 'is_system': True},
        )
        admin_role.permissions.set([
            permissions[PERM_VIEW_DASHBOARD], permissions[PERM_MANAGE_TENANT],
        ])
        roles[ROLE_PLATFORM_ADMIN] = admin_role
        if created:
            audit.record_event(
                action='role.created', tenant=tenant, obj=admin_role,
                detail={'code': ROLE_PLATFORM_ADMIN}, provider='seed',
            )

        # Reserved Credential Administrator role — least-privilege boundary for a
        # future domain. Seeded now, gates nothing until credentials exist.
        cred_role, created = Role.objects.get_or_create(
            tenant=tenant, code=ROLE_CREDENTIAL_ADMIN,
            defaults={'name': 'Credential Administrator', 'is_system': True},
        )
        cred_role.permissions.set([permissions[PERM_ADMINISTER_CREDENTIALS]])
        roles[ROLE_CREDENTIAL_ADMIN] = cred_role
        if created:
            audit.record_event(
                action='role.created', tenant=tenant, obj=cred_role,
                detail={'code': ROLE_CREDENTIAL_ADMIN}, provider='seed',
            )

        self.stdout.write(f'  = {len(roles)} system roles ensured')
        return roles

    def _seed_bootstrap_admin(self, tenant, admin_role, username, admin_email):
        beacon_user = self._find_beacon_user(username)
        if beacon_user is None:
            self.stdout.write(self.style.WARNING(
                '  ! no Beacon superuser found — skipped bootstrap admin mapping. '
                'Re-run after creating one, or pass --beacon-username.'
            ))
            return

        subject = beacon_subject_for(beacon_user)
        email = admin_email or (beacon_user.email or f'{beacon_user.username}@beacon.local')

        platform_user, pu_created = PlatformUser.objects.get_or_create(
            email=email,
            defaults={'display_name': beacon_user.get_full_name() or beacon_user.username},
        )
        identity, id_created = ProviderIdentity.objects.get_or_create(
            provider=PROVIDER_NAME, subject=subject,
            defaults={'platform_user': platform_user},
        )
        membership, m_created = Membership.objects.get_or_create(
            tenant=tenant, platform_user=platform_user, role=admin_role,
            defaults={'is_active': True},
        )
        if m_created:
            audit.record_event(
                action='membership.granted', tenant=tenant, actor=platform_user,
                obj=membership, provider='seed',
                detail={'role': admin_role.code, 'email': email},
            )
        state = 'created' if (pu_created or id_created or m_created) else 'already present'
        self.stdout.write(f'  = bootstrap admin {email} ({state})')

    def _find_beacon_user(self, username):
        # Isolated Beacon dependency (bootstrap seam only). Imported lazily.
        from django.contrib.auth import get_user_model

        User = get_user_model()
        if username:
            return User.objects.filter(username=username).first()
        return User.objects.filter(is_superuser=True).order_by('pk').first()
