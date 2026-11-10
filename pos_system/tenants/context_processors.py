from django.core.exceptions import ValidationError

from tenants.models import Tenant


def current_tenant(request):
    """Expose the signed-in store to templates as `current_tenant` (or None)."""
    session = getattr(request, 'session', None)
    tenant_id = session.get('tenant_id') if session is not None else None
    if not tenant_id:
        return {'current_tenant': None}
    try:
        tenant = Tenant.objects.only('name', 'tin').get(id=tenant_id)
    except (Tenant.DoesNotExist, ValueError, ValidationError):
        tenant = None
    return {'current_tenant': tenant}
