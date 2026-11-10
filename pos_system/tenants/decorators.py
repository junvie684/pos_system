# tenants/decorators.py
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from functools import wraps


def is_platform_admin(user):
    """
    Platform (all-stores) administrator = an active superuser who is NOT linked
    to any store. Store admins are also Django superusers (that is how the POS
    marks the "Admin" role), so `is_superuser` alone must never grant
    platform-wide access.
    """
    if not (user.is_authenticated and user.is_active and user.is_superuser):
        return False
    from accounts.models import UserProfile
    return not UserProfile.all_objects.filter(user=user, tenant_id__isnull=False).exists()


def _platform_session_ok(request):
    return is_platform_admin(request.user) and not request.session.get('tenant_id')


def platform_admin_required(view_func):
    """Allow only platform admins on a platform (non-store) session."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('platform_admin:login')

        if not _platform_session_ok(request):
            messages.error(request, 'Access denied.')
            return redirect('platform_admin:login')

        return view_func(request, *args, **kwargs)
    return wrapper


def platform_permission_required(perm):
    """
    Check custom platform admin permissions.
    perm format: 'app_label.action_model'  e.g., 'tenants.add_tenant'
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('platform_admin:login')

            if not _platform_session_ok(request):
                messages.error(request, 'Access denied.')
                return redirect('platform_admin:login')

            if not request.user.has_perm(perm):
                raise PermissionDenied(f"You don't have permission: {perm}")

            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
