from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.contrib import messages
from django.http import JsonResponse

from .decorators import admin_required
from .models import UserProfile
from .throttle import ThrottledAuthenticationForm
from tenants.middleware import get_current_tenant_id
from tenants.models import Tenant


# ─── Auth ────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated and request.session.get('app_type') == 'pos':
        return redirect('/')

    form = ThrottledAuthenticationForm(request, data=request.POST or None)
    if form.is_valid():
        user = form.get_user()
        profile = UserProfile.all_objects.filter(user=user).exclude(tenant_id__isnull=True).first()
        tenant = Tenant.objects.filter(id=profile.tenant_id).first() if profile else None

        # Every POS session must belong to exactly one existing store; otherwise
        # tenant scoping has nothing to scope to.
        if tenant is None:
            messages.error(request, 'This account is not linked to a store. Please contact your administrator.')
            return render(request, 'accounts/login.html', {'form': form})
        if not tenant.is_active:
            messages.error(request, 'This store has been deactivated. Please contact your administrator.')
            return render(request, 'accounts/login.html', {'form': form})

        login(request, user)
        request.session['tenant_id'] = str(tenant.id)
        request.session['app_type'] = 'pos'
        return redirect('/')

    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    request.session.pop('tenant_id', None)
    request.session.pop('app_type', None)    # ← clean up on logout too
    logout(request)
    return redirect('/accounts/login/')


# ─── User Management — Redirect to Admin Platform ────────────
@admin_required
def user_list(request):
    """Redirect POS users to the admin platform for user management."""
    tenant_id = get_current_tenant_id()
    if tenant_id:
        return redirect('platform_admin:store_detail', tenant_id=tenant_id)
    # Fallback if no tenant (shouldn't happen for POS users)
    messages.error(request, 'Unable to determine store. Please contact support.')
    return redirect('sales:dashboard')