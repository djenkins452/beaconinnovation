"""BeaconSessionProvider — the incubation authentication provider (decision B2).

This is the ONE deliberately-approved seam where the platform reads Beacon's
authenticated user. It reuses Beacon's existing session/login as an *external
identity provider only*: it derives a stable subject string from the Beacon user
and hands it to the platform's own identity/authorization stack. It stores no FK
to ``auth.User`` and makes no authorization decision.

Extraction note: replacing Beacon SSO with an enterprise IdP later means adding a
new provider class here and remapping ProviderIdentity subjects — no changes to
PlatformUser, RBAC, or sessions.
"""
from aegis.core.auth.base import AuthenticationProvider

#: Provider name, also stored on ProviderIdentity.provider.
PROVIDER_NAME = 'beacon-session'


def beacon_subject_for(user):
    """Return the stable external subject string for a Beacon auth.User."""
    return f'beacon:{user.pk}'


class BeaconSessionProvider(AuthenticationProvider):
    name = PROVIDER_NAME

    def get_subject(self, request):
        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            return beacon_subject_for(user)
        return None
