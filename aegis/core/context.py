"""Request-scoped tenant and platform-user context.

The current tenant and platform user are stored in :class:`contextvars.ContextVar`
so they are isolated per request/thread/async-task and never leak between them.
:class:`aegis.core.middleware.TenantMiddleware` sets them for platform requests;
management commands and tests use :func:`tenant_context`.
"""
import contextlib
from contextvars import ContextVar

_current_tenant_id: ContextVar = ContextVar('aegis_current_tenant_id', default=None)
_current_platform_user_id: ContextVar = ContextVar(
    'aegis_current_platform_user_id', default=None
)


def get_current_tenant_id():
    """Return the current tenant id (UUID) or ``None`` if unset."""
    return _current_tenant_id.get()


def set_current_tenant_id(tenant_id):
    """Set the current tenant id; returns a token for :meth:`ContextVar.reset`."""
    return _current_tenant_id.set(tenant_id)


def reset_current_tenant_id(token):
    _current_tenant_id.reset(token)


def get_current_platform_user_id():
    """Return the current platform user id (UUID) or ``None`` if unset."""
    return _current_platform_user_id.get()


def set_current_platform_user_id(platform_user_id):
    return _current_platform_user_id.set(platform_user_id)


def reset_current_platform_user_id(token):
    _current_platform_user_id.reset(token)


@contextlib.contextmanager
def tenant_context(tenant_id, platform_user_id=None):
    """Bind the given tenant (and optional platform user) for the enclosed block.

    Always restores the previous values on exit, so it is safe to nest.
    """
    t_token = _current_tenant_id.set(tenant_id)
    u_token = _current_platform_user_id.set(platform_user_id)
    try:
        yield
    finally:
        _current_platform_user_id.reset(u_token)
        _current_tenant_id.reset(t_token)
