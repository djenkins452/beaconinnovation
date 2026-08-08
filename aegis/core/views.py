"""Platform views. Phase 0 ships only a gated placeholder dashboard."""
from django.shortcuts import render

from aegis.core.auth.access import require_platform_access
from aegis.core.models import Membership


@require_platform_access
def dashboard(request):
    """Proof-of-life shell: reachable only with an active tenant membership.

    Renders the tenant, the signed-in platform user, and their roles. No
    business modules exist yet — this exists to prove the boundary end-to-end.
    """
    platform_user = request.platform_user
    memberships = (
        Membership.objects.filter(platform_user=platform_user, is_active=True)
        .select_related('role')
    )
    roles = [m.role for m in memberships]
    context = {
        'tenant': request.platform_tenant,
        'platform_user': platform_user,
        'roles': roles,
    }
    return render(request, 'aegis/dashboard.html', context)
