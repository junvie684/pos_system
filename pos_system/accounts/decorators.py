from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def get_user_role(user):
    """Return the role string for a given user."""
    if user.is_superuser:
        return 'admin'
    elif user.is_staff:
        return 'manager'
    return 'cashier'


def _is_pos_session(request):
    """True only when the request carries a genuine POS login session."""
    return request.user.is_authenticated and request.session.get('app_type') == 'pos'


def admin_required(view_func):
    """Allow only Admin (superuser) POS users."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')

        # Reject admin-platform sessions trying to access POS views
        if not _is_pos_session(request):
            messages.error(request, 'Please log in to the POS system.')
            return redirect('accounts:login')

        if not request.user.is_superuser:
            messages.error(request, 'Access denied. Admin privileges required.')
            return redirect('sales:dashboard')

        return view_func(request, *args, **kwargs)
    return _wrapped


def manager_or_admin_required(view_func):
    """Allow Admin and Manager POS users (staff or superuser)."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')

        # Reject admin-platform sessions trying to access POS views
        if not _is_pos_session(request):
            messages.error(request, 'Please log in to the POS system.')
            return redirect('accounts:login')

        if not (request.user.is_staff or request.user.is_superuser):
            messages.error(request, 'Access denied. Manager or Admin privileges required.')
            return redirect('sales:dashboard')

        return view_func(request, *args, **kwargs)
    return _wrapped


def pos_login_required(view_func):
    """
    Use this on any POS view that only requires authentication (no role check).
    Drop-in replacement for Django's @login_required for POS views.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not _is_pos_session(request):
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return _wrapped