"""The single write path for immutable audit events.

Application/services call :func:`record_event` for every security-sensitive
operation (membership grants/revocations, provider-identity links, bootstrap
seeding, and — in later phases — credential lifecycle transitions). This is the
wiring that Beacon's finance ``AuditLogMixin`` never got.
"""
from aegis.core.models import AuditEvent


def _extract_request_meta(request):
    if request is None:
        return None, ''
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
    return ip, user_agent


def record_event(
    *,
    action,
    tenant=None,
    actor=None,
    provider='',
    obj=None,
    model_name='',
    object_id=None,
    object_repr='',
    detail=None,
    request=None,
):
    """Create and return an immutable :class:`AuditEvent`.

    Pass either ``obj`` (a model instance, from which model_name/object_id/repr
    are derived) or the explicit ``model_name``/``object_id``/``object_repr``.
    """
    if obj is not None:
        model_name = model_name or obj.__class__.__name__
        object_id = object_id or getattr(obj, 'pk', None)
        object_repr = object_repr or str(obj)[:500]

    ip_address, user_agent = _extract_request_meta(request)

    return AuditEvent.objects.create(
        tenant=tenant,
        actor=actor,
        provider=provider,
        action=action,
        model_name=model_name,
        object_id=object_id,
        object_repr=object_repr[:500] if object_repr else '',
        detail=detail or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )
