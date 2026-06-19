# tenants/decorators.py
from django.shortcuts import redirect
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from functools import wraps


def platform_admin_required(view_func):
    """Check if user is authenticated superuser without tenant session."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('platform_admin:login')

        if not request.user.is_superuser or request.session.get('tenant_id'):
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

            if not request.user.is_superuser or request.session.get('tenant_id'):
                messages.error(request, 'Access denied.')
                return redirect('platform_admin:login')

            if not request.user.has_perm(perm):
                raise PermissionDenied(f"You don't have permission: {perm}")

            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator