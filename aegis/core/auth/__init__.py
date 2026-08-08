"""Authentication seam for the Enterprise Platform.

Authentication is provider-based (decision B2): a provider proves an external
subject; the platform then maps that subject to a :class:`PlatformUser` via
:class:`ProviderIdentity` and authorizes via tenant :class:`Membership`.

The flow is strictly:

    provider → external subject → ProviderIdentity → PlatformUser
        → Membership → Roles/Permissions → authorized access

A valid external login **never** grants platform access on its own. During
Beacon incubation the only registered provider is ``BeaconSessionProvider``;
future providers (Entra/OIDC, Google, SAML, CAC/PIV) plug into the same seam
without changing PlatformUser/RBAC/session.
"""
from aegis.core.auth.base import (
    AuthenticationProvider,
    get_providers,
    register_provider,
    resolve_platform_user,
)


def register_default_providers():
    """Register the providers active during Beacon incubation."""
    from aegis.core.auth.beacon_session import BeaconSessionProvider

    register_provider(BeaconSessionProvider())


__all__ = [
    'AuthenticationProvider',
    'get_providers',
    'register_provider',
    'resolve_platform_user',
    'register_default_providers',
]
