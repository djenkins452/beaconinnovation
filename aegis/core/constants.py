"""Stable string constants for Phase 0 permissions and system roles."""

# Permission codes (global vocabulary).
PERM_VIEW_DASHBOARD = 'platform.view_dashboard'
PERM_MANAGE_TENANT = 'platform.manage_tenant'
# Reserved for the credential domain (Phases 3+). Seeded now so the Credential
# Administrator role can exist as a distinct, least-privilege concept, but it
# gates nothing until the credential module is built.
PERM_ADMINISTER_CREDENTIALS = 'credential.administer'

PHASE0_PERMISSIONS = [
    (PERM_VIEW_DASHBOARD, 'View the Enterprise Platform dashboard'),
    (PERM_MANAGE_TENANT, 'Manage tenant configuration, users, and roles'),
    (PERM_ADMINISTER_CREDENTIALS, 'Administer credentials (reserved — future phase)'),
]

# System role codes.
ROLE_PLATFORM_ADMIN = 'platform-admin'
ROLE_CREDENTIAL_ADMIN = 'credential-admin'  # reserved, seeded, unused in Phase 0
