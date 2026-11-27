from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse


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


def dashboard_access_required(view_func):
    """
    The Dashboard is the default landing page, so a user without the Dashboard
    switch is sent to New Sale quietly instead of being told off on every login.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not _is_pos_session(request):
            return redirect('accounts:login')
        if not getattr(getattr(request.user, 'profile', None), 'can_access_dashboard', False):
            return redirect('sales:create_sale')
        return view_func(request, *args, **kwargs)
    return _wrapped


FEATURE_NAMES = {
    'can_access_dashboard': 'Dashboard',
    'can_access_products': 'Products',
    'can_access_categories': 'Categories',
    'can_access_reports': 'Reports',
    'can_access_shift_report': 'Cash closing',
}


def feature_required(flag):
    """
    Allow a POS user whose profile has `flag` switched on, whatever their role.
    The access switches on the user form are the source of truth: the sidebar
    hides what's switched off, and this refuses it on the server too.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not _is_pos_session(request):
                return redirect('accounts:login')

            profile = getattr(request.user, 'profile', None)
            if not getattr(profile, flag, False):
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'success': False, 'ok': False, 'error': 'Access denied.'}, status=403)
                messages.error(request, f"You don't have access to {FEATURE_NAMES.get(flag, 'that page')}.")
                return redirect('sales:dashboard')

            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
