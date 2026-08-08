"""AuthenticationProvider abstraction + registry + subject→PlatformUser mapping."""
from abc import ABC, abstractmethod

from aegis.core.models import PlatformUser, ProviderIdentity

# Provider registry, keyed by provider name. Populated at app startup by
# aegis.core.apps.AegisCoreConfig.ready().
_REGISTRY = {}


class AuthenticationProvider(ABC):
    """Proves the identity of an external subject for a given request.

    Concrete providers implement :meth:`get_subject`, returning a stable external
    subject string (unique within the provider) or ``None`` if the request
    carries no authenticated identity for this provider. Providers must not make
    authorization decisions — they only assert *who* the external subject is.
    """

    #: Stable provider name; also stored on ProviderIdentity.provider.
    name: str = ''

    @abstractmethod
    def get_subject(self, request):
        """Return the external subject id (str) or ``None``."""
        raise NotImplementedError


def register_provider(provider):
    if not provider.name:
        raise ValueError('AuthenticationProvider.name must be set.')
    _REGISTRY[provider.name] = provider


def get_providers():
    return list(_REGISTRY.values())


def clear_providers():
    """Test helper: empty the registry."""
    _REGISTRY.clear()


def resolve_platform_user(request):
    """Map the request's authenticated external subject to a PlatformUser.

    Returns the mapped, active :class:`PlatformUser`, or ``None`` if the request
    is unauthenticated, the subject has no :class:`ProviderIdentity`, or the
    mapped user is inactive. This function performs **no** auto-provisioning: an
    unmapped external subject yields ``None`` (fail closed). Provisioning is an
    explicit administrative/bootstrap action.
    """
    for provider in get_providers():
        subject = provider.get_subject(request)
        if not subject:
            continue
        try:
            identity = ProviderIdentity.objects.select_related('platform_user').get(
                provider=provider.name, subject=subject
            )
        except ProviderIdentity.DoesNotExist:
            continue
        if identity.platform_user.is_active:
            return identity.platform_user
    return None
